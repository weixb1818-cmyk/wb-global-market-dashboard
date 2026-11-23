"""审计溯源数据结构测试（P2）。运行：python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from provenance import make_record, summarize  # noqa: E402


class TestProvenance(unittest.TestCase):
    def test_sha256_deterministic(self):
        a = make_record("FRED", "https://x?id=DGS10", 200, "date,value\n2026-01-01,4.2\n",
                        "2026-01-01T00:00:00+00:00", redistributable=True)
        b = make_record("FRED", "https://x?id=DGS10", 200, "date,value\n2026-01-01,4.2\n",
                        "2026-01-01T00:00:00+00:00", redistributable=True)
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertEqual(len(a["sha256"]), 64)
        self.assertEqual(a["http_status"], 200)

    def test_non_redistributable_no_raw(self):
        r = make_record("CNBC", "https://quote.cnbc.com/x", 200, "secret body",
                        "2026-01-01T00:00:00+00:00", redistributable=False)
        self.assertFalse(r["redistributable"])
        self.assertIsNone(r["raw_ref"])
        # 原始正文不得内联到记录里
        self.assertNotIn("secret body", str(r.values()))

    def test_failed_request_recorded(self):
        r = make_record("CNBC", "https://x", None, None, "2026-01-01T00:00:00+00:00")
        self.assertIsNone(r["sha256"])
        self.assertIsNone(r["http_status"])
        self.assertEqual(r["bytes"], 0)

    def test_summarize_counts(self):
        recs = [
            make_record("FRED", "u", 200, "a", "t"),
            make_record("FRED", "u", 200, "b", "t"),
            make_record("CNBC", "u", None, None, "t"),
        ]
        s = summarize(recs)
        self.assertEqual(s["summary"]["FRED"], {"requests": 2, "ok": 2, "fail": 0})
        self.assertEqual(s["summary"]["CNBC"], {"requests": 1, "ok": 0, "fail": 1})

    def test_different_body_different_hash(self):
        a = make_record("FRED", "u", 200, "a", "t")
        b = make_record("FRED", "u", 200, "b", "t")
        self.assertNotEqual(a["sha256"], b["sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
