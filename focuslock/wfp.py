"""Windows x64 WFP dynamic-session IP filters; no persistent firewall changes.

SDK structures use fixed-width integers (Windows DWORD is 32 bits).
Every filter is restricted to ONE public remote IP AND ONE web port.
"""
import ctypes as c
import ipaddress
import sys
import uuid

U8, U16, U32, U64 = c.c_uint8, c.c_uint16, c.c_uint32, c.c_uint64
P = c.c_void_p


class GUID(c.Structure):
    _fields_ = [('a', U32), ('b', U16), ('d', U16), ('tail', U8 * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(str(value)).bytes_le)


class Display(c.Structure):
    _fields_ = [('name', c.c_wchar_p), ('description', c.c_wchar_p)]


class Blob(c.Structure):
    _fields_ = [('size', U32), ('data', P)]


class ValueUnion(c.Union):
    _fields_ = [('u8', U8), ('u16', U16), ('u32', U32), ('pointer', P)]


class Value(c.Structure):
    _fields_ = [('type', U32), ('value', ValueUnion)]


class Condition(c.Structure):
    _fields_ = [('field', GUID), ('match', U32), ('value', Value)]


class Action(c.Structure):
    _fields_ = [('type', U32), ('key', GUID)]


class Context(c.Union):
    _fields_ = [('raw', U64), ('key', GUID)]


class Filter(c.Structure):
    _fields_ = [('key', GUID), ('display', Display), ('flags', U32),
                ('provider', P), ('provider_data', Blob), ('layer', GUID),
                ('sublayer', GUID), ('weight', Value), ('count', U32),
                ('conditions', c.POINTER(Condition)), ('action', Action),
                ('context', Context), ('reserved', P), ('id', U64), ('effective_weight', Value)]


class Session(c.Structure):
    _fields_ = [('key', GUID), ('display', Display), ('flags', U32),
                ('wait_ms', U32), ('pid', U32), ('sid', P), ('username', c.c_wchar_p),
                ('kernel', c.c_int32)]


class Sublayer(c.Structure):
    _fields_ = [('key', GUID), ('display', Display), ('flags', U32),
                ('provider', P), ('provider_data', Blob), ('weight', U16)]


V4_LAYER = GUID.parse('c38d57d1-05a7-4c33-904f-7fbceee60e82')
V6_LAYER = GUID.parse('4a72393b-319f-44bc-84c3-ba54dcb3b6b4')
REMOTE_IP = GUID.parse('b235ae9a-1d64-49b8-a44c-5ff3d9095045')
REMOTE_PORT = GUID.parse('c35a604d-d22b-4e1a-91b4-68f674ee674b')


def public_ip(value):
    address = ipaddress.ip_address(value)
    if (not address.is_global or address.is_multicast or address.is_unspecified
            or getattr(address, 'ipv4_mapped', None) is not None):
        raise ValueError(f'Only public Internet addresses may be filtered: {address}')
    return address


def make_filter(ip, port, sublayer):
    address = public_ip(ip)
    if port not in (80, 443):
        raise ValueError('Only web ports 80 and 443 are supported.')
    conditions = (Condition * 2)()
    conditions[0].field = REMOTE_IP
    buffer = None
    if address.version == 4:
        conditions[0].value.type = 3  # FWP_UINT32; IPv4 value in host byte order
        conditions[0].value.value.u32 = int(address)
    else:
        buffer = (U8 * 16).from_buffer_copy(address.packed)
        conditions[0].value.type = 11  # FWP_BYTE_ARRAY16_TYPE
        conditions[0].value.value.pointer = c.cast(buffer, P)
    conditions[1].field = REMOTE_PORT
    conditions[1].value.type = 2  # FWP_UINT16, host byte order
    conditions[1].value.value.u16 = port
    rule = Filter()
    rule.key = GUID.parse(uuid.uuid4())
    rule.display.name = f'StayLocked temporary web block: {address}:{port}'
    rule.layer = V4_LAYER if address.version == 4 else V6_LAYER
    rule.sublayer = sublayer
    rule.weight.type = 0  # FWP_EMPTY: Windows assigns a weight
    rule.count = 2
    rule.conditions = conditions
    rule.action.type = 0x1001  # FWP_ACTION_BLOCK | terminating flag
    # Keep condition storage alive through FwpmFilterAdd0.
    return rule, conditions, buffer


class DynamicFilters:
    def __init__(self):
        self.handle = P()
        self.addresses = set()
        self.key = GUID.parse(uuid.uuid4())
        self.api = None

    def _call(self, name, *args):
        code = getattr(self.api, name)(*args)
        if code:
            hint = ' Run StayLocked as administrator.' if code == 5 else ''
            raise OSError(f'{name} failed: 0x{code:08X}.{hint}')

    def __enter__(self):
        if sys.platform != 'win32' or c.sizeof(P) != 8:
            raise OSError('Website filtering requires 64-bit Python on Windows 10/11.')
        self.api = c.WinDLL('fwpuclnt.dll')
        signatures = {
            'FwpmEngineOpen0': [c.c_wchar_p, U32, P, c.POINTER(Session), c.POINTER(P)],
            'FwpmEngineClose0': [P],
            'FwpmSubLayerAdd0': [P, c.POINTER(Sublayer), P],
            'FwpmTransactionBegin0': [P, U32],
            'FwpmTransactionCommit0': [P],
            'FwpmTransactionAbort0': [P],
            'FwpmFilterAdd0': [P, c.POINTER(Filter), P, c.POINTER(U64)],
        }
        for name, arguments in signatures.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = arguments, U32
        session = Session()
        session.display.name = 'StayLocked temporary focus session'
        session.flags = 1  # FWPM_SESSION_FLAG_DYNAMIC; NEVER persistent or boot-time
        session.wait_ms = 3000
        self._call('FwpmEngineOpen0', None, 10, None, c.byref(session), c.byref(self.handle))
        try:
            sublayer = Sublayer()
            sublayer.key = self.key
            sublayer.display.name = 'StayLocked temporary website filters'
            sublayer.weight = 0x100
            self._call('FwpmSubLayerAdd0', self.handle, c.byref(sublayer), None)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def add(self, addresses):
        candidate = {str(public_ip(ip)) for ip in addresses} - self.addresses
        if len(self.addresses | candidate) > 2048:
            raise ValueError('Too many IP addresses for this experimental session (maximum 2048).')
        if not candidate:
            return
        self._call('FwpmTransactionBegin0', self.handle, 0)
        try:
            for address in sorted(candidate):
                for port in (80, 443):
                    rule, conditions, backing = make_filter(address, port, self.key)
                    identifier = U64()
                    self._call('FwpmFilterAdd0', self.handle, c.byref(rule), None, c.byref(identifier))
            self._call('FwpmTransactionCommit0', self.handle)
        except BaseException:
            self.api.FwpmTransactionAbort0(self.handle)
            raise
        self.addresses.update(candidate)

    def __exit__(self, *unused):
        if self.handle.value:
            self._call('FwpmEngineClose0', self.handle)
            self.handle = P()
