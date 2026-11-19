"""Browser bridge: exposes status only, never accepts start/stop or file commands."""
import json
import os
import struct
import sys
import time
from .storage import data_directory
from .service_client import read_state

MAX_FRAME = 65536


def read_exact(stream, count):
    chunks = bytearray()
    while len(chunks) < count:
        data = stream.read(count - len(chunks))
        if not data:
            if not chunks:
                return None
            raise ValueError('Truncated native message.')
        chunks.extend(data)
    return bytes(chunks)


def receive(stream):
    header = read_exact(stream, 4)
    if header is None:
        return None
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError('Invalid native message size.')
    payload = read_exact(stream, size)
    if payload is None:
        raise ValueError('Truncated native message.')
    return json.loads(payload.decode('utf-8'))


def send(stream, value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_FRAME:
        raise ValueError('Status message too large.')
    stream.write(struct.pack('<I', len(data)) + data)
    stream.flush()


def snapshot(state):
    kind = state.get('state', 'IDLE')
    if kind == 'ACTIVE':
        from .websites import validate_websites
        domains = validate_websites(state.get('websites', []))
        if state.get('mode') == 'until_reboot':
            return {'protocol': 2, 'state': 'active', 'sessionId': state.get('session_id', ''),
                    'domains': domains, 'mode': 'until_reboot', 'remainingSeconds': 15}
        remaining = state.get('remaining_seconds', 0)
        if type(remaining) is not int or not 0 <= remaining <= 43200:
            raise ValueError('Invalid timer state.')
        return {'protocol': 1, 'state': 'active', 'sessionId': state.get('session_id', ''),
                'domains': domains, 'remainingSeconds': remaining}
    if kind == 'SERVICE_MISSING':
        return {'protocol': 2, 'state': 'error', 'message': state.get('message', 'Install the Windows service.')}
    if kind == 'STARTING':
        return {'protocol': 1, 'state': 'preparing'}
    return {'protocol': 1, 'state': 'idle', 'domains': [], 'remainingSeconds': 0}


def serve(source, destination, get_state=read_state):
    while True:
        message = receive(source)
        if message is None:
            return
        if message != {'type': 'get_state'}:
            send(destination, {'protocol': 1, 'state': 'error', 'message': 'Only get_state is supported.'})
            continue
        try:
            response = snapshot(get_state())
        except Exception as exc:
            response = {'protocol': 1, 'state': 'error', 'message': str(exc)}
        send(destination, response)


def allowed_caller(args):
    from .extension_setup import EXTENSION_ID, FIREFOX_ID
    if args and args[0] == f'chrome-extension://{EXTENSION_ID}/':
        return True
    # Firefox supplies manifest path, then the stable add-on ID.
    return len(args) == 2 and args[1] == FIREFOX_ID and args[0].lower().endswith('.json')


def main():
    if sys.platform != 'win32':
        return 1
    try:
        if not allowed_caller(sys.argv[1:]):
            return 1
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        last_heartbeat = 0.0
        def connected_state():
            nonlocal last_heartbeat
            state = read_state()
            now = time.monotonic()
            if now - last_heartbeat >= 2:
                try:
                    (data_directory() / 'bridge-heartbeat').touch()
                    last_heartbeat = now
                except OSError:
                    pass  # Optional setup indicator must never break blocking.
            return state
        from .winapi import InstallationMarker
        with InstallationMarker():
            serve(sys.stdin.buffer, sys.stdout.buffer, connected_state)
        return 0
    except (BrokenPipeError, EOFError):
        return 0
    except Exception as exc:
        print(f'StayLocked native bridge: {exc}', file=sys.stderr)
        return 1
