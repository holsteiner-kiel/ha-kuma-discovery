"""Stable monitor identity tests; all data is synthetic."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_reliability import app


class StableMonitorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch.object(app.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_push_rename_reuses_monitor_id_without_creating_duplicate(self):
        old = {
            "id": 41,
            "name": "Matter: Old name",
            "type": "push",
            "interval": 180,
            "retryInterval": 180,
            "maxretries": 0,
        }
        renamed = {**old, "name": "Matter: New name"}
        state = {
            "_monitor_identities": {
                "matter:device-1": {
                    "monitor_id": 41,
                    "name": "Matter: Old name",
                    "type": "push",
                }
            }
        }
        api = Mock()
        api.get_monitors.return_value = [renamed]
        monitors = [old]

        result = app.ensure_push_monitor(
            api, monitors, "Matter: New name", 180, [],
            state=state, identity="matter:device-1",
        )

        api.add_monitor.assert_not_called()
        api.edit_monitor.assert_called_once_with(41, name="Matter: New name")
        self.assertEqual(result, renamed)
        self.assertEqual(
            state["_monitor_identities"]["matter:device-1"],
            {"monitor_id": 41, "name": "Matter: New name", "type": "push"},
        )

    def test_ping_rename_and_host_change_reuse_monitor_id(self):
        old = {
            "id": 52,
            "name": "ESPHome: Old name",
            "type": "ping",
            "hostname": "old.example",
            "interval": 60,
            "retryInterval": 60,
            "maxretries": 2,
        }
        renamed = {**old, "name": "ESPHome: New name", "hostname": "new.example"}
        state = {
            "_monitor_identities": {
                "esphome:entry-1": {
                    "monitor_id": 52,
                    "name": "ESPHome: Old name",
                    "type": "ping",
                }
            }
        }
        api = Mock()
        api.get_monitors.return_value = [renamed]

        result = app.ensure_ping_monitor(
            api, [old], "ESPHome: New name", "new.example", 60, 2, [],
            state=state, identity="esphome:entry-1",
        )

        api.add_monitor.assert_not_called()
        api.edit_monitor.assert_called_once_with(
            52, name="ESPHome: New name", hostname="new.example",
        )
        self.assertEqual(result, renamed)
        self.assertEqual(state["_monitor_identities"]["esphome:entry-1"]["monitor_id"], 52)

    def test_existing_same_name_monitor_bootstraps_identity(self):
        monitor = {
            "id": 63,
            "name": "Shelly: Garage",
            "type": "ping",
            "hostname": "shelly-garage.local",
            "interval": 60,
            "retryInterval": 60,
            "maxretries": 2,
        }
        state = {}
        api = Mock()

        result = app.ensure_ping_monitor(
            api, [monitor], monitor["name"], monitor["hostname"], 60, 2, [],
            state=state, identity="shelly:device-1",
        )

        self.assertEqual(result, monitor)
        api.add_monitor.assert_not_called()
        api.edit_monitor.assert_not_called()
        self.assertEqual(
            state["_monitor_identities"]["shelly:device-1"],
            {"monitor_id": 63, "name": "Shelly: Garage", "type": "ping"},
        )

    def test_missing_cached_id_falls_back_to_previous_name(self):
        old = {
            "id": 74,
            "name": "Hue: Old name",
            "type": "push",
            "interval": 180,
            "retryInterval": 180,
            "maxretries": 0,
        }
        renamed = {**old, "name": "Hue: New name"}
        state = {
            "_monitor_identities": {
                "hue_device:device-1": {
                    "monitor_id": 999,
                    "name": "Hue: Old name",
                    "type": "push",
                }
            }
        }
        api = Mock()
        api.get_monitors.return_value = [renamed]

        app.ensure_push_monitor(
            api, [old], "Hue: New name", 180, [],
            state=state, identity="hue_device:device-1",
        )

        api.add_monitor.assert_not_called()
        api.edit_monitor.assert_called_once_with(74, name="Hue: New name")
        self.assertEqual(state["_monitor_identities"]["hue_device:device-1"]["monitor_id"], 74)

    def test_failed_rename_keeps_identity_state_unchanged(self):
        old = {
            "id": 85,
            "name": "MQTT: Old name",
            "type": "push",
            "interval": 180,
            "retryInterval": 180,
            "maxretries": 0,
        }
        state = {
            "_monitor_identities": {
                "mqtt_devices:device-1": {
                    "monitor_id": 85,
                    "name": "MQTT: Old name",
                    "type": "push",
                }
            }
        }
        before = copy.deepcopy(state)
        api = Mock()
        api.edit_monitor.side_effect = TimeoutError("synthetic secret")

        with self.assertRaises(TimeoutError):
            app.ensure_push_monitor(
                api, [old], "MQTT: New name", 180, [],
                state=state, identity="mqtt_devices:device-1",
            )

        self.assertEqual(state, before)
        api.add_monitor.assert_not_called()
        self.assertFalse(hasattr(api, "delete_monitor") and api.delete_monitor.called)

    def test_identity_state_roundtrips_with_existing_state_format(self):
        state = {
            "known_slugs": ["example"],
            "_monitor_identities": {
                "addon:example": {
                    "monitor_id": 96,
                    "name": "HA Add-on: Example",
                    "type": "push",
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, "STATE", Path(directory) / "state.json"):
            app.save_state(state)
            self.assertEqual(app.load_state(), state)


if __name__ == "__main__":
    unittest.main()
