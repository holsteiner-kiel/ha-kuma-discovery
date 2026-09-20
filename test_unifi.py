"""Focused tests for the extracted UniFi integration module."""

import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from test_reliability import app


class FakeHAWebSocket:
    responses = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def call(self, command):
        return self.responses[command["type"]]


class UniFiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_websocket = app.HAWebSocket
        self.original_storage = app.HA_CONFIG_ENTRIES
        app.HAWebSocket = FakeHAWebSocket
        self.addCleanup(setattr, app, "HAWebSocket", self.original_websocket)
        self.addCleanup(setattr, app, "HA_CONFIG_ENTRIES", self.original_storage)

    def test_absent_integration_is_a_clean_noop(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [],
            "config/device_registry/list": [],
            "config/entity_registry/list": [],
            "get_states": [],
        }
        app.HA_CONFIG_ENTRIES = Path("missing-synthetic-storage")
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_unifi_network_devices(), [])

    def test_discovers_infrastructure_from_matching_tracker(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [{"entry_id": "entry-1"}],
            "config/device_registry/list": [{
                "id": "device-1",
                "config_entry_id": "entry-1",
                "connections": [["mac", "02:00:00:00:00:01"]],
                "name": "Workshop Switch",
                "model": "Synthetic Switch",
            }],
            "config/entity_registry/list": [
                {
                    "entity_id": "update.workshop_switch",
                    "device_id": "device-1",
                    "config_entry_id": "entry-1",
                },
                {
                    "entity_id": "device_tracker.workshop_switch",
                    "device_id": None,
                    "config_entry_id": "entry-1",
                    "unique_id": "02:00:00:00:00:01",
                },
            ],
            "get_states": [{
                "entity_id": "device_tracker.workshop_switch",
                "state": "home",
                "attributes": {"ip": "switch.example.test"},
            }],
        }
        with tempfile.TemporaryDirectory() as temp:
            app.HA_CONFIG_ENTRIES = Path(temp) / "core.config_entries"
            app.HA_CONFIG_ENTRIES.write_text('{"data":{"entries":[]}}')
            devices = app.discover_unifi_network_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "device-1")
        self.assertEqual(devices[0]["name"], "Workshop Switch")
        self.assertEqual(devices[0]["host"], "switch.example.test")

    def test_sync_preserves_monitor_identity_and_state(self):
        device = {
            "device_id": "device-1",
            "name": "Workshop Switch",
            "host": "switch.example.test",
            "model": "Synthetic Switch",
            "ip_source": "device_tracker.workshop_switch",
        }
        ensure = Mock()
        state = {}
        opts = {
            "unifi_monitor_prefix": "UniFi: ",
            "unifi_ping_interval": 60,
            "unifi_max_retries": 2,
        }

        app.integration_unifi.sync_unifi_network_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-unifi"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "unifi:device-1")
        self.assertEqual(state["known_unifi_device_ids"], ["device-1"])
        self.assertEqual(state["unifi_devices"]["device-1"]["host"], "switch.example.test")


if __name__ == "__main__":
    unittest.main()
