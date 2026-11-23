"""运行记录测试（P2 + 审计 WB 第 4 项）。

覆盖：计划/启动/完成时间、定时延迟、触发类型区分（scheduled /
manual_dispatch / manual_local）、手动不计入定时延迟、失败检测、
审计要求的 8 个必含字段、不伪造历史。
运行：python3 -m unittest discover -s tests -v
"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.update_data as ud  # noqa: E402
from core import load_config  # noqa: E402

CFG = load_config()
_ORIGINAL_PATH = ud.RUN_LOG_PATH
SCHEDULED_ENV = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_RUN_ID": "111",
                 "GITHUB_SHA": "abc123"}
DISPATCH_ENV = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "222",
                "GITHUB_SHA": "def456"}


class TestRunLog(unittest.TestCase):
    def tearDown(self):
        ud.RUN_LOG_PATH = _ORIGINAL_PATH

    def test_planned_time_and_delay_scheduled(self):
        """定时运行：计划 UTC 00:15，启动 00:20 -> 延迟 5 分钟。"""
        started = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
        finished = dt.datetime(2026, 11, 23, 0, 20, 30, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            rec = ud.append_run_log(CFG, started, finished, [], {}, "insufficient",
                                    env=SCHEDULED_ENV)
        self.assertEqual(rec["planned_utc"], "2026-11-23T00:15:00+00:00")
        self.assertAlmostEqual(rec["delay_minutes"], 5.0, places=1)
        self.assertAlmostEqual(rec["duration_seconds"], 30.0, places=1)
        self.assertEqual(rec["conclusion"], "ok")
        self.assertEqual(rec["trigger_type"], "scheduled")

    def test_early_scheduled_trigger_negative_delay(self):
        """定时提前触发 -> 延迟为负，如实记录不裁剪为 0。"""
        started = dt.datetime(2026, 11, 23, 0, 10, tzinfo=dt.timezone.utc)
        finished = started + dt.timedelta(seconds=10)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            rec = ud.append_run_log(CFG, started, finished, [], {}, "insufficient",
                                    env=SCHEDULED_ENV)
        self.assertAlmostEqual(rec["delay_minutes"], -5.0, places=1)

    def test_manual_does_not_count_schedule_delay(self):
        """手动派发/本地手动：delay_minutes=null，不计入定时延迟统计。"""
        started = dt.datetime(2026, 11, 23, 10, 0, tzinfo=dt.timezone.utc)
        finished = started + dt.timedelta(seconds=10)
        for env, expected_trigger in ((DISPATCH_ENV, "manual_dispatch"),
                                      ({}, "manual_local")):
            with tempfile.TemporaryDirectory() as td:
                ud.RUN_LOG_PATH = Path(td) / "run_log.json"
                rec = ud.append_run_log(CFG, started, finished, [], {}, "x", env=env)
            self.assertIsNone(rec["delay_minutes"])
            self.assertEqual(rec["trigger_type"], expected_trigger)
            self.assertIn("不计入", rec["delay_note"])

    def test_required_eight_fields_present(self):
        """审计要求每条记录至少含 8 个字段，且取值合理。"""
        started = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
        finished = started + dt.timedelta(seconds=10)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            rec = ud.append_run_log(CFG, started, finished, [], {}, "insufficient",
                                    env=SCHEDULED_ENV)
        for field in ("run_id", "trigger_type", "started_at", "completed_at",
                      "conclusion", "script_started", "snapshot_generated", "commit_sha"):
            self.assertIn(field, rec, field)
        self.assertEqual(rec["run_id"], "111")
        self.assertEqual(rec["commit_sha"], "abc123")
        self.assertTrue(rec["script_started"])
        self.assertTrue(rec["snapshot_generated"])

    def test_failure_detection_status(self):
        """有失败源 -> conclusion=fail；有逐指标失败但源级成功 -> partial。"""
        started = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
        finished = started + dt.timedelta(seconds=10)
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            r1 = ud.append_run_log(CFG, started, finished, ["FRED"], {}, "insufficient",
                                   env=SCHEDULED_ENV)
            r2 = ud.append_run_log(CFG, started, finished, [], {"gold": "x"},
                                   "insufficient", env=SCHEDULED_ENV)
        self.assertEqual(r1["conclusion"], "fail")
        self.assertEqual(r2["conclusion"], "partial")
        self.assertIn("FRED", r1["failed_sources"])
        self.assertIn("gold", r2["failed_indicators"])

    def test_append_and_keep_last(self):
        """多次追加，且仅保留最近 keep_last 条。"""
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            base = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
            for i in range(5):
                st = base + dt.timedelta(days=i)
                ud.append_run_log(CFG, st, st + dt.timedelta(seconds=5), [], {}, "x",
                                  env=SCHEDULED_ENV)
            data = ud.load_json_safe(ud.RUN_LOG_PATH)
            self.assertEqual(len(data["runs"]), 5)
            self.assertEqual(data["runs"][-1]["planned_utc"], "2026-11-27T00:15:00+00:00")

    def test_no_fabricated_runs(self):
        """新日志仅含本次真实执行，不预填历史日期。"""
        with tempfile.TemporaryDirectory() as td:
            ud.RUN_LOG_PATH = Path(td) / "run_log.json"
            st = dt.datetime(2026, 11, 23, 0, 20, tzinfo=dt.timezone.utc)
            ud.append_run_log(CFG, st, st + dt.timedelta(seconds=5), [], {}, "x",
                              env=SCHEDULED_ENV)
            data = ud.load_json_safe(ud.RUN_LOG_PATH)
            self.assertEqual(len(data["runs"]), 1)

    def test_trigger_type_mapping(self):
        """GITHUB_EVENT_NAME 到触发类型的映射互斥。"""
        self.assertEqual(ud._trigger_type({"GITHUB_EVENT_NAME": "schedule"}), "scheduled")
        self.assertEqual(ud._trigger_type({"GITHUB_EVENT_NAME": "workflow_dispatch"}),
                         "manual_dispatch")
        self.assertEqual(ud._trigger_type({}), "manual_local")
        self.assertEqual(ud._trigger_type({"GITHUB_EVENT_NAME": "push"}), "manual_local")


if __name__ == "__main__":
    unittest.main(verbosity=2)
