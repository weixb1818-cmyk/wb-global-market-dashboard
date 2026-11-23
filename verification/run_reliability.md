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

## 三、漏跑 / 失败发现机制

- **失败发现**：任一源级失败 → `status=fail`；仅逐指标失败 → `status=partial`；全部成功 → `ok`。快照中 `failed_sources`/`failed_indicators` 同步记录。
- **漏跑发现**：`run_log.json` 每条记录带 `planned_utc`；按日比对即可发现缺失日期。但未实现主动告警（受免费条件与零成本约束，不接入付费通知服务）。给出复核命令（见第五节），人工/审计可随时核对。
- **改进已做**：workflow 的 `git add` 已纳入 `data/provenance.json`、`data/run_log.json`，确保溯源文件随每日提交入库（此前遗漏，本轮修复）。`data/raw/`（原始响应）按合规要求仅本地留存、不提交公开仓库。

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

# 导出 GitHub Actions 真实运行记录（需 token）
curl -sS -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/weixb1818-cmyk/wb-global-market-dashboard/actions/runs?per_page=100"
```

## 六、结论

- 计划时间、实际时间、延迟、失败状态均已实现如实记录；漏跑/失败可通过 run_log 逐日核对。
- 免费条件下的可靠性改进（并发防重入、超时、溯源文件入库、时间打点）已优先完成。
- 未购买服务器或第三方调度，符合零成本约束。
- 连续 10 日记录受项目运行时长所限暂不能满足，已给出累积机制与真实进度，不伪造数据。
