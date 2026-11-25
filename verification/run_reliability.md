# 每日更新可靠性与运行记录（P2）

> 目标：北京时间 08:15 更新，记录计划/实际时间，减少延迟，发现漏跑/失败，提供连续 10 个自然日记录。
> 边界：**项目运行至今不足 10 个自然日，且未来日期不可预填**。按项目一贯原则（宁可显示不足，也不伪造），本文件给出全部真实记录与可持续收集机制，不编造 10 日数据。

## 一、计划时间与调度配置

| 项 | 值 |
|---|---|
| 计划时间 | 北京时间 08:15（= UTC 00:15 = 东京 09:15） |
| cron | `15 0 * * *`（UTC） |
| 触发方式 | 定时调度 + `workflow_dispatch` 手动 |
| SLA | 不承诺——GitHub Actions 免费定时无法保证严格准点，延迟数分钟属正常 |
| 超时保护 | job `timeout-minutes: 20`；并发组 `daily-snapshot` 防重入（`cancel-in-progress: false`） |

## 二、时间记录机制（已实现）

1. **workflow 层**：`记录调度时刻`步打印计划时间、实际启动 UTC、触发事件；`记录完成时刻`步打印完成 UTC。
2. **脚本层**：`scripts/update_data.py` 的 `append_run_log()` 追加记录到 `data/run_log.json`。
   每条记录含审计要求的全部字段（WB 第 4 项）：

   | 字段 | 含义 |
   |---|---|
   | `run_id` | `GITHUB_RUN_ID`（Actions）或 `local-<UTC时间戳>`（本地） |
   | `trigger_type` | `scheduled`（定时）/ `manual_dispatch`（GitHub 手动派发）/ `manual_local`（本地手动），三类中互斥 |
   | `started_at` / `completed_at` | 实际启动/完成 UTC |
   | `conclusion` | `ok` / `partial` / `fail`（脚本层执行结论） |
   | `script_started` / `snapshot_generated` | 恒为 `true`（本记录由脚本执行末尾写入） |
   | `commit_sha` | `GITHUB_SHA` 或 `local` |
   | `planned_utc` / `delay_minutes` / `delay_note` | 计划时间、延迟、口径说明 |
   | `duration_seconds` / `macro_state` / `failed_sources` / `failed_indicators` | 耗时、宏观状态、失败源与失败指标 |
   | `status` / `trigger` | 旧字段名，与 `conclusion` / `trigger_type` 同值（兼容） |

   - **定时延迟**：仅 `scheduled` 计算 `delay_minutes`（实际启动 − 当天 UTC 00:15，提前为负）；`manual_dispatch`/`manual_local` 的 `delay_minutes=null`，`delay_note="手动运行：不计入定时任务延迟统计"`，**不污染定时延迟统计**。
   - 保留最近 60 条（`config.run_log.keep_last`）。
3. 每次运行均由脚本真实写入，**不预填、不伪造历史运行**。

### 两层记录映射（脚本层 vs workflow 层）

| 维度 | `data/run_log.json`（脚本层） | `verification/github_actions_runs.json`（workflow 层） |
|---|---|---|
| 记录对象 | 脚本真实执行的运行 | 全部 workflow run（含脚本未启动即失败） |
| `script_started` | 恒 true | 解析失败/前置步骤失败时为 false |
| `snapshot_generated` | 恒 true | 仅脚本成功执行时为 true |
| 触发类型 | scheduled / manual_dispatch / manual_local | schedule / workflow_dispatch / push 等事件 |

- **YAML 解析阶段失败**（如 run `45190822884`）：只出现在 workflow 层，`conclusion=failure` 且 `script_started=false`、`snapshot_generated=false`，明确标记脚本未启动、没有生成快照；**不在脚本层伪造记录**。
- 两层的 `run_id`（`GITHUB_RUN_ID`）可对应同一 workflow run；本地手动运行只在脚本层出现。
- 早期（加入 run_log 字段前）的脚本运行缺少新字段，属历史记录，**不回填、不补造**。

### 记录口径与数量澄清（审计第三轮文档修正）

为避免"共 5 次运行"与实际 6 条记录被误读，明确如下口径——**两类文件各 6 条，含义不同，不可相加、不可互相替代**：

| 文件 | 记录对象 | 当前条数 | 口径 |
|---|---|---|---|
| `data/run_log.json` | **实际执行了取数脚本**的运行（script_started 恒 true） | 6 条 | 其中 5 条为加入新字段前的早期记录（保留原始字段结构，不回填新字段），1 条为本轮带完整 8 字段的本地运行 |
| `verification/github_actions_runs.json` | **全部 workflow 运行**（含脚本未启动即失败者） | 6 条 | 5 success + 1 failure（该 failure 在 YAML 解析阶段失败、脚本未启动） |

- 早期曾被概括为"共 5 次运行"，指的是当时**脚本层连续成功的 5 条早期记录**；同期 workflow 层还有 1 条解析失败（脚本未启动）。按审计要求，现统一按各自文件的**实际条数（均为 6 条）**披露，不再使用"共 5 次"这一易混口径。
- `github_actions_runs.json` 中的 failure（run `45190822884`）**只计入 workflow 记录**，因脚本未启动，`run_log.json` 中无对应记录，也不补造。
- 早期 5 条 `run_log.json` 记录保留原始字段（`started_utc`/`finished_utc` 等），**不回填**新字段（`run_id`/`trigger_type` 等）；新字段仅出现在其后的新记录中。

## 三、漏跑 / 失败发现机制

- **失败发现**：任一源级失败 → `status=fail`；仅逐指标失败 → `status=partial`；全部成功 → `ok`。快照中 `failed_sources`/`failed_indicators` 同步记录。
- **漏跑发现（严格口径）**：以 `run_log.json` 中 `trigger_type == "scheduled"` 的记录为依据，按 `planned_utc` 逐日比对计划触发日，缺失即为漏跑。
  - **手动运行不计入**：`manual_dispatch` / `manual_local` 即使某日成功，也**不得**视为当天定时任务成功；某日只有手动记录而无 `scheduled` 记录，仍按漏跑处理。
  - 该口径与延迟统计一致：只有 `scheduled` 计算 `delay_minutes`，手动的 `delay_minutes=null`。
  - 未实现主动告警（受免费条件与零成本约束，不接入付费通知服务）。给出复核命令（见第五节），人工/审计可随时核对。
- **改进已做**：workflow 的 `git add` 已纳入 `data/provenance.json`、`data/run_log.json`，确保溯源文件随每日提交入库（此前遗漏，本轮修复）。`data/raw/`（原始响应）按合规要求仅本地留存、不提交公开仓库。

## 三之一、定时运行大延迟根因排查（2026-11-25）

审计关注到定时运行延迟达数小时，本节点给出完整排查与结论，数据均来自 GitHub Actions API 与脚本自身记录，未推测、未补造。

### 现象（三次 scheduled 运行，延迟逐日增大）

| Run ID | 计划(UTC) | 实际启动(UTC) | 延迟 | 作业时长 | 结论 |
|---|---|---|---|---|---|
| 44995019830 | 00:15 | 11-22 06:43:35 | 389 min | 19 秒 | success |
| 45131890988 | 00:15 | 11-23 07:32:49 | 438 min | 18 秒 | success |
| 45368417711 | 00:15 | 11-24 09:46:47 | 572 min | 21 秒 | success |

### 排查过程与排除项

1. **cron 配置**：本地与远端 `.github/workflows/update.yml` 均为 `15 0 * * *`（UTC 00:15），已错开整点，配置正确、一致。
2. **作业本身是否卡住**：三次作业实际时长仅 18/19/21 秒，**排除**脚本执行慢或挂起。
3. **GitHub 侧排队延迟**：API 的 `created_at` 与 `run_started_at` **完全相等**（差 0 秒），**排除** job 进入执行队列后等待 runner 的排队延迟。
4. **并发组阻塞**：`concurrency.group=daily-snapshot, cancel-in-progress=false`，但单次运行仅约 20 秒，不存在长时间占用；**排除**。
5. **本地时钟错误**：`run_log.json` 由脚本在执行时真实写入，`planned_utc=00:15`、`started_at=09:46:58` 与 API 的 `created_at=09:46:47` 吻合；**排除**本地时钟或记录口径问题。

### 根因结论

延迟发生在 **GitHub 调度器发出 schedule 事件之前**：`created_at`（= GitHub 创建这次 run 的时刻）本身就是 06:43 / 07:32 / 09:46，而非 00:15。即 GitHub 免费层共享调度器**没有在计划时刻派发该事件**，而是数小时后才触发；一旦触发，job 立即启动（排队 0 秒）、约 20 秒完成。

这与 GitHub 官方说明一致（[Events that trigger workflows#schedule](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule)）：

> The `schedule` event can be delayed during periods of high loads of GitHub Actions workflow runs. High load times include the start of every hour. If the load is sufficiently high enough, some queued jobs may be dropped. To decrease the chance of delay, schedule your workflow to run at a different time of the hour.

即：schedule 事件在高负载期会被延迟甚至丢弃,官方仅承诺"尽可能"、非 SLA。本仓库 cron 已错开整点（00:15），但仍被延迟数小时,属于免费共享调度资源紧张所致,**不是本项目代码、配置或数据链路的缺陷**。

### 影响与边界

- **数据真实性不受影响**：每次被延迟触发后,脚本都真实取数、生成新快照、无失败源,历史观测正常累积（DXY 等从 2 → 3）。
- **时效性受影响**：快照实际发布时间不固定在 08:15（北京）,可能推迟数小时；面板各卡 `as_of` 仍标注真实行情日期,`data_note` 明示"非同一时刻实时行情"。
- **不伪造、不补偿**：延迟照实记录于 `run_log.json`；未因延迟手动补跑或回填记录（审计明确禁止）。
- **可选缓解（未实施，需审计批准）**：把 cron 改到更冷门的分钟（如 `17 3 * * *`）以降低撞车概率；但这属于调整调度策略、且免费层无法根除延迟,本阶段按"其他工作保持冻结"原则不擅自更改。

## 四、真实运行记录（全部，未伪造）

数据源：GitHub Actions API，原始响应固化于 `verification/github_actions_runs.json`。

| Run ID | 启动(UTC) | 事件 | 结论 | Head SHA |
|---|---|---|---|---|
| 45192190028 | 2026-11-23 14:1x | workflow_dispatch | success | 9a5ef91e7d |
| 45190822884 | 2026-11-23 14:0x | push | **failure** | 6bbddeb93 |
| 45166640886 | 2026-11-23 11:35 | workflow_dispatch | success | 7af53330 |
| 45156913932 | 2026-11-23 10:31 | workflow_dispatch | success | 13ff98d6 |
| 45131890988 | 2026-11-23 07:32 | schedule | success | d942ebf9 |
| 44995019830 | 2026-11-22 06:43 | schedule | success | b058cc97 |

- 共 6 次运行（5 success + 1 failure），跨 **2 个自然日**（11-22、11-23）。

### 失败案例与修复（如实记录，对应审计"失败能够发现并提示"）

- **run 45190822884（failure）**：本阶段首次提交（commit `6bbddeb`）后由 push 触发，失败。
- **根因**：新增的"记录完成时刻"步骤写成单行 `run: echo "...(UTC): $(date ...)"`，其中 `(UTC): ` 的冒号加空格在 YAML 中被解析为映射分隔符，导致 `.github/workflows/update.yml` **YAML 语法错误**，GitHub 无法解析该 workflow（workflows API 显示名称为文件名占位、手动 dispatch 返回 422 "does not have workflow_dispatch trigger"）。
- **发现方式**：提交后主动核查 Actions 运行记录时发现该 failure 与 dispatch 422，随即定位到 YAML 解析错误（`yaml.safe_load` 报 `ScannerError` line 48）。
- **修复**：将该步骤改为块标量 `run: |`；`yaml.safe_load` 复验通过，workflows API 名称由文件名占位恢复为"每日更新市场快照"，dispatch 返回 204。修复后手动运行 **run 45192190028 → success**（head = 修复 commit `9a5ef91`），闭环验证。
- **数据影响**：该 failure 发生在 workflow 解析阶段，**未执行取数脚本，未改动任何数据文件**；数据真实性不受影响。
- **教训**：workflow 单行 `run:` 含 `: ` 必须加引号或改用 `run: |`；已将复验纳入提交前检查。
- 本地 `data/run_log.json` 另记录每次脚本执行的精确计划/启动/完成时间（当前为本地手动运行样本）。
- **关于"连续 10 个自然日"**：仓库于 2026-11 建立，运行至今仅 2 个自然日，无法提供 10 日记录；这是客观事实，非遗漏。随项目持续运行，`run_log.json` 将逐日累积，约 10 日后自然满足。审计复核时可随时导出。

## 五、复核命令

```bash
# 查看本地运行记录（run_id/触发类型/启动/完成/延迟/结论/字段完整性）
python3 -c "import json; d=json.load(open('data/run_log.json')); [print(r['run_id'],r['trigger_type'],r['started_at'],r['completed_at'],r['delay_minutes'],r['conclusion']) for r in d['runs']]"

# 仅统计定时运行的真实延迟（手动运行 delay_minutes=null，自动排除）
python3 -c "import json; d=json.load(open('data/run_log.json')); print([(r['started_at'],r['delay_minutes']) for r in d['runs'] if r['trigger_type']=='scheduled'])"

# 漏跑核对：只看 scheduled 触发的计划日，手动运行不算定时任务成功
python3 -c "import json; d=json.load(open('data/run_log.json')); print(sorted({r['planned_utc'][:10] for r in d['runs'] if r.get('trigger_type')=='scheduled'}))"

# 导出 GitHub Actions 真实运行记录（需 token）
curl -sS -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/weixb1818-cmyk/wb-global-market-dashboard/actions/runs?per_page=100"
```

## 六、结论

- 计划时间、实际时间、延迟、失败状态均已实现如实记录；漏跑/失败可通过 run_log 逐日核对。
- 免费条件下的可靠性改进（并发防重入、超时、溯源文件入库、时间打点）已优先完成。
- 未购买服务器或第三方调度，符合零成本约束。
- 连续 10 日记录受项目运行时长所限暂不能满足，已给出累积机制与真实进度，不伪造数据。
