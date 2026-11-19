"""Experimental domain-to-IP web guard, owned entirely by the service."""
import ctypes
import queue
import socket
import sys
import threading
import time
from .websites import validate_websites
from .wfp import DynamicFilters, public_ip


def require_admin():
    if sys.platform != 'win32' or not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError('Website filtering requires administrator rights. Exit StayLocked from the tray, '
                              'then launch the installed StayLocked shortcut and accept the Windows UAC prompt.')


def domain_hosts(domains):
    domains = validate_websites(domains)
    if not domains or len(domains) > 20:
        raise ValueError('Select 1–20 websites for an experimental network session.')
    hosts = set(domains)
    for domain in domains:
        if not domain.startswith('www.'):
            hosts.add('www.' + domain)
    return domains, sorted(hosts)


def resolve_host(host):
    rows = socket.getaddrinfo(host, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    addresses = {str(public_ip(row[4][0])) for row in rows}
    if not addresses:
        raise ValueError(f'No public IP addresses found for {host}.')
    return addresses


class DNSJob:
    """Bounded parallel DNS reads. Resolver threads never touch WFP or session state."""
    def __init__(self, hosts, resolver=resolve_host, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + 15
        self.pending = set(hosts)
        self.results = {}
        self.errors = {}
        self.queue = queue.Queue()
        for host in hosts:
            threading.Thread(target=self._resolve, args=(host, resolver), daemon=True).start()

    def _resolve(self, host, resolver):
        try:
            self.queue.put((host, resolver(host), None))
        except Exception as exc:
            self.queue.put((host, None, str(exc)))

    def poll(self):
        while True:
            try:
                host, addresses, error = self.queue.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(host)
            if error is None:
                self.results[host] = addresses
            else:
                self.errors[host] = error
        if self.pending and self.clock() >= self.deadline:
            for host in self.pending:
                self.errors[host] = 'DNS lookup timed out.'
            self.pending.clear()
        return not self.pending


class WebsiteGuard:
    def __init__(self, domains, engine_factory=DynamicFilters, job_factory=DNSJob):
        self.domains, self.hosts = domain_hosts(domains)
        self.engine_factory = engine_factory
        self.job_factory = job_factory
        self.engine = None
        self.job = None
        self.mapping = {}
        self.next_refresh = 0
        self.warning = ''

    def __enter__(self):
        require_admin()
        job = self.job_factory(self.hosts)
        while not job.poll():
            time.sleep(0.05)
        missing = [domain for domain in self.domains if not job.results.get(domain)]
        if missing:
            raise ValueError('Cannot resolve selected websites: ' + ', '.join(missing)
                             + '. Check spelling and Internet access; no session was started.')
        self.engine = self.engine_factory()
        self.engine.__enter__()
        try:
            self._apply(job)
        except BaseException:
            self.engine.__exit__(None, None, None)
            self.engine = None
            raise
        self.next_refresh = time.monotonic() + 30
        return self

    def _apply(self, job):
        addresses = set()
        for host, values in job.results.items():
            addresses.update(values)
        self.engine.add(addresses)
        self.mapping.update({host: sorted(ips) for host, ips in job.results.items()})
        failures = sorted(job.errors)
        self.warning = ('DNS unavailable for: ' + ', '.join(failures)
                        + '. Existing IP filters remain active.') if failures else ''
        print('StayLocked network snapshot:', self.mapping, self.warning, flush=True)

    def tick(self):
        # Never wait for DNS inside the timer loop; expiry is checked every 250 ms.
        if self.job is not None and self.job.poll():
            self._apply(self.job)
            self.job = None
            self.next_refresh = time.monotonic() + 30
        if self.job is None and time.monotonic() >= self.next_refresh:
            self.job = self.job_factory(self.hosts)

    def status(self):
        return {'website_ip_count': len(self.engine.addresses), 'website_warning': self.warning}

    def __exit__(self, *args):
        if self.engine is not None:
            self.engine.__exit__(*args)
            self.engine = None
        # Outstanding DNS threads have no engine reference and cannot recreate filters.
