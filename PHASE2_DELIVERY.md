# 全球市场每日观察面板 — 下一阶段质量提升交付说明

> 阶段：V1.0 技术验收通过后，零成本质量提升阶段。
> 约束遵守：17 项指标不变、单页架构不变、宏观规则阈值不变、不开发交易系统、不增加预测模型、不补造历史、不购买数据。

## 交付总览（对应审计 7 项要求）

| # | 审计要求 | 交付物 | 状态 |
|---|---|---|---|
| 1 | 最终 Commit 及变更说明 | 本文档末节 + GitHub commit | ✅ |
| 2 | 17 项指标数据质量核验 | `research/history_feasibility.md` | ✅ |
| 3 | 商品连续合约与利差核验 | `research/commodity_contracts.md` + 快照 `crosscheck` | ✅ |
| 4 | 宏观规则历史案例与误判分析 | `research/macro_case_study.md` + `scripts/macro_case_study.py` | ✅ |
| 5 | 每日更新与异常处理记录 | `verification/run_reliability.md` + `data/run_log.json` | ✅（含边界说明） |
| 6 | 自动测试结果及未解决限制 | `verification/test_run.log`（65 项）+ 本文档 | ✅ |
| 7 | 数据来源严谨性证据 | `research/*` + `data/provenance.json`（原文仅本地留存，不公开） | ✅ |

## 一、P0 提高宏观判断可用性

- **免费历史源可行性**：实测 9 类候选源（Stooq/Yahoo/CoinGecko/CNBC 图表子域/Twelve Data/FRED/macrofinance 等），唯一取到数据的 macrofinance DXY CSV 因**周日收盘价异常、品种口径未证实、日收盘 vs 实时口径不同、授权不明**被排除。**未导入任何历史**。
- **口径一致性核对**：逐项核对品种/单位/日期/计算口径，结论详见 `research/history_feasibility.md`。
- **21 观测达标测试**：新增 5 项，覆盖恰好第 21 点 `change_20` 从 `null` 转有效、`insufficient` 转正常分类、不足 21 点不得近似。
- 六项指标（DXY/黄金/WTI/铜/BTC/ETH）继续自然积累，宏观维持 `insufficient`——**合规行为，非故障**。

## 二、P1 商品可比性

- 实测 CNBC 报价：黄金 `Gold COMEX (Dec'26)`、WTI `WTI Crude (Jan'27)`、铜 `Copper (Dec'26)`，均为**近月期货、延迟报价、USD/oz·bbl·lb**。
- CME 官方规格核对：交易所（COMEX/NYMEX）、合约单位、报价单位**一致**。
- 明确区分"已验证"（交易所/单位/近月合约/时间）与"供应商定义未公开"（`.1` 换月时点、复权方式）。
- 跨换月涨跌幅含合约切换因素，已在小字与文档加**限制提示**，不解释为可交易信号。

## 三、P1 美债利差交叉验证

- 新增纯函数 `core.crosscheck_spread()`：**只比同日** T10Y2Y vs DGS10−DGS2、T10Y3M vs DGS10−DGS3MO，`|差异|>2bp` 告警，同日不齐标记 `unverifiable`，**不跨日期强行计算**。
- 快照新增 `crosscheck` 字段。真实数据验证：两组均 `ok`、差异 **0.00bp**、同日 2026-11-19。
- 新增 7 项测试（一致/告警/边界/日期错位/单腿缺失/真实值/取最近共同日）。
- 实测边界：11-20 利差序列比收益率序列快一天，正确标记为无法核验。

## 四、P1 宏观规则投资参考价值（核心）

- 用 400 期真实 FRED 历史做**无前视偏差**复盘：T 日信号只用 T 及之前数据，T+20 表现取 T 之后。
- 五场景逐一验证，有效与误判并列（如压力状态后续上涨占比 46% vs 其他 68%，但有 +12.64% 的误判案例）。
- 关键发现：本窗口内股市显著上涨**从未**伴随 HY 与 VIX 同时恶化（0 例反例），说明指标体系在上涨期无虚假警报。
- 结论：指标是**状态温度计，不是择时器**；对风险管理有帮助（识别防御环境、区分降息驱动），但不产生买卖信号。
- 局限如实说明：窗口仅约 1.5 年、DXY 与加密历史不足、未含危机样本。

## 五、P2 更新可靠性

- 计划时间北京时间 08:15（cron UTC 00:15），workflow 记录计划/启动/完成时刻。
- `data/run_log.json` 追加式记录延迟、时长、状态、失败源；失败/漏跑可逐日核对。
- 修复 workflow 遗漏：溯源文件纳入每日 `git add`。
- **真实记录**：6 次 Actions 运行（11-22、11-23 两天；5 success + 1 failure），固化于 `verification/github_actions_runs.json`。其中 failure（`45190822884`）为本阶段首次提交触发、因 workflow YAML 语法错误在解析阶段失败，已修复并以 `45192190028` success 闭环；详见 `verification/run_reliability.md`。当前快照与该 success run 同批次，日志见 `verification/update_run.log`（原始步骤日志 `actions_run_45192190028.log`）。
- **边界**：运行时长不足 10 个自然日，无法提供 10 日记录，不伪造；给出累积机制。

## 六、P2 审计复现

- `requirements.txt` 精确锁定 5 个依赖版本（`pip freeze` 实测）。
- `data/provenance.json`：37 条请求记录（FRED 10 / CNBC 1 / currency-api 26），含完整 URL、UTC 日期、HTTP 状态、响应 sha256，随每日运行提交公开仓库。
- `data/raw/fred/`：10 个 FRED 原始 CSV 在**本地留存供审计核对**，但**不提交公开仓库**（`data/raw/` 已加入 `.gitignore`）——FRED CSV 可免费下载，但其中 SP500/NASDAQ100/VIX/HY OAS 原始版权归指数方，全文再分发授权未明确，按审计要求"不得公开不允许再分发的第三方原始数据"处理。CNBC/currency-api 同样只记哈希、不存原文。
- 因此公开仓库只含**哈希与元数据**（可核不可读原文），原始响应的本地留存供有授权的审计方现场核验；历史 → 计算 → 快照全链路可追溯。

## 七、未解决限制（如实清单）

1. DXY、黄金、WTI、铜、BTC、ETH 历史仍不足 21 期，宏观维持 `insufficient`——免费口径不可得，自然积累中。
2. 宏观复盘窗口短（约 1.5 年）、无危机样本，统计显著性有限。
3. 连续 10 日运行记录未满（项目运行不足 10 日），持续累积中。
4. 无主动漏跑告警（零成本约束，未接付费通知）；可人工按 run_log 核对。
5. CNBC `.1` 连续合约换月规则为供应商定义，未公开、未核实。
6. 数据授权仍作为独立合规事项保留，技术交付不代表已取得再分发授权。

## 八、评分对应

| 评分项 | 分值 | 本阶段工作 |
|---|---|---|
| 数据来源严谨性 | 40 | 9 类源实测、口径逐项核对、provenance 哈希链、原文本地留存不公开、明确排除不合格源 |
| 指标计算合理性 | 30 | 利差同日交叉验证（0bp）、21 观测达标测试、跨换月限制提示、负零规范化 |
| 投资决策参考价值 | 30 | 无前视 5 场景复盘、有效/误判并列、"状态温度计非择时器"结论、明确不产生买卖信号 |

## 九、最终 Commit 与变更说明

- 仓库：`https://github.com/weixb1818-cmyk/wb-global-market-dashboard`（main）
- 提交内容：
  - 研究文档：`research/history_feasibility.md`、`commodity_contracts.md`、`macro_case_study.md`
  - 代码：`core.py`（crosscheck_spread）、`scripts/update_data.py`（交叉验证 + 溯源 + 运行记录）、`scripts/macro_case_study.py`、`provenance.py`
  - 配置：`config.json`（crosscheck 阈值、schedule、run_log）、`requirements.txt`（锁定版本）
  - 测试：`tests/test_crosscheck.py`、`test_history_threshold.py`、`test_provenance.py`、`test_run_log.py`（共 65 项）
  - 数据：`data/snapshot.json`（含 crosscheck）、`data/provenance.json`、`data/run_log.json`（`data/raw/fred/` 原始响应仅本地留存，不提交）
  - 工作流：`.github/workflows/update.yml`（时间打点 + 溯源文件入库）
  - 证据：`verification/*`（test_run.log、update_run.log、actions_run_45192190028.log、macro_case_study.log、github_actions_runs.json、run_reliability.md）
- Commit ID（按时间顺序）：
  - `6bbddeb93072c8ff709f8f4cd5972d083e0b5a23`：本阶段主体（研究/代码/测试/数据/文档）
  - `9a5ef91e7d1e498a2221c6e87f08cc66c3560988`：修复 workflow YAML 语法错误（该错误导致首次 push run `45190822884` failure、手动 dispatch 返回 422）
  - `610137102705f97bf2394ccef5f05cb80a4c448e`：补全失败 run 诊断闭环与完整 Actions 证据
- 最终 HEAD 以仓库 main 分支为准（上述为关键里程碑 commit）；修复后手动运行 `45192190028` success。
