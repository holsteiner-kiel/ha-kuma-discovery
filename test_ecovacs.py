"""Synthetic Ecovacs fixtures; no live devices, IPs or credentials."""
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class EcovacsTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{"entry_id": "ecovacs-entry"}]
        self.devices, self.entities, self.states = [], [], []

    def add(self, stable_id="robot-1", name="DEEBOT X1 OMNI", state="192.168.30.10", disabled=None):
        device_id = "device-" + stable_id
        self.devices.append({"id": device_id, "name_by_user": name,
                             "config_entries": ["ecovacs-entry"],
                             "identifiers": [["ecovacs", stable_id]]})
        self.entities.append({"entity_id": "sensor." + stable_id + "_ip", "device_id": device_id,
                              "config_entry_id": "ecovacs-entry", "platform": "ecovacs",
                              "translation_key": "network_ip", "disabled_by": disabled})
        self.states.append({"entity_id": "sensor." + stable_id + "_ip", "state": state})

    def discover(self):
        with patch.object(app, "HAWebSocket") as ws:
            responses = {"config_entries/get": self.entries, "config/device_registry/list": self.devices,
                         "config/entity_registry/list": self.entities, "get_states": self.states}
            ws.return_value.__enter__.return_value.call.side_effect = lambda command: responses[command["type"]]
            return app.discover_ecovacs_devices()

    def options(self, ignored=""):
        return {"ecovacs_monitor_prefix": "Ecovacs: ", "ecovacs_ping_interval": 60,
                "ecovacs_max_retries": 2, "ecovacs_ignore": ignored}

    def test_absent_integration_is_noop(self):
        self.entries = []
        self.assertEqual(self.discover(), [])

    def test_valid_ip_creates_one_ping_per_physical_device(self):
        self.add()
        self.add("robot-2", "GOAT G1", "192.168.30.11")
        devices = self.discover()
        self.assertEqual(len(devices), 2)
        with patch.object(app, "discover_ecovacs_devices", return_value=devices), \
             patch.object(app, "ensure_ping_monitor") as ensure:
            app.sync_ecovacs_devices(self.options(), Mock(), [], [], {})
        self.assertEqual(ensure.call_count, 2)
        self.assertEqual(ensure.call_args_list[0].args[3], "192.168.30.10")

    def test_disabled_entity_warns_and_is_skipped(self):
        self.add(disabled="integration")
        devices = self.discover()
        with self.assertLogs(app.LOG, level="WARNING") as logs, \
             patch.object(app, "discover_ecovacs_devices", return_value=devices), \
             patch.object(app, "ensure_ping_monitor") as ensure:
            app.sync_ecovacs_devices(self.options(), Mock(), [], [], {})
        ensure.assert_not_called()
        output = "\n".join(logs.output)
        self.assertIn("network_ip", output)
        self.assertIn("robot-1", output)

    def test_unavailable_or_invalid_ip_warns_and_is_skipped(self):
        for value in ("unavailable", "unknown", "", "not-an-ip"):
            with self.subTest(value=value):
                self.devices, self.entities, self.states = [], [], []
                self.add(state=value)
                devices = self.discover()
                with self.assertLogs(app.LOG, level="WARNING") as logs, \
                     patch.object(app, "discover_ecovacs_devices", return_value=devices), \
                     patch.object(app, "ensure_ping_monitor") as ensure:
                    app.sync_ecovacs_devices(self.options(), Mock(), [], [], {})
                ensure.assert_not_called()
                self.assertIn("no valid IP", "\n".join(logs.output))

    def test_ignored_device_is_silent(self):
        self.add(disabled="integration")
        devices = self.discover()
        with self.assertNoLogs(app.LOG, level="WARNING"), \
             patch.object(app, "discover_ecovacs_devices", return_value=devices), \
             patch.object(app, "ensure_ping_monitor") as ensure:
            app.sync_ecovacs_devices(self.options("robot-1"), Mock(), [], [], {})
        ensure.assert_not_called()

    def test_no_cross_integration_lookup_is_used(self):
        self.add()
        with patch.object(app, "discover_unifi_network_devices", side_effect=AssertionError), \
             patch.object(app, "discover_fritz_network_devices", side_effect=AssertionError):
            self.assertEqual(self.discover()[0]["host"], "192.168.30.10")


if __name__ == "__main__":
    unittest.main()
