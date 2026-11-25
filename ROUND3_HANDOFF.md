# WB 下一轮整改清单 — 完成情况与交付说明

> 对应审计团队《WB 下一轮整改清单》及《关于 WB 下一轮整改三个技术口径的正式回复》。
> 本轮严格遵守最终边界：不增加 17 项以外的指标、不改指标定义、不调宏观阈值、不重新设计页面、不购付费数据、不填模拟历史。
> 本轮仅做数据异常边界与记录机制收尾；三个技术口径已按审计正式回复执行。

## 一、逐项完成情况

| # | 审计要求 | 落实 | 证据 |
|---|---|---|---|
| 1 | 宏观只接受明确 `ok`；未知/缺失状态一律阻断；补未知/缺失字段测试 | `classify_macro()` 改为**严格白名单**：仅 `statuses[k]=="ok"` 才放行；`stale/missing/error/unknown/空串/未定义值` 一律阻断；**未传或空 statuses 一律 insufficient**（审计明确拒绝按值降级）。生产调用 `build_snapshot()` 显式传全 7 项状态 | `core.py:classify_macro`；`tests/test_core.py:TestMacroFailClosed`（6 项）+ 既有 `TestMacroClassification`/`test_fault_isolation`/`test_history_threshold` 已改为显式传状态 |
| 2 | 黄金/WTI/铜页面直接显示延迟报价，避免误认实时可成交价 | 三商品在 `config.json` 标 `quote_nature=delayed_futures`；`core.quote_label()` 生成独立标签「延迟报价·非实时可成交价」写入快照 `quote_label` 字段；`app.js` 在卡片头以 `.quote-tag` 独立显示，真实报价日期由 `as_of` 单独展示。**标签与 status 语义完全分离**：不因 `realTime=false` 标 stale；请求失败/日期过期仍按原 status 规则处理；不对未证实实时属性的源标“实时” | `core.py:quote_label`；`scripts/update_data.py`；`app.js`/`styles.css`；`tests/test_quote_label.py`（5 项） |
| 3 | 持续积累真实历史；DXY 满 21 有效观测前不启用完整分类；不导入未核实历史 | 本轮**未导入任何历史**、未改数据源与口径；DXY 等 6 项仍为样本不足，`macro=insufficient`。21 观测边界测试已存在且保留 | `research/history_feasibility.md`；`tests/test_history_threshold.py`；快照 `macro.state=insufficient` |
| 4 | 完成连续 10 天运行观察；区分手动/定时；记录延迟/完成/失败；修正记录数量不一致 | 脚本层 `run_log.json` 每条含审计要求 8 字段（`run_id`/`trigger_type`/`started_at`/`completed_at`/`conclusion`/`script_started`/`snapshot_generated`/`commit_sha`）；三类触发互斥；**定时延迟只对 `scheduled` 计算，手动 `delay_minutes=null` 不计入**；建立脚本层/workflow 层映射，YAML 解析失败记为 workflow failure 且脚本未启动/无快照，不补造 | `scripts/update_data.py:append_run_log`；`tests/test_run_log.py`（8 项，含触发映射/手动不计延迟/8 字段）；`verification/run_reliability.md` |

## 二、第 4 项交付边界（审计已同意分阶段）

- **本轮**：交付机制 + 截至当前真实的 **2 个自然日**记录（Actions 6 次：5 success + 1 failure）。
- **10 天连续运行**：作为后续待验收项，待真实时间自然累积后单独补交；不伪造、不回填。
- 记录数量说明：`run_log.json`（脚本真实执行）与 `github_actions_runs.json`（全部 workflow run）口径不同，已建立映射；早期无脚本日志不补造。

## 三、测试与快照

- 单元测试：**Ran 95 tests ... OK**（原 65 + 上一轮新增 14：fail-closed 6 + 延迟标签 5 + 运行记录 3 + 第三轮技术修正新增 15：浏览器状态映射 5 + 数值有限性 10 + 调度时点调整新增 1），见 `verification/test_run.log`。
- 快照：真实数据更新成功；宏观 `insufficient`（DXY 等 6 项历史样本不足，未补造）；`crosscheck` 两组同日 0.00bp。
- 17 项指标定义、宏观阈值、页面布局均未变；仅新增卡片内一个延迟报价标签（审计要求）。

## 三之一、审计第三轮反馈 — 两个小型技术修正 + 文档修正（本轮完成）

审计第三轮对上一轮三项整改**全部验收通过**（综合 85/100），仅要求补齐两个防御性细节与运行记录文档口径，均已落实，**未新增第 18 项指标、未改指标定义/阈值/页面、未购数据、未回填历史、未重跑更新脚本**（快照与日志批次保持一致）。

| 审计要求 | 落实 | 证据 |
|---|---|---|
| 前端未知状态必须严格映射，不得用 `\|\| "已更新"` 兜底 | `app.js` 改为 `statusText()`/`statusClass()` 严格映射：ok=已更新、stale=数据延迟、missing=数据缺失、error=更新失败，**其余（unknown/未定义/空串/拼错）一律"状态未知，未验证"**；badge 样式类同样严格归为 unknown，不继承 ok 绿标 | `app.js`；`styles.css:.badge.unknown`；`tests/test_browser_status.py`（5 项，Playwright 渲染真实 app.js，断言 unknown/未定义不显示"已更新"） |
| 数值解析/历史合并/宏观分类入口增加 `math.isfinite`，排除 ±Inf | `core.is_finite_number()` 统一闸门；`_num()`、`merge_series()`、`classify_macro()`（即使 status=ok 也过闸门）三处必检点全部落实；并对 `compute_changes()`/`crosscheck_spread()` 加固。**不改变计算公式与宏观阈值** | `core.py`；`scripts/update_data.py`；`tests/test_finite_numbers.py`（10 项） |
| 运行记录文档明确两文件口径、failure 只计 workflow、早期记录不回填、修正"共5次"、漏跑只看 scheduled | `verification/run_reliability.md` 新增"记录口径与数量澄清"：run_log.json=实际执行脚本（6 条，5 早期原始结构+1 完整）、github_actions_runs.json=全部 workflow（6 条，5 success+1 failure）；解析失败只计 workflow 不补造；早期保留原始结构；统一按实际 6 条披露，不再用"共5次"；漏跑仅以 `scheduled` 计划日比对，手动不算定时成功 | `verification/run_reliability.md`；`tests/test_run_log.py` |

## 四、特别声明

本轮**未导入任何未核实的 DXY / 商品 / 加密历史**。拒绝口径不一致的免费历史数据是经审计认可的正确金融工程决策，本轮继续坚持：品种、单位、日期、计算口径不一致的数据一律不导入；DXY 未达 21 个有效观测前不启用完整宏观分类。

## 五、提交信息

- 仓库：`https://github.com/weixb1818-cmyk/wb-global-market-dashboard`（main）
- 最终 commit：见交付回复（以 main HEAD 为准，避免 commit 号自指）
- 关键证据：`verification/test_run.log`、`verification/update_run.log`、`verification/run_reliability.md`、`data/run_log.json`、`data/snapshot.json`
