"""Focused tests for the extracted FRITZ! integration module."""

import json
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


class FritzIntegrationTests(unittest.TestCase):
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
            self.assertEqual(app.discover_fritz_network_devices(), [])

    def test_discovers_native_infrastructure_and_excludes_clients(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [{"entry_id": "entry-1"}],
            "config/device_registry/list": [
                {
                    "id": "router-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["fritz", "router-1"]],
                    "connections": [["mac", "02:00:00:00:00:01"]],
                    "name": "Main Router",
                    "model": "FRITZ!Box Synthetic",
                },
                {
                    "id": "client-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["fritz", "client-1"]],
                    "name": "Example Client",
                    "model": "Phone",
                },
                {
                    "id": "dect-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["fritz", "dect-1"]],
                    "name": "Example Socket",
                    "model": "FRITZ!DECT Synthetic",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp:
            app.HA_CONFIG_ENTRIES = Path(temp) / "core.config_entries"
            app.HA_CONFIG_ENTRIES.write_text(json.dumps({
                "data": {"entries": [{
                    "domain": "fritz",
                    "entry_id": "entry-1",
                    "data": {"host": "router.example.test"},
                }]},
            }))
            devices = app.discover_fritz_network_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["device_id"], "router-1")
        self.assertEqual(devices[0]["host"], "router.example.test")
        self.assertEqual(devices[0]["name"], "Main Router")

    def test_sync_preserves_monitor_identity_and_state(self):
        device = {
            "device_id": "router-1",
            "name": "Main Router",
            "host": "router.example.test",
            "model": "FRITZ!Box Synthetic",
            "source": "fritz_config_entry.host:entry-1",
        }
        ensure = Mock()
        state = {}
        opts = {
            "fritz_monitor_prefix": "FRITZ!: ",
            "fritz_ping_interval": 60,
            "fritz_max_retries": 2,
        }

        app.integration_fritz.sync_fritz_network_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-fritz"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "fritz:router-1")
        self.assertEqual(state["known_fritz_device_ids"], ["router-1"])
        self.assertEqual(state["fritz_devices"]["router-1"]["host"], "router.example.test")


if __name__ == "__main__":
    unittest.main()
