import sqlite3
import unittest
from datetime import timedelta

from monitor import alerts, db
from monitor.checks import make_finding
from tests.helpers import NOON, make_cfg


# A finding for pipeline p1 from the check called `check_name`.
def finding(check_name="freshness", severity="warning", message="too old"):
    return make_finding(make_cfg(), check_name, severity, message, "look here")


# Tests for opening, repeating and closing alerts (in an in-memory database).
class AlertTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_a_new_finding_opens_an_alert(self):
        changes = alerts.sync_alerts(self.conn, [finding()], NOON)
        self.assertEqual(len(changes["opened"]), 1)
        (alert,) = alerts.open_alerts(self.conn)
        self.assertEqual((alert["pipeline"], alert["check_name"]), ("p1", "freshness"))
        self.assertEqual(alert["first_seen"], "2026-03-10 12:00:00")

    def test_the_same_finding_again_is_not_a_new_alert(self):
        alerts.sync_alerts(self.conn, [finding()], NOON)
        for hours in (1, 2, 3):
            changes = alerts.sync_alerts(self.conn, [finding()], NOON + timedelta(hours=hours))
            self.assertEqual((len(changes["opened"]), len(changes["kept"])), (0, 1))
        (alert,) = alerts.open_alerts(self.conn)
        self.assertEqual(alert["times_seen"], 4)
        self.assertEqual(alert["first_seen"], "2026-03-10 12:00:00")
        self.assertEqual(alert["last_seen"], "2026-03-10 15:00:00")

    def test_an_alert_closes_when_the_finding_goes_away_and_can_open_again(self):
        alerts.sync_alerts(self.conn, [finding()], NOON)
        changes = alerts.sync_alerts(self.conn, [], NOON + timedelta(hours=1))
        self.assertEqual(changes["closed"], [{"pipeline": "p1", "check_name": "freshness"}])
        self.assertEqual(alerts.open_alerts(self.conn), [])
        alerts.sync_alerts(self.conn, [finding()], NOON + timedelta(hours=2))
        total = self.conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        self.assertEqual(total, 2)          # the old closed row stays as history

    def test_a_worse_severity_updates_the_open_alert_in_place(self):
        alerts.sync_alerts(self.conn, [finding(severity="warning")], NOON)
        alerts.sync_alerts(self.conn, [finding(severity="critical", message="much older")],
                           NOON + timedelta(hours=1))
        (alert,) = alerts.open_alerts(self.conn)
        self.assertEqual((alert["severity"], alert["message"]), ("critical", "much older"))

    def test_the_database_itself_refuses_two_open_alerts_for_one_check(self):
        alerts.sync_alerts(self.conn, [finding()], NOON)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO alerts (pipeline, check_name, severity, message, runbook,"
                " first_seen, last_seen, times_seen) VALUES ('p1', 'freshness', 'info', 'm', 'r',"
                " 'x', 'x', 1)")


if __name__ == "__main__":
    unittest.main()
