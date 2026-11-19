"""Real Windows pipe regression checks. No installation, EXE locking or WFP.

These run automatically during a Windows build, including the cancellation
path that previously called a missing pywin32 method. Every pipe has a random
test-only name; the installed service and existing focus sessions are untouched.
"""
import os
import sys
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from focuslock import service_ipc as ipc


@unittest.skipUnless(sys.platform == 'win32', 'Real named pipes require Windows')
class WindowsPipeTests(unittest.TestCase):
    def setUp(self):
        import win32api
        import win32security as sec
        token = sec.OpenProcessToken(win32api.GetCurrentProcess(), 8)
        try:
            self.sid = sec.ConvertSidToStringSid(sec.GetTokenInformation(token, sec.TokenUser)[0])
        finally:
            token.Close()
        self.name = rf'\\.\pipe\StayLocked.Test.{uuid.uuid4().hex}'

    def test_connect_timeout_cancels_real_overlapped_io(self):
        import win32pipe
        handle = win32pipe.CreateNamedPipe(self.name, 3 | 0x40000000, 0x8, 1, 4096, 4096, 1000, None)
        try:
            with self.assertRaises(TimeoutError):
                ipc._io(handle, 'connect', deadline=time.monotonic() + .05)
        finally:
            handle.Close()

    def test_roundtrip_disconnect_timeout_and_reconnect(self):
        import pywintypes
        import win32file
        class Core:
            stop_event = threading.Event()
            def snapshot(core, sid):
                return {'state': 'IDLE', 'sid': sid}
        core, failures = Core(), []
        def listener():
            try:
                ipc.serve(core)
            except BaseException as exc:
                failures.append(exc)
        with patch.object(ipc, 'STATUS_PIPE', self.name):
            thread = threading.Thread(target=listener, daemon=True)
            thread.start()
            try:
                for _ in range(4):
                    answer = ipc.request({'op': 'status'}, os.getpid())
                    self.assertEqual(answer['status'], {'state': 'IDLE', 'sid': self.sid})
                with self.assertRaisesRegex(RuntimeError, 'read-only'):
                    ipc.request({'op': 'stop'}, os.getpid())
                with patch.object(ipc, 'client_identity', side_effect=PermissionError('Cannot identify pipe client')):
                    with self.assertRaisesRegex(RuntimeError, 'Cannot identify pipe client'):
                        ipc.request({'op': 'status'}, os.getpid())
                # A client that connects but sends no message must be cancellable.
                deadline = time.monotonic() + 3
                while True:
                    try:
                        handle = win32file.CreateFile(self.name, ipc.CLIENT_ACCESS, 0, None, 3,
                                                     0x40000000 | 0x00100000 | 0x00010000, None)
                        break
                    except pywintypes.error as exc:
                        if exc.winerror != 231 or time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)
                try:
                    with self.assertRaises(TimeoutError):
                        ipc.receive(handle, time.monotonic() + .1)
                finally:
                    handle.Close()
                self.assertEqual(ipc.request({'op': 'status'}, os.getpid())['status']['state'], 'IDLE')
                with self.assertRaisesRegex(PermissionError, 'installed StayLocked service'):
                    ipc.request({'op': 'status'}, os.getpid() + 1)
                self.assertEqual(ipc.request({'op': 'status'}, os.getpid())['status']['state'], 'IDLE')
            finally:
                core.stop_event.set()
                thread.join(5)
            self.assertFalse(thread.is_alive(), 'Pipe listener did not stop')
            self.assertEqual(failures, [])
