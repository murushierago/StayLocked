"""In-memory, single-session coordinator. No disk file can stop enforcement."""
from copy import deepcopy
import threading
import uuid

from . import winapi
from .worker import run_session
from .session import parse_minutes, remaining_seconds
from .websites import validate_websites

SERVICE_NAME = 'StayLockedService'
CONTROL_PIPE = r'\\.\pipe\StayLocked.Control.v1'
STATUS_PIPE = r'\\.\pipe\StayLocked.Status.v1'


class SessionService:
    def __init__(self, runner=run_session, clock=winapi.tick_ms):
        self.runner, self.clock = runner, clock
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.owner = None
        self.data = {'state': 'IDLE'}

    def start(self, message, owner_sid):
        required = {'op', 'applications', 'websites', 'force_running'}
        if (not isinstance(message, dict) or not required <= set(message)
                or set(message) - required - {'minutes'}):
            raise ValueError('Invalid start request.')
        minutes = message.get('minutes')
        if minutes is not None:
            if type(minutes) is not int:
                raise ValueError('Duration must be a whole number of minutes.')
            minutes = parse_minutes(minutes)
        apps = message['applications']
        if (message['op'] != 'start' or type(message['force_running']) is not bool
                or not isinstance(apps, list) or len(apps) > 100
                or any(not isinstance(p, str) or not 1 <= len(p) <= 4096 for p in apps)):
            raise ValueError('Invalid application selection.')
        domains = validate_websites(message['websites'])
        if not apps and not domains:
            raise ValueError('Choose at least one app or website.')
        request = dict(applications=list(apps), websites=domains,
                       force_running=message['force_running'], owner_sid=owner_sid,
                       until_reboot=minutes is None, minutes=minutes,
                       start_before_ms=self.clock() + 60000)
        with self.lock:
            if self.stop_event.is_set():
                raise RuntimeError('The service is shutting down.')
            if self.thread and self.thread.is_alive():
                raise RuntimeError('A focus session is already running on this PC.')
            session_id = uuid.uuid4().hex
            self.owner = owner_sid
            self.data = {'state': 'STARTING', 'session_id': session_id,
                         'mode': 'until_reboot' if minutes is None else 'timed'}
            self.thread = threading.Thread(target=self._run, args=(request, session_id), name='Focus session')
            self.thread.start()
        return {'ok': True, 'session_id': session_id}

    def _run(self, request, session_id):
        mode = 'until_reboot' if request['until_reboot'] else 'timed'
        def publish(state, **extra):
            with self.lock:
                self.data = dict(state=state, session_id=session_id, mode=mode, **extra)
        try:
            self.runner(request, publish, stop_event=self.stop_event)
        except Exception as exc:
            # run_session releases its entire ExitStack before this error is published.
            publish('ERROR', message=str(exc))

    def snapshot(self, sid):
        with self.lock:
            if self.owner and sid != self.owner:
                if self.data['state'] in {'STARTING', 'ACTIVE'}:
                    return {'state': 'STARTING', 'message': 'A focus session belongs to another Windows user.'}
                return {'state': 'IDLE'}
            result = deepcopy(self.data)
        if result['state'] == 'ACTIVE':
            now = self.clock()
            result['elapsed_seconds'] = max(0, (now - result['started_ms']) // 1000)
            if result['mode'] == 'timed':
                result['remaining_seconds'] = remaining_seconds(result['deadline_ms'], now)
        return result

    def stop(self):
        # Only SCM STOP/SHUTDOWN calls this; there is deliberately no stop IPC verb.
        self.stop_event.set()

    def session_busy(self):
        with self.lock:
            return self._session_busy()

    def _session_busy(self):
        return (self.data['state'] in {'STARTING', 'ACTIVE'} or
                bool(self.thread and self.thread.is_alive()))

    def stop_if_idle(self):
        # Share the start() lock: a STOP racing with a new session cannot unlock it.
        with self.lock:
            if self._session_busy():
                return False
            self.stop_event.set()
            return True

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)
