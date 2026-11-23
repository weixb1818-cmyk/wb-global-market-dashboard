#!/usr/bin/env python3
"""
宏观规则历史案例复盘（P1，无前视偏差）。

方法（严格约束）：
- 信号只使用 T 日及之前已公布的观测（20 期变化 = T 与 T-20 两个已发布值之差）。
- 市场表现只取 T 日之后的收益（T+1 到 T+N），不使用任何未来信息生成过去信号。
- 阈值全部来自 config.json，不因复盘结果调整、不做事后优化。
- DXY 历史不足（仅 2 期），无法完整复盘"美元+实际利率"组合，用实际利率单腿替代并明确说明限制。
- 输出：各状态的样本统计（含有效与误判）、逐场景案例、结论边界。
  仅是"市场状态解释"，不含任何买卖信号。

运行：python3 scripts/macro_case_study.py  （只读 history.json / config.json，不改数据）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import classify_macro, load_config  # noqa: E402

HISTORY = ROOT / "data" / "history.json"
WINDOW = 20
HORIZON = 20  # T+N 评估窗口（交易日）


def by_date(series):
    return {o["date"]: float(o["value"]) for o in series if o.get("value") is not None}


def change_at(index, lag):
    """index[date] 在 lag 个观测前的变化：百分比（指数/价格）或 bp（收益率/点数特殊处理另算）。"""
    dates = sorted(index)
    if len(dates) <= lag:
        return None
    d_now, d_old = dates[-1], dates[-1 - lag]
    return (index[d_now], index[d_old], d_now, d_old)


def series_changes(series, kind):
    """返回 list[(date, change_20)]：change_20 单位与 core.compute_changes 一致。"""
    pts = sorted([o for o in series if o.get("value") is not None], key=lambda x: x["date"])
    out = []
    for i in range(WINDOW, len(pts)):
        now, old = float(pts[i]["value"]), float(pts[i - WINDOW]["value"])
        if kind in ("yield", "spread"):
            chg = (now - old) * 100.0  # bp
        elif kind == "vix":
            chg = now - old
        else:
            chg = (now / old - 1.0) * 100.0 if old else None
        out.append((pts[i]["date"], chg))
    return out


def forward_return(index, sig_date, horizon):
    """T 日之后 horizon 个观测的收益（%），只用 T 之后的数据。"""
    dates = sorted(index)
    if sig_date not in dates:
        return None
    i = dates.index(sig_date)
    j = min(i + horizon, len(dates) - 1)
    if j <= i:
        return None
    return (index[dates[j]] / index[dates[i]] - 1.0) * 100.0


def main():
    cfg = load_config()
    hist = json.loads(HISTORY.read_text(encoding="utf-8"))["series"]
    idx = {k: by_date(v) for k, v in hist.items()}

    # 各指标 20 期变化，按日期建索引
    chg = {}
    for key, kind in [("us2y", "yield"), ("us10y_real", "yield"),
                      ("hy_oas", "spread"), ("vix", "vix"),
                      ("sp500", "index"), ("nasdaq100", "index")]:
        chg[key] = dict(series_changes(hist[key], kind))

    # 每日宏观分类（DXY 缺失，dxy20=None -> 规则会判 insufficient）
    # 为做有价值复盘，另用"实际利率 + 2Y + HY + VIX"构造无 DXY 的简化状态机，
    # 严格复用 config 阈值，仅用于历史解释，不写入生产快照。
    t = cfg["macro_thresholds"]
    states = {}  # date -> (state, detail)
    common_dates = sorted(set(chg["us10y_real"]) & set(chg["us2y"])
                          & set(chg["hy_oas"]) & set(chg["vix"]))
    for d in common_dates:
        real20, two20, hy20, vix20 = (chg["us10y_real"][d], chg["us2y"][d],
                                      chg["hy_oas"][d], chg["vix"][d])
        hy_now = idx["hy_oas"].get(d)
        vix_now = idx["vix"].get(d)
        if None in (real20, two20, hy20, vix20, hy_now, vix_now):
            continue
        if hy20 >= t["hy20_widen_bp"] and vix20 >= t["vix20_up_pt"]:
            st = "stress_spread"
        elif two20 <= t["twoyear20_down_bp"] and (
                hy20 >= t["hy20_widen_bp"] or vix20 >= t["vix20_up_pt"]):
            st = "growth_concern"
        elif real20 >= t["real20_up_bp"]:
            st = "real_yields_up"  # DXY 缺失：不能用完整 tightening 规则，单腿标注
        elif real20 <= t["real20_down_bp"] and hy20 < t["hy20_widen_bp"] and vix20 < t["vix20_up_pt"]:
            st = "real_yields_down"
        else:
            st = "mixed"
        states[d] = st

    # 状态统计 + 后续市场表现
    print("=== 状态分布与 T+20 表现（无前视：信号用 T 日数据，收益取 T 之后）===")
    print(f"复盘窗口：{common_dates[0]} ~ {common_dates[-1]}（共 {len(common_dates)} 个信号日，受限于已积累历史）")
    buckets = {}
    for d, st in states.items():
        r_sp = forward_return(idx["sp500"], d, HORIZON)
        r_nq = forward_return(idx["nasdaq100"], d, HORIZON)
        buckets.setdefault(st, []).append((d, r_sp, r_nq))
    for st in sorted(buckets):
        rows = buckets[st]
        sp = [r for _, r, _ in rows if r is not None]
        nq = [r for _, _, r in rows if r is not None]
        avg_sp = sum(sp) / len(sp) if sp else float("nan")
        avg_nq = sum(nq) / len(nq) if nq else float("nan")
        up_sp = sum(1 for r in sp if r > 0) / len(sp) if sp else float("nan")
        print(f"  {st:18s} n={len(rows):3d}  T+{HORIZON}标普均={avg_sp:+6.2f}%  纳指均={avg_nq:+6.2f}%  标普上涨占比={up_sp:.0%}")

    # 逐场景案例：挑每个状态里"后续上涨"和"后续下跌"各一例（有效 vs 误判）
    print("\n=== 逐场景案例（状态解释，非买卖信号）===")
    scenarios = [
        ("stress_spread", "VIX与信用利差同步恶化"),
        ("growth_concern", "短端下行+信用/波动恶化（降息预期 vs 增长担忧）"),
        ("real_yields_up", "美元+实际利率走强（DXY缺失，仅实际利率单腿）"),
        ("real_yields_down", "实际利率回落、信用波动未恶化"),
        ("mixed", "信号分歧"),
    ]
    for st, label in scenarios:
        rows = [(d, sp, nq) for d, sp, nq in buckets.get(st, []) if sp is not None and nq is not None]
        if not rows:
            print(f"\n[{label}] 无可比样本（该状态在本历史窗口内未出现或不足 T+{HORIZON}）")
            continue
        rows_pos = max(rows, key=lambda x: x[1])
        rows_neg = min(rows, key=lambda x: x[1])
        print(f"\n[{label}]  样本 {len(rows)} 例")
        print(f"  后续偏强例：{rows_pos[0]}  信号日标普={idx['sp500'][rows_pos[0]]:.0f}  T+{HORIZON}标普={rows_pos[1]:+.2f}% 纳指={rows_pos[2]:+.2f}%")
        print(f"  后续偏弱例：{rows_neg[0]}  信号日标普={idx['sp500'][rows_neg[0]]:.0f}  T+{HORIZON}标普={rows_neg[1]:+.2f}% 纳指={rows_neg[2]:+.2f}%")

    # 股市上涨但信用/波动不配合的分歧案例
    # 口径A（严格规则）：股市20期涨幅达 note 阈值 且 HY/VIX 同向恶化达规则阈值。
    print("\n=== 场景：股市上涨但信用/波动不配合 ===")
    strict = []
    exploratory = []
    for d in common_dates:
        sp20 = chg["sp500"].get(d)
        hy20 = chg["hy_oas"].get(d)
        vix20 = chg["vix"].get(d)
        if None in (sp20, hy20, vix20):
            continue
        r = forward_return(idx["sp500"], d, HORIZON)
        eq_up = sp20 >= cfg["note_thresholds"]["equity_significant_pct"]
        if eq_up and (hy20 >= t["hy20_widen_bp"] or vix20 >= t["vix20_up_pt"]):
            strict.append((d, sp20, hy20, vix20, r))
        # 口径B（探索性观察，非规则、不调阈值）：股市上涨但 HY 与 VIX 同时处于恶化方向(>0)
        if eq_up and hy20 > 0 and vix20 > 0:
            exploratory.append((d, sp20, hy20, vix20, r))
    print(f"[口径A 严格规则阈值] 命中 {len(strict)} 例")
    if strict:
        for d, sp20, hy20, vix20, r in strict[-5:]:
            rs = f"{r:+.2f}%" if r is not None else "不足T+N"
            print(f"  {d}: 标普20期{sp20:+.1f}% 但 HY{hy20:+.0f}bp/VIX{vix20:+.1f}点 → T+{HORIZON}标普{rs}")
    else:
        print("  本窗口未出现（如实记录，不编造、不放宽规则阈值去凑案例）")
    print(f"[口径B 探索性观察｜非规则不调阈值] 股市20期涨幅≥{cfg['note_thresholds']['equity_significant_pct']}% 且 HY、VIX 同向为正: {len(exploratory)} 例")
    if exploratory:
        ups = [r for *_, r in exploratory if r is not None and r > 0]
        dns = [r for *_, r in exploratory if r is not None and r <= 0]
        print(f"  其中 T+{HORIZON} 后续上涨 {len(ups)} 例 / 下跌或持平 {len(dns)} 例")
        for d, sp20, hy20, vix20, r in exploratory[-3:]:
            rs = f"{r:+.2f}%" if r is not None else "不足T+N"
            print(f"    {d}: 标普20期{sp20:+.1f}% HY{hy20:+.0f}bp VIX{vix20:+.1f}点 → T+{HORIZON}标普{rs}")
    print("  说明：口径B 仅用于观察'表面强势是否伴随压力积累'，不构成交易规则，未据此调整任何阈值。")

    print("\n=== 边界声明 ===")
    print("- 以上均为历史状态解释，不构成任何买卖信号或收益承诺。")
    print("- 复盘窗口仅约 1.5 年（FRED 历史积累上限），样本量有限，统计不代表全周期规律。")
    print("- DXY 历史不足，'美元+实际利率'组合无法完整验证，仅用实际利率单腿近似。")
    print("- 阈值未做任何事后调整；有效与误判案例并列展示。")


if __name__ == "__main__":
    main()
