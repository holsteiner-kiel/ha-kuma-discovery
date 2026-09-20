"""Home Assistant add-on integration tests; all data is synthetic."""

import unittest
from unittest.mock import patch

from test_reliability import app


class AddonIntegrationTests(unittest.TestCase):
    def test_filters_addons_and_preserves_push_state_mapping(self):
        opts = {
            "ignore_slugs_set": {"ignored"},
            "monitor_prefix": "HA Add-on: ",
            "heartbeat_interval": 180,
            "sync_interval": 60,
            "kuma_url": "http://kuma.invalid",
            "verify_ssl": True,
        }
        addons = {
            "addons": [
                {"slug": "running", "name": "Running", "state": "started"},
                {"slug": "stopped", "name": "Stopped", "state": "stopped"},
                {"slug": "ignored", "name": "Ignored", "state": "started"},
                {
                    "slug": "local_ha_kuma_discovery",
                    "name": "HA Kuma Discovery",
                    "state": "started",
                },
                {"slug": "", "name": "Missing slug", "state": "started"},
            ]
        }
        monitors = []
        state = {}

        def monitor_for(_api, _monitors, name, *_args, **_kwargs):
            return {"id": name, "name": name}

        with patch.object(app, "supervisor_get", return_value=addons), \
             patch.object(app, "ensure_push_monitor", side_effect=monitor_for) as ensure, \
             patch.object(app, "push_status_if_needed") as push:
            app.sync_addons(opts, object(), monitors, [7], state)

        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(
            [call.kwargs["identity"] for call in ensure.call_args_list],
            ["addon:running", "addon:stopped"],
        )
        self.assertEqual([call.args[2] for call in push.call_args_list], [True, False])
        self.assertEqual(state["known_slugs"], ["running", "stopped"])
        self.assertEqual(
            state["names"],
            {"running": "Running", "stopped": "Stopped"},
        )


if __name__ == "__main__":
    unittest.main()
