"""Start the GUI without a console; run with .venv\\Scripts\\python.exe."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    if sys.platform != 'win32':
        print('StayLocked requires Windows 10/11.')
        return 1
    from focuslock.session import worker_runtime
    from focuslock.storage import data_directory

    executable, env = worker_runtime()
    base = Path(executable)
    if base.name.lower().startswith('pythonw'):
        windowless = base
    else:
        windowless = base.with_name(base.name.replace('python', 'pythonw', 1))
    if not windowless.is_file():
        raise RuntimeError(f'Windowless Python not found: {windowless}. Use python main.py for diagnostics.')
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'ui.log').open('a', encoding='utf-8') as log:
        child = subprocess.Popen(
            [str(windowless), str(Path(__file__).with_name('main.py').resolve())],
            cwd=str(Path(__file__).resolve().parent), env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    print(f'StayLocked launched (PID {child.pid}). You may close this terminal.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Cannot launch StayLocked: {exc}')
        raise SystemExit(1)
