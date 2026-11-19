"""Optional developer CLI; normal users use the Browser extension button."""
import sys
from focuslock.extension_setup import extension_id, register, unregister


def main():
    if sys.argv[1:] == ['--remove']:
        unregister()
        print('StayLocked bridge registration removed.')
    elif not sys.argv[1:]:
        directory = register()
        print(f'StayLocked bridge registered. Load unpacked extension from: {directory}')
    else:
        raise ValueError('Usage: register_extension.py [--remove]')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Cannot register extension: {exc}', file=sys.stderr)
        raise SystemExit(1)
