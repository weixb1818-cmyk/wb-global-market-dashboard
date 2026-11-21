# 审计文档：全球市场每日观察面板（P0 / V1.0）

> 本文供第三方逐项核对：**每个指标的数据源、字段、单位、计算口径、时间戳与缺失处理**。
> 所有实现均可在同目录源码中核对：`core.py`（纯逻辑）、`scripts/update_data.py`（取数与生成）、`config.json`（阈值与源映射）、`tests/test_core.py`（验收测试）。
> 审计基准版本：`config.json` 的 `version = 1.0`；快照生成时区 `Asia/Tokyo (UTC+9)`。

## 公开源码仓库（供第三方 clone / 本地复现测试）

- 仓库分支：`weixb1818-cmyk/global-market-monitor` 的 **`audit-p0-v1`** 分支（与仓库 main 分支的另一实现版本隔离，未覆盖任何现有代码）。
- Clone：
  ```bash
  git clone -b audit-p0-v1 https://github.com/weixb1818-cmyk/global-market-monitor.git
  cd global-market-monitor
  python3 -m pip install -r requirements.txt
  python3 -m unittest discover -s tests -v     # 复现 26 项测试
  ```
- 四个核心文件免登录直读：
  - `core.py`：`https://raw.githubusercontent.com/weixb1818-cmyk/global-market-monitor/audit-p0-v1/core.py`
  - `config.json`：`https://raw.githubusercontent.com/weixb1818-cmyk/global-market-monitor/audit-p0-v1/config.json`
  - `scripts/update_data.py`：`https://raw.githubusercontent.com/weixb1818-cmyk/global-market-monitor/audit-p0-v1/scripts/update_data.py`
  - `tests/test_core.py`：`https://raw.githubusercontent.com/weixb1818-cmyk/global-market-monitor/audit-p0-v1/tests/test_core.py`
- 在线审计页：托管地址形如 `https://<host>/audit.html?sharecode=<访问码>`（访问码由发布方通过分享链接单独提供，不在源码仓库中硬编码；从带 sharecode 的入口进入后，站内源码链接会自动透传凭据）。

## 数据用途与许可声明（回应审计反馈）

本项目为**非商业的个人学习与技术研究用途**，页面不含投资建议，不转售、不再分发原始数据，并已按数据源标注出处与免责声明。我们理解公开托管可能超出严格意义的"个人使用"范畴，故在此如实披露各数据源的权利归属与许可风险：FRED 为免费分发方（数据多源自美国财政部等公共领域机构），但 `SP500`/`NASDAQ100`/`VIXCLS`/`BAMLH0A0HYM2` 的原始版权分别属于 S&P Dow Jones Indices、Nasdaq、CBOE、BofA；ICE U.S. Dollar Index 为 ICE 注册商标，经 CNBC 非官方接口转发；CNBC 与 currency-api 均无 SLA 或公开分发许可。若后续拟公开商用或面向公众提供服务，应先行取得相关指数权利方（ICE、S&P DJI、Nasdaq、CBOE、BofA）的授权，或改用具备公开分发许可的数据源。以上为工程角度的事实披露，不构成法律意见；如审计方为机构，建议由法务复核。

---

## 一、数据源清单（均为真实源，无模拟数据）

| 代号 | 名称 | 端点模板 | 认证 | 用途 |
|---|---|---|---|---|
| FRED | St. Louis Fed CSV | `https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}` | 无 | 美债收益率、利差、VIX、HY OAS、SP500、NASDAQ100；源端含完整日历史，**本地 `history.json` 仅保留最近 400 期滚动窗口**（`MAX_HISTORY=400`） |
| CNBC | CNBC 公开报价 | `https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={SYMBOLS}&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json` | 无 | 原生 ICE DXY、股指、COMEX/NYMEX 近月期货、BTC/ETH 现货；当前值与前收盘 |
| currency-api | 开源汇率经 jsDelivr | `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/usd.min.json`；`...@latest/...` | 无 | USD/JPY、USD/CNH 日快照；按日期可回溯约 25 天 |
| CoinGecko | 官方 API（可选） | `https://api.coingecko.com/api/v3/coins/{coin}/market_chart?vs_currency=usd&days=30&interval=daily` | `COINGECKO_API_KEY`（环境变量，放 GitHub Secrets） | 可选加密历史；默认关闭（`config.json` 中 `enabled=false`） |

**请求头注意（可复现性关键点）**：FRED 对 `curl/7.81.0` 以外的 UA 会返回连接重置；CNBC 则需要浏览器 UA。实现中通过 `config.json` 的 `network.user_agent`（默认 `curl/7.81.0`）与 `sources.cnbc.user_agent` 分别设置。若第三方复现失败，请先核对 UA。

**未采用及原因**：Stooq / Yahoo Finance / CoinGecko（默认）/ Binance / Coinbase 在开发环境超时或 HTTP 429；FRED 的 `DTWEXBGS` 是贸易加权美元指数，规格禁止冒充原生 DXY，故不用；CNBC 免费接口不提供可回溯日线历史。

---

## 二、17 个指标逐项审计

### 通用计算定义（适用于下表全部指标）

- **有效观测**：数值字段非 `null`、非 `.`（FRED 缺失标记）、非 `NA`，且日期为 `YYYY-MM-DD` 可解析。
- **`value`**：按日期升序合并后的最新有效观测（新抓取优先于历史同日值）。
- **`change_1`（日变化）**：优先采用数据源自带日变化（CNBC 的 `change_pct`）；否则按相邻两个有效观测计算。
- **`change_20`（近20期变化）**：当前值相对 **倒数第 21 个** 有效观测的变化，即最近 **20 个有效观测间隔**；观测数 < 21 时返回 `null`，页面显示 `—`。不是减 20 个日历日。
- **换算函数**（`core.py`）：
  - 价格 / 指数 / 外汇 / DXY：`(current / previous - 1) × 100`，单位 `%`
  - 收益率 / 利差：`(current - previous) × 100`，单位 `bp`
  - VIX：`current - previous`，单位 `点`
  - FRED 利差水平转 bp：`value × 100`
- **`as_of`**：最新有效观测的数据源日期，逐卡展示；总览声明"本页数据截至各卡标注日期"。
- **`status`**：`ok` / `stale`（延迟）/ `missing`（无数据）/ `error`（取数失败）；后三者小字固定为"数据暂未更新，截至 YYYY-MM-DD"，不生成方向性解读。

### 2.1 宏观组（8 项）

| # | 指标 | 数据源与标识 | 原始字段 → 显示值 | 单位换算 | 变化计算 | as_of 来源 |
|---|---|---|---|---|---|---|
| 1 | 美元指数 DXY | CNBC `.DXY`（ICE U.S. Dollar Index） | `last` → 指数点 | 无 | `change_pct`；历史由 `history.json` 累积后按 `%` 公式 | `last_time` |
| 2 | 美国2年期国债收益率 | FRED `DGS2` | `DGS2` 数值 → `4.76%` | 原值即百分数，显示 `%.2f%%` | `(cur-prev)×100` → bp | CSV `observation_date` |
| 3 | 美国10年期国债收益率 | FRED `DGS10` | 同上 | 同上 | 同上 | 同上 |
| 4 | 美国10年期实际收益率 | FRED `DFII10`（10年 TIPS 收益率，非 CPI 相减） | 同上 | 同上 | 同上 | 同上 |
| 5 | 10Y-2Y 利差 | FRED `T10Y2Y`（**原始序列**，非自行相减） | 原始 `0.29` → `+29bp` | `×100`；带正负号 | `(cur-prev)×100` → bp | 同上 |
| 6 | 10Y-3M 利差 | FRED `T10Y3M`（原始序列） | 同上 | 同上 | 同上 | 同上 |
| 7 | VIX | FRED `VIXCLS`（收盘） | 原始点数 → `28.44` | 无 | `cur-prev` → 点（**不用百分比**） | 同上 |
| 8 | HY OAS | FRED `BAMLH0A0HYM2`（期权调整信用利差，非债券收益率） | 原始 `3.52` → `352bp`（不带正号） | `×100` | `(cur-prev)×100` → bp | 同上 |

**利差校验**：`tests/test_core.py` 验证 `DGS10=4.30, DGS2=4.00 → 10Y-2Y=+30bp`、`DGS10=4.00, DGS2=4.50 → -50bp`；利差水平若与同日 DGS10/DGS2 相差超过合理误差会记录告警（实现中使用 FRED 原始利差为主值，不以跨日相减结果替代）。

### 2.2 美股组（2 项）

| # | 指标 | 数据源与标识 | 原始字段 → 显示值 | 变化计算 | as_of 来源 |
|---|---|---|---|---|---|
| 9 | 标普500指数 | FRED `SP500`（指数本身，非 SPY ETF）+ CNBC `.SPX` 补充最新日 | `last` → 点 | `change_pct`；无该字段时按合并序列 `%` 公式 | `last_time` / CSV 日期 |
| 10 | 纳斯达克100指数 | FRED `NASDAQ100`（**非**纳斯达克综合指数）+ CNBC `.NDX` | 同上 | 同上 | 同上 |

说明：FRED 序列提供完整历史，CNBC 提供更新一日的收盘；`merge_series()` 按日期去重合并后计算，因此"近20期"来自同一指数的连续有效观测，不混入 ETF。

### 2.3 大宗组（3 项，均为近月期货）

| # | 指标 | 数据源与标识 | 单位 | 变化计算 | as_of 来源 |
|---|---|---|---|---|---|
| 11 | 黄金 COMEX 近月期货 | CNBC `@GC.1`（名称含合约月份，如 Dec'26） | USD/oz | `change_pct`；历史累积后按 `%` 公式 | `last_time` |
| 12 | WTI NYMEX 近月期货 | CNBC `@CL.1`（合约月份固定口径） | USD/bbl | 同上 | 同上 |
| 13 | 铜 COMEX 近月期货 | CNBC `@HG.1` | USD/lb（**不是** USD/吨） | 同上 | 同上 |

合约换月：CNBC 的 `.1` 代表近月连续报价；页面名称显示其实际合约月份，避免"期货写成现货"。换月跳跃属于真实市场口径，不由脚本平滑处理。

### 2.4 加密组（2 项，现货口径）

| # | 指标 | 数据源与标识 | 单位 | 变化计算 | as_of 来源 |
|---|---|---|---|---|---|
| 14 | BTC 现货 | CNBC `BTC=`（Bitcoin/US Dollar FX Spot Rate）；可选 CoinGecko `bitcoin` 覆盖 | USD | `change_pct`；CoinGecko 启用时按 `%` 公式 | `last_time` / UTC 日 |
| 15 | ETH 现货 | CNBC `ETH=`（Ether/US Dollar FX Spot Rate）；可选 CoinGecko `ethereum` | USD | 同上 | 同上 |

BTC/ETH 为 24×7 市场：`is_stale()` 对 `kind=crypto` 采用 **36 小时**阈值（其余指标采用"超过 2 个预期发布交易日"）；近20期口径为 20 个日观测（约 20 天）。**未使用**灰度 ETF（`BTC`、`ETH` 符号）冒充现货。

### 2.5 外汇组（2 项）

| # | 指标 | 数据源与标识 | 原始字段 → 显示值 | 变化计算 | as_of 来源 |
|---|---|---|---|---|---|
| 16 | USD/JPY | currency-api `usd.jpy` | 1 美元折合日元，显示 `%.3f` | 相邻观测 `%` 公式 | 快照 JSON 的 `date` 字段 |
| 17 | USD/CNH（离岸） | currency-api `usd.cnh` | 1 美元折合离岸人民币，显示 `%.3f` | 同上 | 同上 |

**方向含义**：上涨 = 美元相对日元/离岸人民币升值（`card_note()` 明确写出），下跌则反之。**未使用** `usd.cny`（在岸）替代 CNH。

---

## 三、宏观状态识别审计

### 3.1 输入（全部来自上表指标的近20期变化或当前水平）

`dxy20`、`real20bp`（10Y实际）、`twoYear20bp`（2Y）、`hy20bp`、`vix20pt`、`hyNow`、`vixNow`。
利差与 10Y 名义收益率仅作解释项，不独立加权。

### 3.2 阈值（`config.json` → `macro_thresholds`，非硬编码）

| 条件 | 阈值 | 方向 |
|---|---|---|
| 美元显著走强 / 走弱 | `dxy20 >= +1.0%` / `<= -1.0%` | 强 / 弱 |
| 实际利率显著上行 / 下行 | `real20bp >= +15` / `<= -15` | bp |
| 信用风险走高 | `hy20bp >= +25bp`；高位 `hyNow >= 450bp` | bp |
| 波动风险走高 | `vix20pt >= +3点`；高位 `vixNow >= 25` | 点 |
| 短端显著下行 | `twoYear20bp <= -25bp` | bp |

### 3.3 分类顺序（`core.py: classify_macro()`，按顺序匹配，只显示一个主状态）

1. **金融压力扩散**：`hy20bp >= +25` 且 `vix20pt >= +3`
2. **增长担忧定价**：`twoYear20bp <= -25` 且（`hy20bp >= +25` 或 `vix20pt >= +3`）
3. **金融条件趋紧**：`dxy20 >= +1.0` 且 `real20bp >= +15`
4. **温和宽松**：`dxy20 <= -1.0` 且 `real20bp <= -15` 且 `hy20bp < +25` 且 `vix20pt < +3` 且 `hyNow < 450` 且 `vixNow < 25`
5. **中性/信号分歧**：其余，列出互相矛盾的信号，不强行看多/看空

### 3.4 强制约束

- 上述 7 个输入中**任一关键 20 期数据缺失或超期** → 输出 `数据不足：暂不判断`，并列出缺失项；**不沿用昨日结论**。
- 高位但大幅回落不判为"扩散"（规则 1 要求 20 期同时上行）。
- 顶部结构为"状态 + 为什么 + 不确定因素"。
- 禁止输出买入/卖出/做多/做空/必涨等投资指令；倒挂恢复不得写成"经济复苏"。

### 3.5 当前部署的真实状态

截至本次生成，FRED 系指标（历史 400 期）与外汇 USD/JPY、USD/CNH（历史 25 期）已具备 20 期变化；以下 **6 个指标的 20 期变化当前均为空（`—`）**：**DXY、黄金 COMEX、WTI、铜 COMEX、BTC、ETH**——它们的 `history.json` 目前各只有 **1 个观测**，近20期变化依赖脚本每日运行累积（CNBC 免费接口不提供可回溯日线）。因此宏观状态正确显示为"数据不足：暂不判断（缺少 dxy20 等）"。这是规格要求的行为，**不是故障**，也不通过补造历史规避。注意 `change_20` 需要 **21 个有效观测**（当前值 + 倒数第 21 个），即再积累 20 个交易日后才会自动转为正常分类。

---

## 四、小字解读审计（`core.py: card_note()`）

按指标 ID 使用固定中文模板，阈值来自 `config.json → note_thresholds`，无大模型、无随机性。要点：

- DXY 近20期 ≥ +1% → "美元走强，关注全球风险资产压力"；≤ -1% → "美元走弱，外部美元压力可能缓解"
- 2Y ≤ -25bp → "短端利率下行，市场可能增加降息定价"；≥ +25bp → "短端利率上行，政策利率预期偏紧"
- 10Y / 实际利率 / VIX / HY OAS 按各自阈值输出上行/下行/稳定文案
- 10Y-2Y、10Y-3M：先判倒挂/正利差，再按 ±15bp 补"曲线变陡/变平"；变陡时用同日 2Y/10Y 变化解释"短端下降更快/长端上升更快/混合驱动"，不提示看多
- 外汇按方向写"美元相对日元/离岸人民币升值/贬值"
- 数据缺失或 `change_20 is None` → "数据暂未更新，截至 YYYY-MM-DD"，**不生成方向性解读**

---

## 五、时间、过期与失败处理审计

| 场景 | 实现 |
|---|---|
| 美股/期货/外汇 | 使用数据源最新已完成交易时段；逐卡显示 `as_of` |
| BTC/ETH | 24×7；超过 36 小时无新日值标 `stale` |
| 普通指标延迟 | `expected_trading_days_between(as_of, today) > 2` 标 `stale`（含美国主要假日与周末判断） |
| 周末/美国假日 | 正常休市不虚报故障；页面标注各卡日期与"非同一时刻实时行情" |
| 单源失败 | 保留上一次有效值并标 `stale`，记录 `failed_sources`；不影响其他指标 |
| 数据损坏 | 原子写入（临时文件 + `os.replace`）；格式校验失败不写快照 |
| 浏览器端 | 只读取静态 JSON/JS，不暴露任何 API Key，无实时 WebSocket |

---

## 六、测试覆盖（`tests/test_core.py`，26 项全通过）

1. 17 指标名称与单位完整且正确；配置中无就业/ISM/CPI 等越界指标
2. 10Y-2Y 正负 bp 计算；HY OAS 3.20% → 320bp；变化不混淆 `%` 与 `bp`
3. USD/CNH、USD/JPY 方向文案正确
4. 五种宏观状态分支 + 高位回落不误判 + 关键数据缺失不判断 + 无投资指令措辞
5. 曲线由 -20bp 到 +10bp 只写"倒挂结束/曲线变陡"，不写"经济复苏"
6. 近20期需 21 个观测；日变化优先用源自带值
7. 周末不误报、`>2` 交易日与加密 36 小时阈值、假日表存在
8. 小字长度上限 45 字；缺失数据文案含日期且无方向词

运行方式：`python3 -m unittest discover -s tests -v`

---

## 七、已知限制（供审计判定，非隐瞒项）

- CNBC 为公开网页报价接口，非有 SLA 的官方开发者 API；currency-api 为社区源，非央行官方源。稳定性与使用条款见 `README.md`。
- CoinGecko 在开发环境不可达，适配器已实现但默认关闭；启用后覆盖 CNBC 加密源。
- DXY / 黄金 / WTI / 铜 / BTC / ETH 的近20期变化依赖每日运行累积，初始部署显示 `—`，宏观判断相应显示"数据不足"。
- 宏观规则为 V1 解释性分类，阈值未经回测，不声称科学预测。
- 本审计文档随源码一同发布；如数据与文档不一致，以 `config.json` 与快照 `data/snapshot.json` 的实际字段为准。
