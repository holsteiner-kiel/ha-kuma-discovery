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
            "ecovacs_ignore": " ecovacs-1, ecovacs-2 , ,ecovacs-1 ",
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
        self.assertEqual(options["ecovacs_ignore_set"], {"ecovacs-1", "ecovacs-2"})
        self.assertTrue(options["discover_homeconnect_local_devices"])
        self.assertTrue(options["discover_homeconnect_cloud_devices"])
        self.assertTrue(options["discover_ecovacs_devices"])
        self.assertEqual(options["homeconnect_local_monitor_prefix"], "Home Connect Local: ")

    def test_requires_kuma_credentials(self):
        path = self.write_options({"kuma_url": "https://kuma.example.test"})

        with self.assertRaisesRegex(RuntimeError, "kuma_username, kuma_password"):
            option_loader.load_options(path)


if __name__ == "__main__":
    unittest.main()
