"""Protect optional-integration absence without swallowing actual failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


DISCOVERY = [
    'discover_shelly_devices', 'discover_unifi_network_devices',
    'discover_fritz_network_devices', 'discover_fully_kiosk_devices',
    'discover_homematic_ip_infrastructure', 'discover_matter_devices',
    'discover_e3dc_devices', 'discover_overkiz_devices', 'discover_hue',
    'discover_smlight_devices', 'discover_stiebel_eltron',
    'discover_synology_dsm', 'discover_esphome_devices', 'discover_home_connect_local',
    'discover_home_connect_cloud', 'discover_ecovacs_devices', 'discover_mqtt_physical_devices',
]


class OptionalIntegrationTests(unittest.TestCase):
    def test_all_discovery_modules_accept_absent_sources(self):
        for name in DISCOVERY:
            with self.subTest(name=name), patch.object(app, 'HAWebSocket') as ws, \
                 patch.object(app, 'HA_CONFIG_ENTRIES') as storage, \
                 self.assertNoLogs(app.LOG, level='WARNING'):
                ws.return_value.__enter__.return_value.call.return_value = []
                storage.exists.return_value = False
                result = getattr(app, name)()
                self.assertFalse(any(result.values()) if isinstance(result, dict) else result)
                storage.exists.assert_not_called()

    def test_all_enabled_modules_complete_empty_cycle_without_monitors(self):
        with tempfile.TemporaryDirectory() as temp:
            options = Path(temp) / 'options.json'
            options.write_text(json.dumps({'kuma_url': 'http://example.invalid',
                                           'kuma_username': 'synthetic', 'kuma_password': 'synthetic'}))
            with patch.object(app, 'OPTIONS', options):
                opts = app.read_options()
        opts['discover_hue_devices'] = True
        with patch.object(app, 'HAWebSocket') as ws, patch.object(app, 'UptimeKumaApi') as factory, \
             patch.object(app, 'supervisor_get', return_value={'addons': []}), \
             patch.object(app, 'load_state', return_value={}), patch.object(app, 'save_state'), \
             patch.object(app, 'get_default_notification_ids', return_value=[]), \
             patch.object(app, 'HA_CONFIG_ENTRIES') as storage, \
             patch.object(app, 'push_status') as push, self.assertNoLogs(app.LOG, level='WARNING'):
            ws.return_value.__enter__.return_value.call.return_value = []
            api = factory.return_value.__enter__.return_value
            api.get_monitors.return_value = []
            app.sync_once(opts)
            api.add_monitor.assert_not_called()
            api.edit_monitor.assert_not_called()
            push.assert_not_called()
            storage.exists.assert_not_called()

    def test_empty_entities_for_existing_mqtt_device_are_legitimate(self):
        device = {'id': 'sample', 'identifiers': [['mqtt', 'physical-sample']]}
        with patch.object(app, 'HAWebSocket') as ws:
            ws.return_value.__enter__.return_value.call.side_effect = lambda cmd: (
                [device] if cmd['type'] == 'config/device_registry/list' else [])
            self.assertEqual(app.discover_mqtt_physical_devices(), {'zigbee2mqtt': [], 'mqtt': []})

    def test_api_errors_are_not_converted_to_absence(self):
        for name in DISCOVERY:
            with self.subTest(name=name), patch.object(app, 'HAWebSocket') as ws:
                ws.return_value.__enter__.return_value.call.side_effect = TimeoutError('synthetic failure')
                with self.assertRaises(TimeoutError):
                    getattr(app, name)()

    def test_malformed_entry_is_not_converted_to_absence(self):
        with patch.object(app, 'HAWebSocket') as ws:
            ws.return_value.__enter__.return_value.call.return_value = [42]
            with self.assertRaises(AttributeError):
                app.discover_esphome_devices()

    def test_present_integration_still_reports_missing_storage(self):
        with patch.object(app, 'HA_CONFIG_ENTRIES') as storage:
            storage.exists.return_value = False
            with self.assertLogs(app.LOG, level='WARNING'):
                self.assertEqual(app._config_entry_hosts_from_storage('esphome', {'entry'}), {})
