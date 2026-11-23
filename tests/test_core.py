"""规格第 8 节验收点的单元测试：python3 -m unittest discover -s tests -v"""
import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    card_note, classify_macro, compute_changes, diff_bp, expected_trading_days_between,
    fmt_change, fmt_value, is_stale, load_config, pct_change, to_bp, us_market_holidays,
)

CFG = load_config()


def macro_inputs(**overrides):
    base = {
        "dxy20": 0.0, "real20bp": 0.0, "twoYear20bp": 0.0,
        "hy20bp": 0.0, "vix20pt": 0.0, "hyNow": 320.0, "vixNow": 18.0,
    }
    base.update(overrides)
    return base


class TestIndicators(unittest.TestCase):
    def test_all_17_indicators_with_units(self):
        inds = CFG["indicators"]
        self.assertEqual(len(inds), 17)
        expected = {
            "dxy": "点", "us2y": "%", "us10y": "%", "us10y_real": "%",
            "t10y2y": "bp", "t10y3m": "bp", "vix": "点", "hy_oas": "bp",
            "sp500": "点", "nasdaq100": "点", "gold": "USD/oz",
            "wti": "USD/bbl", "copper": "USD/lb", "btc": "USD", "eth": "USD",
            "usdjpy": "JPY/USD", "usdcnh": "CNH/USD",
        }
        actual = {i["id"]: i["unit"] for i in inds}
        self.assertEqual(actual, expected)

    def test_no_holiday_ism_cpi_in_config(self):
        blob = str(CFG).lower()
        for banned in ("非农", "ism", "cpi", "trade signal", "自动交易"):
            self.assertNotIn(banned, blob)


class TestUnitsAndChanges(unittest.TestCase):
    def test_10y2y_bp_from_yields(self):
        self.assertAlmostEqual(diff_bp(4.30, 4.00), 30.0)
        self.assertAlmostEqual(diff_bp(4.00, 4.50), -50.0)

    def test_spread_level_to_bp(self):
        self.assertAlmostEqual(to_bp(0.30), 30.0)
        self.assertAlmostEqual(to_bp(-0.50), -50.0)
        self.assertAlmostEqual(to_bp(3.20), 320.0)

    def test_display_units_not_confused(self):
        self.assertEqual(fmt_value(320, "bp"), "+320bp")
        self.assertEqual(fmt_value(320, "bp", signed=False), "320bp")
        self.assertEqual(fmt_change(25, "spread"), "+25bp")
        self.assertEqual(fmt_change(25, "yield"), "+25bp")
        self.assertEqual(fmt_value(4.2, "percent"), "4.20%")
        self.assertNotIn("+0.25%", fmt_change(25, "spread"))

    def test_pct_change(self):
        self.assertAlmostEqual(pct_change(110, 100), 10.0)

    def test_change_20_needs_21_observations(self):
        series = [{"date": f"2026-01-{i+1:02d}", "value": 100 + i} for i in range(20)]
        r = compute_changes(series, "index", window=20)
        self.assertIsNone(r["change_20"])
        series.append({"date": "2026-01-21", "value": 130})
        r = compute_changes(series, "index", window=20)
        self.assertIsNotNone(r["change_20"])

    def test_provider_change_1_preferred(self):
        series = [
            {"date": "2026-01-01", "value": 100},
            {"date": "2026-01-02", "value": 105},
        ]
        r = compute_changes(series, "index", provider_change_1=-2.5)
        self.assertAlmostEqual(r["change_1"], -2.5)


class TestMacroClassification(unittest.TestCase):
    def test_tightening(self):
        r = classify_macro(macro_inputs(dxy20=1.5, real20bp=20), CFG)
        self.assertEqual(r["state"], "tightening")

    def test_moderate_easing(self):
        r = classify_macro(macro_inputs(dxy20=-1.5, real20bp=-20,
                                        hy20bp=-10, vix20pt=-2,
                                        hyNow=300, vixNow=16), CFG)
        self.assertEqual(r["state"], "moderate_easing")

    def test_stress_beats_easing(self):
        r = classify_macro(macro_inputs(dxy20=-2.0, real20bp=-20,
                                        hy20bp=40, vix20pt=5), CFG)
        self.assertEqual(r["state"], "stress_spread")
        self.assertIn("防御", r["headline"])

    def test_growth_concern(self):
        r = classify_macro(macro_inputs(twoYear20bp=-40, hy20bp=30,
                                        vix20pt=1), CFG)
        self.assertEqual(r["state"], "growth_concern")

    def test_high_but_falling_is_not_stress(self):
        r = classify_macro(macro_inputs(hyNow=500, vixNow=30,
                                        hy20bp=-30, vix20pt=-4), CFG)
        self.assertNotEqual(r["state"], "stress_spread")

    def test_missing_key_data(self):
        r = classify_macro(macro_inputs(dxy20=None), CFG)
        self.assertEqual(r["state"], "insufficient")
        self.assertIn("dxy20", r["missing"])
        self.assertIn("暂不判断", r["headline"])

    def test_stale_key_data_with_value_is_rejected(self):
        """P1：关键指标有历史数值但状态为 stale，不得据此给出正常分类。"""
        r = classify_macro(
            macro_inputs(dxy20=1.5, real20bp=20), CFG,
            statuses={"dxy20": "stale"},
        )
        self.assertEqual(r["state"], "insufficient")
        self.assertIn("dxy20", r["missing"])
        self.assertIn("暂不判断", r["headline"])

    def test_error_and_missing_status_also_rejected(self):
        """P1：error / missing 状态同样视为数据不足。"""
        r = classify_macro(macro_inputs(), CFG,
                           statuses={"hy20bp": "error", "vixNow": "missing"})
        self.assertEqual(r["state"], "insufficient")
        self.assertIn("hy20bp", r["missing"])
        self.assertIn("vixNow", r["missing"])

    def test_ok_status_allows_classification(self):
        """P1：状态显式为 ok 时正常分类（防止过度拒绝）。"""
        r = classify_macro(macro_inputs(dxy20=1.5, real20bp=20), CFG,
                           statuses={k: "ok" for k in macro_inputs()})
        self.assertEqual(r["state"], "tightening")

    def test_no_investment_instruction(self):
        for kw in ("买入", "做多", "做空", "必涨", "衰退已至"):
            for kwargs in ({}, {"dxy20": 2, "real20bp": 20},
                           {"dxy20": -2, "real20bp": -20, "hy20bp": -5, "vix20pt": -1}):
                text = str(classify_macro(macro_inputs(**kwargs), CFG))
                self.assertNotIn(kw, text)


class TestCardNotes(unittest.TestCase):
    def test_fx_direction_cnh(self):
        up = card_note("usdcnh", 2.0, CFG)
        down = card_note("usdcnh", -2.0, CFG)
        self.assertIn("美元相对离岸人民币升值", up)
        self.assertIn("美元相对离岸人民币贬值", down)

    def test_fx_direction_jpy(self):
        self.assertIn("美元相对日元升值", card_note("usdjpy", 2.0, CFG))

    def test_curve_steepen_not_recovery(self):
        note = card_note("t10y2y", 30, CFG,
                         aux={"level_bp": 10, "us2y20bp": -30, "us10y20bp": 0})
        self.assertIn("当前为正利差", note)
        self.assertIn("曲线变陡", note)
        self.assertNotIn("经济复苏", note)
        self.assertNotIn("股市必涨", note)

    def test_curve_inversion(self):
        note = card_note("t10y2y", 5, CFG, aux={"level_bp": -20})
        self.assertIn("仍处倒挂", note)

    def test_missing_data_note(self):
        note = card_note("vix", None, CFG, status="stale", as_of="2026-11-14")
        self.assertIn("数据暂未更新", note)
        self.assertIn("2026-11-14", note)
        self.assertNotIn("上升", note)

    def test_insufficient_history_note(self):
        """P2：当前数据正常、历史样本不足，应显示样本不足而非数据延迟。"""
        for ind_id in ("dxy", "gold", "wti", "copper", "btc", "eth"):
            note = card_note(ind_id, None, CFG, status="ok",
                             as_of="2026-11-20", observations=1)
            self.assertIn("历史样本不足", note, (ind_id, note))
            self.assertNotIn("数据暂未更新", note, (ind_id, note))

    def test_stale_with_value_shows_data_not_updated(self):
        """P2：数据过期时，即使有历史变化值也应显示数据暂未更新。"""
        note = card_note("dxy", 2.0, CFG, status="stale", as_of="2026-11-01")
        self.assertIn("数据暂未更新", note)
        self.assertIn("2026-11-01", note)

    def test_vix_note_uses_point_unit(self):
        self.assertIn("风险偏好降温", card_note("vix", 4, CFG))
        self.assertIn("波动预期回落", card_note("vix", -4, CFG))

    def test_note_length_reasonable(self):
        for ind in CFG["indicators"]:
            n = card_note(ind["id"], 30, CFG,
                          aux={"level_bp": 20, "us2y20bp": -30, "us10y20bp": 10})
            self.assertLessEqual(len(n), 45, (ind["id"], n))


class TestStaleness(unittest.TestCase):
    def test_weekend_not_stale(self):
        cfg = CFG
        # 2026-11-19 周四数据，2026-11-21 周六检查：仅 1 个预期发布交易日
        self.assertEqual(expected_trading_days_between(
            dt.date(2026, 11, 19), dt.date(2026, 11, 21)), 1)
        self.assertFalse(is_stale("2026-11-19", "yield", cfg,
                                  dt.datetime(2026, 11, 21, tzinfo=dt.timezone.utc)))

    def test_long_gap_is_stale(self):
        self.assertTrue(is_stale("2026-11-09", "yield", CFG,
                                 dt.datetime(2026, 11, 21, tzinfo=dt.timezone.utc)))

    def test_crypto_36h(self):
        self.assertFalse(is_stale("2026-11-20", "crypto", CFG,
                                  dt.datetime(2026, 11, 21, 12, tzinfo=dt.timezone.utc)))
        self.assertTrue(is_stale("2026-11-19", "crypto", CFG,
                                 dt.datetime(2026, 11, 21, 12, tzinfo=dt.timezone.utc)))

    def test_holidays_exist(self):
        h = us_market_holidays(2026)
        self.assertIn(dt.date(2026, 12, 25), h)
        self.assertNotIn(dt.date(2026, 11, 21), h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
