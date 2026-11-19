"""Domain validation only; this module does not enforce network restrictions."""
import ipaddress
import re
from urllib.parse import urlsplit


def normalize_domain(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Enter a domain or an HTTP/HTTPS URL.')
    value = value.strip()
    if any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        raise ValueError('Whitespace and backslashes are not allowed.')
    try:
        parts = urlsplit(value if '://' in value else 'https://' + value)
        if parts.scheme not in ('http', 'https') or parts.username is not None or parts.password is not None:
            raise ValueError('Use an HTTP/HTTPS domain without login details.')
        if parts.port is not None:
            raise ValueError('Enter a domain without a port.')
        domain = (parts.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f'Invalid website: {exc}') from exc
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError('Enter a domain, not an IP address.')
    labels = domain.split('.')
    if (len(domain) > 253 or len(labels) < 2 or domain.endswith('.localhost')
            or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
            or labels[-1].isdigit()):
        raise ValueError('Enter a valid public-style domain, e.g. youtube.com.')
    return domain


def validate_websites(items):
    if not isinstance(items, list):
        raise ValueError('Websites must be a list.')
    result = [normalize_domain(item) for item in items]
    if len(set(result)) != len(result):
        raise ValueError('Duplicate website.')
    return result
