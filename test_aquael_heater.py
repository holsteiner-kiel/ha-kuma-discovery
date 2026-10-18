"""Aquael Heater availability discovery uses only its native Connectivity entity."""
import logging
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class FakeWS:
    responses = {}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def call(self, command): return self.responses[command["type"]]


class AquaelHeaterTests(unittest.TestCase):
    def setUp(self):
        self.old = app.HAWebSocket
        app.HAWebSocket = FakeWS
        self.addCleanup(setattr, app, "HAWebSocket", self.old)

    def test_absent_integration_is_a_clean_noop(self):
        FakeWS.responses = {"config_entries/get": []}
        self.assertEqual(app.discover_aquael_heater_devices(), [])

    def test_native_connectivity_is_the_only_liveness_source(self):
        FakeWS.responses = {
            "config_entries/get": [{"entry_id": "aquael-entry"}],
            "config/device_registry/list": [{"id": "heater-1", "name": "Aquael Flow Heater BT", "model": "Flow Heater BT"}],
            "config/entity_registry/list": [
                {"entity_id": "climate.aquael_flow_heater_bt", "platform": "aquael_heater", "config_entry_id": "aquael-entry", "device_id": "heater-1", "translation_key": "heater"},
                {"entity_id": "binary_sensor.aquael_flow_heater_bt_erreichbarkeit", "platform": "aquael_heater", "config_entry_id": "aquael-entry", "device_id": "heater-1", "translation_key": "connectivity"},
                {"entity_id": "binary_sensor.old_mqtt_availability", "platform": "mqtt", "config_entry_id": "aquael-entry", "device_id": "heater-1", "translation_key": "connectivity"},
            ],
            "get_states": [{"entity_id": "binary_sensor.aquael_flow_heater_bt_erreichbarkeit", "state": "on"}],
        }
        found = app.discover_aquael_heater_devices()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["connectivity_entity"], "binary_sensor.aquael_flow_heater_bt_erreichbarkeit")
        self.assertEqual(found[0]["state"], "on")

    def test_sync_debounces_down_and_recovers_immediately(self):
        data = [{"device_id": "heater-1", "name": "Aquael Flow Heater BT", "model": "Flow Heater BT", "connectivity_entity": "binary_sensor.aquael", "state": "off"}]
        opts = {"aquael_heater_monitor_prefix": "Aquael Heater: ", "heartbeat_interval": 180, "sync_interval": 60, "push_down_grace_cycles": 3, "kuma_url": "http://example.invalid", "verify_ssl": True}
        push, send, state = Mock(return_value={"id": 1}), Mock(), {}
        app.integration_aquael_heater.sync_aquael_heater_devices(opts, Mock(), [], [], state, lambda: data, push, lambda *_: (True, 1), send, logging.getLogger("test"))
        self.assertEqual(push.call_args.kwargs["identity"], "aquael_heater:heater-1")
        self.assertIn("DOWN grace 1/3", send.call_args.args[3])


if __name__ == "__main__": unittest.main()
