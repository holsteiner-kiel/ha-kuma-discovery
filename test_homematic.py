"""Native HCU registry fixtures, including translated names and disabled sensors."""
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class HomematicTests(unittest.TestCase):
    def setUp(self):
        self.entries = [{'entry_id': 'hcu-entry', 'data': {'host': 'hcu.example'}}]
        self.devices, self.entities, self.states = [], [], []

    def device(self, did, model='HmIP-SWDO', **extra):
        self.devices.append(dict(id=did, name=did, model=model,
                                 config_entries=['hcu-entry'],
                                 identifiers=[['hcu_integration', did]], **extra))

    def connectivity(self, did, state='on', **extra):
        eid = 'binary_sensor.' + did
        self.entities.append(dict(entity_id=eid, device_id=did,
                                  config_entry_id='hcu-entry', platform='hcu_integration',
                                  unique_id=did + '_0_unreach', original_name='Verbunden', **extra))
        self.states.append({'entity_id': eid, 'state': state,
                            'attributes': {'device_class': 'connectivity', 'is_group': False}})

    def discover(self):
        responses = {'config_entries/get': self.entries, 'config/device_registry/list': self.devices,
                     'config/entity_registry/list': self.entities, 'get_states': self.states}
        with patch.object(app, 'HAWebSocket') as ws, \
             patch.object(app, '_config_entry_hosts_from_storage', return_value={}):
            ws.return_value.__enter__.return_value.call.side_effect = lambda cmd: responses[cmd['type']]
            return app.discover_homematic_ip_infrastructure()

    def test_hcu_ping_hap_and_children_push(self):
        self.device('controller', 'HmIP-HCU1')
        self.connectivity('controller')
        self.device('Access Point', 'HmIP-HAP')
        self.connectivity('Access Point')
        self.device('Window', name_by_user='Window handle')
        self.connectivity('Window')
        data = self.discover()
        self.assertEqual(data['hcu']['name'], 'HCU')
        self.assertEqual(data['hcu']['host'], 'hcu.example')
        self.assertEqual([d['name'] for d in data['devices']], ['Access Point', 'Window handle'])

    def test_nonphysical_and_disabled_are_excluded(self):
        for model in ['VirtualVariable', 'VirtualDevice', 'Heating Group', 'Room', 'Helper', 'HmIP-Virtual']:
            self.device(model, model)
            self.connectivity(model)
        self.device('service', entry_type='service')
        self.connectivity('service')
        self.device('disabled', disabled_by='user')
        self.connectivity('disabled')
        self.device('no-entity')
        self.device('disabled-entity')
        self.connectivity('disabled-entity', disabled_by='integration')
        self.assertEqual(self.discover()['devices'], [])

    def test_multiple_connectivity_entities_and_duplicate_registry_do_not_duplicate_hap(self):
        self.device('hap', 'HmIP-HAP')
        self.connectivity('hap')
        self.devices.append(self.devices[0].copy())
        self.entities.append(dict(self.entities[0], entity_id='binary_sensor.extra', unique_id='hap_1_unreach'))
        self.assertEqual(len(self.discover()['devices']), 1)

    def test_connectivity_class_fallback_ignores_translated_name(self):
        self.device('window')
        self.connectivity('window', 'off')
        self.entities[0]['unique_id'] = 'opaque'
        self.entities[0]['original_name'] = 'Beliebiger Name'
        self.assertEqual(self.discover()['devices'][0]['state'], 'off')
        self.states[0]['attributes']['device_class'] = 'battery'
        self.assertEqual(self.discover()['devices'], [])

    def test_foreign_platform_cannot_supply_liveness(self):
        self.device('window')
        self.connectivity('window')
        self.entities[0]['platform'] = 'template'
        self.assertEqual(self.discover()['devices'], [])

    def test_unavailable_and_missing_state_are_down_observations(self):
        self.device('window')
        self.connectivity('window', 'unavailable')
        self.assertEqual(self.discover()['devices'][0]['state'], 'unavailable')
        self.states = []
        self.assertEqual(self.discover()['devices'][0]['state'], 'unknown')

    def test_sync_reuses_hap_and_shared_debounce(self):
        self.device('hcu', 'HmIP-HCU1')
        self.device('hap', 'HmIP-HAP')
        self.connectivity('hap')
        data = self.discover()
        opts = {'homematic_ip_monitor_prefix': 'Homematic IP: ', 'homematic_ip_ping_interval': 60,
                'homematic_ip_max_retries': 2, 'heartbeat_interval': 180, 'sync_interval': 60,
                'push_down_grace_cycles': 3, 'kuma_url': 'http://example.invalid', 'verify_ssl': True}
        monitor = {'id': 1, 'name': 'Homematic IP: hap', 'type': 'push',
                   'interval': 180, 'retryInterval': 180, 'maxretries': 0}
        api, state = Mock(), {}
        with patch.object(app, 'discover_homematic_ip_infrastructure', return_value=data), \
             patch.object(app, 'ensure_ping_monitor') as ping, \
             patch.object(app, 'push_status_if_needed') as send:
            for ha_state in ['on', 'off', 'unavailable', 'off', 'on', 'off']:
                data['devices'][0]['state'] = ha_state
                app.sync_homematic_ip_infrastructure(opts, api, [monitor], [], state)
        self.assertEqual([c.args[2] for c in send.call_args_list], [True, True, True, False, True, True])
        self.assertTrue(all(c.args[2] == 'Homematic IP: HCU' for c in ping.call_args_list))
        api.add_monitor.assert_not_called()
        self.assertEqual(list(state['homematic_ip']['access_points']), ['hap'])
        self.assertEqual(state['_push_down_debounce']['homematic_ip']['hap']['down_cycles'], 1)

    def test_absent_integration_is_noop(self):
        self.entries = []
        self.assertEqual(self.discover(), {})
