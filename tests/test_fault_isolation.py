"""逐指标故障隔离测试（P1）：模拟部分报价成功/部分失败、CNBC 时间戳边界。
运行：python3 -m unittest discover -s tests -v
"""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.update_data as ud  # noqa: E402

CFG = ud.load_config()


class TestCNBCFaultIsolation(unittest.TestCase):
    def test_partial_quotes_only_failed_marked(self):
        """部分报价成功、部分失败：成功指标有值，失败指标进入 failed 字典。"""
        sym_map = CFG["sources"]["cnbc"]["symbols"]
        # 只返回第一个符号的有效报价，其余缺失
        first_sym = list(sym_map.values())[0]
        payload = {
            "FormattedQuoteResult": {
                "FormattedQuote": [{
                    "symbol": first_sym, "code": 0,
                    "last": "100.0", "change_pct": "0.5%",
                    "last_time": "2026-11-20", "name": "Probe",
                }]
            }
        }
        with mock.patch.object(ud, "http_json", return_value=payload):
            out, failed = ud.fetch_cnbc_all(CFG)
        self.assertIn(first_sym and list(sym_map.keys())[0], out)
        self.assertTrue(failed)
        # 失败的指标不应出现在 out 中
        for ind_id in failed:
            self.assertNotIn(ind_id, out)
        # 成功 + 失败 = 全部 CNBC 指标
        self.assertEqual(len(out) + len(failed), len(sym_map))

    def test_whole_source_failure_marks_all(self):
        """整个 CNBC 源失败：所有 CNBC 指标都进入 failed。"""
        with mock.patch.object(ud, "http_json", side_effect=RuntimeError("network down")):
            out, failed = ud.fetch_cnbc_all(CFG)
        self.assertEqual(out, {})
        self.assertEqual(set(failed), set(CFG["sources"]["cnbc"]["symbols"]))

    def test_parse_cnbc_date_valid(self):
        """合法时间戳：ISO 与 MM/DD/YY 均能解析。"""
        self.assertEqual(ud._parse_cnbc_date("2026-11-20"), "2026-11-20")
        self.assertEqual(ud._parse_cnbc_date("2026-11-20T16:00:00Z"), "2026-11-20")
        self.assertEqual(ud._parse_cnbc_date("11/20/26 EST"), "2026-11-20")

    def test_parse_cnbc_date_missing_or_illegal(self):
        """无时间戳、非法时间戳（含非法日历日）一律返回 None，不回填系统日期。"""
        for bad in (None, "", "garbage", "2026-13-45", "02/30/26", "2026-02-30 EST", 0):
            self.assertIsNone(ud._parse_cnbc_date(bad), bad)

    def test_missing_timestamp_quote_is_failed_not_ok(self):
        """CNBC 报价无 last_time：该指标进 failed，不进 out（不会被当作当天 ok 数据）。"""
        sym = list(CFG["sources"]["cnbc"]["symbols"].values())[0]
        ind = list(CFG["sources"]["cnbc"]["symbols"].keys())[0]
        payload = {"FormattedQuoteResult": {"FormattedQuote": [{
            "symbol": sym, "code": 0, "last": "103.5", "change_pct": "0.5%",
            "name": "Probe",  # 故意不提供 last_time / last_timedate
        }]}}
        with mock.patch.object(ud, "http_json", return_value=payload):
            out, failed = ud.fetch_cnbc_all(CFG)
        self.assertNotIn(ind, out)
        self.assertIn(ind, failed)
        self.assertIn("timestamp", failed[ind])

    def test_illegal_timestamp_quote_is_failed_not_ok(self):
        """CNBC 报价时间戳非法（2026-13-45）：进 failed，不进 out。"""
        sym = list(CFG["sources"]["cnbc"]["symbols"].values())[0]
        ind = list(CFG["sources"]["cnbc"]["symbols"].keys())[0]
        payload = {"FormattedQuoteResult": {"FormattedQuote": [{
            "symbol": sym, "code": 0, "last": "103.5",
            "last_time": "2026-13-45", "name": "Probe",
        }]}}
        with mock.patch.object(ud, "http_json", return_value=payload):
            out, failed = ud.fetch_cnbc_all(CFG)
        self.assertNotIn(ind, out)
        self.assertIn(ind, failed)


class TestCurrencyFaultIsolation(unittest.TestCase):
    def test_one_pair_missing_does_not_affect_other(self):
        """某一币种在所有快照中都缺失，只标记该币种，另一币种仍成功。"""
        pairs = CFG["sources"]["currency_api"]["pairs"]  # {usdjpy: jpy, usdcnh: cnh}
        (id_a, key_a), (id_b, key_b) = list(pairs.items())

        def fake_http(url, cfg, **kwargs):
            # 所有日期快照都只含 key_a 的汇率，不含 key_b
            return {"date": "2026-11-20", "usd": {key_a: 150.0}}

        with mock.patch.object(ud, "http_json", side_effect=fake_http):
            out, failed = ud.fetch_currency_api(CFG)
        self.assertTrue(out[id_a], f"{id_a} 应有观测")
        self.assertEqual(out[id_b], [])
        self.assertIn(id_b, failed)
        self.assertNotIn(id_a, failed)


class TestBuildSnapshotStatus(unittest.TestCase):
    def _minimal_cfg(self):
        # 用真实配置，但只构造两个指标的快照场景
        return CFG

    def test_failed_indicator_marked_stale(self):
        """failed_indicators 中的指标状态为 stale，且保留上次有效值。"""
        cfg = CFG
        ind_id = "dxy"
        old_history = {"series": {ind_id: [
            {"date": "2026-11-18", "value": 103.0},
            {"date": "2026-11-19", "value": 103.5},
        ]}}
        old_snapshot = {"indicators": {ind_id: {
            "value": 103.5, "display_value": "103.50", "as_of": "2026-11-19",
            "source": "CNBC:.DXY", "status": "ok",
        }}}
        snap, _ = ud.build_snapshot(
            cfg, {}, {}, [], old_history, old_snapshot,
            failed_indicators={ind_id: "CNBC quote missing/invalid"},
        )
        self.assertEqual(snap["indicators"][ind_id]["status"], "stale")
        # 保留上次有效值
        self.assertEqual(snap["indicators"][ind_id]["value"], 103.5)
        self.assertIn("数据暂未更新", snap["indicators"][ind_id]["note"])

    def test_stale_macro_input_blocks_classification(self):
        """端到端：关键指标 stale 时宏观输出 insufficient（即使有历史值）。"""
        cfg = CFG
        # 构造足够的历史让 dxy 有 change_20 数值
        hist = {}
        for i in range(25):
            d = f"2026-10-{i+1:02d}"
            for ind in ("dxy", "us2y", "us10y_real", "hy_oas", "vix",
                        "sp500", "nasdaq100"):
                hist.setdefault(ind, []).append({"date": d, "value": 100.0 + i})
        old_history = {"series": hist}
        # dxy 本轮取数失败
        snap, _ = ud.build_snapshot(
            cfg, {}, {}, [], old_history, {},
            failed_indicators={"dxy": "CNBC quote missing/invalid"},
        )
        self.assertEqual(snap["indicators"]["dxy"]["status"], "stale")
        self.assertEqual(snap["macro"]["state"], "insufficient")
        self.assertIn("dxy20", snap["macro"]["missing"])


class TestNoSystemDateBackfill(unittest.TestCase):
    def test_snapshot_does_not_backfill_system_date(self):
        """端到端：CNBC 报价无 as_of 时，build_snapshot 绝不写入系统当天日期。"""
        cfg = CFG
        ind_id = "dxy"
        today = dt.date.today().isoformat()
        old_history = {"series": {ind_id: [
            {"date": "2026-11-18", "value": 103.0},
            {"date": "2026-11-19", "value": 103.5},
        ]}}
        # 直接构造一个缺失 as_of 的报价传入（fetch 层本应已拦截，此处验证 build 层防御）
        cnbc = {ind_id: {"value": 104.0, "as_of": None, "change_1": 0.5,
                         "source": "CNBC:.DXY"}}
        snap, hist = ud.build_snapshot(cfg, {}, cnbc, [], old_history, {})
        dates = [o["date"] for o in hist["series"][ind_id]]
        self.assertNotIn(today, dates)
        self.assertLessEqual(max(dates), "2026-11-19")


class TestFredSeriesIsolation(unittest.TestCase):
    def test_one_fred_series_failure_does_not_affect_others(self):
        """FRED 单序列取数失败：该序列进 failed 标记，其余序列仍正常取到。"""
        series = CFG["sources"]["fred"]["series"]
        (id_a, sid_a), (id_b, sid_b) = list(series.items())[:2]

        def one(url, cfg, params=None, **kwargs):
            if params and params.get("id") == sid_a:
                raise RuntimeError("simulated FRED failure")
            return "observation_date,VALUE\n2026-11-18,1.5\n2026-11-19,1.6\n"

        with mock.patch.object(ud, "http_text", side_effect=one):
            out = ud.fetch_fred_all(CFG)
        self.assertNotIn(id_a, out)
        self.assertIn(id_b, out)
        self.assertTrue(out[id_b])


class TestMacroFailClosed(unittest.TestCase):
    def test_all_stale_inputs_force_insufficient(self):
        """所有关键输入有值但状态全为 stale：宏观必须 fail-closed。"""
        from core import classify_macro
        inputs = {k: 1.0 for k in (
            "dxy20", "real20bp", "twoYear20bp", "hy20bp", "vix20pt", "hyNow", "vixNow")}
        statuses = {k: "stale" for k in inputs}
        r = classify_macro(inputs, CFG, statuses)
        self.assertEqual(r["state"], "insufficient")
        self.assertEqual(len(r["missing"]), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
