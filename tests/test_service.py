"""Service lifetime/security contracts. OS integration is separately tested on Windows."""
from contextlib import contextmanager
import threading
import time
import unittest
from unittest.mock import Mock, patch
from focuslock.service_core import SessionService
from focuslock import service_client
from focuslock.worker import run_session
from focuslock.native_host import snapshot, allowed_caller
from focuslock.service_ipc import encode, MAX_FRAME, STATUS_SDDL, CLIENT_ACCESS
from focuslock.force_close import force_close_selected
from test_force_clipboard import FakeAPI


class ServiceTests(unittest.TestCase):
    def message(self, **values):
        return dict(op='start', applications=['app.exe'], websites=[], force_running=True, **values)

    def test_service_survives_client_disappearance_until_os_stop(self):
        held, events = [], []
        started = threading.Event()
        now = [1000]
        @contextmanager
        def lock(path):
            held.append(path)
            try: yield
            finally: held.remove(path)
        def runner(request, publish, stop_event):
            def status(kind, **extra):
                events.append((kind, list(held)))
                publish(kind, **extra)
                if kind == 'ACTIVE': started.set()
            run_session(request, status, stop_event=stop_event, lock_factory=lock,
                        validate=lambda x:x, check=lambda x:None, force_closer=lambda *a,**k:None,
                        clock=lambda:now[0])
        core = SessionService(runner, clock=lambda:now[0])
        try:
            response = core.start(self.message(), 'owner')
            self.assertTrue(started.wait(2))
            # GUI/bridge is absent, no heartbeats are required by enforcement.
            now[0] += 86_400_000
            state = core.snapshot('owner')
            self.assertEqual(state['session_id'], response['session_id'])
            self.assertEqual(state['state'], 'ACTIVE')
            self.assertEqual(state['elapsed_seconds'], 86400)
            self.assertNotIn('deadline_ms', state)
            self.assertEqual(held, ['app.exe'])
            with self.assertRaises(RuntimeError): core.start(self.message(), 'owner')
            other = core.snapshot('someone else')
            self.assertEqual(other['state'], 'STARTING')
            self.assertNotIn('applications', other)
            core.stop()
            core.join(2)
            self.assertEqual(held, [])
            self.assertEqual(events[-1], ('ENDED', []))
            self.assertEqual(SessionService().snapshot('owner'), {'state':'IDLE'})
        finally:
            core.stop(); core.join(2)

    def test_partial_failure_publishes_error_after_rollback(self):
        held=[]
        @contextmanager
        def lock(path):
            if path=='bad.exe': raise OSError('occupied')
            held.append(path)
            try: yield
            finally: held.remove(path)
        def runner(request,publish,stop_event):
            run_session(request,publish,stop_event=stop_event,lock_factory=lock,validate=lambda x:x,
                        check=lambda x:None,clock=lambda:0)
        core=SessionService(runner,clock=lambda:0)
        msg=self.message(); msg.update(applications=['ok.exe','bad.exe'],force_running=False)
        core.start(msg,'owner'); core.join(2)
        self.assertEqual(core.snapshot('owner')['state'],'ERROR')
        self.assertEqual(held,[])

    def test_untrusted_requests_cannot_stop_or_set_arbitrary_lifetime(self):
        core=SessionService()
        for message in ({'op':'stop'}, {'op':'start'}, self.message(deadline_ms=1),
                        self.message(owner_sid='someone else')):
            with self.assertRaises(ValueError): core.start(message,'owner')
        message=self.message(); message['applications']=['a.exe']*101
        with self.assertRaises(ValueError): core.start(message,'owner')
        self.assertEqual(CLIENT_ACCESS & 4, 0)
        self.assertIn('(D;;GA;;;NU)',STATUS_SDDL)
        with self.assertRaises(ValueError): encode({'x':'x'*MAX_FRAME})

    def test_invalid_timer_is_rejected_before_any_worker_starts(self):
        runner = Mock()
        core = SessionService(runner, clock=lambda: 0)
        for minutes in (0, -1, 721, True, 1.5, '1', [], {}):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                core.start(self.message(minutes=minutes), 'owner')
        runner.assert_not_called()

    def test_timer_expires_in_service_without_gui_or_status_polling(self):
        now, held, events = [1000], [], []
        active = threading.Event()
        @contextmanager
        def lock(path):
            held.append(path)
            try:
                yield
            finally:
                held.remove(path)
        def runner(request, publish, stop_event):
            def status(kind, **extra):
                events.append((kind, list(held)))
                publish(kind, **extra)
                if kind == 'ACTIVE':
                    active.set()
            run_session(request, status, stop_event=stop_event, lock_factory=lock,
                        validate=lambda x: x, check=lambda x: None,
                        force_closer=lambda *a, **k: None, clock=lambda: now[0])
        core = SessionService(runner, clock=lambda: now[0])
        try:
            core.start(self.message(minutes=1), 'owner')
            self.assertTrue(active.wait(2))
            state = core.snapshot('owner')
            self.assertEqual(state['mode'], 'timed')
            self.assertEqual(state['remaining_seconds'], 60)
            self.assertEqual(state['deadline_ms'], 61000)
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                core.start(self.message(minutes=1), 'owner')
            now[0] = 32001
            self.assertEqual(core.snapshot('owner')['remaining_seconds'], 29)
            self.assertEqual(held, ['app.exe'])
            # No status requests, UI or browser: only the service loop expires it.
            now[0] = 61000
            core.join(2)
            self.assertFalse(core.thread.is_alive())
            self.assertEqual(held, [])
            self.assertEqual(events[-1], ('ENDED', []))
            self.assertEqual(core.snapshot('owner')['state'], 'ENDED')
            self.assertFalse(core.stop_event.is_set())
            # Expiry does not stop the service or prevent a subsequent session.
            active.clear()
            core.start(self.message(minutes=1), 'owner')
            self.assertTrue(active.wait(2))
            self.assertEqual(core.snapshot('owner')['remaining_seconds'], 60)
        finally:
            core.stop()
            core.join(2)

    def test_client_sends_duration_without_owning_lifetime(self):
        with patch.object(service_client, 'service_status', return_value={'ProcessId': 42}) as status, \
             patch.object(service_client, 'request', return_value={'session_id': 'id'}) as request:
            self.assertEqual(service_client.launch_session(['app.exe'], minutes=50), 'id')
            status.assert_called_once_with(start=True)
            self.assertEqual(request.call_args.args[0]['minutes'], 50)
            service_client.launch_session(['app.exe'], minutes=None)
            self.assertIsNone(request.call_args.args[0]['minutes'])

    def test_old_service_rejection_has_actionable_upgrade_message(self):
        with patch.object(service_client, 'service_status', return_value={'ProcessId': 42}), \
             patch.object(service_client, 'request', side_effect=RuntimeError('Invalid start request.')):
            with self.assertRaisesRegex(RuntimeError, 'Updating only the GUI is not enough'):
                service_client.launch_session(['app.exe'])

    def test_bridge_reports_real_service_countdown_and_then_clears_domains(self):
        value = snapshot(dict(state='ACTIVE', mode='timed', session_id='s',
                              websites=['youtube.com'], remaining_seconds=51))
        self.assertEqual(value['protocol'], 1)
        self.assertEqual(value['remainingSeconds'], 51)
        self.assertEqual(snapshot({'state': 'ENDED'})['domains'], [])

    def test_stopped_or_missing_service_does_not_resurrect_a_session(self):
        with patch.object(service_client,'service_status',return_value={'CurrentState':1}), \
             patch.object(service_client,'request') as request:
            self.assertEqual(service_client.read_state(),{'state':'IDLE'})
            request.assert_not_called()
        with patch.object(service_client,'service_status',return_value=None):
            self.assertEqual(service_client.read_state()['state'],'SERVICE_MISSING')
            with self.assertRaisesRegex(RuntimeError,'installer'):
                service_client.launch_session(['a.exe'])

    def test_owner_check_precedes_any_termination(self):
        api=FakeAPI()
        api.owner=lambda handle: 'other' if handle[0]==102 else 'owner'
        with self.assertRaisesRegex(ValueError,'another Windows account'):
            force_close_selected([r'C:\Apps\Discord.exe'],api=api,owner_sid='owner')
        self.assertEqual(api.killed,[])
        self.assertCountEqual(api.opened,api.closed)

    def test_browser_receives_a_status_lease_not_a_focus_timer(self):
        state=dict(state='ACTIVE',mode='until_reboot',session_id='s',applications=['private.exe'],
                   websites=['youtube.com'],elapsed_seconds=400)
        value=snapshot(state)
        self.assertEqual(value['protocol'],2)
        self.assertEqual(value['mode'],'until_reboot')
        self.assertEqual(value['remainingSeconds'],15)
        self.assertNotIn('applications',value)
        self.assertEqual(snapshot({'state':'IDLE'})['domains'],[])
        self.assertTrue(allowed_caller(['chrome-extension://mmcnhdgobmfalggffgjfhbogfoblhheo/']))
        self.assertTrue(allowed_caller([r'C:\host.json','staylocked@staylocked.local']))
        self.assertFalse(allowed_caller(['chrome-extension://someone-else/']))
        self.assertFalse(allowed_caller([r'C:\host.json','another-addon']))

    def test_stop_during_preparation_cannot_force_close_apps(self):
        stop=threading.Event(); stop.set()
        closer=Mock()
        with self.assertRaisesRegex(RuntimeError,'stopping'):
            run_session(dict(until_reboot=True,applications=['app.exe'],force_running=True,
                             start_before_ms=1000),Mock(),stop_event=stop,clock=lambda:0,force_closer=closer)
        closer.assert_not_called()
