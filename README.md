# 全球市场每日观察面板

一个无需登录、每天看一眼的单页金融仪表盘。严格实现开发规格 **V1.0 的 P0 功能**：固定 17 个指标、真实数据、每日更新、宏观状态识别、逐卡中文小字解读，以及缺失/延迟/休市处理。**不含**就业、ISM、CPI、自动交易、复杂预测或交易信号。

## 1. 快速开始（本地）

```bash
git clone https://github.com/weixb1818-cmyk/wb-global-market-dashboard.git
cd wb-global-market-dashboard
python3 -m pip install -r requirements.txt      # 仅需 requests
python3 -m unittest discover -s tests -v         # 运行测试
python3 scripts/update_data.py                   # 抓取真实数据，生成快照
```

打开页面有两种方式：

1. **直接双击 `index.html`**（推荐，最快）：页面读取 `data/snapshot.js`，无需本地服务器。
2. **本地服务器**：`python3 -m http.server 8000`，然后访问 `http://localhost:8000/`。此时页面优先读取 `data/snapshot.js`，若不存在则回退 `fetch('data/snapshot.json')`。

> 第一次运行必须先执行 `update_data.py`。在没有快照时页面会明确显示“快照不可用”，**不会**生成任何模拟数字。

手动刷新：再次执行 `python3 scripts/update_data.py` 即可。

## 2. 数据与口径

### 2.1 实际使用的数据源

| 指标组 | 数据源 | 取数方式 | 历史 | 说明 |
|---|---|---|---|---|
| 2Y / 10Y / 实际收益率 / 10Y-2Y / 10Y-3M / VIX / HY OAS / 标普500 / 纳指100 | **FRED**（St. Louis Fed） | 公开 CSV 端点 `fredgraph.csv?id=...`，无需 Key | 各序列源端起始日不同、长度不一；本地 `history.json` 仅保留每条序列最近 400 个有效观测 | FRED 为免费分发方；利差用 FRED 原始序列，不跨日期相减；部分序列原始版权归 S&P/Nasdaq/CBOE/BofA，见下方许可声明 |
| DXY（ICE 美元指数）、标普500、纳指100、COMEX 黄金/WTI 原油/铜**近月期货**、BTC/ETH 现货 | **CNBC** 公开行情页接口 | `restQuote` JSON，无需 Key | 当前值 + 前收盘（可算日变化） | 非官方开发者 API，见下方稳定性说明 |
| USD/JPY、USD/CNH（**离岸**） | **currency-api** 经 jsDelivr CDN | 按日期的日快照 JSON | 可回溯 25 天 | 非央行官方源，见下方说明 |
| BTC/ETH（可选） | CoinGecko | 官方 API，Key 放 Secrets | 30 天日线 | 本环境连接超时，默认关闭；启用方法见 2.3 |

### 2.2 数据源限制与替代方案（重要，未擅自更换指标定义）

实测结果（2026-11-21，本沙箱网络出口）：

- **CoinGecko / Stooq / Yahoo Finance / Binance / Coinbase**：连接超时或 HTTP 429，无法作为稳定主源。按规格要求，不得因此填入模拟数据。
  - 替代：BTC/ETH 使用 **CNBC `BTC=` / `ETH=` 现货汇率**（真实现货价，非 ETF）。规格允许“其他可靠现货价格源”。
  - CoinGecko 适配器已写好，配置 `sources.coingecko.enabled=true` 即可启用（成功时会覆盖 CNBC 结果）。
- **FRED 无原生 DXY**：`DTWEXBGS` 是贸易加权美元指数，规格明确禁止冒充 DXY，因此**不使用**。DXY 采用 CNBC `.DXY`（ICE U.S. Dollar Index），确认是原生定义。
- **期货历史**：CNBC 只给当前价与前收盘，不提供免费日线历史；DXY/黄金/WTI/铜的“近20期”变化由脚本每日运行时**自行累积**到 `data/history.json`。样本不足时按规格显示 `—`，宏观判断随之显示“数据不足：暂不判断”，不补造历史。约 20 个交易日后自动生效。
- **CNBC 接口性质**：它是 CNBC 网页使用的公开报价接口，不是有 SLA 的官方开发者 API。适合个人每日观察；若不稳定，可在 `config.json` 的 `sources.cnbc` 中替换等价端点，页面字段不变。
- **CNBC 时间戳边界**：报价只有具备可校验的行情日期（`YYYY-MM-DD` 或 `MM/DD/YY`）才被接受；无时间戳或非法日期（如 `2026-13-45`）的报价不计入有效数据，该指标沿用上次有效值并标记 `stale`，宏观判断随之 fail-closed。脚本**不会用系统当天日期回填**缺失的行情日期，以免污染历史与误判时效。
- **currency-api 性质**：开源项目按日发布汇率快照，经 jsDelivr CDN 分发。它提供 `cnh`（离岸人民币），因此**没有**用 `USD/CNY` 在岸价替代。若需央行级权威源，可在 `sources.currency_api` 适配器内替换，指标定义不变。
- **黄金/铜/原油单位**：严格按 `USD/oz`、`USD/lb`、`USD/bbl` 展示，且名称标注“近月期货”，不把期货写成现货。

### 2.3 密钥（可选）

默认配置**不需要任何 API Key**。若启用 CoinGecko：

1. 在 CoinGecko 注册获取 Demo API Key；
2. 在 GitHub 仓库 `Settings → Secrets and variables → Actions` 新增 `COINGECKO_API_KEY`；
3. 将 `config.json` 中 `sources.coingecko.enabled` 设为 `true`，并在 `fetch_coingecko` 中从 `os.environ["COINGECKO_API_KEY"]` 读取 Header（模板已预留适配器位置）。

> **绝不要**把 Key 写进网页或提交到仓库；浏览器只读取已生成的静态 JSON。

## 3. 计算口径与宏观规则

- **日变化**：价格/指数/外汇/DXY 为 `(当前/前值-1)×100`%，利率与利差为 `(当前-前值)×100` bp，VIX 为点数差。
- **近20期变化**：该指标自身最近 **20 个有效观测间隔**（需 21 个观测点），不是减 20 个日历日；不足显示 `—`。
- **利差水平**：FRED 原始百分数（如 0.30）按 `×100` 显示为 `+30bp`；HY OAS 3.20% 显示为 `320bp`。
- **宏观状态**：按规格 5.3 顺序匹配（金融压力扩散 → 增长担忧定价 → 金融条件趋紧 → 温和宽松 → 中性/信号分歧）。任一关键 20 期数据缺失/超期即显示“数据不足：暂不判断”。所有阈值位于 `config.json` 的 `macro_thresholds`，可调整，无需改主代码。
- **颜色**：涨跌数字沿用中国市场习惯（涨红、跌绿），但方向解释以中文小字为准；不依赖颜色唯一传达信息，也不因上涨机械判定为“好”。

## 4. 部署为每天自动更新的网址（GitHub Pages）

1. 将本目录推送到 GitHub 仓库（例如 `global-market-dashboard`）。
2. 进入 `Settings → Pages`，Source 选择 `Deploy from a branch`，分支 `main`、目录 `/ (root)`，保存。
3. 进入 `Actions` 标签，确认工作流 `每日更新市场快照` 已启用；也可点 `Run workflow` 手动触发一次。
4. 定时规则为 UTC `02:17`（北京时间 10:17 / 东京时间 11:17，避开刻钟与整点拥挤）。GitHub 免费定时调度不承诺准点，可能延迟数分钟乃至更久，属平台侧客观限制。工作流会运行测试、抓取数据、提交 `data/*.json/js`，Pages 随之重新发布。
5. 访问 `https://<你的用户名>.github.io/<仓库名>/`。

无数据库、无账号、无实时 WebSocket、无浏览器端 API Key，托管成本为零。

## 5. 目录结构

```
global-market-dashboard/
├── index.html              页面入口
├── styles.css              蓝白金融终端样式（桌面一屏 / 移动自适应）
├── app.js                  仅负责渲染，不含数据生成
├── core.py                 纯逻辑：单位换算、20期变化、状态识别、小字解读
├── config.json             17指标定义、阈值、数据源映射（不硬编码）
├── scripts/update_data.py  取数、校验、合并历史、失败降级、原子写入
├── data/
│   ├── snapshot.json       最新快照（供程序读取）
│   ├── snapshot.js         同一快照的 JS 包装（供 file:// 双击打开）
│   └── history.json        各指标滚动历史（用于近20期累积）
├── tests/test_core.py      覆盖规格第 8 节验收点
└── .github/workflows/update.yml
```

## 6. 故障排查

| 现象 | 原因与处理 |
|---|---|
| 页面显示“快照不可用” | 尚未运行 `update_data.py`，或 `data/snapshot.js` 损坏。重新运行脚本。 |
| 某卡显示“数据暂未更新” | 对应数据源超时或该指标取数失败；脚本保留上一次有效值、标 `stale` 并标注日期。查看运行日志、`failed_sources` 与 `failed_indicators`。 |
| 某卡显示“历史样本不足，等待积累” | 当前价格正常，只是近20期历史观测不够 21 个（新部署常见）。不是数据源故障，等待每日运行累积即可。 |
| 宏观状态显示“数据不足：暂不判断” | DXY / 实际利率 / 2Y / HY OAS / VIX 的 20 期变化尚不齐（新部署前约 20 个交易日常见）。等待累积，不要手动填数。 |
| FRED 值为 `.` | FRED 用 `.` 表示缺失（假日等），脚本自动跳过，不作为 0 处理。 |
| 更新后数字全部未变 | 可能遇到周末或美国假日；页面会标注各卡日期，`data_note` 明确“非同一时刻实时行情”。 |
| GitHub Actions 提交失败 | 检查仓库 `Permissions → Workflow permissions` 是否为 `Read and write`。 |

## 7. 许可与限制

- **用途与许可**：本项目为**非商业的个人学习与技术研究用途**，不含投资建议，不转售、不再分发原始数据，已按源署名并附免责声明。FRED 为免费分发方，但 `SP500`/`NASDAQ100`/`VIXCLS`/`BAMLH0A0HYM2` 原始版权分别归 S&P DJI、Nasdaq、CBOE、BofA；ICE U.S. Dollar Index 为 ICE 注册商标，经 CNBC 非官方接口转发；CNBC 与 currency-api 无 SLA 或公开分发许可。**若拟公开商用或面向公众服务，须先取得相关指数权利方授权或改用具备公开分发许可的数据源。** 此为工程事实披露，不构成法律意见，机构使用请由法务复核。详见 `AUDIT.md`。
- 本面板是**解释性**价格信号分类，不是 GDP/衰退预测，不构成任何投资建议。
- 规格 V1 阈值为未回测的启发式初值，仅用于统一观察口径。
