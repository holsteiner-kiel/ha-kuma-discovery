"""Focused tests for the extracted Synology DSM integration module."""

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


class SynologyIntegrationTests(unittest.TestCase):
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
            self.assertEqual(app.discover_synology_dsm(), [])

    def test_discovers_only_root_nas_and_deduplicates_host(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [
                {"entry_id": "entry-1", "data": {"host": "nas.example.test"}},
                {"entry_id": "entry-2", "data": {"host": "NAS.EXAMPLE.TEST"}},
            ],
            "config/device_registry/list": [
                {
                    "id": "nas-1",
                    "config_entry_id": "entry-1",
                    "identifiers": [["synology_dsm", "serial-1"]],
                    "name_by_user": "Main NAS",
                    "model": "DS Synthetic",
                },
                {
                    "id": "disk-1",
                    "config_entry_id": "entry-1",
                    "via_device_id": "nas-1",
                    "identifiers": [["synology_dsm", "disk-1"]],
                    "name": "Drive 1",
                },
            ],
        }

        with patch.object(app, "_config_entry_hosts_from_storage", return_value={}):
            devices = app.discover_synology_dsm()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["entry_id"], "entry-1")
        self.assertEqual(devices[0]["name"], "Main NAS")
        self.assertEqual(devices[0]["model"], "DS Synthetic")

    def test_sync_preserves_monitor_identity_and_saved_inventory(self):
        device = {
            "entry_id": "entry-1",
            "name": "Main NAS",
            "model": "DS Synthetic",
            "host": "nas.example.test",
        }
        ensure = Mock()
        state = {}
        opts = {
            "synology_monitor_prefix": "Synology: ",
            "synology_ping_interval": 60,
            "synology_max_retries": 2,
        }

        app.integration_synology.sync_synology_dsm(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-synology"),
        )

        self.assertEqual(
            ensure.call_args.kwargs["identity"], "synology_dsm:entry-1"
        )
        self.assertEqual(state["synology_dsm"]["entry-1"]["model"], "DS Synthetic")


if __name__ == "__main__":
    unittest.main()
