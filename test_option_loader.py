import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent / "ha_kuma_discovery"))

import option_loader


class OptionLoaderTests(unittest.TestCase):
    def write_options(self, payload):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "options.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_normalizes_defaults_and_bounds(self):
        path = self.write_options({
            "kuma_url": "https://kuma.example.test///",
            "kuma_username": "synthetic",
            "kuma_password": "synthetic",
            "sync_interval": 1,
            "heartbeat_interval": 1,
            "shelly_ping_interval": 1,
            "shelly_max_retries": -1,
            "ignore_slugs": " one, two , ,one ",
        })

        options = option_loader.load_options(path)

        self.assertEqual(options["kuma_url"], "https://kuma.example.test")
        self.assertEqual(options["sync_interval"], 20)
        self.assertEqual(options["heartbeat_interval"], 50)
        self.assertEqual(options["shelly_ping_interval"], 20)
        self.assertEqual(options["shelly_max_retries"], 0)
        self.assertEqual(options["monitor_prefix"], "HA Add-on: ")
        self.assertTrue(options["discover_airgradient_devices"])
        self.assertEqual(options["ignore_slugs_set"], {"one", "two"})

    def test_requires_kuma_credentials(self):
        path = self.write_options({"kuma_url": "https://kuma.example.test"})

        with self.assertRaisesRegex(RuntimeError, "kuma_username, kuma_password"):
            option_loader.load_options(path)


if __name__ == "__main__":
    unittest.main()
