"""历史首次达到 21 个有效观测时的计算与宏观分类转变测试（P0）。

覆盖审计要求：完善"历史首次达到 21 个有效观测"时的计算与分类测试。
运行：python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import classify_macro, compute_changes, load_config  # noqa: E402

CFG = load_config()


def make_series(n, kind_value, start=1):
    """构造 n 个按日递增的合成序列（仅用于验证计数边界，不写入生产快照）。"""
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    return [{"date": (base + timedelta(days=i)).isoformat(),
             "value": kind_value(i)} for i in range(n)]


def macro_inputs(**overrides):
    base = {
        "dxy20": 0.0, "real20bp": 0.0, "twoYear20bp": 0.0,
        "hy20bp": 0.0, "vix20pt": 0.0, "hyNow": 320.0, "vixNow": 18.0,
    }
    base.update(overrides)
    return base


class TestHistoryThreshold(unittest.TestCase):
    def test_change20_transitions_at_exactly_21(self):
        """恰好 20 点 -> None；第 21 点到达 -> 有效值。"""
        s20 = make_series(20, lambda i: 100 + i)
        s21 = make_series(21, lambda i: 100 + i)
        self.assertIsNone(compute_changes(s20, "index", 20)["change_20"])
        r21 = compute_changes(s21, "index", 20)
        self.assertIsNotNone(r21["change_20"])
        # 20 期变化：从索引0(100) 到索引20(120) = +20%
        self.assertAlmostEqual(r21["change_20"], 20.0, places=3)
        self.assertEqual(r21["observations"], 21)

    def test_yield_kind_change20_at_21(self):
        """收益率口径：21 点时 change_20 为 bp 差。"""
        s = make_series(21, lambda i: 4.00 + 0.01 * i)  # 4.00 -> 4.20 = +20bp
        r = compute_changes(s, "yield", 20)
        self.assertAlmostEqual(r["change_20"], 20.0, places=3)

    def test_macro_insufficient_until_dxy20_available(self):
        """端到端逻辑链：dxy 历史不足 -> dxy20=None -> insufficient；
        第21点到 -> dxy20 有效且状态 ok -> 正常分类（tightening）。"""
        s20 = make_series(20, lambda i: 100 + i)
        s21 = make_series(21, lambda i: 100 + 1.5 * i)  # +30% 20期

        def to_input(series):
            return compute_changes(series, "index", 20)["change_20"]

        before = to_input(s20)
        self.assertIsNone(before)
        r_before = classify_macro(macro_inputs(dxy20=before), CFG,
                                  statuses={"dxy20": "ok"})
        self.assertEqual(r_before["state"], "insufficient")
        self.assertIn("dxy20", r_before["missing"])

        after = to_input(s21)
        self.assertIsNotNone(after)
        r_after = classify_macro(
            macro_inputs(dxy20=after, real20bp=20), CFG,
            statuses={k: "ok" for k in macro_inputs()},
        )
        self.assertEqual(r_after["state"], "tightening")

    def test_no_partial_window_derivation(self):
        """不足 21 点时不得用较短窗口近似替代 change_20。"""
        for n in (2, 10, 19, 20):
            s = make_series(n, lambda i: 100 + i)
            self.assertIsNone(
                compute_changes(s, "index", 20)["change_20"],
                f"n={n} 不应产生 change_20",
            )

    def test_insufficient_does_not_reuse_stale_value(self):
        """样本不足阶段（缺 change_20）不得沿用昨日分类结论。"""
        r = classify_macro(macro_inputs(dxy20=None), CFG)
        self.assertEqual(r["state"], "insufficient")
        self.assertIn("不沿用旧结论", r["uncertainty"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
