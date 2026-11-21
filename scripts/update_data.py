#!/usr/bin/env python3
"""
全球市场每日观察面板 — 每日数据更新脚本

流程：取数 -> 校验日期/单位 -> 对齐单指标历史 -> 计算变化 -> 宏观状态识别
      -> 生成 data/snapshot.json 与 data/history.json

原则：
1. 只写真实观测；任何缺失用 null / "—" 表示，绝不填充模拟值。
2. 单一数据源失败不影响其他指标；失败时沿用上一次有效值并标记延迟。
3. 写入采用临时文件 + 原子替换，避免数据损坏。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    card_note, classify_macro, compute_changes, fmt_change, fmt_value,
    is_stale, load_config, to_bp,
)

LOG = logging.getLogger("dashboard.update")
DATA_DIR = ROOT / "data"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
SNAPSHOT_JS_PATH = DATA_DIR / "snapshot.js"
HISTORY_PATH = DATA_DIR / "history.json"
MAX_HISTORY = 400


# --------------------------------------------------------------------------
# HTTP 基础
# --------------------------------------------------------------------------
def _session(cfg: Dict[str, Any], ua: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": ua or cfg["network"]["user_agent"],
                      "Accept": "application/json,text/csv,text/plain,*/*"})
    return s


def http_text(url: str, cfg: Dict[str, Any], params: Optional[dict] = None,
              ua: Optional[str] = None, headers: Optional[dict] = None) -> str:
    timeout = cfg["network"]["timeout_seconds"]
    retries = cfg["network"]["retries"]
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            session = _session(cfg, ua)
            if headers:
                session.headers.update(headers)
            r = session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001 - 记录后重试
            last_exc = exc
            if attempt < retries:
                LOG.warning("请求失败，%s 秒后重试 %s: %s", 1 + attempt, url, exc)
                time.sleep(1 + attempt)
    raise RuntimeError(f"请求失败 {url}: {last_exc}")


def http_json(url: str, cfg: Dict[str, Any], params: Optional[dict] = None,
              ua: Optional[str] = None, headers: Optional[dict] = None) -> Any:
    return json.loads(http_text(url, cfg, params, ua, headers))


def _num(text: Any) -> Optional[float]:
    if text is None:
        return None
    s = str(text).strip().replace(",", "").replace("%", "")
    if s in ("", ".", "--", "None", "null", "NA", "N/A"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v == v else None  # 排除 NaN


def _atomically_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# 数据源适配器
# --------------------------------------------------------------------------
def fetch_fred_all(cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """FRED CSV：无需 API Key，返回按序列 id 索引的观测列表。"""
    series = cfg["sources"]["fred"]["series"]
    base = cfg["sources"]["fred"]["base_url"]
    out: Dict[str, List[Dict[str, Any]]] = {}

    def one(item):
        name, sid = item
        text = http_text(base, cfg, params={"id": sid})
        lines = text.strip().splitlines()
        if len(lines) < 2 or not lines[0].lower().startswith("observation_date"):
            raise RuntimeError(f"FRED {sid} 返回格式异常")
        obs = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 2:
                continue
            value = _num(parts[1])
            if value is None:  # FRED 用 '.' 表示缺失
                continue
            try:
                dt.date.fromisoformat(parts[0].strip())
            except ValueError:
                continue
            obs.append({"date": parts[0].strip(), "value": value,
                        "source": f"FRED:{sid}"})
        return name, obs

    # FRED 对并发下载会限流（RemoteDisconnected / 超时），改为串行并轻微节流
    for name, sid in series.items():
        try:
            key, obs = one((name, sid))
            out[key] = obs
            LOG.info("FRED %s 取得 %d 个有效观测", key, len(obs))
        except Exception as exc:  # noqa: BLE001
            LOG.error("FRED %s 抓取失败: %s", name, exc)
        time.sleep(0.35)
    return out


def _parse_cnbc_date(raw: Any) -> Optional[str]:
    if not raw:
        return None
    s = str(raw)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # 形如 11/20/26 EST
    try:
        d = dt.datetime.strptime(s.split()[0], "%m/%d/%y").date()
        return d.isoformat()
    except ValueError:
        return None


def fetch_cnbc_all(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """CNBC 公开报价：当前值、前收盘、日变化百分比、数据日期。"""
    src = cfg["sources"]["cnbc"]
    sym_map = src["symbols"]
    out: Dict[str, Dict[str, Any]] = {}
    try:
        data = http_json(src["base_url"], cfg, params={
            "symbols": "|".join(sym_map.values()),
            "requestMethod": "itv", "noform": "1", "partnerId": "2",
            "fund": "1", "exthrs": "1", "output": "json",
        }, ua=src.get("user_agent"))
        quotes = data["FormattedQuoteResult"]["FormattedQuote"]
    except Exception as exc:  # noqa: BLE001
        LOG.error("CNBC 报价抓取失败: %s", exc)
        return out

    by_symbol = {q.get("symbol"): q for q in quotes}
    for ind_id, symbol in sym_map.items():
        q = by_symbol.get(symbol)
        if not q or q.get("code") not in (0, "0", None):
            LOG.warning("CNBC 未返回有效报价: %s (%s)", ind_id, symbol)
            continue
        value = _num(q.get("last"))
        if value is None:
            LOG.warning("CNBC %s 无有效价格", symbol)
            continue
        as_of = _parse_cnbc_date(q.get("last_time") or q.get("last_timedate"))
        chg_pct = _num(q.get("change_pct"))
        if chg_pct is None:
            chg = _num(q.get("change"))
            prev = _num(q.get("previous_day_closing"))
            chg_pct = pct_from_change(chg, prev)
        out[ind_id] = {
            "value": value,
            "as_of": as_of,
            "change_1": chg_pct,
            "name": q.get("name") or symbol,
            "source": f"CNBC:{symbol}",
            "previous_close": _num(q.get("previous_day_closing")),
        }
        LOG.info("CNBC %s 取得 %s @ %s", ind_id, value, as_of)
    return out


def pct_from_change(change: Optional[float], previous: Optional[float]) -> Optional[float]:
    if change is None or previous in (None, 0):
        return None
    return change / previous * 100.0


def fetch_currency_api(cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """按日期取 USD/JPY、USD/CNH 日快照，构造真实历史序列。"""
    src = cfg["sources"]["currency_api"]
    pairs = src["pairs"]
    days = int(src["history_days"])
    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in pairs}
    today = dt.date.today()

    dates = [(today - dt.timedelta(days=i)).isoformat() for i in range(days)]

    def one(date_str: str):
        url = src["base_url"].replace("{date}", date_str)
        return date_str, http_json(url, cfg)

    results: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(one, d): d for d in dates}
        for fut in as_completed(futures):
            try:
                date_str, payload = fut.result()
                if isinstance(payload, dict) and isinstance(payload.get("usd"), dict):
                    results[date_str] = payload
            except Exception as exc:  # noqa: BLE001
                LOG.debug("currency-api %s 不可用: %s", futures[fut], exc)

    # latest 作为当日快照补充（其 date 字段可能比本地今天更新）
    try:
        latest = http_json(src["latest_url"], cfg)
        if isinstance(latest.get("usd"), dict):
            results[str(latest.get("date") or today.isoformat())] = latest
    except Exception as exc:  # noqa: BLE001
        LOG.warning("currency-api latest 失败: %s", exc)

    for date_str in sorted(results):
        usd = results[date_str]["usd"]
        for ind_id, key in pairs.items():
            value = _num(usd.get(key))
            if value is None:
                continue
            out[ind_id].append({"date": date_str, "value": value,
                                "source": "currency-api/jsDelivr"})
    for ind_id, obs in out.items():
        LOG.info("currency-api %s 取得 %d 个有效观测", ind_id, len(obs))
    return out


def fetch_coingecko(cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """可选加密适配器：默认关闭；启用失败时返回空，不影响 CNBC 现货源。"""
    src = cfg["sources"].get("coingecko", {})
    if not src.get("enabled"):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    api_key = os.environ.get("COINGECKO_API_KEY", "")
    headers = {"x-cg-demo-api-key": api_key} if api_key else None
    for ind_id, coin in src.get("ids", {}).items():
        try:
            payload = http_json(
                src["market_chart_url"].replace("{coin}", coin), cfg,
                params={"vs_currency": "usd", "days": 30, "interval": "daily"},
                headers=headers,
            )
            obs = []
            for ts, price in payload.get("prices", []):
                day = dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat()
                obs.append({"date": day, "value": float(price),
                            "source": f"CoinGecko:{coin}"})
            out[ind_id] = obs
        except Exception as exc:  # noqa: BLE001
            LOG.warning("CoinGecko %s 失败: %s", coin, exc)
    return out


# --------------------------------------------------------------------------
# 历史合并与指标构建
# --------------------------------------------------------------------------
def merge_series(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按日期去重合并，新数据优先；仅保留有效数值。"""
    mapping: Dict[str, Dict[str, Any]] = {}
    for obs in list(old or []) + list(new or []):
        if not obs or obs.get("value") is None or not obs.get("date"):
            continue
        try:
            dt.date.fromisoformat(obs["date"])
        except (ValueError, TypeError):
            continue
        mapping[obs["date"]] = {"date": obs["date"], "value": float(obs["value"]),
                                "source": obs.get("source", "")}
    return [mapping[d] for d in sorted(mapping)][-MAX_HISTORY:]


def _status_for(as_of: Optional[str], kind: str, cfg: Dict[str, Any],
                source_failed: bool = False) -> str:
    if not as_of:
        return "missing"
    if source_failed or is_stale(as_of, kind, cfg):
        return "stale"
    return "ok"


def build_snapshot(cfg: Dict[str, Any], fetched: Dict[str, List[Dict[str, Any]]],
                   cnbc: Dict[str, Dict[str, Any]], failed_sources: List[str],
                   old_history: Dict[str, Any], old_snapshot: Dict[str, Any]) -> tuple:
    now_utc = dt.datetime.now(dt.timezone.utc)
    tz = dt.timezone(dt.timedelta(hours=9))  # Asia/Tokyo 固定偏移 JST
    generated_at = now_utc.astimezone(tz).isoformat(timespec="seconds")

    old_series = old_history.get("series", {}) if isinstance(old_history, dict) else {}
    prev_indicators = old_snapshot.get("indicators", {}) if isinstance(old_snapshot, dict) else {}

    indicators: Dict[str, Any] = {}
    new_history: Dict[str, Any] = {}

    for meta in cfg["indicators"]:
        ind_id = meta["id"]
        kind = meta["kind"]
        series = list(fetched.get(ind_id, []))
        provider_change_1 = None
        source_label = ""

        from_coingecko = any(
            str(o.get("source", "")).startswith("CoinGecko") for o in series
        )
        if ind_id in cnbc and not from_coingecko:
            q = cnbc[ind_id]
            series.append({"date": q["as_of"] or now_utc.date().isoformat(),
                           "value": q["value"], "source": q["source"]})
            provider_change_1 = q["change_1"]
            source_label = q["source"]
        elif series:
            source_label = series[-1].get("source", "")

        merged = merge_series(old_series.get(ind_id, []), series)
        new_history[ind_id] = merged

        source_failed = any(
            s in failed_sources and _source_owns(s, ind_id, cfg) for s in failed_sources
        )
        calc = compute_changes(merged, kind, cfg["change_window"], provider_change_1)
        as_of = calc["as_of"]
        status = _status_for(as_of, kind, cfg, source_failed)

        value = calc["value"]
        if value is not None and meta["display"] == "bp":
            value = to_bp(value)  # FRED 利差原始百分数 -> bp 水平

        prev = prev_indicators.get(ind_id, {})
        if calc["value"] is None and prev.get("value") is not None:
            # 更新失败：保留上一次有效值，但明确标记延迟
            value = prev.get("value")
            calc = {
                "value": None, "as_of": prev.get("as_of"),
                "change_1": None, "change_20": None,
                "observations": 0,
            }
            status = "stale"
            if not source_label:
                source_label = prev.get("source", "")

        aux = {}
        if ind_id in ("t10y2y", "t10y3m"):
            aux = {
                "level_bp": value,
                "us2y20bp": indicators.get("us2y", {}).get("change_20"),
                "us10y20bp": indicators.get("us10y", {}).get("change_20"),
            }
        # 10Y-3M 的驱动解释需要同日 DGS3MO：仅在存在时补充，不跨日期相减
        if ind_id == "t10y3m":
            three_m = fetched.get("dgs3mo", [])
            us10 = fetched.get("us10y", [])
            if three_m and us10 and three_m[-1]["date"] == us10[-1]["date"]:
                aux["dgs3mo_bp"] = to_bp(three_m[-1]["value"])

        note = card_note(ind_id, calc["change_20"], cfg, status, as_of, aux)
        display_value = (fmt_value(value, meta["display"],
                                   signed=meta.get("signed_level", True))
                         if value is not None else "—")

        indicators[ind_id] = {
            "name": meta["name"],
            "group": meta["group"],
            "unit": meta["unit"],
            "display": meta["display"],
            "value": value if value is not None else None,
            "display_value": display_value,
            "change_1": calc["change_1"],
            "change_1_text": fmt_change(calc["change_1"], kind),
            "change_20": calc["change_20"],
            "change_20_text": fmt_change(calc["change_20"], kind),
            "as_of": as_of,
            "source": source_label or "未知",
            "status": status,
            "note": note,
            "observations": calc["observations"],
        }

    # 宏观状态输入（规格 5.1）
    def cv(ind_id: str, field: str) -> Optional[float]:
        return indicators.get(ind_id, {}).get(field)

    macro_inputs = {
        "dxy20": cv("dxy", "change_20"),
        "real20bp": cv("us10y_real", "change_20"),
        "twoYear20bp": cv("us2y", "change_20"),
        "hy20bp": cv("hy_oas", "change_20"),
        "vix20pt": cv("vix", "change_20"),
        "hyNow": cv("hy_oas", "value"),
        "vixNow": cv("vix", "value"),
    }
    macro = classify_macro(macro_inputs, cfg)

    snapshot = {
        "version": cfg["version"],
        "generated_at": generated_at,
        "generated_at_tz": "Asia/Tokyo",
        "data_note": "本页数据截至各卡标注日期，非同一时刻实时行情",
        "change_window": cfg["change_window"],
        "macro": macro,
        "indicators": indicators,
        "failed_sources": failed_sources,
        "source_terms": {
            "fred": cfg["sources"]["fred"]["license"],
            "cnbc": cfg["sources"]["cnbc"]["license"],
            "currency_api": cfg["sources"]["currency_api"]["license"],
        },
    }
    history = {
        "version": cfg["version"],
        "updated_at": generated_at,
        "series": new_history,
    }
    return snapshot, history


def _source_owns(source_name: str, ind_id: str, cfg: Dict[str, Any]) -> bool:
    return (source_name.startswith("FRED") and ind_id in cfg["sources"]["fred"]["series"]
            or source_name.startswith("CNBC") and ind_id in cfg["sources"]["cnbc"]["symbols"]
            or source_name.startswith("currency-api") and ind_id in cfg["sources"]["currency_api"]["pairs"])


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def load_json_safe(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        LOG.warning("读取 %s 失败，按空处理: %s", path, exc)
        return {}


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    old_snapshot = load_json_safe(SNAPSHOT_PATH)
    old_history = load_json_safe(HISTORY_PATH)

    failed_sources: List[str] = []
    fetched_raw: Dict[str, List[Dict[str, Any]]] = {}

    try:
        fred = fetch_fred_all(cfg)
        for ind_id in cfg["sources"]["fred"]["series"]:
            if ind_id in fred:
                fetched_raw[ind_id] = fred[ind_id]
            else:
                failed_sources.append("FRED")
    except Exception as exc:  # noqa: BLE001
        LOG.error("FRED 整体失败: %s", exc)
        failed_sources.append("FRED")

    cnbc = fetch_cnbc_all(cfg)
    if not cnbc:
        failed_sources.append("CNBC")

    fx = fetch_currency_api(cfg)
    for ind_id, obs in fx.items():
        fetched_raw[ind_id] = obs
    if not any(fx.values()):
        failed_sources.append("currency-api")

    cg = fetch_coingecko(cfg)
    for ind_id, obs in cg.items():
        if obs:
            fetched_raw[ind_id] = obs  # CoinGecko 启用时覆盖，作为可选主源

    snapshot, history = build_snapshot(
        cfg, fetched_raw, cnbc, list(dict.fromkeys(failed_sources)),
        old_history, old_snapshot,
    )

    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    _atomically_write(SNAPSHOT_PATH, payload + "\n")
    _atomically_write(SNAPSHOT_JS_PATH,
                      "window.GLOBAL_MARKET_SNAPSHOT = " + payload + ";\n")
    _atomically_write(HISTORY_PATH,
                      json.dumps(history, ensure_ascii=False, indent=2) + "\n")

    LOG.info("快照已写入 %s；宏观状态=%s；失败源=%s",
             SNAPSHOT_PATH, snapshot["macro"]["state"], snapshot["failed_sources"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
