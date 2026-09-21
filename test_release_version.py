"""Keep the add-on manifest and startup banner on the same release version."""

from pathlib import Path
import sys
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).parent / "ha_kuma_discovery"))

import app


class ReleaseVersionTests(unittest.TestCase):
    def test_startup_version_matches_addon_manifest(self):
        config = yaml.safe_load(
            (Path(__file__).parent / "ha_kuma_discovery" / "config.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(app.APP_VERSION, config["version"])


if __name__ == "__main__":
    unittest.main()
