"""
审计溯源数据结构与持久化（纯函数，P2）。

每个原始请求记录：源、URL、请求日期(UTC)、HTTP 状态、响应 sha256、字节数、
以及是否允许保存原始响应体。仅允许再分发的源（FRED 公开 CSV）落盘原文；
CNBC / currency-api / macrofinance 等未明确授权的源只记录元数据与哈希，
不保存、不公开原始响应，符合"不得公开不允许再分发的第三方原始数据"。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional


def make_record(source: str, url: str, status: Optional[int], body: Optional[str],
                fetched_at_utc: str, redistributable: bool = False) -> Dict[str, Any]:
    """构造单条溯源记录；body 仅在 redistributable=True 时以 raw_ref 引用，不内联。"""
    raw: Optional[bytes] = body.encode("utf-8") if body is not None else None
    return {
        "source": source,
        "url": url,
        "fetched_at_utc": fetched_at_utc,
        "http_status": status,
        "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
        "bytes": len(raw) if raw is not None else 0,
        "redistributable": redistributable,
        "raw_ref": None,  # 由调用方在落盘原始文件后填入相对路径
    }


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总 manifest：按源统计请求数、成功数、失败数。"""
    by_source: Dict[str, Dict[str, int]] = {}
    for r in records:
        s = r.get("source", "unknown")
        b = by_source.setdefault(s, {"requests": 0, "ok": 0, "fail": 0})
        b["requests"] += 1
        if r.get("http_status") == 200:
            b["ok"] += 1
        else:
            b["fail"] += 1
    return {
        "records": records,
        "summary": by_source,
        "note": "sha256 为原始响应体哈希；仅 redistributable=true 的源保存原文，其余只存元数据",
    }
