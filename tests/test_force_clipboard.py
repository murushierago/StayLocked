import os
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from focuslock.force_close import force_close_selected
from focuslock.website_dialog import paste_text, control_key
from focuslock.worker import run_session


class FakeAPI:
    def __init__(self):
        self.paths = {101: r'C:\Apps\Discord.exe', 102: r'C:\Apps\Discord.exe',
                      103: r'C:\Other\Discord.exe'}
        self.opened = []
        self.closed = []
        self.killed = []
        self.critical_pid = None
        self.changed_pid = None
        self.denied_pid = None

    def pids(self):
        return [0, 4, *self.paths, os.getpid()]

    def open(self, pid, terminate=False):
        if terminate and pid == self.denied_pid:
            return None
        handle = (pid, terminate)
        self.opened.append(handle)
        return handle

    def close(self, handle):
        self.closed.append(handle)

    def path(self, handle):
        pid, terminate = handle
        if terminate and pid == self.changed_pid:
            return r'C:\Other\Discord.exe'
        return self.paths[pid]

    def critical(self, handle):
        return handle[0] == self.critical_pid

    def alive(self, handle):
        return True

    def terminate(self, handle):
        self.killed.append(handle[0])

    def wait(self, handle):
        pass


class ForceTests(unittest.TestCase):
    def run_api(self, api):
        try:
            force_close_selected([r'C:\Apps\Discord.exe'], api=api)
        finally:
            self.assertCountEqual(api.opened, api.closed)

    def test_all_exact_instances_but_not_same_name_elsewhere(self):
        api = FakeAPI()
        self.run_api(api)
        self.assertEqual(api.killed, [101, 102])

    def test_critical_candidate_prevents_all_kills(self):
        api = FakeAPI()
        api.critical_pid = 102
        with self.assertRaisesRegex(ValueError, 'Critical'):
            self.run_api(api)
        self.assertEqual(api.killed, [])

    def test_path_is_rechecked_on_termination_handle(self):
        api = FakeAPI()
        api.changed_pid = 101
        self.run_api(api)
        self.assertEqual(api.killed, [102])

    def test_permission_denied_prevents_all_kills(self):
        api = FakeAPI()
        api.denied_pid = 102
        with self.assertRaises(OSError):
            self.run_api(api)
        self.assertEqual(api.killed, [])

    def test_no_force_without_explicit_request(self):
        force = Mock()
        # Existing running-process check rejects the session; no force flag.
        with self.assertRaises(ValueError):
            run_session({'minutes': 1, 'applications': ['a'], 'start_before_ms': 60000},
                        Mock(), clock=lambda: 0, validate=lambda x: x,
                        check=Mock(side_effect=ValueError('running')), force_closer=force)
        force.assert_not_called()

    def test_validation_failure_never_terminates(self):
        force = Mock()
        with self.assertRaises(ValueError):
            run_session({'minutes': 1, 'applications': ['a'], 'start_before_ms': 60000,
                         'force_running': True}, Mock(), clock=lambda: 0,
                        validate=Mock(side_effect=ValueError('protected')), force_closer=force)
        force.assert_not_called()

    def test_failed_termination_never_acquires_locks(self):
        lock = Mock()
        with self.assertRaises(OSError):
            run_session({'minutes': 1, 'applications': ['a'], 'start_before_ms': 60000,
                         'force_running': True}, Mock(), clock=lambda: 0, validate=lambda x: x,
                        force_closer=Mock(side_effect=OSError('denied')), lock_factory=lock)
        lock.assert_not_called()


class ClipboardTests(unittest.TestCase):
    def test_paste_replaces_selection_once(self):
        entry = Mock()
        entry.clipboard_get.return_value = 'https://youtube.com'
        entry.selection_present.return_value = True
        self.assertEqual(paste_text(entry), 'break')
        entry.delete.assert_called_once_with('sel.first', 'sel.last')
        entry.insert.assert_called_once_with('insert', 'https://youtube.com')

    def test_empty_clipboard_preserves_selection(self):
        entry = Mock()
        entry.clipboard_get.side_effect = tk.TclError('no text')
        paste_text(entry)
        entry.delete.assert_not_called()
        entry.insert.assert_not_called()

    def test_russian_shortcut_uses_windows_keycode(self):
        entry = Mock()
        entry.clipboard_get.return_value = 'reddit.com'
        event = SimpleNamespace(keycode=86, keysym='Cyrillic_em')
        self.assertEqual(control_key(event, entry), 'break')
        entry.insert.assert_called_once_with('insert', 'reddit.com')
