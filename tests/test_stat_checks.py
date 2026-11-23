import unittest
from datetime import timedelta

from monitor.checks import check_rejects_spike, check_row_count, check_runtime_creep
from tests.helpers import NOON, daily_runs, make_cfg, make_run, steady_runs

# Ten daily runs that wobble a little around 1000 rows. Median 1000, MAD 10.
WOBBLY = [990, 1010, 1000, 980, 1020, 1000, 990, 1010, 1000, 1000]


# Row count: the percent band (30% in make_cfg) and the MAD rule.
class RowCountTests(unittest.TestCase):
    def test_a_normal_run_is_healthy(self):
        self.assertEqual(check_row_count(make_cfg(), daily_runs(WOBBLY + [1015]), NOON), [])

    def test_a_sudden_drop_is_critical_and_says_how_big(self):
        (finding,) = check_row_count(make_cfg(), daily_runs(WOBBLY + [450]), NOON)
        self.assertEqual(finding["severity"], "critical")
        self.assertIn("-55%", finding["message"])
        self.assertIn("source send fewer rows", finding["runbook"])

    def test_a_double_load_is_critical_and_points_to_a_duplicate(self):
        (finding,) = check_row_count(make_cfg(), daily_runs(WOBBLY + [2000]), NOON)
        self.assertEqual(finding["severity"], "critical")
        self.assertIn("duplicated load", finding["runbook"])

    def test_the_mad_rule_catches_a_move_the_wide_band_would_miss(self):
        # 1150 is only +15%, inside the 30% band. But this pipeline barely moves (its usual
        # wobble is 10 rows, raised to the 2% floor = 20), and a gap of 150 is more than
        # 6 x 20 = 120, so the MAD rule raises a warning.
        (finding,) = check_row_count(make_cfg(), daily_runs(WOBBLY + [1150]), NOON)
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("MAD rule", finding["message"])

    def test_not_enough_history_means_no_guess(self):
        self.assertEqual(check_row_count(make_cfg(), [], NOON), [])
        self.assertEqual(check_row_count(make_cfg(), daily_runs([1000]), NOON), [])
        # Only 4 earlier runs: below the minimum of 5, so even a huge drop is not judged.
        self.assertEqual(check_row_count(make_cfg(), daily_runs([1000] * 4 + [10]), NOON), [])

    def test_failed_runs_are_ignored_and_one_old_outlier_does_not_move_the_median(self):
        runs = daily_runs([50] + WOBBLY + [1005])       # one old freak run of 50 rows
        runs.append(make_run(NOON - timedelta(hours=1), status="failed"))
        self.assertEqual(check_row_count(make_cfg(), runs, NOON), [])


# Run-time creep: newest 5 runs against the oldest 7 of the last 30.
class RuntimeCreepTests(unittest.TestCase):
    # `minutes_list` gives the run time of each daily run, oldest first.
    def history(self, minutes_list):
        runs = steady_runs(len(minutes_list))
        for run, minutes in zip(runs, minutes_list):
            run["end"] = run["start"] + timedelta(minutes=minutes)
        return runs

    def test_steady_run_times_are_healthy(self):
        self.assertEqual(check_runtime_creep(make_cfg(), self.history([10] * 20), NOON), [])

    def test_a_slow_creep_is_a_warning(self):
        (finding,) = check_runtime_creep(make_cfg(), self.history([10] * 15 + [14] * 5), NOON)
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("1.4x", finding["message"])

    def test_a_big_slowdown_is_critical(self):
        runs = self.history([10] * 15 + [20] * 5)
        self.assertEqual(check_runtime_creep(make_cfg(), runs, NOON)[0]["severity"], "critical")

    def test_too_few_runs_to_judge(self):
        self.assertEqual(check_runtime_creep(make_cfg(), self.history([10] * 5 + [50] * 5), NOON), [])


# Rejects spike: the share of incoming rows thrown away.
class RejectsSpikeTests(unittest.TestCase):
    # Ten runs with 1% rejected, then one more run with `rejected` rows rejected (of 1000).
    def history(self, rejected):
        runs = steady_runs(10, rows_out=990, rejected=10)
        return runs + [make_run(NOON - timedelta(hours=1), rows_out=1000 - rejected,
                                rejected=rejected)]

    def test_a_normal_reject_rate_is_healthy(self):
        self.assertEqual(check_rejects_spike(make_cfg(), self.history(12), NOON), [])

    def test_a_clear_spike_is_a_warning_and_a_huge_one_is_critical(self):
        (warning,) = check_rejects_spike(make_cfg(), self.history(60), NOON)
        (critical,) = check_rejects_spike(make_cfg(), self.history(150), NOON)
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(critical["severity"], "critical")
        self.assertIn("6.0%", warning["message"])

    def test_a_tiny_baseline_does_not_alert_on_small_numbers(self):
        # Normal is 0%, and 1.5% is 'infinitely more', but still under the 2% floor.
        runs = steady_runs(10) + [make_run(NOON - timedelta(hours=1), rows_out=985, rejected=15)]
        self.assertEqual(check_rejects_spike(make_cfg(), runs, NOON), [])


if __name__ == "__main__":
    unittest.main()
