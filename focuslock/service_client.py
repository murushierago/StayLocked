"""Desktop and bridge share the service status; neither owns the restrictions."""
import time
from .service_core import SERVICE_NAME
from .service_ipc import request


def service_status(start=False):
    import pywintypes
    import win32service as s
    manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT)
    try:
        try:
            service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_QUERY_STATUS | (s.SERVICE_START if start else 0))
        except pywintypes.error as exc:
            if exc.winerror == 1060:
                return None
            raise
        try:
            status = s.QueryServiceStatusEx(service)
            if start and status['CurrentState'] == s.SERVICE_STOPPED:
                try:
                    s.StartService(service, None)
                except pywintypes.error as exc:
                    if exc.winerror != 1056:
                        raise
            if start:
                deadline = time.monotonic() + 10
                while status['CurrentState'] != s.SERVICE_RUNNING:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Service did not start. Check Windows Event Viewer → Application.')
                    time.sleep(.1)
                    status = s.QueryServiceStatusEx(service)
            return status
        finally:
            s.CloseServiceHandle(service)
    finally:
        s.CloseServiceHandle(manager)


def read_state():
    status = service_status()
    if status is None:
        return {'state': 'SERVICE_MISSING', 'message': 'Install StayLocked 0.6.1 with its installer to enable the Windows service.'}
    if status['CurrentState'] == 1:  # SERVICE_STOPPED: normal after a restart
        return {'state': 'IDLE'}
    if status['CurrentState'] != 4:
        return {'state': 'STARTING', 'message': 'Windows service is starting or stopping…'}
    return request({'op': 'status'}, status['ProcessId'])['status']


def launch_session(applications, force_running=False, websites=None, minutes=25):
    # No fallback to a user-owned worker: that would silently weaken enforcement.
    status = service_status(start=True)
    if status is None:
        raise RuntimeError('Install StayLocked 0.6.1 using its installer, then reopen the app.')
    try:
        return request({'op': 'start', 'applications': list(applications),
                        'websites': list(websites or []), 'force_running': bool(force_running),
                        'minutes': minutes},
                       status['ProcessId'], control=True)['session_id']
    except RuntimeError as exc:
        if str(exc) == 'Invalid start request.':
            raise RuntimeError('The installed service may be an older version. Install StayLocked 0.6.1 '
                               'using the new installer, then reopen the app. Updating only the GUI is not enough.') from exc
        raise
