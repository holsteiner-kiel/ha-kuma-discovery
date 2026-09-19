"""Synthetic observations and failures: no live credentials or services."""
import copy
import unittest
from unittest.mock import Mock, patch
from test_reliability import app


class PushReliabilityTests(unittest.TestCase):
    def test_global_failed_cycle_preserves_saved_push_state(self):
        state = {'_push_status_cache': {'sample': {'up': True, 'last_push': 42}}}
        before = copy.deepcopy(state)
        opts = {'kuma_url': 'http://example.invalid', 'verify_ssl': True,
                'kuma_username': 'synthetic', 'kuma_password': 'synthetic'}
        with patch.object(app, 'load_state', return_value=state), patch.object(app, 'save_state') as save, \
             patch.object(app, 'UptimeKumaApi') as factory, patch.object(app, 'push_status') as send:
            factory.return_value.__enter__.return_value.login.side_effect = TimeoutError('synthetic')
            with self.assertRaises(TimeoutError):
                app.sync_once(opts)
        self.assertEqual(state, before)
        save.assert_called_once_with(before)
        send.assert_not_called()

    def test_failed_push_preserves_entire_state(self):
        for initial in ({}, {'_push_status_cache': {'sample': {'up': True, 'last_push': 42}}}):
            with self.subTest(initial=initial):
                state = copy.deepcopy(initial)
                with patch.object(app, 'push_status', side_effect=TimeoutError('synthetic secret')):
                    with self.assertRaises(TimeoutError):
                        app.push_status_if_needed('http://example.invalid', {'name': 'sample'},
                                                  False, 'test', True, state, 180, 60)
                self.assertEqual(state, initial)

    def test_failed_discovery_never_fabricates_up(self):
        state = {'_push_status_cache': {'Matter: sample': {'up': True, 'last_push': 42}}}
        before = copy.deepcopy(state)
        with patch.object(app, 'discover_matter_devices', side_effect=TimeoutError), \
             patch.object(app, 'push_status') as send:
            with self.assertRaises(TimeoutError):
                app.sync_matter_devices({}, Mock(), [], [], state)
        send.assert_not_called()
        self.assertEqual(state, before)

    def test_debounced_observations_are_sent_and_recovery_resets(self):
        state = {}
        with patch.object(app, 'push_status') as send:
            for observed in [True, False, False, False, True, False]:
                effective, _ = app._push_effective_up(state, 'sample', 'device', observed, 3)
                app.push_status_if_needed('http://example.invalid', {'name': 'sample'},
                                          effective, 'test', True, state, 180, 60)
        self.assertEqual([c.args[2] for c in send.call_args_list],
                         [True, True, True, False, True, True])

    def test_stage_errors_redact_exception_payload(self):
        for stage in ['authentication/login', 'fetching monitors', 'fetching notifications',
                      'monitor creation', 'monitor update']:
            with self.subTest(stage=stage), self.assertLogs(app.LOG, level='ERROR') as logs:
                with self.assertRaises(TimeoutError):
                    app.kuma_call(stage, Mock(side_effect=TimeoutError('password=test-secret')))
            output = '\n'.join(logs.output)
            self.assertIn(stage, output)
            self.assertIn('TimeoutError', output)
            self.assertNotIn('test-secret', output)

    def test_session_open_stage_redacts_credentials(self):
        for phase in ['constructor', 'enter']:
            with self.subTest(phase=phase), patch.object(app, 'UptimeKumaApi') as factory:
                if phase == 'constructor':
                    factory.side_effect = TimeoutError('test-secret')
                else:
                    factory.return_value.__enter__.side_effect = TimeoutError('test-secret')
                with self.assertLogs(app.LOG, level='ERROR') as logs:
                    with self.assertRaises(TimeoutError):
                        with app.kuma_session({'kuma_url': 'http://example.invalid', 'verify_ssl': True}):
                            self.fail('must not open')
                self.assertIn('opening Kuma API session', '\n'.join(logs.output))
                self.assertNotIn('test-secret', '\n'.join(logs.output))

    def test_push_http_stage_redacts_url_and_payload(self):
        with patch.object(app.HTTP, 'get', side_effect=TimeoutError('http://example.invalid/api/push/test-secret')), \
             self.assertLogs(app.LOG, level='ERROR') as logs:
            with self.assertRaises(TimeoutError):
                app.push_status('http://example.invalid', {'pushToken': 'test-secret'}, True, 'OK', True)
        output = '\n'.join(logs.output)
        self.assertIn('Push heartbeat HTTP call', output)
        self.assertNotIn('test-secret', output)
        self.assertNotIn('http://', output)

    def test_monitor_helpers_label_actual_api_failures(self):
        for kind in ['ping', 'push']:
            for stage in ['monitor creation', 'monitor update', 'fetching monitors']:
                api = Mock()
                existing = {'id': 1, 'name': 'sample', 'type': kind, 'interval': 1}
                monitors = [] if stage != 'monitor update' else [existing]
                method = {'monitor creation': api.add_monitor, 'monitor update': api.edit_monitor,
                          'fetching monitors': api.get_monitors}[stage]
                method.side_effect = TimeoutError('test-secret')
                with self.subTest(kind=kind, stage=stage), patch.object(app.time, 'sleep'), \
                     self.assertLogs(app.LOG, level='ERROR') as logs:
                    with self.assertRaises(TimeoutError):
                        if kind == 'ping':
                            app.ensure_ping_monitor(api, monitors, 'sample', 'device.example', 60, 2, [])
                        else:
                            app.ensure_push_monitor(api, monitors, 'sample', 180, [])
                self.assertIn(stage, '\n'.join(logs.output))
                self.assertNotIn('test-secret', '\n'.join(logs.output))
