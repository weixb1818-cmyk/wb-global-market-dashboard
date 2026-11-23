"""美债利差同日交叉验证 + 21 观测达标测试。运行：python3 -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import crosscheck_spread  # noqa: E402


def series(*pairs):
    return [{"date": d, "value": v} for d, v in pairs]


class TestSpreadCrosscheck(unittest.TestCase):
    def test_consistent_same_day(self):
        """官方利差 == 同日两腿之差，差异 0bp -> ok。"""
        t10y2y = series(("2026-11-18", 0.27), ("2026-11-19", 0.28))
        dgs10 = series(("2026-11-18", 5.03), ("2026-11-19", 5.04))
        dgs2 = series(("2026-11-18", 4.76), ("2026-11-19", 4.76))
        r = crosscheck_spread(t10y2y, dgs10, dgs2, 2.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["diff_bp"], 0.0, places=3)
        self.assertEqual(r["date"], "2026-11-19")
        self.assertAlmostEqual(r["computed_bp"], 28.0, places=3)
        self.assertAlmostEqual(r["derived_bp"], 28.0, places=3)

    def test_alert_when_exceeds_threshold(self):
        """同日差异超过 2bp -> alert。"""
        derived = series(("2026-11-19", 0.40))   # 40bp
        dgs10 = series(("2026-11-19", 5.04))
        dgs2 = series(("2026-11-19", 4.76))      # 28bp
        r = crosscheck_spread(derived, dgs10, dgs2, 2.0)
        self.assertEqual(r["status"], "alert")
        self.assertAlmostEqual(r["diff_bp"], 12.0, places=3)

    def test_within_threshold_is_ok(self):
        """差异恰在阈值内（含边界）-> ok。"""
        derived = series(("2026-11-19", 0.30))   # 30bp vs 28bp = 2bp
        r = crosscheck_spread(derived,
                              series(("2026-11-19", 5.04)),
                              series(("2026-11-19", 4.76)), 2.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["diff_bp"], 2.0, places=3)

    def test_unverifiable_when_dates_mismatch(self):
        """三序列无共同日期 -> 无法核验，绝不跨日期强行相减。"""
        derived = series(("2026-11-20", 0.29))
        dgs10 = series(("2026-11-19", 5.04))     # 晚一天，不与其相减
        dgs2 = series(("2026-11-19", 4.76))
        r = crosscheck_spread(derived, dgs10, dgs2, 2.0)
        self.assertEqual(r["status"], "unverifiable")
        self.assertIsNone(r["diff_bp"])
        self.assertIn("不跨日期", r["reason"])

    def test_unverifiable_when_one_leg_missing(self):
        """任一腿缺失该日 -> 无法核验。"""
        derived = series(("2026-11-19", 0.28))
        dgs10 = series(("2026-11-19", 5.04))
        r = crosscheck_spread(derived, dgs10, [], 2.0)
        self.assertEqual(r["status"], "unverifiable")

    def test_t10y3m_real_values(self):
        """用实测 FRED 值（2026-11-19）：T10Y3M=0.70, 10Y=5.04, 3M=4.34。"""
        derived = series(("2026-11-19", 0.70))
        r = crosscheck_spread(derived,
                              series(("2026-11-19", 5.04)),
                              series(("2026-11-19", 4.34)), 2.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["computed_bp"], 70.0, places=3)
        self.assertAlmostEqual(r["diff_bp"], 0.0, places=3)

    def test_uses_latest_common_date(self):
        """多日重叠时取最近共同日，差异按该日计算。"""
        derived = series(("2026-11-18", 0.27), ("2026-11-19", 0.28))
        dgs10 = series(("2026-11-18", 5.03), ("2026-11-19", 5.04))
        dgs2 = series(("2026-11-18", 4.76), ("2026-11-19", 4.75))
        r = crosscheck_spread(derived, dgs10, dgs2, 2.0)  # 11-19: 28 vs 29 = -1bp
        self.assertEqual(r["date"], "2026-11-19")
        self.assertAlmostEqual(r["diff_bp"], -1.0, places=3)
        self.assertEqual(r["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
