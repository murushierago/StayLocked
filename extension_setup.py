"""Windowed setup companion; always runs as the current Windows user."""
import sys
from focuslock.extension_setup import register, unregister, show_wizard


def main():
    try:
        if sys.argv[1:] == ['--register']:
            register()
        elif sys.argv[1:] == ['--remove']:
            unregister()
        elif not sys.argv[1:]:
            show_wizard()
        else:
            raise ValueError('Unknown setup argument.')
        return 0
    except Exception as exc:
        from focuslock.storage import data_directory
        folder = data_directory()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'extension-setup-error.txt').write_text(str(exc), encoding='utf-8')
        if not sys.argv[1:]:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'StayLocked browser setup', 0x10)
        return 1


if __name__ == '__main__':
    from focuslock.winapi import InstallationMarker
    with InstallationMarker():
        raise SystemExit(main())
