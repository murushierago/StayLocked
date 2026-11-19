"""Small, explicit Win32 wrappers. No registry/ACL changes or process killing."""
import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import sys

if sys.platform == 'win32':
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    def bind(name, args, result):
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = args, result
        return fn

    create_file = bind('CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                                      w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)
    close_handle = bind('CloseHandle', [w.HANDLE], w.BOOL)
    create_mutex = bind('CreateMutexW', [w.LPVOID, w.BOOL, w.LPCWSTR], w.HANDLE)
    open_mutex = bind('OpenMutexW', [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE)
    release_mutex = bind('ReleaseMutex', [w.HANDLE], w.BOOL)
    get_ticks = bind('GetTickCount64', [], ctypes.c_ulonglong)
    open_process = bind('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
    process_times = bind('GetProcessTimes', [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL)
    wait = bind('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD)


def tick_ms():
    return int(get_ticks())


def mutex_name(directory):
    key = hashlib.sha256(str(directory).casefold().encode()).hexdigest()[:24]
    return 'Local\\FocusLock.Session.' + key


def worker_present(directory):
    handle = open_mutex(0x00100000, False, mutex_name(directory))  # SYNCHRONIZE
    if handle:
        close_handle(handle)
        return True
    error = ctypes.get_last_error()
    if error == 2:  # ERROR_FILE_NOT_FOUND
        return False
    raise ctypes.WinError(error)


class SessionMutex:
    def __init__(self, directory):
        self.directory = directory
        self.handle = None

    def __enter__(self):
        handle = create_mutex(None, True, mutex_name(self.directory))
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS; we did not acquire ownership
            close_handle(handle)
            raise RuntimeError('A Focus Session is already running.')
        self.handle = handle
        return self

    def __exit__(self, *args):
        release_mutex(self.handle)
        close_handle(self.handle)


def process_identity(pid):
    """Creation time + PID avoids mistaking a reused PID for the old worker."""
    handle = open_process(0x1000 | 0x00100000, False, pid)
    if not handle:
        return None
    try:
        if wait(handle, 0) != 258:  # WAIT_TIMEOUT means still running
            return None
        times = [w.FILETIME() for _ in range(4)]
        if not process_times(handle, *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        close_handle(handle)


class ExecutableLock:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        # Read-only, no sharing, OPEN_EXISTING. Never writes to the executable.
        handle = create_file(str(self.path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            raise OSError(f'Cannot lock {self.path.name}: {ctypes.WinError(error)}. '
                          'Close the app and any updater, then try again.')
        self.handle = handle
        return self

    def __exit__(self, *args):
        if not close_handle(self.handle):
            raise ctypes.WinError(ctypes.get_last_error())


class InstallationMarker:
    """Shared lifetime marker, not a lock: GUI and worker can both hold it."""
    def __enter__(self):
        self.handle = create_mutex(None, False, 'Local\\FocusLock.InstalledRunning')
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return self

    def __exit__(self, *args):
        close_handle(self.handle)
