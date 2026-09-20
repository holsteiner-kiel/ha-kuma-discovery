"""Focused tests for the extracted Overkiz/Somfy integration module."""

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


class OverkizIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_websocket = app.HAWebSocket
        self.original_storage = app.HA_CONFIG_ENTRIES
        app.HAWebSocket = FakeHAWebSocket
        self.addCleanup(setattr, app, "HAWebSocket", self.original_websocket)
        self.addCleanup(setattr, app, "HA_CONFIG_ENTRIES", self.original_storage)

    def test_absent_integration_is_a_clean_noop(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [], "config/device_registry/list": [],
            "config/entity_registry/list": [], "get_states": [],
        }
        app.HA_CONFIG_ENTRIES = Path("missing-synthetic-storage")
        with self.assertNoLogs(app.LOG, level="WARNING"):
            self.assertEqual(app.discover_overkiz_devices(), {})

    def test_discovers_hub_and_native_child_without_duplicate_hub(self):
        FakeHAWebSocket.responses = {
            "config_entries/get": [{
                "entry_id": "entry-1", "data": {"hub": "somfy"},
            }],
            "config/device_registry/list": [
                {
                    "id": "hub-1", "config_entry_id": "entry-1",
                    "identifiers": [["overkiz", "hub-1"]],
                    "name": "TaHoma Switch", "model": "Gateway",
                },
                {
                    "id": "cover-1", "config_entry_id": "entry-1",
                    "identifiers": [["overkiz", "cover-1"]],
                    "name": "Living Room Cover", "model": "Synthetic Cover",
                    "manufacturer": "Somfy",
                },
                {
                    "id": "foreign-1", "config_entry_id": "entry-1",
                    "identifiers": [["other", "foreign-1"]],
                    "name": "Foreign Device",
                },
            ],
            "config/entity_registry/list": [{
                "entity_id": "cover.living_room", "device_id": "cover-1",
                "config_entry_id": "entry-1", "platform": "overkiz",
            }],
            "get_states": [{"entity_id": "cover.living_room", "state": "open"}],
        }

        with patch.object(
            app, "_config_entry_hosts_from_storage",
            return_value={"entry-1": "gateway.example.test:8443"},
        ):
            data = app.discover_overkiz_devices()

        self.assertEqual(data["hub"]["name"], "Tahoma Switch")
        self.assertEqual(data["hub"]["host"], "gateway.example.test")
        self.assertEqual(len(data["children"]), 1)
        self.assertEqual(data["children"][0]["device_id"], "cover-1")
        self.assertTrue(data["children"][0]["up"])

    def test_sync_preserves_hub_and_child_monitor_identities(self):
        data = {
            "hub": {
                "entry_id": "entry-1", "name": "Tahoma Switch",
                "host": "gateway.example.test", "source": "overkiz.config_entry.host",
            },
            "children": [{
                "device_id": "cover-1", "name": "Living Room Cover",
                "manufacturer": "Somfy", "model": "Synthetic Cover",
                "up": True, "available_entities": 1, "checked_entities": 1,
                "sample_entity": "cover.living_room",
            }],
        }
        ping, push, send = Mock(), Mock(return_value={"id": 7}), Mock()
        state = {}
        opts = {
            "overkiz_monitor_prefix": "Somfy: ", "overkiz_ping_interval": 60,
            "overkiz_max_retries": 2, "heartbeat_interval": 180,
            "sync_interval": 60, "push_down_grace_cycles": 3,
            "kuma_url": "http://example.invalid", "verify_ssl": True,
        }

        app.integration_overkiz.sync_overkiz_devices(
            opts, Mock(), [], [9], state, lambda: data, ping, push,
            lambda *_: (True, 0), send, logging.getLogger("test-overkiz"),
        )

        self.assertEqual(ping.call_args.kwargs["identity"], "overkiz_hub:entry-1")
        self.assertEqual(push.call_args.kwargs["identity"], "overkiz_device:cover-1")
        self.assertTrue(send.call_args.args[2])
        self.assertEqual(list(state["overkiz"]["devices"]), ["cover-1"])


if __name__ == "__main__":
    unittest.main()
