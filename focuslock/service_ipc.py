"""Local authenticated named pipes with bounded, cancellable overlapped I/O.

The status pipe cannot start/stop sessions. The control pipe accepts elevated
administrators only. Clients verify the server PID against Windows SCM.
"""
import json
import struct
import time

from .service_core import CONTROL_PIPE, STATUS_PIPE

MAX_FRAME = 65536
CONTROL_SDDL = 'D:P(D;;GA;;;NU)(A;;GA;;;SY)(A;;GA;;;BA)'
# No FILE_CREATE_PIPE_INSTANCE (0x4) for ordinary clients.
STATUS_SDDL = CONTROL_SDDL + '(A;;0x100083;;;AU)'
CLIENT_ACCESS = 0x100083  # SYNCHRONIZE, READ_ATTRIBUTES, READ_DATA, WRITE_DATA


def encode(value):
    payload = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if not 0 < len(payload) <= MAX_FRAME:
        raise ValueError('IPC message is too large.')
    return struct.pack('<I', len(payload)) + payload


def _io(handle, operation, buffer=None, deadline=None, stop=None):
    import pywintypes
    import win32event
    import win32file
    import win32pipe
    ov = pywintypes.OVERLAPPED()
    ov.hEvent = win32event.CreateEvent(None, True, False, None)
    pending = False
    try:
        if operation == 'connect':
            code = win32pipe.ConnectNamedPipe(handle, ov)
            if code == 535:  # A client connected between CreateNamedPipe and Connect.
                return 0
        elif operation == 'read':
            code, _ = win32file.ReadFile(handle, buffer, ov)
        elif operation == 'write':
            code, _ = win32file.WriteFile(handle, buffer, ov)
        else:
            raise ValueError('Unknown pipe operation.')
        pending = code == 997
        if code not in (0, 997):
            raise OSError(f'Unexpected pipe I/O result: {code}')
        while pending:
            if win32event.WaitForSingleObject(ov.hEvent, 100) == 0:
                break
            if (stop and stop.is_set()) or (deadline is not None and time.monotonic() >= deadline):
                raise TimeoutError('StayLocked service connection timed out.')
        result = win32file.GetOverlappedResult(handle, ov, False)
        pending = False
        return result
    finally:
        try:
            if pending:
                # Each handle has one I/O at a time, issued/cancelled on this
                # same thread. pywin32 exposes CancelIo, not CancelIoEx.
                win32file.CancelIo(handle)
                # Keep OVERLAPPED and its buffer alive until cancellation completes.
                try:
                    win32file.GetOverlappedResult(handle, ov, True)
                except pywintypes.error:
                    pass
        finally:
            ov.hEvent.Close()


def read_exact(handle, count, deadline, stop=None):
    import win32file
    result = bytearray()
    while len(result) < count:
        buffer = win32file.AllocateReadBuffer(count - len(result))
        received = _io(handle, 'read', buffer, deadline, stop)
        if not received:
            raise EOFError('Service pipe closed.')
        result.extend(buffer[:received])
    return bytes(result)


def receive(handle, deadline, stop=None):
    size = struct.unpack('<I', read_exact(handle, 4, deadline, stop))[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError('Invalid IPC frame size.')
    value = json.loads(read_exact(handle, size, deadline, stop).decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('IPC object required.')
    return value


def write(handle, data, deadline, stop=None):
    offset = 0
    while offset < len(data):
        buffer = data[offset:]
        size = _io(handle, 'write', buffer, deadline, stop)
        if not size:
            raise EOFError('Service pipe closed.')
        offset += size


def client_identity(handle):
    import win32api
    import win32security
    win32security.ImpersonateNamedPipeClient(handle)
    try:
        token = win32security.OpenThreadToken(win32api.GetCurrentThread(), 8, True)
        try:
            sid = win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token, win32security.TokenUser)[0])
            elevated = bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
            return sid, elevated
        finally:
            token.Close()
    finally:
        win32security.RevertToSelf()


def serve(core, control=False):
    import pywintypes
    import win32pipe
    import win32security
    sa = pywintypes.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        CONTROL_SDDL if control else STATUS_SDDL, 1)
    handle = win32pipe.CreateNamedPipe(
        CONTROL_PIPE if control else STATUS_PIPE,
        3 | 0x40000000 | 0x00080000,  # DUPLEX, OVERLAPPED, FIRST_PIPE_INSTANCE
        0x8,  # byte pipe, PIPE_REJECT_REMOTE_CLIENTS
        1, MAX_FRAME + 4, MAX_FRAME + 4, 1000, sa)
    try:
        while not core.stop_event.is_set():
            try:
                _io(handle, 'connect', stop=core.stop_event)
                deadline = time.monotonic() + 3
                message = receive(handle, deadline, core.stop_event)
                try:
                    sid, elevated = client_identity(handle)
                    if control:
                        if not elevated:
                            raise PermissionError('Run StayLocked as administrator to start a session.')
                        answer = core.start(message, sid)
                    else:
                        if message != {'op': 'status'}:
                            raise ValueError('The browser connection is read-only.')
                        answer = {'ok': True, 'status': core.snapshot(sid)}
                except Exception as exc:
                    answer = {'ok': False, 'error': str(exc)}
                write(handle, encode(answer), deadline, core.stop_event)
                # Receipt ensures DisconnectNamedPipe cannot discard unread output.
                read_exact(handle, 1, deadline, core.stop_event)
            except (OSError, EOFError, ValueError, pywintypes.error):
                pass  # Broken clients do not affect the session.
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except pywintypes.error:
                    pass
    finally:
        handle.Close()


def request(message, server_pid, control=False, timeout=3):
    import pywintypes
    import win32file
    import win32pipe
    name = CONTROL_PIPE if control else STATUS_PIPE
    deadline = time.monotonic() + timeout
    while True:
        try:
            # Identification-level impersonation: a server may inspect, not use, our token.
            handle = win32file.CreateFile(name, CLIENT_ACCESS, 0, None, 3,
                                          0x40000000 | 0x00100000 | 0x00010000, None)
            break
        except pywintypes.error as exc:
            if exc.winerror not in (2, 231) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    try:
        if win32pipe.GetNamedPipeServerProcessId(handle) != server_pid:
            raise PermissionError('The pipe does not belong to the installed StayLocked service.')
        write(handle, encode(message), deadline)
        try:
            answer = receive(handle, deadline)
        except TimeoutError as exc:
            raise TimeoutError('StayLocked service did not reply. The start request may have been accepted. '
                               'Reopen StayLocked to check its status; do not assume the block is off.') from exc
        write(handle, b'\x01', deadline)
        if answer.get('ok') is not True:
            raise RuntimeError(answer.get('error', 'StayLocked service rejected the request.'))
        return answer
    finally:
        handle.Close()
