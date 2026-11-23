import os
import unittest
from datetime import datetime, timedelta

from monitor import alerts, db, seed
from monitor.cli import collect
from monitor.config import load_config

REAL_CONFIG = os.path.join(os.path.dirname(__file__), "..", "pipelines.json")
HEALTHY = ["orders_daily", "carrier_events"]
FIRST_STEP = datetime(2026, 10, 25)          # day 1: every pipeline has run at least once
LAST_STEP = datetime(2026, 11, 22, 18, 30)   # just after the last run in the log


# The end-to-end proof. We seed the fake 30 days, replay the checks hour by hour
# (as the monitor would have run them), and compare with the answer key
# in seed.PROBLEMS. The numbers printed here are real.
class SeededDataTests(unittest.TestCase):
    # Replay once, remember every alert that opened or closed, and share it with all tests.
    @classmethod
    def setUpClass(cls):
        cls.configs = load_config(REAL_CONFIG)
        cls.runs = seed.build_runs(cls.configs)
        conn = db.connect(":memory:")
        db.add_runs(conn, cls.runs)
        memory = db.connect(":memory:")
        cls.opened, cls.closed = [], []      # (moment, pipeline, check_name)
        cls.steps = cls.finding_count = 0
        moment = FIRST_STEP
        while moment <= LAST_STEP:
            findings, _ = collect(conn, cls.configs, moment)
            changes = alerts.sync_alerts(memory, findings, moment)
            cls.opened += [(moment, f["pipeline"], f["check_name"]) for f in changes["opened"]]
            cls.closed += [(moment, f["pipeline"], f["check_name"]) for f in changes["closed"]]
            cls.steps += 1
            cls.finding_count += len(findings)
            moment += timedelta(hours=1)
        cls.open_at_end = {(a["pipeline"], a["check_name"]) for a in alerts.open_alerts(memory)}
        conn.close()
        memory.close()

    # The first time an alert for (pipeline, check_name) opened, or None.
    def first_alert(self, pipeline, check_name):
        times = [m for m, p, c in self.opened if (p, c) == (pipeline, check_name)]
        return min(times) if times else None

    def test_the_seed_is_repeatable_and_has_the_expected_size(self):
        self.assertEqual(self.runs, seed.build_runs(self.configs))
        self.assertEqual(len(self.runs), 331)
        self.assertEqual(len({run["pipeline"] for run in self.runs}), 8)
        print(f"\nSeed: {len(self.runs)} runs, 8 pipelines, {len(seed.PROBLEMS)} injected problems")

    def test_every_injected_problem_is_detected(self):
        print("\nDetection (hourly checks, 2026-10-25 to 2026-11-22):")
        found = expected = 0
        for problem in seed.PROBLEMS:
            started = seed.START + timedelta(days=problem["day"])
            for check_name in problem["expect"]:
                expected += 1
                first = self.first_alert(problem["pipeline"], check_name)
                self.assertIsNotNone(first, f"{problem['name']}: no {check_name} alert")
                self.assertGreaterEqual(first, started, "alert came before the problem")
                found += 1
                print(f"  {problem['name']:<31}{problem['pipeline']:<19}{check_name:<16}"
                      f"injected {started:%m-%d}  first alert {first:%m-%d %H:%M}")
        print(f"Detected {found} of {expected} expected alerts for "
              f"{len(seed.PROBLEMS)} of {len(seed.PROBLEMS)} injected problems")

    def test_healthy_pipelines_raise_no_alerts_and_nothing_unexpected_fires(self):
        for _, pipeline, check_name in self.opened:
            self.assertNotIn(pipeline, HEALTHY, f"{check_name} fired on a healthy pipeline")
        allowed = {(p["pipeline"], c) for p in seed.PROBLEMS for c in p["expect"]}
        unexplained = {(p, c) for _, p, c in self.opened} - allowed
        self.assertEqual(unexplained, set())
        print(f"\nFalse alarms: 0. Alerts on the {len(HEALTHY)} healthy pipelines: 0 "
              f"in {self.steps} hourly checks each.")

    def test_each_alert_opens_once_and_closes_when_the_problem_is_gone(self):
        pairs = [(p, c) for _, p, c in self.opened]
        self.assertEqual(len(pairs), len(set(pairs)), "an alert was opened twice")
        still_open = {("route_plans", "schema_drift"), ("inventory_snapshot", "runtime_creep"),
                      ("shipments_feed", "rejects_spike")}
        self.assertEqual(self.open_at_end, still_open)
        self.assertEqual({(p, c) for _, p, c in self.closed}, set(pairs) - still_open)
        print(f"\nDe-duplication: {self.finding_count} findings across {self.steps} hourly checks "
              f"became {len(self.opened)} alerts ({len(self.closed)} closed, "
              f"{len(self.open_at_end)} still open at the end).")

    def test_the_seeded_problems_are_where_the_answer_key_says(self):
        by_pipeline = {p["pipeline"] for p in seed.PROBLEMS}
        self.assertEqual(by_pipeline | set(HEALTHY), {c["name"] for c in self.configs})


if __name__ == "__main__":
    unittest.main()
