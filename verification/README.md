# 运行证据（供第三轮独立复核）

本目录保存第二轮整改后的实际运行证据，均可对照源码复现。

## 1. 单元测试完整结果

- 文件：`test_run.log`
- 命令：`python3 -m unittest discover -s tests -v`
- 结果：**Ran 43 tests ... OK**（原 36 项 + 终轮整改新增 7 项）
- 新增项涵盖：CNBC 合法/无/非法时间戳解析、无/非法时间戳报价进 failed、端到端不回填系统日期，以及两项可选测试（FRED 单序列失败隔离、宏观全 stale fail-closed）。

## 2. 更新脚本运行日志

- 文件：`update_run.log`（**与当前 `snapshot.json` 同一批次**，run `45166640886` / commit `3863434`）。
- 命令：`python3 scripts/update_data.py`（由 GitHub Actions 执行）。
- 结果：`失败源=[]`，全部真实数据源取数成功；`快照已写入 … 宏观状态=insufficient`。
- 日志逐条记录 FRED 各序列、CNBC 各报价、currency-api 各币种的观测数与数据日期。
- Actions runner 时区为 UTC，日志时间戳 `11:36:xx` 与快照 `generated_at=20:36:21+09:00` 是同一绝对时刻 `2026-11-23T11:36:21Z`；日志中行情数值（如 `CNBC dxy 103.905`、`gold 3620.8`）与快照逐项吻合。
- 原始带 GitHub 时间戳的完整步骤日志：`actions_run_45166640886.log`。此前另有一次本地预验证运行（`19:33:35 +08:00 = 11:33:35Z`），属**不同批次**，已被 Actions 批次覆盖，不再作为当前快照的对应日志。

## 3. 更新后的数据文件

- `data/snapshot.json`：本轮生成的快照，含 `failed_indicators` 字段（本轮为空 `{}`）。
- `data/history.json`：滚动历史（FRED 每条序列保留最近 400 个有效观测、外汇 25 期、CNBC 系每日累积）。
- 宏观状态当前为 `insufficient`（数据不足：暂不判断），原因：DXY/黄金/WTI/铜/BTC/ETH 近20期历史样本不足，需每日运行累积，未用假数据补齐。

## 4. P2 页面小字验收

在 `data/snapshot.json` 中核对：

| 指标 | observations | status | change_20 | note |
|---|---|---|---|---|
| dxy / gold / wti / copper / btc / eth | 2 | ok | null | 历史样本不足，等待积累 |
| us2y / hy_oas（历史完整） | 400 | ok | 有值 | 正常趋势解读 |

即：当前数据正常、仅历史样本不足时，显示"历史样本不足，等待积累"；数据真正失败/过期时才显示"数据暂未更新"。

## 5. 自动更新工作流

- `.github/workflows/update.yml`：每日 UTC 00:15（东京 09:15）定时运行，并支持 `workflow_dispatch` 手动触发；`permissions.contents: write`；步骤为 检出 → 装依赖 → 跑测试 → 取数 → 提交 `data/`。
- Actions 运行记录见仓库 Actions 标签页；最近一次手动触发的 run ID 在交接说明中给出。

## 6. 终轮（CNBC 时间戳边界）复核点

- 时间戳解析：合法 `2026-11-20` / `11/20/26 EST` 通过；`2026-13-45`、`02/30/26`、`garbage`、空值一律判为无效。
- 无/非法时间戳的 CNBC 报价进入 `failed_indicators`、不进有效报价，指标标 `stale` 并沿用上次有效值。
- 端到端断言 `build_snapshot()` 不把系统当天日期写入历史（`test_snapshot_does_not_backfill_system_date`）。
- 两项可选测试：`test_one_fred_series_failure_does_not_affect_others`、`test_all_stale_inputs_force_insufficient` 均通过。

## 7. 执行机时钟、日志批次与时间口径核对（终轮收尾）

审计方指出两点，均属实并已据实处理：

### 7.1 两份文件原属不同运行批次（已修正日志）

初核对时误将两次不同运行的产物放在一起比较：

| 文件 | 原取值 | 所属批次 |
|---|---|---|
| `update_run.log`（旧） | `19:33:35 +08:00` = `11:33:35Z` | 本地预验证运行（commit `7af5333` 附带） |
| `snapshot.json`（当前） | `20:36:21 +09:00` = `11:36:21Z` | Actions run `45166640886` / commit `3863434` |

二者相差约 2 分 46 秒，确属**不同运行批次**，不是时钟错误。修正措施：`update_run.log` 已替换为**生成当前快照的同批次** Actions 日志（`11:36:15`–`11:36:21Z`，runner 时区 UTC，=`20:36:15`–`20:36:21+09:00`），日志中 `dxy 103.905` 等行情数值与快照逐项吻合；原始带 GitHub 时间戳的日志存于 `actions_run_45166640886.log`。

### 7.2 时区换算正确，但不以 `date`/`date -u` 冒充 NTP 证据

- 时区换算：`11:36:21Z`（Actions runner，UTC）= `20:36:21+09:00`（快照，Asia/Tokyo）= `19:36:21 +08:00`（本地），均为同一绝对时刻；审计方此前给出的 `11:33:35Z = 20:33:35+09` 换算式同样正确（那是被覆盖的旧批次）。
- `date` 与 `date -u` 只能证明本机两时区表示一致，**不能独立证明 NTP 同步精度**。本沙箱无 systemd/chrony/ntpq（`timedatectl` 报 "System has not been booted with systemd"，`chronyc`/`ntpq` 未安装），因此**不声称具备独立 NTP 守护进程**。
- 替代证据（外部时间基准比对，可复现）：本机 `date -u` 与 `curl -sSI https://api.github.com` 响应头 `Date:` 对比，实测为 `12:02:22Z`（本机）对 `12:02:15 GMT`（GitHub），**偏差约 7 秒**。说明执行机时钟由宿主同步、与外部基准基本一致，不存在足以影响"日更新"粒度的漂移。

### 7.3 真实数据日期未受任何影响

各指标 `as_of`（CNBC `@ 2026-11-23`、FRED `observation_date`）直接取自数据源，与上述生成时间戳/日志时间是**互相独立的字段**。本轮只替换了证据日志文件，**未改动任何 `snapshot.json` / `history.json` 的数据值或行情日期**。复核时间相关字段时，请统一换算为 UTC（`Z`）或带偏移绝对时刻比较，勿按字面本地时间直接相减。
