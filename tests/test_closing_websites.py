import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from focuslock.closing import close_selected
from focuslock.websites import normalize_domain
from focuslock.storage import ConfigStore
from focuslock.worker import run_session


class ClosingTests(unittest.TestCase):
    def test_not_running_sends_nothing(self):
        send = Mock()
        close_selected([], send=send, check=lambda _: None)
        send.assert_not_called()

    def test_normal_exit_sends_once(self):
        send = Mock()
        check = Mock(side_effect=[ValueError('running'), ValueError('running'), None])
        close_selected(['test.exe'], send=send, check=check, sleep=lambda _: None)
        send.assert_called_once_with(['test.exe'])

    def test_refusal_times_out_without_retrying_close(self):
        send = Mock()
        with self.assertRaisesRegex(ValueError, 'stayed open'):
            close_selected([], send=send, check=Mock(side_effect=ValueError('running')),
                           clock=Mock(side_effect=[0, 21]), sleep=lambda _: None)
        send.assert_called_once()

    def test_verification_failure_never_sends(self):
        send = Mock()
        with self.assertRaises(OSError):
            close_selected([], send=send, check=Mock(side_effect=OSError('tasklist failed')))
        send.assert_not_called()

    def test_close_failure_prevents_locks_and_active(self):
        locks = Mock()
        publish = Mock()
        with self.assertRaises(ValueError):
            run_session({'minutes': 1, 'applications': ['test.exe'], 'start_before_ms': 60000,
                         'close_running': True}, publish, validate=lambda x: x,
                        clock=lambda: 0, lock_factory=locks,
                        closer=Mock(side_effect=ValueError('refused')))
        locks.assert_not_called()
        self.assertEqual([c.args[0] for c in publish.call_args_list], ['STARTING'])


class WebsiteTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_domain(' HTTPS://YouTube.COM/watch?v=test '), 'youtube.com')
        self.assertEqual(normalize_domain('пример.рф'), 'xn--e1afmkfd.xn--p1ai')
        self.assertEqual(normalize_domain('www.reddit.com'), 'www.reddit.com')

    def test_reject_ambiguous_inputs(self):
        for value in ['', 'localhost', '127.0.0.1', '*.example.com', 'https://u:p@example.com',
                      'example.com:443', 'bad domain.com', 'ftp://example.com', '-bad.com', 'x..com']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_domain(value)

    def test_old_config_migration_preserves_both_lists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            apps = [r'C:\Apps\example.exe']
            path.write_text(json.dumps({'schema_version': 1, 'applications': apps}))
            store = ConfigStore(path)
            self.assertEqual(store.load_websites(), [])
            store.save_websites(['youtube.com'])
            self.assertEqual(store.load(), apps)
            store.save([])
            self.assertEqual(store.load_websites(), ['youtube.com'])
            self.assertEqual(json.loads(path.read_text())['schema_version'], 3)

    def test_corrupt_websites_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            original = json.dumps({'schema_version': 2, 'applications': [], 'websites': 'bad'})
            path.write_text(original)
            with self.assertRaises(ValueError):
                ConfigStore(path).save([])
            self.assertEqual(path.read_text(), original)
