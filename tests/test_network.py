import ctypes as c
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, MagicMock, patch
from focuslock import wfp, network
from focuslock.worker import run_session


class FilterTests(unittest.TestCase):
    def test_x64_sdk_layout(self):
        if c.sizeof(c.c_void_p) != 8:
            self.skipTest('x64 ABI test')
        for cls, size in [(wfp.Filter, 200), (wfp.Session, 72), (wfp.Condition, 40), (wfp.Sublayer, 72)]:
            self.assertEqual(c.sizeof(cls), size)

    def test_ipv4_filters_are_exact_ip_and_web_port(self):
        f, cond, backing = wfp.make_filter('8.8.8.8', 443, wfp.GUID())
        self.assertEqual(f.count, 2)
        self.assertEqual(f.flags, 0)
        self.assertEqual(f.action.type, 0x1001)
        self.assertEqual(bytes(f.layer), bytes(wfp.V4_LAYER))
        self.assertEqual(cond[0].value.type, 3)
        self.assertEqual(cond[0].value.value.u32, 0x08080808)
        self.assertEqual(cond[1].value.value.u16, 443)
        self.assertEqual(cond[1].value.type, 2)
        self.assertIsNone(backing)

    def test_ipv6_bytes_stay_alive(self):
        f, cond, backing = wfp.make_filter('2606:4700:4700::1111', 80, wfp.GUID())
        self.assertEqual(bytes(f.layer), bytes(wfp.V6_LAYER))
        self.assertEqual(cond[0].value.type, 11)
        self.assertEqual(c.string_at(cond[0].value.value.pointer, 16), bytes(backing))

    def test_never_filters_local_addresses_or_arbitrary_ports(self):
        for ip in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '::1', '224.0.0.1', '0.0.0.0', 'fe80::1']:
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                wfp.make_filter(ip, 443, wfp.GUID())
        with self.assertRaises(ValueError):
            wfp.make_filter('8.8.8.8', 53, wfp.GUID())

    def test_failed_filter_batch_aborts_without_marking_installed(self):
        engine = wfp.DynamicFilters()
        engine.api = Mock()
        engine._call = Mock(side_effect=[None, OSError('add failed')])
        with self.assertRaises(OSError):
            engine.add(['8.8.8.8'])
        engine.api.FwpmTransactionAbort0.assert_called_once()
        self.assertEqual(engine.addresses, set())

    def test_no_empty_or_unrestricted_batch(self):
        engine = wfp.DynamicFilters()
        engine._call = Mock()
        engine.add([])
        engine._call.assert_not_called()


class NetworkTests(unittest.TestCase):
    def test_domain_expansion_is_limited_and_explicit(self):
        domains, hosts = network.domain_hosts(['youtube.com', 'www.reddit.com'])
        self.assertEqual(hosts, ['www.reddit.com', 'www.youtube.com', 'youtube.com'])
        with self.assertRaises(ValueError):
            network.domain_hosts([f'a{i}.com' for i in range(21)])

    def test_unresolvable_selected_domain_never_opens_engine(self):
        job = Mock(results={}, errors={'youtube.com': 'DNS unavailable'})
        job.poll.return_value = True
        factory = Mock()
        with patch.object(network, 'require_admin'), self.assertRaises(ValueError):
            with network.WebsiteGuard(['youtube.com'], factory, lambda hosts: job):
                pass
        factory.assert_not_called()

    def test_partial_setup_closes_dynamic_engine(self):
        job = Mock(results={'youtube.com': {'8.8.8.8'}}, errors={})
        job.poll.return_value = True
        engine = MagicMock()
        engine.add.side_effect = OSError('filter failed')
        with patch.object(network, 'require_admin'), self.assertRaises(OSError):
            with network.WebsiteGuard(['youtube.com'], lambda: engine, lambda hosts: job):
                pass
        engine.__exit__.assert_called_once()


class WorkerWebsiteTests(unittest.TestCase):
    def test_website_only_expiry_releases_before_ended(self):
        held = []
        events = []
        now = [0]
        guard = Mock()
        guard.status.return_value = {'website_ip_count': 2, 'website_warning': ''}

        @contextmanager
        def factory(domains):
            self.assertEqual(domains, ['youtube.com'])
            held.append('network')
            try:
                yield guard
            finally:
                held.clear()

        def sleep(seconds):
            now[0] += 61000

        def publish(state, **kwargs):
            events.append((state, list(held), kwargs))

        check, validate = Mock(), Mock()
        run_session({'applications': [], 'websites': ['youtube.com'], 'minutes': 1,
                     'start_before_ms': 60000}, publish, clock=lambda: now[0], sleep=sleep,
                    check=check, validate=validate, network_factory=factory)
        validate.assert_not_called()
        check.assert_not_called()
        self.assertEqual(events[-1][0:2], ('ENDED', []))
        self.assertEqual(events[1][0:2], ('ACTIVE', ['network']))
        self.assertEqual(events[1][2]['websites'], ['youtube.com'])

    def test_network_setup_failure_does_not_close_apps(self):
        closer = Mock()
        with self.assertRaises(OSError):
            run_session({'applications': ['app'], 'websites': ['youtube.com'], 'minutes': 1,
                         'force_running': True, 'start_before_ms': 60000}, Mock(),
                        validate=lambda x: x, clock=lambda: 0, force_closer=closer,
                        network_factory=Mock(side_effect=OSError('WFP refused')))
        closer.assert_not_called()

    def test_app_failure_rolls_back_network(self):
        exited = []

        @contextmanager
        def factory(domains):
            try:
                yield Mock()
            finally:
                exited.append(True)

        with self.assertRaises(OSError):
            run_session({'applications': ['app'], 'websites': ['youtube.com'], 'minutes': 1,
                         'force_running': True, 'start_before_ms': 60000}, Mock(),
                        validate=lambda x: x, clock=lambda: 0,
                        force_closer=Mock(side_effect=OSError('cannot close')),
                        network_factory=factory)
        self.assertEqual(exited, [True])
