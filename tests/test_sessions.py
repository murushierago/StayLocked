"""Portable lifecycle tests using fake OS locks/clock; no Windows claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from focuslock.worker import run_session
from focuslock import session
from focuslock.storage import ConfigStore


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.held = []
        self.events = []
        self.checks = 0
        self.request = {'applications': ['a.exe', 'b.exe'], 'minutes': 1,
                        'start_before_ms': 31000}

    def lock(self, name):
        owner = self

        class Lock:
            def __enter__(self):
                owner.held.append(name)
                return self

            def __exit__(self, *args):
                owner.held.remove(name)
        return Lock()

    def publish(self, state, **extra):
        self.events.append((state, list(self.held), extra))

    def check(self, targets):
        self.checks += 1

    def sleep(self, seconds):
        # Simulate a sleep/hibernate jump exceeding the whole duration.
        self.now += 120000

    def run_request(self, **overrides):
        kwargs = dict(lock_factory=self.lock, validate=lambda xs: list(xs),
                      check=self.check, clock=lambda: self.now, sleep=self.sleep)
        kwargs.update(overrides)
        run_session(self.request, self.publish, **kwargs)

    def test_expiry_and_sleep_release_before_ended(self):
        self.run_request()
        self.assertEqual(self.checks, 2)
        self.assertEqual(self.events[0][0:2], ('ACTIVE', ['a.exe', 'b.exe']))
        self.assertEqual(self.events[0][2]['deadline_ms'], 61000)
        self.assertEqual(self.events[-1][0:2], ('ENDED', []))
        self.assertEqual(self.held, [])

    def test_partial_acquisition_rolls_back(self):
        def lock(name):
            if name == 'b.exe':
                raise OSError('occupied')
            return self.lock(name)
        with self.assertRaises(OSError):
            self.run_request(lock_factory=lock)
        self.assertEqual(self.held, [])
        self.assertEqual(self.events, [])

    def test_running_target_prevents_any_locks(self):
        def check(targets):
            raise ValueError('running')
        with self.assertRaises(ValueError):
            self.run_request(check=check)
        self.assertEqual(self.held, [])
        self.assertEqual(self.events, [])

    def test_post_acquire_running_check_rolls_back(self):
        def check(targets):
            self.checks += 1
            if self.checks == 2:
                raise ValueError('started during preparation')
        with self.assertRaises(ValueError):
            self.run_request(check=check)
        self.assertEqual(self.held, [])
        self.assertEqual(self.events, [])

    def test_status_write_failure_releases_all(self):
        def publish(*args, **kwargs):
            raise PermissionError('status file unavailable')
        self.publish = publish
        with self.assertRaises(PermissionError):
            self.run_request()
        self.assertEqual(self.held, [])

    def test_expired_start_cannot_activate_later(self):
        self.now = 40000
        with self.assertRaises(ValueError):
            self.run_request()
        self.assertEqual(self.events, [])
        self.assertEqual(self.held, [])

    def test_elapsed_during_preparation_rolls_back(self):
        def check(targets):
            self.now += 20000
        with self.assertRaises(ValueError):
            self.run_request(check=check)
        self.assertEqual(self.events, [])
        self.assertEqual(self.held, [])

    def test_durations(self):
        for bad in ['', '0', '-1', '721', 'NaN', '1.5']:
            with self.assertRaises(ValueError):
                session.parse_minutes(bad)
        self.assertEqual(session.parse_minutes(' 90 '), 90)
        self.assertEqual(session.remaining_seconds(2000, 1001), 1)
        self.assertEqual(session.remaining_seconds(2000, 3000), 0)
        self.assertEqual(session.format_remaining(3661), '01:01:01')


class StateTests(unittest.TestCase):
    def test_reconnect_reboot_and_pid_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            session.write_json(folder / 'session.json', {
                'state': 'ACTIVE', 'session_id': 'example', 'pid': 123,
                'process_identity': 999, 'deadline_ms': 61000, 'applications': ['a.exe']})
            with patch.object(session, 'data_directory', return_value=folder), \
                 patch.object(session.winapi, 'worker_present', return_value=True) as present, \
                 patch.object(session.winapi, 'process_identity', return_value=999) as identity, \
                 patch.object(session.winapi, 'tick_ms', return_value=31000):
                self.assertEqual(session.read_state()['remaining_seconds'], 30)
                # Dead worker/reboot: never resurrect an on-disk ACTIVE snapshot.
                present.return_value = False
                self.assertEqual(session.read_state()['state'], 'INTERRUPTED')
                present.return_value = True
                identity.return_value = 1000
                self.assertEqual(session.read_state()['state'], 'STARTING')

    def test_old_config_compatible_and_failed_save_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / 'config.json')
            items = [r'C:\Apps\Steam\steam.exe']
            store.save(items)
            self.assertEqual(store.load(), items)
            with patch('focuslock.storage.os.replace', side_effect=PermissionError):
                with self.assertRaises(PermissionError):
                    store.save([])
            self.assertEqual(store.load(), items)


if __name__ == '__main__':
    unittest.main()
