"""Legacy permission migration must be narrow and preserve unrelated policy."""
import unittest
from unittest.mock import Mock, patch
from focuslock.service_admin import legacy_acl_entries, ensure_idle, SessionInProgress


class ACL:
    def __init__(self, entries):
        self.entries = entries
    def GetAceCount(self):
        return len(self.entries)
    def GetAce(self, index):
        return self.entries[index]


class LegacyAclTests(unittest.TestCase):
    def test_only_missing_admin_stop_bit_is_added(self):
        entries = [((0, 0), 0xf01ff, 'S-1-5-18'),
                   ((0, 0), 0xf01df, 'S-1-5-32-544'),
                   ((0, 0), 0x2018d, 'S-1-5-4')]
        fixed = legacy_acl_entries(ACL(entries), 0xf01ff, 0x20, str)
        self.assertEqual(fixed, [entries[0], ((0, 0), 0xf01ff, entries[1][2]), entries[2]])
        self.assertEqual(entries[1][1], 0xf01df)

    def test_denies_and_unrecognized_policies_are_never_rewritten(self):
        admin = ((0, 0), 0xf01df, 'S-1-5-32-544')
        for entries in ([((1, 0), 0x20, 'S-1-1-0'), admin],
                        [((0, 0), 0x20004, 'S-1-5-32-544')],
                        [((0, 0), 0xf01df, 'S-1-5-21-123')],
                        [((0, 0), 0xf01ff, 'S-1-5-32-544')],
                        [admin, admin]):
            self.assertIsNone(legacy_acl_entries(ACL(entries), 0xf01ff, 0x20, str))
        self.assertIsNone(legacy_acl_entries(None, 0xf01ff, 0x20, str))

    def test_maintenance_refuses_active_or_unknown_state(self):
        import sys
        from types import SimpleNamespace
        api = SimpleNamespace(SERVICE_STOPPED=1, QueryServiceStatus=lambda _: (0, 4))
        with patch.dict(sys.modules, {'win32service': api}):
            for state in ('ACTIVE', 'STARTING', 'SERVICE_MISSING', None):
                with patch('focuslock.service_client.read_state', return_value={'state': state}):
                    with self.assertRaises(SessionInProgress):
                        ensure_idle(object())
            with patch('focuslock.service_client.read_state', return_value={'state': 'IDLE'}):
                ensure_idle(object())
