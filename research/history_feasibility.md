# 免费历史数据可得性与口径一致性研究（P0）

> 目标：为 DXY、黄金、WTI、铜、BTC、ETH 六个"仅 2 期"的指标寻找**可验证的真实历史**。
> 结论先行：**未发现任何同时满足"免费 + 同品种 + 同单位 + 同日期口径 + 同计算口径 + 可合法再分发"的源**，因此按审计要求继续自然积累，不导入、不拼接、不模拟。
> 实测日期：2026-11-23。

## 一、为什么"口径一致"比"有数据"更重要

`change_20`（近 20 期变化）要求 21 个**同口径**有效观测。若把来源不同、品种不同或计算方式不同的序列拼接，得到的 20 期变化在金融上是无意义的，甚至会误导宏观判断。审计明确要求：只有"完全满足一致性"才允许导入；否则宁可显示"数据不足"。本项目遵循这一底线。

现有六项指标的当前值来自 CNBC 报价，因此任何候选历史必须与 CNBC 报价口径逐项对齐：

| 指标 | 当前源 | 品种/合约 | 报价性质 | 单位 |
|---|---|---|---|---|
| DXY | CNBC `.DXY` | ICE U.S. Dollar Index（现货指数） | 实时指数，`realTime=true` | 点 |
| 黄金 | CNBC `@GC.1` | COMEX 黄金**近月期货**（Dec'26） | 延迟报价，`realTime=false` | USD/oz |
| WTI | CNBC `@CL.1` | NYMEX WTI **近月期货**（Jan'27） | 延迟报价 | USD/bbl |
| 铜 | CNBC `@HG.1` | COMEX 铜**近月期货**（Dec'26） | 延迟报价 | USD/lb |
| BTC | CNBC `BTC=` | BTC/USD 现货 | 实时 | USD |
| ETH | CNBC `ETH=` | ETH/USD（Coinbase）现货 | 实时 | USD |

## 二、候选源实测结果

所有请求在本沙箱（网络出口受限）于 2026-11-23 实测，UA 分别测试浏览器与 `curl/7.81.0`：

| 候选源 | 目标 | 实测 HTTP | 结果 | 判定 |
|---|---|---|---|---|
| Stooq `dx.f/gc.f/cl.f/hg.f/btcusd` | 期货/加密日线 CSV | 200 但返回 **JS 验证页**（`This site requires JavaScript to verify your browser`） | 拿不到 CSV | ❌ 不可用 |
| Yahoo Finance `DX-Y.NYB`、`BTC-USD`（query1/query2） | 指数/加密日线 | **429** `Edge: Too Many Requests` | 被限流 | ❌ 不可用 |
| CoinGecko `simple/price`、`market_chart` | 加密现货历史 | `ConnectionResetError(104)` | 本环境连接被重置 | ❌ 不可用 |
| CNBC 图表子域 `api.cnbc.com` | 同口径历史 | `ConnectionError`（域名不通） | 无法连接 | ❌ 不可用 |
| CNBC `webql-redesign.cnbcfm.com` GraphQL | 同口径历史 | 400 `Must provide query string`（需未公开的持久化查询哈希） | 需非公开参数 | ❌ 不可用 |
| Twelve Data `demo` | 通用历史 | 401，demo key 仅限示例品种 | 需付费/注册 | ❌ 不可用 |
| FRED `DTWEXBGS` / `DTWEXAFEGS` | 美元指数 | 200，2006 起 | **贸易加权**美元指数，非 ICE DXY | ❌ 口径不符 |
| FRED `DEXUSEU` | 美元指数 | 200，1999 起 | 仅为 EUR/USD 单一汇率 | ❌ 口径不符 |
| macrofinance.ai `mf_history`（`secid=6207&tpid=6`） | ICE DXY 日收盘 | **200，text/csv，2603 行，2016-11-23 起** | 见第三节详尽核对 | ❌ 口径存疑（不导入） |

## 三、macrofinance.ai DXY 历史：最接近但被排除

这是唯一真正取到数据的候选（`sha256=07f2978804f1aab42c1a676d4515b734afdd5e4852afea658d924d3e0c8097c8`，44923 bytes）。末段：

```
2026-11-19,103.89
2026-11-20,103.81
2026-11-22,103.85
```

数值与 CNBC 前收盘 `103.807` 高度吻合，说明它大概率追踪 ICE DXY。但逐项核对后**仍不满足导入条件**：

1. **日期口径异常（决定性）**：末行 `2026-11-22` 是**星期日**，全球市场休市，不可能产生收盘价。且缺失 `2026-11-21`（周六，正常）却凭空出现周日值，说明该源日期标注或抓取逻辑存在缺陷。把这类记录当作"有效日观测"会直接污染 `change_20`。
2. **品种口径未证实一致**：页面只标 "US Dollar Index"，未明确是 ICE DXY 现货指数本身还是其期货连续；CNBC `.DXY` 明确返回 `name=ICE U.S. Dollar Index`、`type=INDEX`。二者是否同一标的，供应商未给出可核验的说明。
3. **计算口径不同**：该源是**日收盘价**，CNBC 当前值是**盘中实时**（`realTime=true`, `curmktstatus=REG_MKT`）。把日收盘历史与盘中现价拼接成一个 21 点序列，跨口径计算 20 期变化，违反"同口径观测"要求。
4. **授权/再分发不明**：第三方聚合站，页面未给出可核验的数据来源授权与再分发条款；项目预算为零且不得公开不允许再分发的第三方原始数据。仅"页面可访问"不等于"可入库再分发"。

**结论**：数值接近不等于口径一致。按审计"只有完全满足一致性才允许导入"的要求，该源**不导入**。它可作为"未来若取得官方授权且核实口径后"的候选记录在案。

## 四、商品与加密为何同样不可得

- **商品（金/油/铜）**：CNBC 用**近月期货**（当前分别为 Dec'26 / Jan'27 / Dec'26，见 `commodity_contracts.md`）。免费源（Stooq `gc.f/cl.f/hg.f`）即使可取也是**连续合约**，其换月拼接规则是供应商定义、不透明，与 CNBC 近月合约的换月时点未必一致；免费条件下无法取得与 CNBC 逐日同合约、同换月的历史。
- **加密（BTC/ETH）**：CNBC `BTC=` 是 FX Spot Rate、`ETH=` 标注 Coinbase。CoinGecko 免费 Demo 在本环境不可连接，且即使可连接，其全球综合指数与 CNBC 单一报价源的收盘口径不同。

## 五、最终决定与后续

- **不导入**任何上述历史；六个指标**继续按日自然积累**真实观测。
- 系统行为保持不变：`change_20` 需 21 个有效观测，未达标时返回 `null`、小字显示"历史样本不足，等待积累"，宏观分类因关键输入缺失而 `insufficient`。这是**预期合规行为，不是故障**。
- 已补充测试：第 21 个观测到达时 `change_20` 从 `null` 正确转为有效值、宏观从 `insufficient` 转为正常分类（见 `tests/test_history_threshold.py`）。
- 若日后取得官方/可再分发授权且口径完全一致的源，再按 `config.json` 增加适配器，并经同样的一致性核对后再导入。

## 六、实测可复现命令

```bash
# Stooq（返回 JS 验证页）
curl -sS -A 'Mozilla/5.0' 'https://stooq.com/q/d/l/?s=dx.f&i=d' | head -c 120
# Yahoo（429）
curl -sS -A 'Mozilla/5.0' 'https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=1mo&interval=1d'
# macrofinance DXY（唯一取到数据，但日期异常，不导入）
curl -sS -A 'Mozilla/5.0' 'https://macrofinance.ai/wp-admin/admin-ajax.php?action=mf_history&secid=6207&tpid=6&format=csv&years=10' | tail -4
# FRED 口径确认：贸易加权，非 DXY
curl -sS -A 'curl/7.81.0' 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS' | head -2
```
