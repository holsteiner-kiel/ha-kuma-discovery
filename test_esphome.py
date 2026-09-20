"""Focused tests for the extracted ESPHome integration module."""

import logging
from pathlib import Path
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


class ESPHomeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_websocket = app.HAWebSocket
        self.original_storage = app.HA_CONFIG_ENTRIES
        app.HAWebSocket = FakeHAWebSocket
        self.addCleanup(setattr, app, "HAWebSocket", self.original_websocket)
        self.addCleanup(setattr, app, "HA_CONFIG_ENTRIES", self.original_storage)

    def test_absent_integration_is_a_clean_noop(self):
        FakeHAWebSocket.responses = {"config_entries/get": []}
        app.HA_CONFIG_ENTRIES = Path("missing-synthetic-storage")
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_esphome_devices(), [])

    def test_discovers_hosts_and_deduplicates_case_insensitively(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [
                {
                    "entry_id": "entry-2",
                    "title": "Kitchen",
                    "data": {
                        "host": "device.example.test",
                        "port": 6054,
                        "device_name": "kitchen-sensor",
                    },
                },
                {
                    "entry_id": "entry-1",
                    "title": "Duplicate",
                    "data": {"host": "DEVICE.EXAMPLE.TEST"},
                },
                {"entry_id": "entry-3", "title": "Garage", "data": {}},
            ]
        }

        with patch.object(
            app,
            "_config_entry_hosts_from_storage",
            return_value={"entry-3": "garage.example.test"},
        ):
            devices = app.discover_esphome_devices()

        self.assertEqual([d["name"] for d in devices], ["Garage", "Kitchen"])
        self.assertEqual(devices[1]["port"], 6054)
        self.assertEqual(devices[1]["device_name"], "kitchen-sensor")

    def test_sync_preserves_monitor_identity_and_saved_inventory(self):
        device = {
            "entry_id": "entry-1",
            "name": "Kitchen",
            "host": "device.example.test",
            "port": 6053,
            "device_name": "kitchen-sensor",
        }
        ensure = Mock()
        state = {}
        opts = {
            "esphome_monitor_prefix": "ESPHome: ",
            "esphome_ping_interval": 60,
            "esphome_max_retries": 2,
        }

        app.integration_esphome.sync_esphome_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-esphome"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "esphome:entry-1")
        self.assertEqual(state["esphome"]["entry-1"]["device_name"], "kitchen-sensor")


if __name__ == "__main__":
    unittest.main()
