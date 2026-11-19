"""Opt-in Windows integration check against an INSTALLED 0.7.1 service.

Default: read-only status. --exercise: lock one disposable copy of where.exe,
close its requesting process, verify the lock, wait for its one-minute timer,
then verify unlock. Failed-test cleanup waits for the disposable timed session to end.
Never uses your configured blacklist.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from focuslock import service_client as client


def wait_state(expected, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.read_state()
        if state['state'] == expected:
            return state
        if state['state'] == 'ERROR':
            raise RuntimeError(state.get('message'))
        time.sleep(.2)
    raise TimeoutError(f'Expected {expected}; received {state}')


def exercise():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError('Run this test from an administrator PowerShell.')
    state = client.read_state()
    if state['state'] not in {'IDLE', 'ENDED', 'ERROR'}:
        raise RuntimeError('Test refused: service missing, busy or owned by an existing session. Restart Windows first.')
    from focuslock.service_core import SERVICE_NAME
    import win32service as s
    with tempfile.TemporaryDirectory(prefix='StayLocked-probe-') as folder:
        probe = Path(folder) / 'StayLockedProbe.exe'
        shutil.copyfile(Path(os.environ['SystemRoot']) / 'System32' / 'where.exe', probe)
        original = probe.read_bytes()
        requested = None
        try:
            code = ('import json,sys; from focuslock.service_client import launch_session; '
                    'print(json.dumps(launch_session([sys.argv[1]],force_running=False,minutes=1)))')
            # The requesting process exits completely, like ending the desktop task.
            completed = subprocess.run([sys.executable, '-c', code, str(probe)], cwd=ROOT,
                                       capture_output=True, text=True, check=True, timeout=20)
            requested = json.loads(completed.stdout.strip())
            state = wait_state('ACTIVE')
            assert state['session_id'] == requested
            assert state['applications'] == [str(probe)]
            assert state['mode'] == 'timed'
            assert 0 < state['remaining_seconds'] <= 60
            try:
                probe.read_bytes()
            except PermissionError:
                pass
            else:
                raise AssertionError('File was readable after the requesting process exited.')
            # Service-manager Stop (including Task Manager's Services tab) must
            # be unavailable during a session, while shutdown remains accepted.
            manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT)
            service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_STOP | s.SERVICE_QUERY_STATUS)
            try:
                until = time.monotonic() + 5
                while s.QueryServiceStatus(service)[2] & s.SERVICE_ACCEPT_STOP:
                    if time.monotonic() >= until:
                        raise AssertionError('Active service still advertises STOP')
                    time.sleep(.1)
                assert s.QueryServiceStatus(service)[2] & s.SERVICE_ACCEPT_SHUTDOWN
                import pywintypes
                try:
                    s.ControlService(service, s.SERVICE_CONTROL_STOP)
                except pywintypes.error as exc:
                    assert exc.winerror == 1061, exc
                else:
                    raise AssertionError('SCM accepted STOP during an active session')
                assert client.read_state()['session_id'] == requested
                assert client.read_state()['state'] == 'ACTIVE'
            finally:
                s.CloseServiceHandle(service)
                s.CloseServiceHandle(manager)
            service_exe = Path(os.environ['ProgramFiles']) / 'StayLocked' / 'service' / 'StayLockedService.exe'
            for operation in ('--prepare-upgrade', '--remove'):
                result = subprocess.run([str(service_exe), operation, '--quiet'], timeout=15)
                assert result.returncode == 10, (operation, result.returncode)
                assert client.read_state()['state'] == 'ACTIVE'
            print('PASS: SCM STOP and maintenance refused during focus; shutdown remains accepted.', flush=True)
            # Status API remains available while enforcement owns the file.
            for _ in range(3):
                assert client.read_state()['session_id'] == requested
            print('PASS: service accepted IPC, requester exited, executable stayed locked; status is accessible.')
            print('Waiting for the service timer to finish (up to 60 seconds)...', flush=True)
            ended = wait_state('ENDED', timeout=80)
            assert ended['session_id'] == requested
            assert probe.read_bytes() == original
            manager = s.OpenSCManager(None, None, s.SC_MANAGER_CONNECT)
            service = s.OpenService(manager, SERVICE_NAME, s.SERVICE_QUERY_STATUS)
            try:
                until = time.monotonic() + 5
                while not s.QueryServiceStatus(service)[2] & s.SERVICE_ACCEPT_STOP:
                    if time.monotonic() >= until:
                        raise AssertionError('Idle service did not restore STOP')
                    time.sleep(.1)
            finally:
                s.CloseServiceHandle(service)
                s.CloseServiceHandle(manager)
            print('PASS: service timer released the lock without the requester; executable bytes are unchanged.')
        finally:
            current = client.read_state()
            if requested and current.get('session_id') == requested and current['state'] in {'STARTING','ACTIVE'}:
                print('Waiting for this test session to expire before cleanup...', flush=True)
                wait_state('ENDED', timeout=80)
            elif current['state'] in {'STARTING','ACTIVE'}:
                raise RuntimeError('Session identity changed; test will not stop an unrelated session. Restart Windows to clean up.')
        assert probe.read_bytes() == original
        print('Still test a real Windows restart and browser connections manually. This test does not reboot your PC.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('Run this check on Windows after installing StayLocked 0.7.1.')
    if args.exercise:
        exercise()
    else:
        print(json.dumps(client.read_state(), indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'CHECK FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1)
