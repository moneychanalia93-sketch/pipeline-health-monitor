import json
import os
import tempfile
import unittest

from monitor.config import ConfigError, load_config
from tests.helpers import make_cfg

REAL_CONFIG = os.path.join(os.path.dirname(__file__), "..", "pipelines.json")


# Tests for reading and checking pipelines.json.
class ConfigTests(unittest.TestCase):
    # Each test gets a temporary folder that is deleted afterwards.
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    # Write `data` as JSON (or raw text) to a file and return the path.
    def write(self, data):
        path = os.path.join(self.folder.name, "pipelines.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_the_real_config_file_is_valid(self):
        pipelines = load_config(REAL_CONFIG)
        self.assertEqual(len(pipelines), 8)

    def test_a_missing_file_or_broken_json_is_a_clear_error(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_config(os.path.join(self.folder.name, "nope.json"))
        with self.assertRaisesRegex(ConfigError, "not valid JSON"):
            load_config(self.write("{not json"))

    def test_the_file_must_hold_a_non_empty_pipelines_list(self):
        for bad in ([], {}, {"pipelines": []}, {"pipelines": "x"}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                load_config(self.write(bad))

    def test_names_must_be_present_and_unique(self):
        with self.assertRaisesRegex(ConfigError, "used twice"):
            load_config(self.write({"pipelines": [make_cfg(), make_cfg()]}))
        with self.assertRaisesRegex(ConfigError, "non-empty name"):
            load_config(self.write({"pipelines": [make_cfg(name="  ")]}))

    def test_every_field_is_checked(self):
        bad_changes = [{"owner": ""}, {"interval_hours": 0}, {"freshness_hours": "24"},
                       {"band_percent": True}, {"band_percent": 150},
                       {"required_columns": []}, {"required_columns": ["ok", ""]},
                       {"required_columns": "order_id"}]
        for change in bad_changes:
            with self.subTest(change=change), self.assertRaises(ConfigError):
                load_config(self.write({"pipelines": [make_cfg(**change)]}))


if __name__ == "__main__":
    unittest.main()
