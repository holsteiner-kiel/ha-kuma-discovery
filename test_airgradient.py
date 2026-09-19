"""Synthetic native AirGradient entry/device data."""
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class AirGradientTests(unittest.TestCase):
    def setUp(self):
        self.entries, self.devices = [], []

    def add(self, suffix='1', host='sensor.example', name='Living Room'):
        self.entries.append({'entry_id': 'entry-' + suffix, 'title': 'AirGradient One',
                             'data': {'host': host}})
        self.devices.append({'id': 'device-' + suffix, 'name_by_user': name,
                             'config_entries': ['entry-' + suffix],
                             'identifiers': [['airgradient', 'serial-' + suffix]]})

    def discover(self, storage=None):
        with patch.object(app, 'HAWebSocket') as ws, \
             patch.object(app, '_config_entry_hosts_from_storage', return_value=storage or {}) as read:
            ws.return_value.__enter__.return_value.call.side_effect = lambda cmd: (
                self.entries if cmd['type'] == 'config_entries/get' else self.devices)
            result = app.discover_airgradient_devices()
            if not self.entries or not self.devices:
                read.assert_not_called()
            return result

    def test_absent_integration_is_clean_noop(self):
        with self.assertNoLogs(app.LOG, level='WARNING'):
            self.assertEqual(self.discover(), [])

    def test_no_supported_devices_is_noop(self):
        self.add()
        self.devices = []
        self.assertEqual(self.discover(), [])
        self.add('2')
        self.devices[0]['identifiers'] = [['template', 'synthetic']]
        self.assertEqual(self.discover(), [])

    def test_one_and_multiple_physical_devices(self):
        self.add()
        self.assertEqual(self.discover()[0]['host'], 'sensor.example')
        self.add('2', 'sensor2.example', 'Bedroom')
        self.assertEqual(len(self.discover()), 2)

    def test_missing_or_credential_bearing_host_is_skipped_without_leaking(self):
        for host in ['', 'http://user:test-secret@example.invalid', 'bad host', '8.8.8.8']:
            with self.subTest(host=host):
                self.entries, self.devices = [], []
                self.add(host=host)
                with self.assertLogs(app.LOG, level='INFO') as logs:
                    self.assertEqual(self.discover(), [])
                self.assertIn('no usable local config-entry host', '\n'.join(logs.output))
                self.assertNotIn('test-secret', '\n'.join(logs.output))

    def test_storage_host_fallback(self):
        self.add(host='')
        self.assertEqual(self.discover({'entry-1': 'native.example'})[0]['host'], 'native.example')

    def test_native_identity_deduplicates_and_model_names_remain_unique(self):
        self.add(name=None)
        self.add('2', 'other.example', None)
        self.devices.append(self.devices[0].copy())
        result = self.discover()
        self.assertEqual(len(result), 2)
        self.assertEqual(len({d['name'] for d in result}), 2)

    def test_duplicate_user_names_are_distinct(self):
        self.add()
        self.add('2', 'other.example')
        self.assertEqual(len({d['name'] for d in self.discover()}), 2)

    def test_existing_monitor_reused_and_host_updated(self):
        self.add()
        data = self.discover()
        opts = {'airgradient_monitor_prefix': 'AirGradient: ', 'airgradient_ping_interval': 60,
                'airgradient_max_retries': 2}
        monitor = {'id': 1, 'name': 'AirGradient: Living Room', 'type': 'ping',
                   'hostname': 'sensor.example', 'interval': 60, 'retryInterval': 60,
                   'maxretries': 2, 'notificationIDList': {'7': True}}
        api, state = Mock(), {}
        api.get_monitors.return_value = [dict(monitor, hostname='changed.example')]
        with patch.object(app, 'discover_airgradient_devices', return_value=data), patch.object(app.time, 'sleep'):
            app.sync_airgradient_devices(opts, api, [monitor], [7], state)
            api.edit_monitor.assert_not_called()
            data[0]['host'] = 'changed.example'
            app.sync_airgradient_devices(opts, api, [monitor], [7], state)
        api.add_monitor.assert_not_called()
        api.edit_monitor.assert_called_once_with(1, hostname='changed.example')
        self.assertEqual(state['airgradient']['device-1']['host'], 'changed.example')

    def test_new_monitor_uses_default_notifications(self):
        self.add()
        api = Mock()
        api.get_monitors.return_value = [{'id': 1, 'name': 'AirGradient: Living Room', 'type': 'ping'}]
        opts = {'airgradient_monitor_prefix': 'AirGradient: ', 'airgradient_ping_interval': 60,
                'airgradient_max_retries': 2}
        with patch.object(app, 'discover_airgradient_devices', return_value=self.discover()), \
             patch.object(app.time, 'sleep'):
            app.sync_airgradient_devices(opts, api, [], [7], {})
        self.assertEqual(api.add_monitor.call_args.kwargs['notificationIDList'], [7])
        self.assertEqual(api.add_monitor.call_args.kwargs['hostname'], 'sensor.example')
