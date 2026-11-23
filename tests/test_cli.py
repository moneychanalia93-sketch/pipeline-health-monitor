import contextlib
import io
import os
import tempfile
import unittest

from monitor.cli import main

REAL_CONFIG = os.path.join(os.path.dirname(__file__), "..", "pipelines.json")


# Tests that run the real command line (main) against a temporary database.
class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.folder.name, "runs.db")

    def tearDown(self):
        self.folder.cleanup()

    # Run main() with the temp database and the real config. Returns (code, stdout, stderr).
    def run_cli(self, *args, config=REAL_CONFIG):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--db", self.db, "--config", config, *args])
        return code, out.getvalue(), err.getvalue()

    def test_seed_then_check_prints_the_table_and_writes_the_html_page(self):
        code, out, _ = self.run_cli("seed")
        self.assertEqual(code, 0)
        self.assertIn("Wrote 331 runs for 8 pipelines", out)
        page = os.path.join(self.folder.name, "health.html")
        code, out, _ = self.run_cli("check", "--html", page)
        self.assertEqual(code, 0)
        self.assertIn("8 pipelines: 5 green, 2 amber, 1 red", out)
        self.assertRegex(out, r"route_plans\s+RED")
        with open(page, encoding="utf-8") as handle:
            self.assertIn("<svg", handle.read())

    def test_checking_again_does_not_repeat_the_same_alerts(self):
        self.run_cli("seed")
        _, first, _ = self.run_cli("check")
        _, second, _ = self.run_cli("check")
        self.assertIn("This check: 3 new, 0 still open, 0 closed", first)
        self.assertIn("This check: 0 new, 3 still open, 0 closed", second)
        self.assertIn("Open alerts (3):", second)

    def test_bad_input_gives_exit_code_2_and_a_clear_message(self):
        code, _, err = self.run_cli("check")                     # no database yet
        self.assertEqual((code, "run the seed command first" in err), (2, True))
        bad_config = os.path.join(self.folder.name, "bad.json")
        with open(bad_config, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.run_cli("seed")
        code, _, err = self.run_cli("check", config=bad_config)
        self.assertEqual((code, "config error" in err), (2, True))
        code, _, err = self.run_cli("replay", "--from", "2026-11-10", "--to", "2026-11-01")
        self.assertEqual((code, "on or after" in err), (2, True))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["--db", self.db, "check", "--as-of", "last tuesday"])

    def test_replay_shows_an_alert_opening_then_closing_and_leaves_the_alert_table_alone(self):
        self.run_cli("seed")
        code, out, _ = self.run_cli("replay", "--from", "2026-11-12", "--to", "2026-11-14 04:00")
        self.assertEqual(code, 0)
        self.assertRegex(out, r"2026-11-13 03:00  OPENED  critical returns_daily / row_count")
        self.assertIn("2026-11-14 03:00  CLOSED  returns_daily / row_count", out)
        _, checked, _ = self.run_cli("check")
        self.assertIn("3 new", checked)        # replay saved nothing in the real alert table


if __name__ == "__main__":
    unittest.main()
