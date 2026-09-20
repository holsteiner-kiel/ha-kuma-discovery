"""Focused tests for the extracted Matter integration module."""

import unittest
from unittest.mock import Mock, patch

from test_reliability import app


class FakeHAWebSocket:
    responses = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def call(self, command):
        return self.responses[command["type"]]


class MatterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_websocket = app.HAWebSocket
        app.HAWebSocket = FakeHAWebSocket
        self.addCleanup(setattr, app, "HAWebSocket", self.original_websocket)

    def test_absent_integration_is_a_clean_noop(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [],
            "config/device_registry/list": [],
            "config/entity_registry/list": [],
            "get_states": [],
        }
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_matter_devices(), [])

    def test_availability_uses_enabled_stateful_native_entities(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [{"entry_id": "matter-entry"}],
            "config/device_registry/list": [
                {
                    "id": "available-device",
                    "config_entry_id": "matter-entry",
                    "identifiers": [["matter", "available-device"]],
                    "name": "Available Light",
                    "model": "Synthetic Light",
                },
                {
                    "id": "offline-device",
                    "config_entry_id": "matter-entry",
                    "identifiers": [["matter", "offline-device"]],
                    "name": "Offline Plug",
                    "model": "Synthetic Plug",
                },
                {
                    "id": "foreign-device",
                    "config_entry_id": "matter-entry",
                    "identifiers": [["other", "foreign-device"]],
                    "name": "Foreign Device",
                },
            ],
            "config/entity_registry/list": [
                {
                    "entity_id": "light.available",
                    "device_id": "available-device",
                    "config_entry_id": "matter-entry",
                    "platform": "matter",
                },
                {
                    "entity_id": "button.available_identify",
                    "device_id": "available-device",
                    "config_entry_id": "matter-entry",
                    "platform": "matter",
                },
                {
                    "entity_id": "switch.offline",
                    "device_id": "offline-device",
                    "config_entry_id": "matter-entry",
                    "platform": "matter",
                },
                {
                    "entity_id": "sensor.disabled",
                    "device_id": "offline-device",
                    "config_entry_id": "matter-entry",
                    "platform": "matter",
                    "disabled_by": "integration",
                },
            ],
            "get_states": [
                {"entity_id": "light.available", "state": "on"},
                {"entity_id": "button.available_identify", "state": "unknown"},
                {"entity_id": "switch.offline", "state": "unavailable"},
                {"entity_id": "sensor.disabled", "state": "42"},
            ],
        }

        devices = app.discover_matter_devices()

        self.assertEqual([item["name"] for item in devices], ["Available Light", "Offline Plug"])
        self.assertTrue(devices[0]["up"])
        self.assertEqual(devices[0]["checked_entities"], 1)
        self.assertFalse(devices[1]["up"])
        self.assertEqual(devices[1]["available_entities"], 0)

    def test_sync_preserves_push_identity_and_saved_inventory(self):
        device = {
            "device_id": "matter-1",
            "name": "Example Light",
            "manufacturer": "Synthetic",
            "model": "Synthetic Light",
            "up": True,
            "available_entities": 1,
            "checked_entities": 1,
            "sample_entity": "light.example",
        }
        opts = {
            "matter_monitor_prefix": "Matter: ",
            "heartbeat_interval": 180,
            "sync_interval": 60,
            "push_down_grace_cycles": 3,
            "kuma_url": "http://example.invalid",
            "verify_ssl": True,
        }
        state = {}
        monitor = {"id": 7, "name": "Matter: Example Light", "type": "push"}

        with patch.object(app, "discover_matter_devices", return_value=[device]), \
             patch.object(app, "ensure_push_monitor", return_value=monitor) as ensure, \
             patch.object(app, "_push_effective_up", return_value=(True, 0)), \
             patch.object(app, "push_status_if_needed") as send:
            app.sync_matter_devices(opts, Mock(), [], [9], state)

        self.assertEqual(ensure.call_args.kwargs["identity"], "matter:matter-1")
        self.assertTrue(send.call_args.args[2])
        self.assertEqual(state["known_matter_device_ids"], ["matter-1"])
        self.assertEqual(state["matter_devices"]["matter-1"]["model"], "Synthetic Light")


if __name__ == "__main__":
    unittest.main()
