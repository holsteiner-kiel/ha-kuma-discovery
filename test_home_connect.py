"""Synthetic Home Connect Local/Cloud fixtures; no live appliances or credentials."""
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class HomeConnectTests(unittest.TestCase):
    def setUp(self):
        self.local_entries = []
        self.cloud_entries = []
        self.devices, self.entities, self.states = [], [], []

    def local(self, serial="serial-1", host="192.168.20.10", title="NEFF Dishwasher"):
        entry_id = "local-" + serial
        self.local_entries.append({"entry_id": entry_id, "unique_id": serial, "title": title,
                                   "data": {"host": host}})
        self.devices.append({"id": "local-device-" + serial, "name_by_user": title,
                             "config_entries": [entry_id],
                             "identifiers": [["homeconnect_ws", serial]]})

    def cloud(self, serial="serial-1", state="on", name="NEFF Dishwasher", connectivity=True):
        entry_id, device_id = "cloud-entry", "cloud-device-" + serial
        self.cloud_entries.append({"entry_id": entry_id, "title": "Home Connect"})
        self.devices.append({"id": device_id, "name_by_user": name, "config_entries": [entry_id],
                             "identifiers": [["home_connect", serial]]})
        if connectivity:
            self.entities.append({"entity_id": "binary_sensor." + serial, "device_id": device_id,
                                  "config_entry_id": entry_id, "platform": "home_connect",
                                  "original_device_class": "connectivity",
                                  "unique_id": serial + ".BSH.Common.Appliance.Connected"})
            self.states.append({"entity_id": "binary_sensor." + serial, "state": state})

    def discover_local(self):
        with patch.object(app, "HAWebSocket") as ws:
            def call(command):
                if command["type"] == "config_entries/get":
                    return self.local_entries
                return self.devices
            ws.return_value.__enter__.return_value.call.side_effect = call
            return app.discover_home_connect_local()

    def discover_cloud(self):
        with patch.object(app, "HAWebSocket") as ws:
            def call(command):
                if command["type"] == "config_entries/get":
                    return self.local_entries if command["domain"] == "homeconnect_ws" else self.cloud_entries
                if command["type"] == "config/device_registry/list":
                    return self.devices
                if command["type"] == "config/entity_registry/list":
                    return self.entities
                if command["type"] == "get_states":
                    return self.states
                raise AssertionError(command)
            ws.return_value.__enter__.return_value.call.side_effect = call
            return app.discover_home_connect_cloud()

    def test_local_host_creates_ping_and_absent_is_noop(self):
        self.local()
        device = self.discover_local()["devices"][0]
        self.assertEqual(device["host"], "192.168.20.10")
        opts = {"homeconnect_local_monitor_prefix": "Home Connect Local: ",
                "homeconnect_local_ping_interval": 60, "homeconnect_local_max_retries": 2}
        with patch.object(app, "discover_home_connect_local", return_value={"devices": [device]}), \
             patch.object(app, "ensure_ping_monitor") as ensure:
            app.sync_home_connect_local(opts, Mock(), [], [], {})
        self.assertEqual(ensure.call_args.args[2], "Home Connect Local: NEFF Dishwasher")
        self.assertEqual(ensure.call_args.args[3], "192.168.20.10")
        self.local_entries = []
        self.assertEqual(self.discover_local()["devices"], [])

    def test_local_invalid_or_missing_host_skips(self):
        for host in ("", "https://secret@example.invalid", "8.8.8.8"):
            with self.subTest(host=host):
                self.local_entries, self.devices = [], []
                self.local(host=host)
                with self.assertLogs(app.LOG, level="INFO") as logs:
                    self.assertEqual(self.discover_local()["devices"], [])
                self.assertNotIn("secret", "\n".join(logs.output))

    def test_cloud_connectivity_states_and_missing_entity(self):
        self.cloud(state="on")
        self.assertTrue(self.discover_cloud()[0]["up"])
        for state in ("off", "unavailable", "unknown"):
            self.states[0]["state"] = state
            self.assertFalse(self.discover_cloud()[0]["up"])
        self.entities = []
        self.assertEqual(self.discover_cloud(), [])

    def test_local_wins_over_same_cloud_identifier_and_cloud_only_is_kept(self):
        self.local("same")
        self.cloud("same")
        self.cloud("cloud-only", name="Coffee machine")
        cloud = self.discover_cloud()
        self.assertEqual([item["appliance_id"] for item in cloud], ["cloud-only"])
        self.local_entries = []
        self.assertEqual(self.discover_cloud()[0]["appliance_id"], "cloud-only")
        self.assertEqual(len(self.discover_cloud()), 2)

    def test_cloud_sync_debounces_down_and_recovers_immediately(self):
        self.cloud("cloud-only", "on")
        device = self.discover_cloud()[0]
        opts = {"homeconnect_monitor_prefix": "Home Connect: ", "heartbeat_interval": 180,
                "push_down_grace_cycles": 3, "kuma_url": "http://example.invalid", "verify_ssl": True,
                "sync_interval": 60}
        monitor = {"id": 1, "name": "Home Connect: NEFF Dishwasher", "type": "push"}
        state, api = {}, Mock()
        with patch.object(app, "discover_home_connect_cloud", return_value=[device]), \
             patch.object(app, "ensure_push_monitor", return_value=monitor), \
             patch.object(app, "push_status_if_needed") as send:
            for observed in ("on", "off", "unavailable", "unknown", "on"):
                device["state"], device["up"] = observed, observed == "on"
                app.sync_home_connect_cloud(opts, api, [monitor], [], state)
        self.assertEqual([call.args[2] for call in send.call_args_list], [True, True, True, False, True])

    def test_no_cross_integration_lookup_is_used(self):
        self.local()
        with patch.object(app, "discover_unifi_network_devices", side_effect=AssertionError), \
             patch.object(app, "discover_fritz_network_devices", side_effect=AssertionError):
            self.assertEqual(self.discover_local()["devices"][0]["host"], "192.168.20.10")


if __name__ == "__main__":
    unittest.main()
