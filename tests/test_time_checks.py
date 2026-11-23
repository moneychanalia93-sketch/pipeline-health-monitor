import unittest
from datetime import timedelta

from monitor.checks import check_freshness, check_missed_schedule
from tests.helpers import NOON, make_cfg, make_run, steady_runs


# Freshness: how old is the last GOOD run? (limit in make_cfg is 30 hours)
class FreshnessTests(unittest.TestCase):
    def test_a_recent_success_is_healthy_even_exactly_at_the_limit(self):
        self.assertEqual(check_freshness(make_cfg(), steady_runs(3), NOON), [])
        # The last run ended 30 hours before NOON: exactly the limit, still fine.
        runs = [make_run(NOON - timedelta(hours=30, minutes=10))]
        self.assertEqual(check_freshness(make_cfg(), runs, NOON), [])

    def test_older_than_the_limit_is_a_warning(self):
        runs = [make_run(NOON - timedelta(hours=40))]
        (finding,) = check_freshness(make_cfg(), runs, NOON)
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("40h ago", finding["message"])

    def test_older_than_twice_the_limit_is_critical(self):
        runs = [make_run(NOON - timedelta(hours=70))]
        (finding,) = check_freshness(make_cfg(), runs, NOON)
        self.assertEqual(finding["severity"], "critical")

    def test_no_history_at_all_is_a_warning_not_a_crash(self):
        (finding,) = check_freshness(make_cfg(), [], NOON)
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("no successful run", finding["message"])

    def test_a_failed_run_does_not_make_data_fresh(self):
        runs = [make_run(NOON - timedelta(hours=60)),
                make_run(NOON - timedelta(hours=2), status="failed")]
        self.assertEqual(len(check_freshness(make_cfg(), runs, NOON)), 1)


# Missed schedule: did a run START in time? (interval is 24 hours, grace 1.5 intervals)
class MissedScheduleTests(unittest.TestCase):
    def test_a_run_inside_the_grace_time_is_healthy(self):
        runs = [make_run(NOON - timedelta(hours=35))]     # 35h < 36h
        self.assertEqual(check_missed_schedule(make_cfg(), runs, NOON), [])

    def test_a_long_silence_is_a_warning_then_critical(self):
        warning = check_missed_schedule(make_cfg(), [make_run(NOON - timedelta(hours=40))], NOON)
        critical = check_missed_schedule(make_cfg(), [make_run(NOON - timedelta(hours=61))], NOON)
        self.assertEqual(warning[0]["severity"], "warning")
        self.assertEqual(critical[0]["severity"], "critical")

    def test_a_failed_run_still_counts_as_a_start_and_empty_history_is_left_to_freshness(self):
        runs = [make_run(NOON - timedelta(hours=3), status="failed")]
        self.assertEqual(check_missed_schedule(make_cfg(), runs, NOON), [])
        self.assertEqual(check_missed_schedule(make_cfg(), [], NOON), [])

if __name__ == "__main__":
    unittest.main()
