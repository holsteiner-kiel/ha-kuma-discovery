"""Focused tests for the extracted E3/DC integration module."""

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


class E3DCIntegrationTests(unittest.TestCase):
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
        }
        app.HA_CONFIG_ENTRIES = Path("missing-synthetic-storage")
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_e3dc_devices(), [])

    def test_discovers_only_top_level_controller_with_mac(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [{"entry_id": "entry-1"}],
            "config/device_registry/list": [
                {
                    "id": "controller-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["e3dc_rscp", "serial-1"]],
                    "connections": [["mac", "02:00:00:00:00:01"]],
                    "name": "E3DC_Home",
                    "model": "Synthetic Controller",
                },
                {
                    "id": "battery-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["e3dc_rscp", "battery-1"]],
                    "connections": [["mac", "02:00:00:00:00:02"]],
                    "via_device_id": "controller-1",
                    "name": "Battery",
                },
                {
                    "id": "module-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["e3dc_rscp", "module-1"]],
                    "name": "Module",
                },
            ],
        }

        with patch.object(
            app,
            "_config_entry_hosts_from_storage",
            return_value={"entry-1": "e3dc.example.test"},
        ):
            devices = app.discover_e3dc_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "controller-1")
        self.assertEqual(devices[0]["name"], "E3DC Home")
        self.assertEqual(devices[0]["host"], "e3dc.example.test")
        self.assertEqual(devices[0]["serial"], "serial-1")

    def test_sync_preserves_monitor_identity_and_saved_inventory(self):
        device = {
            "device_id": "controller-1",
            "name": "E3DC Home",
            "host": "e3dc.example.test",
            "model": "Synthetic Controller",
            "serial": "serial-1",
            "source": "e3dc_rscp.config_entry.host:entry-1",
        }
        ensure = Mock()
        state = {}
        opts = {
            "e3dc_monitor_prefix": "E3DC: ",
            "e3dc_ping_interval": 60,
            "e3dc_max_retries": 2,
        }

        app.integration_e3dc.sync_e3dc_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-e3dc"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "e3dc:controller-1")
        self.assertEqual(state["known_e3dc_device_ids"], ["controller-1"])
        self.assertEqual(state["e3dc_devices"]["controller-1"]["serial"], "serial-1")


if __name__ == "__main__":
    unittest.main()
