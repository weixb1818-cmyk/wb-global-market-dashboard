"""
全球市场每日观察面板 — 核心逻辑（纯函数，无网络依赖）
所有阈值来自 config.json；本模块不硬编码任何业务阈值。
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent


def load_config(path: Optional[str | Path] = None) -> Dict[str, Any]:
    cfg_path = Path(path) if path else ROOT / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# 单位与变化计算
# --------------------------------------------------------------------------
def to_bp(value_pct: float) -> float:
    """FRED 以百分数发布的利差水平（3.52）转为 bp（352）。"""
    return value_pct * 100.0


def pct_change(current: float, previous: float) -> float:
    """价格/指数/外汇的百分比变化。"""
    if previous == 0:
        raise ZeroDivisionError("previous value is zero")
    return (current / previous - 1.0) * 100.0


def diff_bp(current_pct: float, previous_pct: float) -> float:
    """收益率/利差变化的 bp 口径：原始数值差乘 100。"""
    return (current_pct - previous_pct) * 100.0


def diff_point(current: float, previous: float) -> float:
    """VIX 等点数指标的点数差。"""
    return current - previous


def crosscheck_spread(derived: Sequence[Dict[str, Any]],
                      leg_a: Sequence[Dict[str, Any]],
                      leg_b: Sequence[Dict[str, Any]],
                      threshold_bp: float) -> Dict[str, Any]:
    """
    官方利差序列与同日两条收益率之差的一致性交叉验证（P1）。

    - derived：官方利差序列（FRED T10Y2Y / T10Y3M），单位为百分数（0.28 表示 28bp）。
    - leg_a / leg_b：构成该利差的两条收益率序列（如 DGS10 与 DGS2 / DGS3MO）。
    - 只比较**同日**观测；任一序列在该日缺失则跳过，绝不跨日期强行相减。
    - 差额 = (官方利差 − (腿A − 腿B)) × 100，单位 bp；|差额| > threshold_bp 记为 alert。

    返回字段：
      status: ok（一致）/ alert（超阈值）/ unverifiable（无同日可比数据）
      date / derived_bp / computed_bp / diff_bp / threshold_bp / reason
    """
    def index_of(series: Sequence[Dict[str, Any]]) -> Dict[str, float]:
        idx: Dict[str, float] = {}
        for o in series or []:
            if not o:
                continue
            d, v = o.get("date"), o.get("value")
            if d and v is not None:
                idx[str(d)] = float(v)
        return idx

    di, ai, bi = index_of(derived), index_of(leg_a), index_of(leg_b)
    common = sorted(set(di) & set(ai) & set(bi))
    if not common:
        return {
            "status": "unverifiable", "date": None,
            "derived_bp": None, "computed_bp": None, "diff_bp": None,
            "threshold_bp": threshold_bp,
            "reason": "同日数据不齐，无法核验（不跨日期计算）",
        }
    day = common[-1]
    derived_bp = (di[day] - (ai[day] - bi[day])) * 100.0
    computed_bp = (ai[day] - bi[day]) * 100.0
    official_bp = di[day] * 100.0
    diff_bp = derived_bp
    if abs(diff_bp) < 1e-9:  # 规范化浮点负零，避免 -0.0 显示
        diff_bp = 0.0
    alert = abs(diff_bp) > threshold_bp
    return {
        "status": "alert" if alert else "ok",
        "date": day,
        "derived_bp": round(official_bp, 4),
        "computed_bp": round(computed_bp, 4),
        "diff_bp": round(diff_bp, 4),
        "threshold_bp": threshold_bp,
        "reason": ("同日差异超过告警阈值" if alert
                   else "同日一致（在阈值内）"),
    }


def _change_for_kind(current: float, previous: float, kind: str) -> float:
    if kind in ("yield", "spread"):
        return diff_bp(current, previous)
    if kind == "vix":
        return diff_point(current, previous)
    if kind in ("index", "price", "crypto", "fx"):
        return pct_change(current, previous)
    raise ValueError(f"unknown indicator kind: {kind}")


def compute_changes(
    series: Sequence[Dict[str, Any]],
    kind: str,
    window: int = 20,
    provider_change_1: Optional[float] = None,
) -> Dict[str, Any]:
    """
    由按日期升序排列的有效观测序列计算变化。
    - change_1：相邻两个有效观测间的变化；provider_change_1 优先（数据源自带的日变化）。
    - change_20：最近 window 个'有效观测间隔'的变化，需要 window+1 个观测点；不足返回 None。
    返回中不含任何模拟或填充值。
    """
    pts = [p for p in series if p.get("value") is not None]
    pts = sorted(pts, key=lambda p: p["date"])
    if not pts:
        return {"value": None, "as_of": None, "change_1": None,
                "change_20": None, "observations": 0}

    current = float(pts[-1]["value"])
    out: Dict[str, Any] = {
        "value": current,
        "as_of": pts[-1]["date"],
        "observations": len(pts),
        "change_1": provider_change_1,
        "change_20": None,
    }
    if len(pts) >= 2 and provider_change_1 is None:
        out["change_1"] = _change_for_kind(
            current, float(pts[-2]["value"]), kind
        )
    if len(pts) >= window + 1:
        out["change_20"] = _change_for_kind(
            current, float(pts[-(window + 1)]["value"]), kind
        )
    return out


# --------------------------------------------------------------------------
# 交易日 / 过期判断
# --------------------------------------------------------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """某月第 n 个星期 weekday（0=周一）。"""
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    return nxt - dt.timedelta(days=(nxt.weekday() - weekday) % 7 + 1)


def _easter(year: int) -> dt.date:
    """匿名 Gregorian 算法，用于推算耶稣受难日（美股休市）。"""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def us_market_holidays(year: int) -> set[dt.date]:
    """美国主要证券市场假日（含提前收盘日按休市处理，简化）。"""
    easter = _easter(year)
    days = {
        dt.date(year, 1, 1),                       # 元旦
        _nth_weekday(year, 1, 0, 3),               # 马丁·路德·金日
        _nth_weekday(year, 2, 0, 3),               # 总统日
        easter - dt.timedelta(days=2),             # 耶稣受难日
        _last_weekday(year, 5, 0),                 # 阵亡将士纪念日
        dt.date(year, 6, 19),                      # 六月节
        dt.date(year, 7, 4),                       # 独立日
        _nth_weekday(year, 9, 0, 1),               # 劳动节
        _nth_weekday(year, 11, 3, 4),              # 感恩节
        dt.date(year, 12, 25),                     # 圣诞节
    }
    # 假日落在周末时顺延至最近工作日（市场惯例简化处理）
    adjusted = set()
    for d in days:
        if d.weekday() == 5:
            d = d - dt.timedelta(days=1)
        elif d.weekday() == 6:
            d = d + dt.timedelta(days=1)
        adjusted.add(d)
    return adjusted


def is_trading_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day not in us_market_holidays(day.year)


def expected_trading_days_between(start: dt.date, end: dt.date) -> int:
    """统计 (start, end] 区间内预期发布交易日数量。"""
    if end <= start:
        return 0
    n, cur = 0, start + dt.timedelta(days=1)
    while cur <= end:
        if is_trading_day(cur):
            n += 1
        cur += dt.timedelta(days=1)
    return n


def is_stale(as_of: Optional[str], kind: str, config: Dict[str, Any],
             now: Optional[dt.datetime] = None) -> bool:
    """按规格 4.9 判断数据是否延迟。休市本身不视为故障。"""
    if not as_of:
        return True
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        last = dt.date.fromisoformat(as_of)
    except ValueError:
        return True
    today = now.date()
    if kind == "crypto":
        # 以 UTC 自然日近似 36 小时阈值（日更新脚本粒度足够）
        return (now - dt.datetime.combine(last, dt.time(), tzinfo=dt.timezone.utc)).total_seconds() > \
               config["staleness"]["crypto_max_hours"] * 3600
    limit = config["staleness"]["max_expected_trading_days"]
    return expected_trading_days_between(last, today) > limit


# --------------------------------------------------------------------------
# 宏观状态识别（规格 5）
# --------------------------------------------------------------------------
REQUIRED_MACRO_KEYS = (
    "dxy20", "real20bp", "twoYear20bp", "hy20bp", "vix20pt", "hyNow", "vixNow"
)


def classify_macro(inputs: Dict[str, Optional[float]],
                   config: Dict[str, Any],
                   statuses: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    按规格 5.3 顺序匹配，只输出一个主状态。

    审计 WB 第 1 项（fail-closed 严格白名单）：
    - 仅当某关键输入的 statuses[k] 严格等于 'ok' 时，该输入才允许参与分类；
    - stale/missing/error/unknown/空串/未定义值一律阻断，即使其数值非空；
    - 未传 statuses 或 statuses 为空 -> 视为状态未经验证，一律 insufficient，
      不再退化为“按值校验”（审计明确拒绝按值降级）；
    - 不复用昨日结论。
    保留 statuses 参数结构，仅收紧判定语义，不做架构变更。
    """
    t = config["macro_thresholds"]
    # 严格 fail-closed：statuses 缺失/为空 -> 状态未经验证，直接不足。
    if not statuses:
        return {
            "state": "insufficient",
            "headline": "数据不足：暂不判断",
            "why": "状态未经验证（未提供 statuses），不输出宏观结论",
            "uncertainty": "需为全部关键输入显式提供已核实状态，不沿用旧结论",
            "missing": list(REQUIRED_MACRO_KEYS),
        }
    # 白名单：只认严格字符串 'ok'；未知/空串/None/其它值一律阻断。
    missing = []
    for k in REQUIRED_MACRO_KEYS:
        if inputs.get(k) is None:
            missing.append(k)
        elif statuses.get(k) != "ok":
            missing.append(k)
    if missing:
        return {
            "state": "insufficient",
            "headline": "数据不足：暂不判断",
            "why": f"缺少关键数据：{', '.join(missing)}",
            "uncertainty": "需等待缺失指标取得足量有效观测，不沿用旧结论",
            "missing": missing,
        }

    dxy20 = float(inputs["dxy20"])
    real20 = float(inputs["real20bp"])
    two20 = float(inputs["twoYear20bp"])
    hy20 = float(inputs["hy20bp"])
    vix20 = float(inputs["vix20pt"])
    hy_now = float(inputs["hyNow"])
    vix_now = float(inputs["vixNow"])

    if hy20 >= t["hy20_widen_bp"] and vix20 >= t["vix20_up_pt"]:
        return {
            "state": "stress_spread",
            "headline": "金融压力扩散｜信用利差与波动率共同上升，市场防御需求增强",
            "why": f"HY OAS 近20期 +{hy20:.0f}bp，VIX 近20期 +{vix20:.0f}点",
            "uncertainty": "利差与波动高位但不代表必然下跌；需观察是否持续走坏",
            "missing": [],
        }
    if two20 <= t["twoyear20_down_bp"] and (
        hy20 >= t["hy20_widen_bp"] or vix20 >= t["vix20_up_pt"]
    ):
        return {
            "state": "growth_concern",
            "headline": "增长担忧定价｜短端利率下行，但信用或波动信号恶化；降息预期未必利好风险资产",
            "why": f"2Y 近20期 {two20:.0f}bp，HY OAS {hy20:+.0f}bp，VIX {vix20:+.0f}点",
            "uncertainty": "降息定价不等同于经济走弱已被完全定价",
            "missing": [],
        }
    if dxy20 >= t["dxy20_strong_pct"] and real20 >= t["real20_up_bp"]:
        return {
            "state": "tightening",
            "headline": "金融条件趋紧｜美元与实际利率同步上升；信用利差暂未显著恶化",
            "why": f"DXY 近20期 {dxy20:+.1f}%，10Y实际利率 {real20:+.0f}bp",
            "uncertainty": "利差与波动是否随后跟上仍需观察",
            "missing": [],
        }
    if (
        dxy20 <= t["dxy20_weak_pct"]
        and real20 <= t["real20_down_bp"]
        and hy20 < t["hy20_widen_bp"]
        and vix20 < t["vix20_up_pt"]
        and hy_now < t["hy_high_bp"]
        and vix_now < t["vix_high"]
    ):
        return {
            "state": "moderate_easing",
            "headline": "温和宽松｜美元和实际利率下降，信用及波动风险尚未同步恶化",
            "why": f"DXY 近20期 {dxy20:+.1f}%，实际利率 {real20:+.0f}bp，HY OAS {hy_now:.0f}bp",
            "uncertainty": "不代表风险资产的确定方向",
            "missing": [],
        }

    conflicts = []
    if dxy20 >= t["dxy20_strong_pct"] and real20 <= t["real20_down_bp"]:
        conflicts.append("美元走强但实际利率下行")
    if dxy20 <= t["dxy20_weak_pct"] and real20 >= t["real20_up_bp"]:
        conflicts.append("美元走弱但实际利率上行")
    if hy20 >= t["hy20_widen_bp"] and vix20 <= t["vix20_down_pt"]:
        conflicts.append("信用溢价扩大而波动预期回落")
    if not conflicts:
        conflicts.append("各信号未同时达到同向阈值")
    return {
        "state": "mixed",
        "headline": "中性/信号分歧｜" + "；".join(conflicts[:2]),
        "why": f"DXY {dxy20:+.1f}%，实际利率 {real20:+.0f}bp，HY OAS {hy20:+.0f}bp，VIX {vix20:+.0f}点",
        "uncertainty": "信号互相矛盾，不做方向性判断",
        "missing": [],
    }


# --------------------------------------------------------------------------
# 卡片小字解读（规格 6）
# --------------------------------------------------------------------------
def _n(s: str) -> str:
    """去掉多余空格，避免小字过长。"""
    return "".join(s.split())


def card_note(ind_id: str, change_20: Optional[float], config: Dict[str, Any],
              status: str = "ok", as_of: Optional[str] = None,
              aux: Optional[Dict[str, Any]] = None,
              observations: Optional[int] = None) -> str:
    # P2 整改：区分「数据延迟/失败」与「当前正常但历史样本不足」。
    # - 数据本身失败或过期 -> 数据暂未更新（附带数据日期）
    # - 当前值正常、仅近20期样本不足 -> 历史样本不足，等待积累（不暗示数据源故障）
    if status in ("missing", "stale", "error"):
        date_part = as_of or "未知日期"
        return _n(f"数据暂未更新，截至{date_part}")
    if change_20 is None:
        return "历史样本不足，等待积累"

    t = config["note_thresholds"]
    c = float(change_20)
    aux = aux or {}

    if ind_id == "dxy":
        if c >= t["dxy_significant_pct"]:
            return "美元走强，关注全球风险资产压力"
        if c <= -t["dxy_significant_pct"]:
            return "美元走弱，外部美元压力可能缓解"
        return "美元阶段性震荡"

    if ind_id == "us2y":
        if c <= -t["twoyear_big_bp"]:
            return "短端利率下行，市场可能增加降息定价"
        if c >= t["twoyear_big_bp"]:
            return "短端利率上行，政策利率预期偏紧"
        return "短端利率变化有限"

    if ind_id == "us10y":
        if c >= t["tenyear_significant_bp"]:
            return "长期融资及估值折现压力上升"
        if c <= -t["tenyear_significant_bp"]:
            return "长期收益率回落，需辨别增长预期与避险驱动"
        return "长端利率基本稳定"

    if ind_id == "us10y_real":
        if c >= t["real_significant_bp"]:
            return "实际利率上行，黄金及高估值资产或承压"
        if c <= -t["real_significant_bp"]:
            return "实际利率下行，相关估值压力缓解"
        return "实际利率变化有限"

    if ind_id in ("t10y2y", "t10y3m"):
        level_bp = aux.get("level_bp")
        base = "仍处倒挂" if (level_bp or 0) < 0 else "当前为正利差"
        if ind_id == "t10y3m":
            base = ("期限结构仍偏异常" if (level_bp or 0) < 0
                    else "已恢复正斜率，不等于衰退风险消失")
        slope = ""
        thr = t["curve_significant_bp"]
        if c >= thr:
            slope = "，曲线变陡"
            d2 = aux.get("us2y20bp")
            d10 = aux.get("us10y20bp")
            if d2 is not None and d10 is not None:
                if d2 <= -thr and d10 < thr:
                    slope += "，短端下降更快"
                elif d10 >= thr and d2 > -thr:
                    slope += "，长端上升更快"
                else:
                    slope += "，混合驱动"
        elif c <= -thr:
            slope = "，曲线变平"
        return _n(base + slope)

    if ind_id == "vix":
        if c >= t["vix_significant_pt"]:
            return "波动率预期上升，风险偏好降温"
        if c <= -t["vix_significant_pt"]:
            return "波动预期回落"
        return "波动预期变化有限"

    if ind_id == "hy_oas":
        if c >= t["hy_significant_bp"]:
            return "信用风险溢价扩大，关注风险扩散"
        if c <= -t["hy_significant_bp"]:
            return "信用风险溢价回落"
        return "信用市场相对稳定"

    if ind_id in ("sp500", "nasdaq100"):
        thr = t["equity_significant_pct"]
        if c >= thr:
            tail = "，成长/科技权重较高" if ind_id == "nasdaq100" else ""
            return _n(f"近20期累计上行，趋势偏强{tail}")
        if c <= -thr:
            tail = "，成长/科技权重较高" if ind_id == "nasdaq100" else ""
            return _n(f"近20期累计回落，趋势偏弱{tail}")
        return "近20期区间震荡"

    if ind_id == "gold":
        if c >= t["commodity_significant_pct"]:
            return "近20期金价上行，需结合实际利率与美元判断"
        if c <= -t["commodity_significant_pct"]:
            return "近20期金价回落，需结合实际利率与美元判断"
        return "近20期金价震荡，需结合实际利率与美元判断"

    if ind_id in ("wti", "copper"):
        subject = "油价" if ind_id == "wti" else "铜价"
        driver = "关注能源供需变化" if ind_id == "wti" else "关注工业需求变化"
        if c >= t["commodity_significant_pct"]:
            return _n(f"近20期{subject}上行，{driver}")
        if c <= -t["commodity_significant_pct"]:
            return _n(f"近20期{subject}回落，{driver}")
        return _n(f"近20期{subject}震荡，{driver}")

    if ind_id in ("btc", "eth"):
        name = "BTC" if ind_id == "btc" else "ETH"
        trend = "上行" if c > 0 else ("回落" if c < 0 else "震荡")
        return _n(f"近20期{name}价格{trend}，不宜视为流动性改善证明")

    if ind_id in ("usdjpy", "usdcnh"):
        target = "日元" if ind_id == "usdjpy" else "离岸人民币"
        thr = t["fx_significant_pct"]
        if c >= thr:
            return _n(f"美元相对{target}升值")
        if c <= -thr:
            return _n(f"美元相对{target}贬值")
        return "汇率基本稳定"

    return "暂无解读模板"


# --------------------------------------------------------------------------
# 报价性质标签（审计 WB 第 2 项：延迟报价提示）
# --------------------------------------------------------------------------
QUOTE_NATURE_LABELS = {
    # 仅描述“报价性质”，与数据时效状态 status（ok/stale/...）相互独立。
    # realTime=false 的 CNBC 近月期货 → 延迟行情；不改变取数状态判定。
    "delayed_futures": "延迟报价·非实时可成交价",
}


def quote_label(ind_id: str, config: Dict[str, Any],
                status: Optional[str] = None) -> Optional[str]:
    """返回报价性质独立标签；与 status 完全分离。

    审计 WB 第 2 项要求：
    - 黄金/WTI/铜（CNBC 近月期货，realTime=false）显示“延迟报价·非实时可成交价”；
    - 不因 realTime=false 把正常报价标成 stale（status 由 _status_for 独立判定）；
    - 真实报价日期由 as_of 单独展示，标签内不含日期；
    - 数据源未提供可靠实时属性时不擅自标“实时”（此处只标确证的延迟品种）。
    status 参数保留供未来扩展，当前标签不受其影响——即使 status=stale，
    仍可显示报价性质标签，而“数据暂未更新”由 note/status badge 另行表达。
    """
    for meta in config.get("indicators", []):
        if meta.get("id") != ind_id:
            continue
        nature = meta.get("quote_nature")
        return QUOTE_NATURE_LABELS.get(nature) if nature else None
    return None


# --------------------------------------------------------------------------
# 展示格式化
# --------------------------------------------------------------------------
def fmt_number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def fmt_value(value: Optional[float], display: str, signed: bool = True) -> str:
    if value is None:
        return "—"
    v = float(value)
    if display == "percent":
        return f"{v:.2f}%"
    if display == "bp":
        return f"{v:+.0f}bp" if signed else f"{v:.0f}bp"
    if display == "fx":
        return f"{v:.3f}"
    if display == "price" and abs(v) < 10:
        return fmt_number(v, 3)
    return fmt_number(v, 2)


def fmt_change(value: Optional[float], kind: str) -> str:
    if value is None:
        return "—"
    v = float(value)
    if kind in ("yield", "spread"):
        return f"{v:+.0f}bp"
    if kind == "vix":
        return f"{v:+.1f}点"
    return f"{v:+.2f}%"
