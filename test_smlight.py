"""Focused tests for the extracted SMLIGHT integration module."""

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


class SMLIGHTIntegrationTests(unittest.TestCase):
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
            self.assertEqual(app.discover_smlight_devices(), [])

    def test_discovers_hosts_and_deduplicates_case_insensitively(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [
                {
                    "entry_id": "entry-2",
                    "title": "Upstairs",
                    "data": {"host": "coordinator.example.test"},
                },
                {
                    "entry_id": "entry-1",
                    "title": "Downstairs",
                    "data": {"host": "COORDINATOR.EXAMPLE.TEST"},
                },
                {"entry_id": "entry-3", "title": "Garage"},
            ]
        }

        with patch.object(
            app,
            "_config_entry_hosts_from_storage",
            return_value={"entry-3": "garage.example.test"},
        ):
            devices = app.discover_smlight_devices()

        self.assertEqual([d["name"] for d in devices], ["Garage", "Upstairs"])
        self.assertEqual(devices[0]["host"], "garage.example.test")
        self.assertEqual(devices[1]["entry_id"], "entry-2")

    def test_sync_preserves_monitor_identity_and_saved_inventory(self):
        device = {
            "entry_id": "entry-1",
            "name": "Coordinator",
            "host": "coordinator.example.test",
        }
        ensure = Mock()
        state = {}
        opts = {
            "smlight_monitor_prefix": "SMLIGHT: ",
            "smlight_ping_interval": 60,
            "smlight_max_retries": 2,
        }

        app.integration_smlight.sync_smlight_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-smlight"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "smlight:entry-1")
        self.assertEqual(state["smlight"]["entry-1"]["host"], "coordinator.example.test")


if __name__ == "__main__":
    unittest.main()
