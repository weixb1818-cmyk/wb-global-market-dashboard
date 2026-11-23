"""运行记录（计划/启动/完成/延迟/失败检测）测试（P2）。

运行：python3 -m unittest discover -s tests -v
"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.update_data as ud  # noqa: E402
from core import load_config  # noqa: E402

CFG = load_config()
_ORIGINAL_PATH = ud.RUN_LOG_PATH


class TestRunLog(unittest.TestCase):
    def tearDown(self):
        ud.RUN_LOG_PATH = _ORIGINAL_PATH

    def test_planned_time_and_delay(self):
        """计划 UTC 00:15；启动 00:20 -> 延迟 5 分钟。"""
        started = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
        finished = dt.datetime(2026, 11, 23, 0, 20, 30, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            rec = ud.append_run_log(CFG, started, finished, [], {}, "insufficient")
        self.assertEqual(rec["planned_utc"], "2026-11-23T00:15:00+00:00")
        self.assertAlmostEqual(rec["delay_minutes"], 5.0, places=1)
        self.assertAlmostEqual(rec["duration_seconds"], 30.0, places=1)
        self.assertEqual(rec["status"], "ok")

    def test_early_trigger_negative_delay(self):
        """手动提前触发 -> 延迟为负，如实记录不裁剪为 0。"""
        started = dt.datetime(2026, 11, 23, 0, 10, tzinfo=dt.timezone.utc)
        finished = dt.datetime(2026, 11, 23, 0, 10, 10, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            rec = ud.append_run_log(CFG, started, finished, [], {}, "insufficient")
        self.assertAlmostEqual(rec["delay_minutes"], -5.0, places=1)

    def test_failure_detection_status(self):
        """有失败源 -> status=fail；有逐指标失败但源级成功 -> partial。"""
        started = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
        finished = started + dt.timedelta(seconds=10)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            r1 = ud.append_run_log(CFG, started, finished, ["FRED"], {}, "insufficient")
            r2 = ud.append_run_log(CFG, started, finished, [], {"gold": "x"}, "insufficient")
        self.assertEqual(r1["status"], "fail")
        self.assertEqual(r2["status"], "partial")
        self.assertIn("FRED", r1["failed_sources"])
        self.assertIn("gold", r2["failed_indicators"])

    def test_append_and_keep_last(self):
        """多次追加，且仅保留最近 keep_last 条。"""
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            base = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
            for i in range(5):
                st = base + dt.timedelta(days=i)
                ud.append_run_log(CFG, st, st + dt.timedelta(seconds=5), [], {}, "x")
            data = ud.load_json_safe(ud.RUN_LOG_PATH)
            self.assertEqual(len(data["runs"]), 5)
            self.assertEqual(data["runs"][-1]["planned_utc"], "2026-11-27T00:15:00+00:00")

    def test_no_fabricated_runs(self):
        """新日志仅含本次真实执行，不预填历史日期。"""
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            st = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
            ud.append_run_log(CFG, st, st + dt.timedelta(seconds=5), [], {}, "x")
            data = ud.load_json_safe(ud.RUN_LOG_PATH)
            self.assertEqual(len(data["runs"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
