# 运行证据（供第三轮独立复核）

本目录保存第二轮整改后的实际运行证据，均可对照源码复现。

## 1. 单元测试完整结果

- 文件：`test_run.log`
- 命令：`python3 -m unittest discover -s tests -v`
- 结果：**Ran 43 tests ... OK**（原 36 项 + 终轮整改新增 7 项）
- 新增项涵盖：CNBC 合法/无/非法时间戳解析、无/非法时间戳报价进 failed、端到端不回填系统日期，以及两项可选测试（FRED 单序列失败隔离、宏观全 stale fail-closed）。

## 2. 更新脚本运行日志

- 文件：`update_run.log`
- 命令：`python3 scripts/update_data.py`
- 结果：`update_rc=0`，`失败源=[]`，全部真实数据源取数成功。
- 日志逐条记录 FRED 各序列、CNBC 各报价、currency-api 各币种的观测数与数据日期。

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
