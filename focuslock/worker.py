"""Enforcement loop: owns file handles, network filters and the session deadline."""
from contextlib import ExitStack
import json
import os
import re
import sys
import time
import traceback

from .storage import data_directory
from .session import write_json, validate_targets, ensure_not_running, parse_minutes
from . import winapi


def run_session(request, publish, lock_factory=winapi.ExecutableLock,
                validate=validate_targets, check=ensure_not_running,
                clock=winapi.tick_ms, sleep=time.sleep, closer=None, force_closer=None, network_factory=None, stop_event=None):
    """Acquire all or roll back all; publish ACTIVE only after successful checks."""
    until_reboot = request.get('until_reboot') is True
    if until_reboot and stop_event is None:
        raise ValueError('A reboot session requires a service lifetime.')
    minutes = None if until_reboot else parse_minutes(request['minutes'])
    def check_cancelled():
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError('Windows service is stopping.')
    check_cancelled()
    if clock() >= request['start_before_ms']:
        raise ValueError('Start request expired. Please start again.')
    from .websites import validate_websites
    domains = validate_websites(request.get('websites', []))
    targets = validate(request['applications']) if request['applications'] else []
    if not targets and not domains:
        raise ValueError('Add at least one application or website.')
    with ExitStack() as locks:
        network = None
        if domains:
            if network_factory is None:
                from .network import WebsiteGuard
                network_factory = WebsiteGuard
            publish('STARTING', message='Resolving websites and preparing temporary Windows filters…')
            network = locks.enter_context(network_factory(domains))
        if clock() >= request['start_before_ms']:
            raise ValueError('Preparation took too long. Please start again.')
        check_cancelled()
        if targets and request.get('force_running') is True:
            if force_closer is None:
                from .force_close import force_close_selected
                force_closer = force_close_selected
            publish('STARTING', message='Ending selected app processes…')
            if request.get('owner_sid'):
                force_closer(targets, owner_sid=request['owner_sid'], stop_event=stop_event)
            else:
                force_closer(targets)
        elif targets and request.get('close_running') is True:
            if closer is None:
                from .closing import close_selected
                closer = close_selected
            publish('STARTING', message='Closing selected apps. Respond to any save dialogs…')
            closer(targets)
        if targets:
            check(targets)
        for target in targets:
            check_cancelled()
            locks.enter_context(lock_factory(target))
        if targets:
            check(targets)
        if clock() >= request['start_before_ms']:
            raise ValueError('Preparation took too long. Please start again.')
        check_cancelled()
        started = clock()
        deadline = None if until_reboot else started + minutes * 60_000

        def active():
            publish('ACTIVE', applications=[str(p) for p in targets], websites=domains,
                    started_ms=started, **({} if until_reboot else dict(deadline_ms=deadline)),
                    **(network.status() if network else {}))

        active()
        last_status = network.status() if network else {}
        while True:
            remaining = 250 if until_reboot else deadline - clock()
            if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                break
            if network:
                network.tick()
                status = network.status()
                if status != last_status:
                    active()
                    last_status = status
            if stop_event is not None:
                stop_event.wait(min(.25, remaining / 1000))
            else:
                sleep(min(0.25, remaining / 1000))
    # All file handles and the WFP dynamic session are released before ENDED.
    publish('ENDED', message='Session complete. App and network restrictions are removed.')


def main(session_id=None):
    if session_id is None:
        session_id = sys.argv[1] if len(sys.argv) == 2 else ''
    if sys.platform != 'win32' or not re.fullmatch('[0-9a-f]{32}', session_id):
        return 1
    directory = data_directory()
    request_path = directory / f'request-{session_id}.json'
    try:
        with winapi.SessionMutex(directory):
            identity = winapi.process_identity(os.getpid())
            if identity is None:
                raise RuntimeError('Cannot identify the worker process.')

            def publish(state, **extra):
                write_json(directory / 'session.json', dict(
                    session_id=session_id, state=state, pid=os.getpid(),
                    process_identity=identity, **extra))

            try:
                publish('STARTING')
                request = json.loads(request_path.read_text(encoding='utf-8'))
                if request.get('session_id') != session_id:
                    raise ValueError('Invalid session request.')
                request_path.unlink()
                run_session(request, publish)
            except Exception as exc:
                # run_session's ExitStack has already released partial locks.
                traceback.print_exc()
                publish('ERROR', message=str(exc))
                return 1
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        request_path.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
