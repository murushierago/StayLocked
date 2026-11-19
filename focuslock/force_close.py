"""Explicitly consented forced exit, restricted to exact validated executable paths."""
import ctypes
from ctypes import wintypes as w
import os
from .storage import path_key


class ProcessAPI:
    def __init__(self):
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('K32EnumProcesses', [ctypes.POINTER(w.DWORD), w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL),
            ('OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            ('CloseHandle', [w.HANDLE], w.BOOL),
            ('QueryFullProcessImageNameW', [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            ('IsProcessCritical', [w.HANDLE, ctypes.POINTER(w.BOOL)], w.BOOL),
            ('TerminateProcess', [w.HANDLE, w.UINT], w.BOOL),
            ('WaitForSingleObject', [w.HANDLE, w.DWORD], w.DWORD),
        ):
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result

    def pids(self):
        count = 1024
        while count <= 131072:
            buffer = (w.DWORD * count)()
            used = w.DWORD()
            if not self.k.K32EnumProcesses(buffer, ctypes.sizeof(buffer), ctypes.byref(used)):
                raise ctypes.WinError(ctypes.get_last_error())
            if used.value < ctypes.sizeof(buffer):
                return list(buffer[:used.value // ctypes.sizeof(w.DWORD)])
            count *= 2
        raise OSError('Cannot enumerate all processes safely.')

    def open(self, pid, terminate=False):
        return self.k.OpenProcess(0x1000 | 0x100000 | (1 if terminate else 0), False, pid)

    def close(self, handle):
        self.k.CloseHandle(handle)

    def path(self, handle):
        buffer = ctypes.create_unicode_buffer(32768)
        size = w.DWORD(len(buffer))
        if not self.k.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value

    def owner(self, handle):
        import win32security as sec
        token = sec.OpenProcessToken(int(handle), sec.TOKEN_QUERY)
        try:
            return sec.ConvertSidToStringSid(sec.GetTokenInformation(token, sec.TokenUser)[0])
        finally:
            token.Close()

    def critical(self, handle):
        value = w.BOOL()
        if not self.k.IsProcessCritical(handle, ctypes.byref(value)):
            raise OSError('Cannot check process safety. No termination requested for this process.')
        return bool(value.value)

    def alive(self, handle):
        result = self.k.WaitForSingleObject(handle, 0)
        if result not in (0, 258):
            raise OSError('Cannot check process status.')
        return result == 258

    def terminate(self, handle):
        if not self.k.TerminateProcess(handle, 1) and self.alive(handle):
            raise OSError('Windows refused to end the selected app. Close it manually and retry.')

    def wait(self, handle):
        if self.k.WaitForSingleObject(handle, 5000) != 0:
            raise OSError('An app has not finished exiting. Focus Mode was not started.')


def force_close_selected(targets, api=None, owner_sid=None, stop_event=None):
    # Worker calls validate_targets before this function. No image-name or tree kill.
    api = api or ProcessAPI()
    selected = {path_key(str(p)) for p in targets}
    handles = []
    try:
        for pid in api.pids():
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError('Windows service is stopping.')
            if pid in (0, 4, os.getpid()):
                continue
            probe = api.open(pid)
            if not probe:
                continue  # Final running check in worker fails closed for uninspectable targets.
            try:
                path = api.path(probe)
                if path is None or path_key(path) not in selected:
                    continue
                handle = api.open(pid, terminate=True)
                if not handle:
                    if api.alive(probe):
                        raise OSError(f'Cannot end {path}. Close it manually and retry.')
                    continue
                handles.append(handle)
                # Re-query through the SAME handle that would be terminated.
                actual = api.path(handle)
                if actual is None or path_key(actual) not in selected:
                    handles.pop()
                    api.close(handle)
                    continue
                if owner_sid is not None and api.owner(handle) != owner_sid:
                    raise ValueError('This app is running under another Windows account. Close it there before starting.')
                if api.critical(handle):
                    raise ValueError('Critical Windows processes cannot be terminated.')
            finally:
                api.close(probe)
        # Preflight all candidates before any termination. Multi-process Discord is covered
        # because every instance of the selected executable is collected, even without a window.
        for handle in handles:
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError('Windows service is stopping.')
            if api.alive(handle):
                api.terminate(handle)
        for handle in handles:
            api.wait(handle)
    finally:
        for handle in handles:
            api.close(handle)
