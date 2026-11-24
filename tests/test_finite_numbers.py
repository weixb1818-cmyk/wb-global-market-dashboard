"""审计第三轮技术修正 2：非有限数值（NaN/±Inf）闸门测试。

覆盖三处必检点：
1. 数值解析：update_data._num 必须排除 NaN / ±Inf；
2. 历史序列合并：update_data.merge_series 必须丢弃非有限观测；
3. 宏观分类入口：core.classify_macro 即使 status=ok，非有限数值也必须阻断。

附带验证计算层加固（compute_changes / crosscheck_spread）不改变正常公式结果。
运行：python3 -m unittest discover -s tests -v
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    classify_macro, compute_changes, crosscheck_spread, is_finite_number, load_config,
)
from scripts.update_data import _num, merge_series  # noqa: E402

CFG = load_config()
NON_FINITE = [float("nan"), float("inf"), float("-inf"),
              "nan", "inf", "-inf", "Infinity"]


def _ok_statuses():
    return {k: "ok" for k in (
        "dxy20", "real20bp", "twoYear20bp", "hy20bp", "vix20pt", "hyNow", "vixNow")}


def _good_inputs():
    return {
        "dxy20": 0.0, "real20bp": 0.0, "twoYear20bp": 0.0,
        "hy20bp": 0.0, "vix20pt": 0.0, "hyNow": 320.0, "vixNow": 18.0,
    }


class TestIsFiniteNumber(unittest.TestCase):
    def test_finite_values_accepted(self):
        for v in (0, 3.14, -2, "3.5", "-0.001"):
            self.assertTrue(is_finite_number(v), v)

    def test_non_finite_rejected(self):
        for v in NON_FINITE + [None, "", True, False, "abc"]:
            self.assertFalse(is_finite_number(v), repr(v))


class TestNumParsingFinite(unittest.TestCase):
    def test_nan_and_inf_return_none(self):
        for v in ["nan", "NaN", "inf", "-inf", "Infinity", "-Infinity"]:
            self.assertIsNone(_num(v), v)

    def test_finite_values_still_parse(self):
        self.assertEqual(_num("3.52"), 3.52)
        self.assertEqual(_num("1,234.5"), 1234.5)
        self.assertEqual(_num("2.5%"), 2.5)


class TestMergeSeriesFinite(unittest.TestCase):
    def test_non_finite_observations_dropped(self):
        old = [
            {"date": "2026-11-20", "value": 100.0, "source": "FRED:x"},
            {"date": "2026-11-21", "value": float("inf"), "source": "FRED:x"},
            {"date": "2026-11-22", "value": float("nan"), "source": "FRED:x"},
        ]
        new = [
            {"date": "2026-11-23", "value": float("-inf"), "source": "FRED:x"},
            {"date": "2026-11-24", "value": 101.5, "source": "FRED:x"},
        ]
        merged = merge_series(old, new)
        self.assertEqual([o["date"] for o in merged],
                         ["2026-11-20", "2026-11-24"])
        for o in merged:
            self.assertTrue(math.isfinite(o["value"]))


class TestMacroFiniteGate(unittest.TestCase):
    def test_inf_blocked_even_with_ok_status(self):
        for bad in (float("inf"), float("-inf"), float("nan")):
            inputs = _good_inputs()
            inputs["dxy20"] = bad
            res = classify_macro(inputs, CFG, _ok_statuses())
            self.assertEqual(res["state"], "insufficient")
            self.assertIn("dxy20", res["missing"])

    def test_non_finite_string_blocked(self):
        inputs = _good_inputs()
        inputs["hyNow"] = "Infinity"
        res = classify_macro(inputs, CFG, _ok_statuses())
        self.assertEqual(res["state"], "insufficient")
        self.assertIn("hyNow", res["missing"])

    def test_all_finite_ok_still_classifies(self):
        """有限数值且状态 ok 时仍正常分类，证明闸门不改变阈值与公式。"""
        inputs = _good_inputs()
        inputs["dxy20"] = 5.0   # >= dxy20_strong_pct
        inputs["real20bp"] = 40.0  # >= real20_up_bp
        res = classify_macro(inputs, CFG, _ok_statuses())
        self.assertEqual(res["state"], "tightening")


class TestComputeFiniteGuard(unittest.TestCase):
    def test_non_finite_observations_ignored_in_changes(self):
        series = [
            {"date": "2026-11-20", "value": 100.0},
            {"date": "2026-11-21", "value": float("inf")},
            {"date": "2026-11-22", "value": 110.0},
        ]
        out = compute_changes(series, "index")
        self.assertEqual(out["observations"], 2)
        self.assertEqual(out["value"], 110.0)
        self.assertAlmostEqual(out["change_1"], 10.0)

    def test_crosscheck_ignores_non_finite(self):
        derived = [{"date": "2026-11-23", "value": 0.28}]
        leg_a = [{"date": "2026-11-23", "value": 4.10}]
        leg_b = [{"date": "2026-11-23", "value": float("nan")}]
        res = crosscheck_spread(derived, leg_a, leg_b, 2.0)
        self.assertEqual(res["status"], "unverifiable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
