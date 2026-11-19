"""Read-only native messaging entry point. stdout is exclusively framed JSON."""
from focuslock.native_host import main

if __name__ == '__main__':
    raise SystemExit(main())
