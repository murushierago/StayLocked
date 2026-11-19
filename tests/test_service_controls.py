"""Ordinary STOP must not interrupt focus; Windows shutdown must still work."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from focuslock.service_core import SessionService


class CoreStopTests(unittest.TestCase):
    def test_stop_refuses_starting_active_and_cleanup(self):
        core = SessionService(clock=lambda: 0)
        for kind in ('STARTING', 'ACTIVE'):
            core.data = {'state': kind}
            self.assertTrue(core.session_busy())
            self.assertFalse(core.stop_if_idle())
            self.assertFalse(core.stop_event.is_set())
        core.data = {'state': 'ENDED'}
        core.thread = Mock(is_alive=lambda: True)
        self.assertFalse(core.stop_if_idle())
        core.thread = None
        self.assertTrue(core.stop_if_idle())
        self.assertTrue(core.stop_event.is_set())

    def test_idle_stop_prevents_subsequent_start(self):
        core = SessionService(clock=lambda: 0)
        self.assertTrue(core.stop_if_idle())
        with self.assertRaisesRegex(RuntimeError, 'shutting down'):
            core.start(dict(op='start', applications=['app.exe'], websites=[], force_running=False, minutes=1), 'owner')

    def test_shutdown_can_always_release_session(self):
        core = SessionService()
        core.data = {'state': 'ACTIVE'}
        core.stop()
        self.assertTrue(core.stop_event.is_set())


class FrameworkStopTests(unittest.TestCase):
    def window_service(self):
        class Framework:
            def GetAcceptedControls(self):
                return 1 | 4  # STOP | SHUTDOWN
        api = SimpleNamespace(SERVICE_ACCEPT_STOP=1, SERVICE_RUNNING=4, SERVICE_STOP_PENDING=3)
        modules = dict(servicemanager=Mock(), win32service=api,
                       win32serviceutil=SimpleNamespace(ServiceFramework=Framework))
        path = Path(__file__).resolve().parents[1] / 'service_entrypoint.py'
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('staylocked_service_controls_test', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        service = module.StayLockedService.__new__(module.StayLockedService)
        service.core = SessionService()
        service.ReportServiceStatus = Mock()
        return service

    def test_active_stop_is_not_advertised_and_cannot_unlock(self):
        service = self.window_service()
        service.core.data = {'state': 'ACTIVE'}
        self.assertEqual(service.GetAcceptedControls(), 4)
        service.SvcStop()  # Even a control racing with state publication is refused.
        self.assertFalse(service.core.stop_event.is_set())
        service.ReportServiceStatus.assert_called_once_with(4)

    def test_stop_is_restored_after_session_and_shutdown_is_accepted(self):
        service = self.window_service()
        service.core.data = {'state': 'ENDED'}
        self.assertEqual(service.GetAcceptedControls(), 5)
        service.SvcStop()
        self.assertTrue(service.core.stop_event.is_set())
        service = self.window_service()
        service.core.data = {'state': 'ACTIVE'}
        service.SvcShutdown()
        self.assertTrue(service.core.stop_event.is_set())
