import unittest
from datetime import timedelta

from monitor.checks import (check_failures, check_reconciliation, check_schema_drift,
                            run_checks)
from monitor.alerts import SEVERITY_RANK
from tests.helpers import NOON, make_cfg, make_run, names, steady_runs


# A history of good runs followed by the given statuses ("success" or "failed").
def history_ending_with(*statuses):
    runs = steady_runs(6)
    for i, status in enumerate(statuses):
        runs.append(make_run(NOON - timedelta(hours=1 + len(statuses) - i), status=status,
                             error="timeout reading source"))
    return runs


# Failure checks: consecutive failures and failure rate.
class FailureTests(unittest.TestCase):
    def test_one_failed_run_alone_raises_nothing(self):
        self.assertEqual(check_failures(make_cfg(), history_ending_with("failed"), NOON), [])

    def test_two_in_a_row_is_a_warning_and_shows_the_error(self):
        (finding,) = check_failures(make_cfg(), history_ending_with("failed", "failed"), NOON)
        self.assertEqual(finding["severity"], "warning")
        self.assertIn("2 failed runs in a row", finding["message"])
        self.assertIn("timeout reading source", finding["message"])

    def test_three_or_more_in_a_row_is_critical(self):
        runs = history_ending_with("failed", "failed", "failed")
        self.assertEqual(check_failures(make_cfg(), runs, NOON)[0]["severity"], "critical")

    def test_a_success_ends_the_streak(self):
        runs = history_ending_with("failed", "failed", "success")
        self.assertEqual(check_failures(make_cfg(), runs, NOON), [])

    def test_a_high_failure_rate_is_a_warning_even_without_a_streak(self):
        runs = history_ending_with("failed", "success", "failed", "success", "failed", "success")
        (finding,) = check_failures(make_cfg(), runs, NOON)
        self.assertIn("of the last 10 runs failed", finding["message"])

    def test_first_run_and_empty_history_are_fine(self):
        self.assertEqual(check_failures(make_cfg(), [], NOON), [])
        self.assertEqual(check_failures(make_cfg(), [make_run(NOON, status="failed")], NOON), [])


# Reconciliation: rows_in must equal rows_out + rows_rejected.
class ReconciliationTests(unittest.TestCase):
    def test_numbers_that_add_up_are_healthy(self):
        runs = [make_run(NOON, rows_out=990, rejected=10)]
        self.assertEqual(check_reconciliation(make_cfg(), runs, NOON), [])

    def test_more_rows_out_than_in_points_to_a_duplicate(self):
        runs = [make_run(NOON, rows_out=2000, rows_in=1000)]
        (finding,) = check_reconciliation(make_cfg(), runs, NOON)
        self.assertEqual(finding["severity"], "critical")
        self.assertIn("+1,000", finding["message"])
        self.assertIn("duplicated load", finding["runbook"])

    def test_fewer_rows_out_than_in_points_to_lost_rows(self):
        runs = [make_run(NOON, rows_out=900, rows_in=1000)]
        (finding,) = check_reconciliation(make_cfg(), runs, NOON)
        self.assertIn("-100", finding["message"])
        self.assertIn("went missing", finding["runbook"])

    def test_failed_runs_and_empty_history_are_skipped(self):
        self.assertEqual(check_reconciliation(make_cfg(), [], NOON), [])
        runs = [make_run(NOON, status="failed", rows_in=500)]
        self.assertEqual(check_reconciliation(make_cfg(), runs, NOON), [])


# Schema drift: columns seen against columns required.
class SchemaDriftTests(unittest.TestCase):
    def test_same_columns_are_healthy_whatever_the_order(self):
        runs = [make_run(NOON, columns=["amount", "order_id"])]
        self.assertEqual(check_schema_drift(make_cfg(), runs, NOON), [])

    def test_a_missing_required_column_is_critical(self):
        (finding,) = check_schema_drift(make_cfg(), [make_run(NOON, columns=["order_id"])], NOON)
        self.assertEqual(finding["severity"], "critical")
        self.assertIn("amount", finding["message"])

    def test_a_new_column_is_info_and_a_missing_one_wins_over_it(self):
        extra = make_run(NOON, columns=["order_id", "amount", "coupon"])
        self.assertEqual(check_schema_drift(make_cfg(), [extra], NOON)[0]["severity"], "info")
        both = make_run(NOON, columns=["order_id", "coupon"])
        (finding,) = check_schema_drift(make_cfg(), [both], NOON)
        self.assertEqual(finding["severity"], "critical")


# The runner that calls every check.
class RunChecksTests(unittest.TestCase):
    def test_a_healthy_pipeline_gets_no_findings(self):
        self.assertEqual(run_checks(make_cfg(), steady_runs(10), NOON), [])

    def test_every_finding_has_a_known_severity_a_message_and_a_runbook(self):
        old_good = make_run(NOON - timedelta(hours=60), columns=["order_id"])
        failed = [make_run(NOON - timedelta(hours=h), status="failed") for h in (3, 2, 1)]
        findings = run_checks(make_cfg(), [old_good] + failed, NOON)
        self.assertEqual(sorted(names(findings)), ["failures", "freshness", "schema_drift"])
        for finding in findings:
            self.assertIn(finding["severity"], SEVERITY_RANK)
            self.assertTrue(finding["message"] and finding["runbook"])
            self.assertEqual(finding["pipeline"], "p1")
        self.assertIn("failures", names(findings))


if __name__ == "__main__":
    unittest.main()
