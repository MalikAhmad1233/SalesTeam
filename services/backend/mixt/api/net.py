"""Client address resolution behind trusted proxies.

``X-Forwarded-For`` is only believed when the direct peer is a trusted proxy
(``MIXT_TRUSTED_PROXIES``). The list is read right to left, skipping trusted hops; the first address
that is not a trusted proxy is the client. A client can prepend anything it likes to the header,
but it cannot get past the proxy's own appended entry, so it cannot pick its own address.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import HTTPConnection

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _networks(entries: tuple[str, ...]) -> tuple[Network, ...]:
    return tuple(ipaddress.ip_network(e, strict=False) for e in entries)


def _parse(value: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted(address: IPAddress, networks: tuple[Network, ...]) -> bool:
    return any(address in network for network in networks)


def resolve_client_ip(request: HTTPConnection, trusted_proxies: list[str]) -> str | None:
    peer = _parse(request.client.host) if request.client else None
    if peer is None:
        return None
    networks = _networks(tuple(trusted_proxies))
    if not _trusted(peer, networks):
        return str(peer)
    hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        address = _parse(hop)
        if address is None:
            return str(peer)  # malformed entry: do not guess past it
        if not _trusted(address, networks):
            return str(address)
    return str(peer)
