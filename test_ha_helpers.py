import json
import logging
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent / "ha_kuma_discovery"))

import ha_client


class HomeAssistantHelperTests(unittest.TestCase):
    def test_entity_domain_and_state_ip(self):
        self.assertEqual(ha_client.entity_domain("sensor.temperature"), "sensor")
        self.assertEqual(ha_client.entity_domain("invalid"), "")
        self.assertEqual(
            ha_client.state_ip({"host": "http://device.example.test:8123/path"}),
            "device.example.test",
        )
        self.assertIsNone(ha_client.state_ip({"ip": "AA:BB:CC:DD:EE:FF"}))

    def test_mac_and_identifier_helpers(self):
        device = {
            "connections": [["bluetooth", "ignored"], ["MAC", "AA:BB:CC:DD:EE:FF"]],
            "identifiers": [["ESPHome", "device-1"]],
        }
        self.assertEqual(ha_client.device_mac_from_registry(device), "aabbccddeeff")
        self.assertTrue(ha_client.looks_like_mac_name("AA-BB-CC-DD-EE-FF"))
        self.assertFalse(ha_client.looks_like_mac_name("Living Room"))
        self.assertTrue(ha_client.device_has_identifier(device, "esphome"))
        self.assertFalse(ha_client.device_has_identifier(device, "mqtt"))

    def test_private_or_local_host(self):
        for host in ("device.local", "192.168.1.5", "127.0.0.1", "fe80::1"):
            with self.subTest(host=host):
                self.assertTrue(ha_client.is_private_or_local_host(host))
        self.assertFalse(ha_client.is_private_or_local_host("8.8.8.8"))
        self.assertFalse(ha_client.is_private_or_local_host(""))

    def test_config_entry_hosts_are_filtered(self):
        payload = {
            "data": {
                "entries": [
                    {"domain": "esphome", "entry_id": "allowed", "data": {"host": "device.local"}},
                    {"domain": "esphome", "entry_id": "other", "data": {"host": "other.local"}},
                    {"domain": "hue", "entry_id": "allowed", "data": {"host": "bridge.local"}},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.config_entries"
            path.write_text(json.dumps(payload), encoding="utf-8")
            hosts = ha_client.config_entry_hosts_from_storage(
                "esphome", {"allowed"}, path, logging.getLogger("test")
            )
        self.assertEqual(hosts, {"allowed": "device.local"})


if __name__ == "__main__":
    unittest.main()
