"""Frozen command routing without requiring a Windows build host."""
import sys
import unittest
from unittest.mock import patch, Mock
from focuslock import session
import entrypoint


class PackagingTests(unittest.TestCase):
    def test_frozen_worker_uses_exe_and_private_mode(self):
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', r'C:\FocusLock\FocusLock.exe'), \
             patch.dict('os.environ', {'__PYVENV_LAUNCHER__': 'old.exe'}):
            command, env = session.worker_command('a' * 32)
        self.assertEqual(command, [r'C:\FocusLock\FocusLock.exe', '--focuslock-worker', 'a' * 32])
        self.assertEqual(env['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        self.assertNotIn('__PYVENV_LAUNCHER__', env)

    def test_worker_mode_never_enters_gui(self):
        gui = Mock()
        with patch.dict(sys.modules, {'main': gui}), \
             patch('focuslock.worker.main', return_value=0) as worker:
            self.assertEqual(entrypoint.dispatch(['--focuslock-worker', 'a' * 32]), 0)
        worker.assert_called_once_with('a' * 32)
        gui.main.assert_not_called()

    def test_normal_exe_enters_gui_only(self):
        gui = Mock()
        gui.main.return_value = 0
        with patch.dict(sys.modules, {'main': gui}), \
             patch('focuslock.worker.main') as worker:
            self.assertEqual(entrypoint.dispatch([]), 0)
        gui.main.assert_called_once_with()
        worker.assert_not_called()

    def test_unknown_arguments_rejected(self):
        with self.assertRaises(ValueError):
            entrypoint.dispatch(['--focuslock-worker'])


if __name__ == '__main__':
    unittest.main()
