"""Shelly integration tests; all Home Assistant data is synthetic."""

import unittest
from unittest.mock import Mock, patch

from test_reliability import app


class ShellyIntegrationTests(unittest.TestCase):
    def test_discovery_collapses_channels_by_physical_host(self):
        websocket = Mock()
        websocket.__enter__ = Mock(return_value=websocket)
        websocket.__exit__ = Mock(return_value=None)
        websocket.call.side_effect = [
            [{"entry_id": "shelly-entry"}],
            [
                {
                    "id": "parent",
                    "config_entry_id": "shelly-entry",
                    "name": "Boiler",
                    "configuration_url": "http://192.0.2.10/",
                },
                {
                    "id": "meter",
                    "config_entry_id": "shelly-entry",
                    "name": "Boiler Energy Meter 0",
                    "configuration_url": "http://192.0.2.10/status",
                },
                {
                    "id": "child-without-host",
                    "config_entry_id": "shelly-entry",
                    "name": "Boiler Output 0",
                },
                {
                    "id": "other-integration",
                    "config_entry_id": "other-entry",
                    "name": "Other",
                    "configuration_url": "http://192.0.2.20/",
                },
            ],
        ]

        with patch.object(app, "HAWebSocket", return_value=websocket):
            devices = app.discover_shelly_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "host:192.0.2.10")
        self.assertEqual(devices[0]["name"], "Boiler")
        self.assertEqual(devices[0]["host"], "192.0.2.10")
        self.assertEqual(devices[0]["source_device_ids"], "meter,parent")

    def test_sync_preserves_identity_and_saved_device_mapping(self):
        opts = {
            "shelly_monitor_prefix": "Shelly: ",
            "shelly_ping_interval": 60,
            "shelly_max_retries": 2,
        }
        devices = [
            {
                "device_id": "host:shelly-one.local",
                "name": "Shelly One",
                "host": "shelly-one.local",
            }
        ]
        state = {}

        with patch.object(app, "discover_shelly_devices", return_value=devices), \
             patch.object(app, "ensure_ping_monitor") as ensure:
            app.sync_shelly(opts, object(), [], [7], state)

        ensure.assert_called_once()
        self.assertEqual(ensure.call_args.kwargs["identity"], "shelly:host:shelly-one.local")
        self.assertEqual(state["known_shelly_device_ids"], ["host:shelly-one.local"])
        self.assertEqual(
            state["shelly_devices"],
            {
                "host:shelly-one.local": {
                    "name": "Shelly One",
                    "host": "shelly-one.local",
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
