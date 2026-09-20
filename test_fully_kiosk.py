"""Focused tests for the extracted Fully Kiosk integration module."""

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


class FullyKioskIntegrationTests(unittest.TestCase):
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
            "config/area_registry/list": [],
        }
        app.HA_CONFIG_ENTRIES = Path("missing-synthetic-storage")
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_fully_kiosk_devices(), [])

    def test_discovers_one_monitor_per_host_with_area_names(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [
                {"entry_id": "entry-1", "title": "Fire_Tablet"},
                {"entry_id": "entry-2", "title": "Fire_Tablet"},
            ],
            "config/device_registry/list": [
                {
                    "id": "tablet-1", "config_entry_id": "entry-1",
                    "name": "Fire Tablet", "model": "Synthetic Tablet", "area_id": "area-1",
                },
                {
                    "id": "tablet-2", "config_entry_id": "entry-2",
                    "name": "Fire Tablet", "model": "Synthetic Tablet", "area_id": "area-2",
                },
            ],
            "config/area_registry/list": [
                {"area_id": "area-1", "name": "Kitchen"},
                {"area_id": "area-2", "name": "Hall"},
            ],
        }

        with tempfile.TemporaryDirectory() as temp:
            app.HA_CONFIG_ENTRIES = Path(temp) / "core.config_entries"
            app.HA_CONFIG_ENTRIES.write_text(json.dumps({
                "data": {"entries": [
                    {"domain": "fully_kiosk", "entry_id": "entry-1",
                     "data": {"host": "tablet-one.example.test"}},
                    {"domain": "fully_kiosk", "entry_id": "entry-2",
                     "data": {"host": "tablet-two.example.test"}},
                ]},
            }))
            devices = app.discover_fully_kiosk_devices()

        self.assertEqual(len(devices), 2)
        self.assertEqual(
            {(item["name"], item["host"]) for item in devices},
            {
                ("Fire Tablet Kitchen", "tablet-one.example.test"),
                ("Fire Tablet Hall", "tablet-two.example.test"),
            },
        )

    def test_sync_preserves_monitor_identity_and_state(self):
        device = {
            "device_id": "tablet-1",
            "name": "Fire Tablet Kitchen",
            "host": "tablet-one.example.test",
            "model": "Synthetic Tablet",
            "area": "Kitchen",
        }
        ensure = Mock()
        state = {}
        opts = {
            "fully_kiosk_monitor_prefix": "Fully Kiosk: ",
            "fully_kiosk_ping_interval": 60,
            "fully_kiosk_max_retries": 2,
        }

        app.integration_fully_kiosk.sync_fully_kiosk_devices(
            opts, Mock(), [], [7], state,
            lambda: [device], ensure, logging.getLogger("test-fully-kiosk"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "fully_kiosk:tablet-1")
        self.assertEqual(state["known_fully_kiosk_device_ids"], ["tablet-1"])
        self.assertEqual(
            state["fully_kiosk_devices"]["tablet-1"]["host"],
            "tablet-one.example.test",
        )


if __name__ == "__main__":
    unittest.main()
