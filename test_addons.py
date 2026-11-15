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


    def test_inactive_monitor_skipped_and_later_addon_processed(self):
        opts = {"ignore_slugs_set": set(), "monitor_prefix": "HA Add-on: ",
                "heartbeat_interval": 180, "sync_interval": 60,
                "kuma_url": "http://kuma.invalid", "verify_ssl": True}
        addons = {"addons": [
            {"slug": "paused", "name": "Paused", "state": "stopped"},
            {"slug": "running", "name": "Running", "state": "started"},
        ]}
        monitors = []
        state = {}
        def ensure(_api, _monitors, name, *_args, **_kwargs):
            return {"id": name, "name": name, "active": 0 if name.endswith("Paused") else 1}
        with patch.object(app, "supervisor_get", return_value=addons), \
             patch.object(app, "ensure_push_monitor", side_effect=ensure), \
             patch.object(app, "push_status_if_needed", return_value=True) as push, \
             self.assertLogs(app.LOG, level="INFO") as logs:
            app.sync_addons(opts, object(), monitors, [], state)
        self.assertEqual(push.call_count, 1)
        self.assertTrue(push.call_args.args[2])
        self.assertIn("1 inactive skipped", "\n".join(logs.output))

    def test_failed_heartbeat_logs_safe_status_and_continues(self):
        from requests.exceptions import HTTPError
        from unittest.mock import Mock
        opts = {"ignore_slugs_set": set(), "monitor_prefix": "HA Add-on: ",
                "heartbeat_interval": 180, "sync_interval": 60,
                "kuma_url": "http://kuma.invalid", "verify_ssl": True}
        addons = {"addons": [
            {"slug": "broken", "name": "Broken", "state": "stopped"},
            {"slug": "working", "name": "Working", "state": "started"},
        ]}
        response = Mock(status_code=404)
        problem = HTTPError("http://kuma.invalid/api/push/secret-token")
        problem.response = response
        def send(*args, **kwargs):
            if args[1]["name"].endswith("Broken"):
                raise problem
            return True
        with patch.object(app, "supervisor_get", return_value=addons), \
             patch.object(app, "ensure_push_monitor",
                          side_effect=lambda api, monitors, name, *a, **kw:
                          {"name": name, "active": 1}), \
             patch.object(app, "push_status_if_needed", side_effect=send) as push, \
             self.assertLogs(app.LOG, level="INFO") as logs:
            app.sync_addons(opts, object(), [], [], {})
        output = "\n".join(logs.output)
        self.assertEqual(push.call_count, 2)
        self.assertIn("HTTP status=404", output)
        self.assertNotIn("secret-token", output)
        self.assertIn("1 failed", output)


if __name__ == "__main__":
    unittest.main()
