"""Behavior tests; no Home Assistant or Kuma credentials/services required."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

APP_DIRECTORY = Path(__file__).parent / "ha_kuma_discovery"
sys.path.insert(0, str(APP_DIRECTORY))
spec = importlib.util.spec_from_file_location("discovery", APP_DIRECTORY / "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state.json'
        self.backup = self.state.with_suffix('.json.bak')
        self.patch = patch.object(app, 'STATE', self.state)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_first_run_and_roundtrip(self):
        self.assertEqual(app.load_state()['known_slugs'], [])
        data = {'names': {'id': 'Küche'}, '_push_down_debounce': {'mqtt': {'id': {'down_cycles': 2}}}}
        app.save_state(data)
        self.assertEqual(app.load_state(), data)

    def test_backup_contains_previous_good_state(self):
        app.save_state({'generation': 1})
        app.save_state({'generation': 2})
        self.assertEqual(json.loads(self.backup.read_text()), {'generation': 1})
        self.assertEqual(app.load_state(), {'generation': 2})

    def test_corrupt_primary_recovers_and_does_not_poison_backup(self):
        self.state.write_text('{broken')
        self.backup.write_text('{"generation": 1}')
        with self.assertLogs(app.LOG, level='WARNING') as logs:
            self.assertEqual(app.load_state(), {'generation': 1})
        self.assertIn('Recovered state', '\n'.join(logs.output))
        app.save_state({'generation': 2})
        self.assertEqual(json.loads(self.backup.read_text()), {'generation': 1})
        self.assertEqual(app.load_state(), {'generation': 2})

    def test_missing_primary_recovers_backup(self):
        self.backup.write_text('{"generation": 1}')
        self.assertEqual(app.load_state(), {'generation': 1})

    def test_wrong_json_root_recovers_backup(self):
        self.state.write_text('[]')
        self.backup.write_text('{"generation": 1}')
        self.assertEqual(app.load_state(), {'generation': 1})

    def test_failed_replace_keeps_primary_and_cleans_temporary_file(self):
        app.save_state({'generation': 1})
        replace = app.os.replace
        def fail_primary(src, dst):
            if dst == self.state:
                raise OSError('simulated disk failure')
            return replace(src, dst)
        with patch.object(app.os, 'replace', side_effect=fail_primary):
            with self.assertRaises(OSError):
                app.save_state({'generation': 2})
        self.assertEqual(app.load_state(), {'generation': 1})
        self.assertEqual(json.loads(self.backup.read_text()), {'generation': 1})
        self.assertEqual(list(Path(self.temp.name).glob('*.tmp')), [])

    def test_fsync_failure_keeps_previous_state(self):
        app.save_state({'generation': 1})
        with patch.object(app.os, 'fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                app.save_state({'generation': 2})
        self.assertEqual(app.load_state(), {'generation': 1})
        self.assertEqual(list(Path(self.temp.name).glob('*.tmp')), [])

    def test_invalid_state_does_not_touch_disk(self):
        app.save_state({'generation': 1})
        with self.assertRaises(ValueError):
            app.save_state([])
        self.assertEqual(app.load_state(), {'generation': 1})


class CycleTests(unittest.TestCase):
    def run_cycle(self, failure=None, login_failure=None, disabled=False):
        opts = {'kuma_url': 'http://example.invalid', 'kuma_username': 'u',
                'kuma_password': 'p', 'verify_ssl': True}
        import ast
        source = Path(app.__file__).read_text()
        opts.update({node.slice.value: not disabled for node in ast.walk(ast.parse(source))
                     if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                     and isinstance(node.slice.value, str) and node.slice.value.startswith('discover_')})
        names = ['sync_addons', 'sync_shelly', 'sync_unifi_network_devices',
                 'sync_fritz_network_devices', 'sync_fully_kiosk_devices',
                 'sync_homematic_ip_infrastructure', 'sync_matter_devices',
                 'sync_e3dc_devices', 'sync_overkiz_devices', 'sync_hue',
                 'sync_smlight_devices', 'sync_stiebel_eltron',
                 'sync_synology_dsm', 'sync_esphome_devices', 'sync_airgradient_devices', 'sync_mqtt_devices']
        state, visited = {}, []
        with ExitStack() as stack:
            stack.enter_context(patch.object(app, 'load_state', return_value=state))
            saved = stack.enter_context(patch.object(app, 'save_state'))
            api_class = stack.enter_context(patch.object(app, 'UptimeKumaApi'))
            api = api_class.return_value.__enter__.return_value
            api.login.side_effect = login_failure
            api.get_monitors.return_value = []
            stack.enter_context(patch.object(app, 'get_default_notification_ids', return_value=[]))
            stack.enter_context(patch.object(app.HAWebSocket, 'begin_cycle'))
            end = stack.enter_context(patch.object(app.HAWebSocket, 'end_cycle'))
            for name in names:
                def sync(*args, name=name):
                    visited.append(name)
                    args[-1][name] = 'processed'
                    if name == 'sync_shelly' and failure:
                        raise failure
                sync.__name__ = name
                stack.enter_context(patch.object(app, name, sync))
            try:
                app.sync_once(opts)
            finally:
                saved.assert_called_once_with(state)
                if login_failure is None:
                    end.assert_called_once()
        return state, visited, names

    def test_failure_does_not_skip_later_integrations_or_successful_state(self):
        with self.assertLogs(app.LOG, level='ERROR') as logs:
            state, visited, names = self.run_cycle(RuntimeError('secret push URL'))
        self.assertEqual(visited, names)
        self.assertEqual(state['sync_mqtt_devices'], 'processed')
        self.assertNotIn('secret push URL', '\n'.join(logs.output))

    def test_all_integrations_still_run_in_original_order(self):
        _, visited, names = self.run_cycle()
        self.assertEqual(visited, names)

    def test_disabled_integrations_do_not_run(self):
        _, visited, _ = self.run_cycle(disabled=True)
        self.assertEqual(visited, [])

    def test_global_login_failure_is_not_swallowed(self):
        with self.assertRaises(ConnectionError):
            self.run_cycle(login_failure=ConnectionError('offline'))

    def test_keyboard_interrupt_is_not_swallowed(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_cycle(failure=KeyboardInterrupt())

    def test_cycle_logs_one_timing_summary_without_secret_errors(self):
        with self.assertLogs(app.LOG, level='INFO') as logs:
            self.run_cycle(RuntimeError('secret push URL'))
        output = '\n'.join(logs.output)
        self.assertIn('Integration timings:', output)
        self.assertIn('sync_addons=', output)
        self.assertIn('sync_mqtt_devices=', output)
        self.assertEqual(output.count('Integration timings:'), 1)
        self.assertNotIn('secret push URL', output)

    def test_kuma_operation_duration_uses_fixed_stage_only(self):
        with patch.object(app.time, 'monotonic', side_effect=[10.0, 10.25]), \
             self.assertLogs(app.LOG, level='INFO') as logs:
            self.assertEqual(app.kuma_call('fetching monitors', lambda: 'ok',
                                           _log_duration=True), 'ok')
        self.assertIn('fetching monitors in 0.2s', '\n'.join(logs.output))


class HeartbeatTests(unittest.TestCase):
    def push(self, state, now, up=True):
        with patch.object(app.time, 'time', return_value=now):
            return app.push_status_if_needed('http://example.invalid',
                {'id': 1, 'name': 'device'}, up, 'status', True, state, 180, 60)

    def test_every_cycle_and_immediate_status_change(self):
        state = {}
        with patch.object(app, 'push_status') as send:
            self.assertTrue(self.push(state, 1000))
            self.assertTrue(self.push(state, 1059))
            self.assertTrue(self.push(state, 1060))
            self.assertTrue(self.push(state, 1061, False))
            self.assertTrue(self.push(state, 1062, True))
            self.assertEqual(send.call_count, 5)
            self.assertEqual(state['_push_status_cache']['device']['last_push'], 1062)

    def test_failed_push_does_not_advance_success_timestamp(self):
        state = {'_push_status_cache': {'device': {'up': True, 'last_push': 1000}}}
        with patch.object(app, 'push_status', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                self.push(state, 1060)
        self.assertEqual(state['_push_status_cache']['device']['last_push'], 1000)

    def test_three_down_cycles_and_immediate_recovery(self):
        state = {}
        for count in (1, 2, 3):
            self.assertEqual(app._push_effective_up(state, 'mqtt', 'id', False, 3),
                             (count < 3, count))
        self.assertEqual(app._push_effective_up(state, 'mqtt', 'id', True, 3), (True, 0))
        self.assertEqual(app._push_effective_up(state, 'mqtt', 'id', False, 3), (True, 1))


class ConnectionTests(unittest.TestCase):
    def tearDown(self):
        app.HAWebSocket.end_cycle(log_stats=False)

    def test_shared_websocket_reconnects_after_transport_failure(self):
        broken, good = Mock(), Mock()
        broken.recv.side_effect = app.websocket.WebSocketTimeoutException('timeout')
        good.recv.return_value = json.dumps({'id': 2, 'type': 'result', 'success': True, 'result': [1]})
        with patch.object(app.HAWebSocket, '_open_socket', side_effect=[broken, good]) as connect:
            app.HAWebSocket.begin_cycle()
            with app.HAWebSocket() as ha:
                with self.assertRaises(app.websocket.WebSocketTimeoutException):
                    ha.call({'type': 'get_states'})
            with app.HAWebSocket() as ha:
                self.assertEqual(ha.call({'type': 'get_states'}), [1])
                self.assertEqual(ha.call({'type': 'get_states'}), [1])
            self.assertEqual(connect.call_count, 2)
            good.send.assert_called_once()
            broken.close.assert_called_once()

    def test_http_keepalive_reuses_connection_and_headers_do_not_leak(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                seen.append((self.client_address, self.headers.get('Authorization')))
                payload = b'{"ok": true, "result": "ok", "data": {}}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port)
            with app.requests.Session() as session, patch.object(app, 'HTTP', session), \
                 patch.object(app, 'SUPERVISOR', url + '/'), \
                 patch.dict(app.os.environ, {'SUPERVISOR_TOKEN': 'test-only'}):
                app.supervisor_get('addons')
                app.push_status(url, {'name': 'test', 'pushToken': 'test-only'}, True, 'ok', True)
                app.push_status(url, {'name': 'test', 'pushToken': 'test-only'}, True, 'ok', True)
            self.assertEqual(len({address for address, _ in seen}), 1)
            self.assertEqual([auth for _, auth in seen], ['Bearer test-only', None, None])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_shutdown_closes_http_session_even_on_error(self):
        with patch.object(app, '_run', side_effect=KeyboardInterrupt), patch.object(app.HTTP, 'close') as close:
            with self.assertRaises(KeyboardInterrupt):
                app.main()
            close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
