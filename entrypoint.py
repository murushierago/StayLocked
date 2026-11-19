"""Entry point for the windowed executable: GUI OR worker, never both."""
import ctypes
import logging
import sys
import traceback


def dispatch(args):
    if len(args) == 2 and args[0] == '--focuslock-worker':
        from focuslock.worker import main as worker_main
        return worker_main(args[1])
    if args:
        raise ValueError('Unknown StayLocked launch arguments.')
    from main import main as gui_main
    return gui_main()


def main():
    args = sys.argv[1:]
    worker = bool(args and args[0] == '--focuslock-worker')
    stream = None
    previous = sys.stdout, sys.stderr
    try:
        from focuslock.storage import data_directory
        directory = data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        # Windowed PyInstaller executables have stdout/stderr = None.
        stream = (directory / ('worker.log' if worker else 'ui.log')).open(
            'a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stderr = stream
        logging.basicConfig(stream=stream, level=logging.WARNING)
        from focuslock.winapi import InstallationMarker
        with InstallationMarker():
            return dispatch(args)
    except Exception as exc:
        if stream:
            traceback.print_exc()
        if not worker and sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None,
                f'{exc}\n\nDetails: %LOCALAPPDATA%\\FocusLock\\ui.log',
                'StayLocked could not start', 0x10)
        return 1
    finally:
        sys.stdout, sys.stderr = previous
        if stream:
            stream.close()


if __name__ == '__main__':
    raise SystemExit(main())
