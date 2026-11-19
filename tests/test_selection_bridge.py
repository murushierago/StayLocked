import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
from focuslock.storage import ConfigStore, path_key
from focuslock.native_host import receive, send, serve, snapshot
from focuslock.ui import FocusLockWindow
from register_extension import extension_id


class SelectionTests(unittest.TestCase):
    def test_schema2_defaults_enabled_and_roundtrip_preserves_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            apps = [r'C:\Apps\Discord.exe', r'C:\Apps\Telegram.exe']
            path.write_text(json.dumps({'schema_version': 2, 'applications': apps, 'websites': ['youtube.com']}))
            store = ConfigStore(path)
            self.assertEqual(store.load_config()['disabled_applications'], [])
            store.save_selection([apps[0]], [])
            store.save_websites(['youtube.com', 'reddit.com'])
            self.assertEqual(store.load(), apps)
            self.assertEqual(store.load_config()['disabled_applications'], [apps[0]])
            store.save([apps[1]])
            self.assertEqual(store.load_config()['disabled_applications'], [])

    def test_invalid_disabled_state_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            text = json.dumps({'schema_version': 3, 'applications': [], 'websites': [],
                               'disabled_applications': [r'C:\Fake.exe']})
            path.write_text(text)
            with self.assertRaises(ValueError):
                ConfigStore(path).save([])
            self.assertEqual(path.read_text(), text)

    def test_disabled_apps_not_in_start_snapshot(self):
        app = FocusLockWindow.__new__(FocusLockWindow)
        app.busy = False
        app.applications = [r'C:\Discord.exe', r'C:\Telegram.exe']
        app.websites = ['youtube.com', 'reddit.com']
        app.disabled_apps = {path_key(app.applications[0])}
        app.disabled_sites = {'reddit.com'}
        app.duration = Mock(get=lambda: '1')
        app.controls = Mock()
        app.root, app.banner, app.status = Mock(), Mock(), Mock()
        with patch('focuslock.network.require_admin'), patch('focuslock.ui.messagebox.askokcancel', return_value=True), \
             patch('focuslock.ui.launch_session', return_value='id') as launch:
            app.start()
        launch.assert_called_once_with([r'C:\Telegram.exe'], force_running=True, websites=['youtube.com'], minutes=1)

    def test_duration_preview_and_invalid_input(self):
        app = FocusLockWindow.__new__(FocusLockWindow)
        app.busy = False
        app.duration = Mock()
        app.timer, app.clock_caption, app.exit_hint = Mock(), Mock(), Mock()
        for value, minutes, display in [('25', 25, '00:25:00'), ('720', 720, '12:00:00'),
                                        ('Until restart', None, '00:00:00')]:
            app.duration.get.return_value = value
            self.assertEqual(app.session_minutes(), minutes)
            app.preview_duration()
            app.timer.set.assert_called_with(display)
        app.duration.get.return_value = '0'
        app.preview_duration()
        app.timer.set.assert_called_with('--:--:--')
        app.busy = True
        app.timer.reset_mock()
        app.preview_duration()
        app.timer.set.assert_not_called()

    def test_active_session_cannot_toggle(self):
        app = FocusLockWindow.__new__(FocusLockWindow)
        app.busy = True
        app.store = Mock()
        app.save_toggles(set(), set())
        app.toggle_apps()
        app.toggle_sites()
        app.store.save_selection.assert_not_called()


class BridgeTests(unittest.TestCase):
    def test_frame_uses_utf8_byte_length(self):
        stream = io.BytesIO()
        data = {'text': 'Сессия\nFocus'}
        send(stream, data)
        stream.seek(0)
        self.assertEqual(receive(stream), data)
        self.assertIsNone(receive(stream))

    def test_oversized_and_truncated_frames_rejected(self):
        for raw in [struct.pack('<I', 70000), struct.pack('<I', 20) + b'{}', b'\x02']:
            with self.assertRaises(ValueError):
                receive(io.BytesIO(raw))

    def test_bridge_cannot_mutate_session(self):
        source, output = io.BytesIO(), io.BytesIO()
        send(source, {'type': 'stop'})
        source.seek(0)
        get_state = Mock()
        serve(source, output, get_state)
        get_state.assert_not_called()
        output.seek(0)
        self.assertEqual(receive(output)['state'], 'error')

    def test_snapshot_excludes_executable_paths(self):
        state = snapshot({'state': 'ACTIVE', 'session_id': '123', 'websites': ['youtube.com'],
                          'remaining_seconds': 60, 'applications': [r'C:\Private\App.exe']})
        self.assertEqual(state['domains'], ['youtube.com'])
        self.assertNotIn('applications', state)
        self.assertEqual(snapshot({'state': 'INTERRUPTED'})['state'], 'idle')
        self.assertEqual(snapshot({'state': 'STARTING'})['state'], 'preparing')

    def test_registered_identity_is_stable(self):
        manifest = json.loads((Path(__file__).resolve().parents[1] / 'extension' / 'manifest.json').read_text())
        identity = extension_id(manifest)
        self.assertEqual(len(identity), 32)
        self.assertTrue(all('a' <= c <= 'p' for c in identity))
