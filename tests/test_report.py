import re
import unittest

from monitor import report
from tests.helpers import NOON, make_cfg, steady_runs


# An open-alert dict shaped like the rows from alerts.open_alerts.
def alert(severity="critical", pipeline="p1", message="a message"):
    return {"severity": severity, "pipeline": pipeline, "check_name": "freshness",
            "message": message, "runbook": "look here", "first_seen": "2026-03-10 11:00:00",
            "times_seen": 3}


# One pipeline summary built from ten good runs and the given open alerts.
def one_summary(open_alerts, name="p1"):
    cfg = make_cfg(name=name)
    return [report.summarize(cfg, steady_runs(10), NOON, open_alerts)]


NO_CHANGES = {"opened": [], "kept": [], "closed": []}


# Tests for the text table, the HTML page and the sparkline.
class ReportTests(unittest.TestCase):
    def test_status_color_follows_the_worst_open_alert(self):
        self.assertEqual(report.pipeline_status([]), "green")
        self.assertEqual(report.pipeline_status([alert("info")]), "green")
        self.assertEqual(report.pipeline_status([alert("warning")]), "amber")
        self.assertEqual(report.pipeline_status([alert("warning"), alert("critical")]), "red")

    def test_text_report_shows_status_counts_alerts_and_the_runbook(self):
        alerts = [alert()]
        changes = {"opened": alerts, "kept": [], "closed": []}
        text = report.text_report(one_summary(alerts), alerts, changes, NOON)
        self.assertIn("Pipeline health as of 2026-03-10 12:00:00", text)
        self.assertIn("1 pipelines: 0 green, 0 amber, 1 red", text)
        self.assertRegex(text, r"p1\s+RED\s+team-a")
        self.assertIn("1 new, 0 still open, 0 closed", text)
        self.assertIn("[CRITICAL] p1 / freshness", text)
        self.assertIn("Check first: look here", text)

    def test_html_escapes_every_message_so_it_cannot_inject_markup(self):
        evil = "<script>alert('x')</script> & <b>bold</b>"
        alerts = [alert(message=evil, pipeline="<i>p&q</i>")]
        page = report.html_report(one_summary(alerts, name="<i>p&q</i>"), alerts, NOON)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>bold", page)
        self.assertNotIn("<i>p&q</i>", page)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;", page)

    def test_html_page_is_self_contained_and_has_the_expected_parts(self):
        alerts = [alert("warning")]
        page = report.html_report(one_summary(alerts), alerts, NOON)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        for part in ["<h1>Pipeline health</h1>", "<th>Pipeline</th>", "<th>Last 30 runs</th>",
                     '<span class="dot amber">', "<svg", "<polyline", "<h2>Open alerts (1)</h2>",
                     '<li class="warning">', "Check first:"]:
            self.assertIn(part, page)
        for outside in ["http", "<script", "<link", "@import", "src="]:
            self.assertNotIn(outside, page)
        self.assertIn("No open alerts", report.html_report(one_summary([]), [], NOON))

    def test_sparkline_scales_the_lowest_to_the_bottom_and_highest_to_the_top(self):
        self.assertEqual(report.sparkline([5]), "n/a")
        svg = report.sparkline([10, 30, 20], width=100, height=24)
        points = re.search(r'points="([^"]+)"', svg).group(1).split()
        self.assertEqual(points, ["0.0,22.0", "50.0,2.0", "100.0,12.0"])
        self.assertIn("<polyline", report.sparkline([7, 7, 7]))       # a flat line must not crash


if __name__ == "__main__":
    unittest.main()
