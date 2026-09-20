"""Focused tests for the extracted Stiebel Eltron integration module."""

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


class StiebelEltronIntegrationTests(unittest.TestCase):
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
            self.assertEqual(app.discover_stiebel_eltron(), [])

    def test_discovers_native_device_name_host_and_port(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [
                {"entry_id": "entry-1", "data": {"port": 1502}}
            ],
            "config/device_registry/list": [
                {
                    "id": "native-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["stiebel_eltron_isg", "serial-1"]],
                    "name": "Stiebel Eltron LWZ",
                    "model": "LWZ Synthetic",
                },
                {
                    "id": "foreign-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["upnp", "foreign"]],
                    "name": "Wrong Device",
                },
            ],
        }

        with patch.object(
            app,
            "_config_entry_hosts_from_storage",
            return_value={"entry-1": "isg.example.test"},
        ):
            devices = app.discover_stiebel_eltron()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["name"], "LWZ")
        self.assertEqual(devices[0]["model"], "LWZ Synthetic")
        self.assertEqual(devices[0]["host"], "isg.example.test")
        self.assertEqual(devices[0]["port"], 1502)

    def test_sync_preserves_monitor_identity_and_saved_inventory(self):
        device = {
            "entry_id": "entry-1",
            "name": "LWZ",
            "model": "LWZ Synthetic",
            "host": "isg.example.test",
            "port": 502,
        }
        ensure = Mock()
        state = {}
        opts = {
            "stiebel_eltron_monitor_prefix": "Stiebel Eltron: ",
            "stiebel_eltron_ping_interval": 60,
            "stiebel_eltron_max_retries": 2,
        }

        app.integration_stiebel_eltron.sync_stiebel_eltron(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-stiebel"),
        )

        self.assertEqual(
            ensure.call_args.kwargs["identity"], "stiebel_eltron:entry-1"
        )
        self.assertEqual(state["stiebel_eltron"]["entry-1"]["port"], 502)


if __name__ == "__main__":
    unittest.main()
