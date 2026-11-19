"""pywin32 boundary regressions, including the reported CancelIoEx failure."""
from contextlib import contextmanager
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from focuslock import service_ipc as ipc


class WinError(Exception):
    def __init__(self, code):
        self.winerror = code


class IdentityTests(unittest.TestCase):
    @contextmanager
    def api(self):
        token = Mock()
        security = SimpleNamespace(
            ImpersonateNamedPipeClient=Mock(), RevertToSelf=Mock(),
            OpenThreadToken=Mock(return_value=token),
            GetTokenInformation=Mock(side_effect=lambda token, kind: ('sid', 0) if kind == 1 else True),
            ConvertSidToStringSid=Mock(return_value='S-1-5-21-owner'),
            TokenUser=1, TokenElevation=20)
        with patch.dict('sys.modules', {
            'win32api': SimpleNamespace(GetCurrentThread=Mock(return_value='thread')),
            'win32security': security,
            # This wrapper belongs to win32security, never win32pipe.
            'win32pipe': SimpleNamespace(),
        }):
            yield security, token

    def test_identity_uses_security_module_and_restores_system_identity(self):
        with self.api() as (security, token):
            self.assertEqual(ipc.client_identity('pipe'), ('S-1-5-21-owner', True))
            security.ImpersonateNamedPipeClient.assert_called_once_with('pipe')
            security.OpenThreadToken.assert_called_once_with('thread', 8, True)
            token.Close.assert_called_once()
            security.RevertToSelf.assert_called_once()

    def test_token_errors_restore_service_identity(self):
        for stage in ('OpenThreadToken', 'GetTokenInformation'):
            with self.subTest(stage=stage), self.api() as (security, token):
                getattr(security, stage).side_effect = PermissionError('Token access denied')
                with self.assertRaisesRegex(PermissionError, 'Token access denied'):
                    ipc.client_identity('pipe')
                security.RevertToSelf.assert_called_once()
                if stage == 'GetTokenInformation':
                    token.Close.assert_called_once()
                else:
                    token.Close.assert_not_called()


class PipeTests(unittest.TestCase):
    @contextmanager
    def api(self, pending=True):
        event = Mock()
        file = SimpleNamespace(
            ReadFile=Mock(return_value=(997 if pending else 0, b'data')),
            WriteFile=Mock(return_value=(997 if pending else 0, 4)),
            CancelIo=Mock(), GetOverlappedResult=Mock(return_value=4))
        events = SimpleNamespace(CreateEvent=Mock(return_value=event),
                                 WaitForSingleObject=Mock(return_value=0))
        pipe = SimpleNamespace(ConnectNamedPipe=Mock(return_value=997 if pending else 0))
        # No CancelIoEx: exactly the API shape on the user's installation.
        with patch.dict('sys.modules', {'pywintypes': SimpleNamespace(OVERLAPPED=SimpleNamespace, error=WinError),
                                        'win32file': file, 'win32event': events, 'win32pipe': pipe}):
            yield file, events, pipe, event

    def test_success_never_cancels_and_always_closes_event(self):
        for operation in ('read', 'write', 'connect'):
            for pending in (False, True):
                with self.subTest(operation=operation, pending=pending), self.api(pending) as (file, events, pipe, event):
                    self.assertEqual(ipc._io('handle', operation, b'data'), 4)
                    file.CancelIo.assert_not_called()
                    event.Close.assert_called_once()

    def test_timeout_uses_same_thread_cancel_and_drains_before_close(self):
        for operation in ('read', 'write', 'connect'):
            with self.subTest(operation=operation), self.api() as (file, events, pipe, event):
                events.WaitForSingleObject.return_value = 258
                order = Mock()
                order.attach_mock(file.CancelIo, 'cancel')
                order.attach_mock(file.GetOverlappedResult, 'drain')
                order.attach_mock(event.Close, 'close')
                file.GetOverlappedResult.side_effect = WinError(995)
                with self.assertRaisesRegex(TimeoutError, 'timed out'):
                    ipc._io('handle', operation, b'data', deadline=0)
                self.assertEqual([call[0] for call in order.mock_calls], ['cancel', 'drain', 'close'])
                file.CancelIo.assert_called_once_with('handle')
                self.assertTrue(file.GetOverlappedResult.call_args.args[2])

    def test_service_stop_cancels_waiting_connection(self):
        with self.api() as (file, events, pipe, event):
            events.WaitForSingleObject.return_value = 258
            stop = threading.Event()
            stop.set()
            with self.assertRaises(TimeoutError):
                ipc._io('handle', 'connect', stop=stop)
            file.CancelIo.assert_called_once_with('handle')
            event.Close.assert_called_once()

    def test_completion_races_with_cancellation(self):
        with self.api() as (file, events, pipe, event):
            events.WaitForSingleObject.return_value = 258
            # Operation has completed by the time CancelIo runs.
            file.GetOverlappedResult.return_value = 4
            with self.assertRaises(TimeoutError):
                ipc._io('handle', 'read', b'data', deadline=0)
            event.Close.assert_called_once()

    def test_already_connected_pipe_does_not_wait_for_an_event(self):
        with self.api() as (file, events, pipe, event):
            pipe.ConnectNamedPipe.return_value = 535
            self.assertEqual(ipc._io('handle', 'connect'), 0)
            events.WaitForSingleObject.assert_not_called()
            file.GetOverlappedResult.assert_not_called()
            event.Close.assert_called_once()

    def test_synchronous_error_keeps_original_error(self):
        with self.api() as (file, events, pipe, event):
            file.ReadFile.side_effect = WinError(109)
            with self.assertRaises(WinError):
                ipc._io('handle', 'read', b'data')
            file.CancelIo.assert_not_called()
            event.Close.assert_called_once()
