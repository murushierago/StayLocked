"""Request normal closure of exact selected executables, never force termination."""
import ctypes
from ctypes import wintypes as w
import time
from .storage import path_key


def request_window_closure(targets):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    signatures = (
        (kernel.OpenProcess, [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        (kernel.CloseHandle, [w.HANDLE], w.BOOL),
        (kernel.QueryFullProcessImageNameW, [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
        (kernel.WaitForSingleObject, [w.HANDLE, w.DWORD], w.DWORD),
        (user.EnumWindows, [callback_type, w.LPARAM], w.BOOL),
        (user.IsWindowVisible, [w.HWND], w.BOOL),
        (user.GetWindow, [w.HWND, w.UINT], w.HWND),
        (user.GetWindowThreadProcessId, [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
        (user.PostMessageW, [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
    )
    for function, arguments, result in signatures:
        function.argtypes, function.restype = arguments, result
    selected = {path_key(str(p)) for p in targets}
    windows = []

    @callback_type
    def collect(hwnd, unused):
        # Snapshot before posting; owned windows such as save dialogs are excluded.
        if user.IsWindowVisible(hwnd) and not user.GetWindow(hwnd, 4):
            pid = w.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append((hwnd, pid.value))
        return True

    if not user.EnumWindows(collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    for hwnd, expected_pid in windows:
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, expected_pid)
        if not handle:
            continue  # Subsequent running check refuses activation; never guess.
        try:
            path = ctypes.create_unicode_buffer(32768)
            size = w.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                continue
            if path_key(path.value) not in selected:
                continue
            pid = w.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if (pid.value != expected_pid or kernel.WaitForSingleObject(handle, 0) != 258
                    or not user.IsWindowVisible(hwnd) or user.GetWindow(hwnd, 4)):
                continue
            if not user.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
                raise OSError('Could not request closure. Close the selected app manually, then retry.')
        finally:
            kernel.CloseHandle(handle)


def close_selected(targets, send=request_window_closure, check=None,
                   clock=time.monotonic, sleep=time.sleep, timeout=20):
    if check is None:
        from .session import ensure_not_running
        check = ensure_not_running
    try:
        check(targets)
        return
    except ValueError:
        pass
    send(targets)
    deadline = clock() + timeout
    while True:
        try:
            check(targets)
            return
        except ValueError as exc:
            if clock() >= deadline:
                raise ValueError('Some apps stayed open after the close request. '
                                 'Complete their save dialogs or use Exit in their tray menu, then retry. '
                                 'Focus Mode was not started.\n\n' + str(exc)) from exc
        sleep(0.5)
