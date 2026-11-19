"""Launch regression: creation flags must reach the real interpreter."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

from focuslock import session


class WorkerLaunchTests(unittest.TestCase):
    def test_venv_bypasses_launcher_and_preserves_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / 'real-python.exe'
            base.touch()
            launcher = str(root / 'venv' / 'Scripts' / 'python.exe')
            with patch.object(session.sys, '_base_executable', str(base), create=True), \
                 patch.object(session.sys, 'executable', launcher), \
                 patch.object(session.sys, 'prefix', str(root / 'venv')), \
                 patch.object(session.sys, 'base_prefix', str(root)), \
                 patch.object(session, 'data_directory', return_value=root), \
                 patch.object(session.winapi, 'worker_present', return_value=False), \
                 patch.object(session.winapi, 'tick_ms', return_value=1000), \
                 patch.object(session.subprocess, 'DETACHED_PROCESS', 8, create=True), \
                 patch.object(session.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                 patch.object(session.subprocess, 'Popen') as popen:
                child, session_id = session.launch_session([r'C:\Apps\steam.exe'], 1)
                args, kwargs = popen.call_args
                self.assertEqual(args[0], [str(base.resolve()), '-m', 'focuslock.worker', session_id])
                self.assertEqual(kwargs['env']['__PYVENV_LAUNCHER__'], launcher)
                self.assertEqual(kwargs['creationflags'], 8 | 512)
                self.assertTrue(kwargs['close_fds'])
                self.assertEqual(kwargs['stdin'], session.subprocess.DEVNULL)
                self.assertIs(child, popen.return_value)

    def test_base_runtime_removes_stale_launcher_hint(self):
        with patch.object(session.sys, 'prefix', 'same'), \
             patch.object(session.sys, 'base_prefix', 'same'), \
             patch.dict(os.environ, {'__PYVENV_LAUNCHER__': 'stale.exe'}):
            executable, env = session.worker_runtime()
            self.assertNotIn('__PYVENV_LAUNCHER__', env)

    def test_failed_spawn_cleans_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(session, 'data_directory', return_value=root), \
                 patch.object(session.winapi, 'worker_present', return_value=False), \
                 patch.object(session.winapi, 'tick_ms', return_value=0), \
                 patch.object(session.subprocess, 'DETACHED_PROCESS', 8, create=True), \
                 patch.object(session.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                 patch.object(session.subprocess, 'Popen', side_effect=OSError('spawn failed')):
                with self.assertRaises(OSError):
                    session.launch_session([r'C:\Apps\steam.exe'], 1)
                self.assertEqual(list(root.glob('request-*.json')), [])


if __name__ == '__main__':
    unittest.main()
