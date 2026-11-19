"""GUI/worker contract. JSON is a status snapshot, never an enforcement switch."""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from .storage import data_directory, validate_applications
from . import winapi

MAX_MINUTES = 720
PROTECTED_NAMES = {
    'taskmgr.exe', 'shutdown.exe', 'explorer.exe', 'cmd.exe', 'powershell.exe',
    'pwsh.exe', 'conhost.exe', 'winlogon.exe', 'csrss.exe', 'lsass.exe',
    'services.exe', 'svchost.exe', 'wininit.exe', 'smss.exe', 'dwm.exe',
    'msmpeng.exe', 'regedit.exe', 'mmc.exe', 'python.exe', 'pythonw.exe',
    'py.exe', 'focuslock.exe', 'focuslock-worker.exe', 'focuslockbridge.exe',
    'staylocked.exe', 'staylockedbridge.exe', 'extensionsetup.exe', 'staylockedservice.exe',
}


def parse_minutes(text):
    try:
        minutes = int(text)
    except (TypeError, ValueError):
        raise ValueError('Enter a whole number of minutes (1–720).') from None
    if not 1 <= minutes <= MAX_MINUTES:
        raise ValueError('Duration must be between 1 and 720 minutes.')
    return minutes


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_targets(items):
    validate_applications(items)
    if not items:
        raise ValueError('Add at least one application.')
    roots = [Path(os.environ['SystemRoot']).resolve(),
             Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve(),
             Path(__file__).resolve().parents[1]]
    if getattr(sys, 'frozen', False):
        roots.append(Path(sys.executable).resolve().parent)
    targets = []
    for value in items:
        path = Path(value).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != '.exe':
            raise ValueError(f'Not an executable file: {path}')
        if path.drive.startswith('\\\\') or ':' in str(path)[2:]:
            raise ValueError('Select a local executable, not a network path or file stream.')
        if path.name.casefold() in PROTECTED_NAMES or any(path.is_relative_to(r) for r in roots):
            raise ValueError(f'Protected target: {path.name}. Windows and StayLocked tools cannot be blocked.')
        targets.append(path)
    return targets


def ensure_not_running(targets):
    tasklist = Path(os.environ['SystemRoot']) / 'System32' / 'tasklist.exe'
    result = subprocess.run([str(tasklist), '/FO', 'CSV', '/NH'], capture_output=True,
                            check=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
    rows = csv.reader(io.StringIO(result.stdout.decode('oem')))
    names = {r[0].casefold() for r in rows if len(r) >= 2 and r[1].isdigit()}
    if not names:
        raise RuntimeError('Cannot verify running applications. Focus Mode was not started.')
    running = [p.name for p in targets if p.name.casefold() in names]
    if running:
        raise ValueError(', '.join(running) + ' is currently running. Close it (including its tray icon) before starting Focus Mode.')


def remaining_seconds(deadline_ms, now_ms):
    return max(0, (deadline_ms - now_ms + 999) // 1000)


def format_remaining(seconds):
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}'


def read_state():
    directory = data_directory()
    present = winapi.worker_present(directory)
    try:
        data = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Invalid session status.')
    except FileNotFoundError:
        data = {}
    except (ValueError, OSError):
        if present:
            return {'state': 'STARTING', 'message': 'Worker is running; status is unavailable.'}
        return {'state': 'IDLE'}
    if not present:
        if data.get('state') in {'ACTIVE', 'STARTING'}:
            return {'state': 'INTERRUPTED', 'session_id': data.get('session_id')}
        return data if data.get('state') in {'ENDED', 'ERROR'} else {'state': 'IDLE'}
    pid, identity = data.get('pid'), data.get('process_identity')
    if type(pid) is not int or identity is None or winapi.process_identity(pid) != identity:
        return {'state': 'STARTING'}
    if data.get('state') == 'ACTIVE':
        if type(data.get('deadline_ms')) is not int or not isinstance(data.get('applications'), list):
            return {'state': 'STARTING', 'message': 'Waiting for valid session status.'}
        data['remaining_seconds'] = remaining_seconds(data['deadline_ms'], winapi.tick_ms())
    # Keep editing locked until the worker has actually released its mutex.
    if data.get('state') in {'ENDED', 'ERROR'}:
        return {'state': 'STARTING', 'message': 'Finishing session cleanup…'}
    return data


def worker_runtime():
    """Bypass the Windows venv redirector, preserving the venv configuration.

    The redirector can launch the real interpreter with creation flags = 0,
    losing DETACHED_PROCESS and allocating a new worker console.
    CPython multiprocessing uses this same base-interpreter/environment pattern.
    """
    executable = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
    if not executable.is_file():
        raise RuntimeError(f'Python runtime is missing: {executable}')
    env = os.environ.copy()
    env.pop('__PYVENV_LAUNCHER__', None)
    if sys.prefix != sys.base_prefix:
        env['__PYVENV_LAUNCHER__'] = sys.executable
    return str(executable), env


def worker_command(session_id):
    if getattr(sys, 'frozen', False):
        env = os.environ.copy()
        env.pop('__PYVENV_LAUNCHER__', None)
        # The worker must have a lifetime independent of its GUI parent.
        env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        return [sys.executable, '--focuslock-worker', session_id], env
    executable, env = worker_runtime()
    return [executable, '-m', 'focuslock.worker', session_id], env


def launch_session(applications, minutes, close_running=False, force_running=False, websites=None):
    from .websites import validate_websites
    websites = validate_websites([] if websites is None else websites)
    if websites:
        from .network import require_admin, domain_hosts
        require_admin()
        domain_hosts(websites)
    minutes = parse_minutes(minutes)
    validate_applications(applications)
    directory = data_directory()
    if winapi.worker_present(directory):
        raise RuntimeError('A Focus Session is already running.')
    session_id = uuid.uuid4().hex
    command, env = worker_command(session_id)
    request_path = directory / f'request-{session_id}.json'
    write_json(request_path, {'session_id': session_id, 'applications': list(applications),
                             'websites': websites, 'minutes': minutes, 'close_running': close_running, 'force_running': force_running,
                             'start_before_ms': winapi.tick_ms() + 60000})
    try:
        # Apply DETACHED_PROCESS to the REAL interpreter, not a venv launcher.
        # Worker remains visible in Task Manager, with output in worker.log.
        with (directory / 'worker.log').open('a', encoding='utf-8') as log:
            child = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, close_fds=True, env=env,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    except Exception:
        request_path.unlink(missing_ok=True)
        raise
    return child, session_id
