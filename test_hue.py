"""Focused tests for the extracted Philips Hue integration."""
import logging
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class FakeWS:
    responses = {}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def call(self, command): return self.responses[command["type"]]


class HueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old = app.HAWebSocket
        app.HAWebSocket = FakeWS
        self.addCleanup(setattr, app, "HAWebSocket", self.old)

    def test_absent_integration_is_clean_noop(self):
        FakeWS.responses = {
            "config_entries/get": [],
            "config/device_registry/list": [],
            "config/entity_registry/list": [],
            "get_states": [],
        }
        self.assertEqual(app.discover_hue(), {})

    def test_bridge_and_physical_child_are_discovered(self):
        FakeWS.responses = {
            "config_entries/get": [{"entry_id": "hue-1", "title": "Example Bridge"}],
            "config/device_registry/list": [
                {"id": "bridge", "config_entry_id": "hue-1", "identifiers": [["hue", "bridge"]], "name": "Hue Bridge", "model": "Hue Bridge"},
                {"id": "light-1", "config_entry_id": "hue-1", "identifiers": [["hue", "light-1"]], "connections": [["mac", "02:00:00:00:00:01"]], "name": "Desk Light", "model": "Synthetic Light", "manufacturer": "Philips"},
                {"id": "room", "config_entry_id": "hue-1", "identifiers": [["hue", "room"]], "name": "Room"},
            ],
            "config/entity_registry/list": [{"entity_id": "light.desk", "device_id": "light-1", "config_entry_id": "hue-1", "platform": "hue"}],
            "get_states": [{"entity_id": "light.desk", "state": "on"}],
        }
        with patch.object(app, "_config_entry_hosts_from_storage", return_value={"hue-1": "bridge.example.test"}):
            data = app.discover_hue()
        self.assertEqual(data["bridges"][0]["host"], "bridge.example.test")
        self.assertEqual([d["device_id"] for d in data["children"]], ["light-1"])
        self.assertTrue(data["children"][0]["up"])

    def test_sync_preserves_bridge_and_child_identities(self):
        data = {"bridges": [{"entry_id": "hue-1", "name": "Bridge", "host": "bridge.example.test", "title": "Example"}], "children": [{"device_id": "light-1", "name": "Desk Light", "manufacturer": "Philips", "model": "Synthetic", "up": True, "available_entities": 1, "checked_entities": 1, "sample_entity": "light.desk"}]}
        opts = {"discover_hue_bridge": True, "discover_hue_devices": True, "hue_monitor_prefix": "Hue: ", "hue_ping_interval": 60, "hue_max_retries": 2, "heartbeat_interval": 180, "sync_interval": 60, "push_down_grace_cycles": 3, "kuma_url": "http://example.invalid", "verify_ssl": True}
        ping, push, send, state = Mock(), Mock(return_value={"id": 7}), Mock(), {}
        app.integration_hue.sync_hue(opts, Mock(), [], [], state, lambda **_: data, ping, push, lambda *_: (True, 0), send, logging.getLogger("test-hue"))
        self.assertEqual(ping.call_args.kwargs["identity"], "hue_bridge:hue-1")
        self.assertEqual(push.call_args.kwargs["identity"], "hue_device:light-1")
        self.assertEqual(list(state["hue"]["devices"]), ["light-1"])


if __name__ == "__main__": unittest.main()
