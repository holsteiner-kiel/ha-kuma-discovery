"""Focused tests for the extracted MQTT integration module."""

import logging
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


class MQTTIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_websocket = app.HAWebSocket
        app.HAWebSocket = FakeHAWebSocket
        self.addCleanup(setattr, app, "HAWebSocket", self.original_websocket)

    def test_discovers_physical_zigbee_and_generic_mqtt_devices(self):
        FakeHAWebSocket.responses = {
            "config/device_registry/list": [
                {
                    "id": "remote-1",
                    "identifiers": [["mqtt", "zigbee2mqtt_0x00124b"]],
                    "name": "Remote",
                    "manufacturer": "Synthetic",
                    "model": "Button",
                },
                {
                    "id": "gateway-1",
                    "identifiers": [["mqtt", "openmqttgateway_node"]],
                    "name": "Gateway",
                    "manufacturer": "Synthetic",
                    "model": "Gateway",
                },
                {
                    "id": "bridge",
                    "identifiers": [["mqtt", "zigbee2mqtt_bridge_main"]],
                    "name": "Bridge",
                },
                {
                    "id": "group",
                    "identifiers": [["mqtt", "zigbee2mqtt_group_lights"]],
                    "name": "Lights",
                    "manufacturer": "Zigbee2MQTT",
                    "model": "Group",
                },
            ],
            "config/entity_registry/list": [
                {
                    "entity_id": "event.remote_action",
                    "device_id": "remote-1",
                    "platform": "mqtt",
                    "unique_id": "remote_action_zigbee2mqtt",
                },
                {
                    "entity_id": "sensor.remote_linkquality",
                    "device_id": "remote-1",
                    "platform": "mqtt",
                    "unique_id": "remote_linkquality_zigbee2mqtt",
                },
                {
                    "entity_id": "sensor.gateway_status",
                    "device_id": "gateway-1",
                    "platform": "mqtt",
                    "unique_id": "gateway_status",
                },
            ],
            "get_states": [
                {"entity_id": "event.remote_action", "state": "2026-09-20T12:00:00+00:00"},
                {"entity_id": "sensor.remote_linkquality", "state": "100"},
                {"entity_id": "sensor.gateway_status", "state": "unavailable"},
            ],
        }

        data = app.discover_mqtt_physical_devices()

        self.assertEqual([d["device_id"] for d in data["zigbee2mqtt"]], ["remote-1"])
        self.assertTrue(data["zigbee2mqtt"][0]["up"])
        self.assertEqual(data["zigbee2mqtt"][0]["availability_mode"], "zigbee2mqtt_event")
        self.assertEqual([d["device_id"] for d in data["mqtt"]], ["gateway-1"])
        self.assertFalse(data["mqtt"][0]["up"])

    def test_sync_list_preserves_debounce_identity_and_inventory(self):
        device = {
            "device_id": "gateway-1",
            "name": "Gateway",
            "manufacturer": "Synthetic",
            "model": "Gateway",
            "mqtt_ids": ["openmqttgateway_node"],
            "up": False,
            "available_entities": 0,
            "checked_entities": 1,
            "sample_entity": "sensor.gateway_status",
            "availability_mode": "stateful",
        }
        opts = {
            "heartbeat_interval": 180,
            "push_down_grace_cycles": 3,
            "kuma_url": "http://example.invalid",
            "verify_ssl": True,
            "sync_interval": 60,
        }
        ensure = Mock(return_value={"id": 9})
        debounce = Mock(return_value=(True, 1))
        send = Mock()
        state = {}

        app.integration_mqtt._sync_mqtt_device_list(
            opts, Mock(), [], [7], state, [device], "MQTT: ", "mqtt",
            ensure, debounce, send, logging.getLogger("test-mqtt"),
        )

        self.assertEqual(ensure.call_args.kwargs["identity"], "mqtt:gateway-1")
        self.assertEqual(debounce.call_args.args[1:4], ("mqtt", "gateway-1", False))
        self.assertTrue(send.call_args.args[2])
        self.assertIn("DOWN grace 1/3", send.call_args.args[3])
        self.assertEqual(state["mqtt"]["gateway-1"]["model"], "Gateway")

    def test_sync_routes_only_enabled_device_classes(self):
        data = {"zigbee2mqtt": [{"device_id": "z2m"}], "mqtt": [{"device_id": "mqtt"}]}
        sync_list = Mock()
        opts = {
            "discover_zigbee2mqtt_devices": True,
            "discover_mqtt_devices": False,
            "zigbee2mqtt_monitor_prefix": "Zigbee2MQTT: ",
            "mqtt_monitor_prefix": "MQTT: ",
        }

        app.integration_mqtt.sync_mqtt_devices(
            opts, Mock(), [], [7], {}, lambda: data, sync_list,
        )

        sync_list.assert_called_once()
        self.assertEqual(sync_list.call_args.args[-2:], ("Zigbee2MQTT: ", "zigbee2mqtt"))


if __name__ == "__main__":
    unittest.main()
