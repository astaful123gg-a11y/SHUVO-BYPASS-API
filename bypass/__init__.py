"""Bypass modules registry.

Add a new site: write bypass/<site>.py with an async or sync resolver
and register it in RESOLVERS below.
"""
import asyncio
import inspect
from urllib.parse import urlparse

from .linksgo import bypass_linksgo
from .earnlinks import bypass_earnlinks
from .vplink import VPLinkBypass


def _vplink(url: str, wait: float = 25.0) -> str:
    return VPLinkBypass(wait=wait, verbose=True).resolve(url)


def _urlking(url: str) -> str:
    # imported lazily: needs playwright + a non-datacenter IP (Cloudflare)
    from .urlking import bypass_urlking
    return bypass_urlking(url)


# domain (without www) -> resolver
RESOLVERS = {
    "linksgo.in": bypass_linksgo,
    "earnlinks.in": bypass_earnlinks,
    "vplink.in": _vplink,
    "viku.urlking.in": _urlking,
    "urlking.in": _urlking,
}

SUPPORTED = sorted(RESOLVERS)


def _host(url: str) -> str:
    h = (urlparse(url).netloc or "").lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def get_resolver(url: str):
    host = _host(url)
    if host in RESOLVERS:
        return RESOLVERS[host]
    for domain, fn in RESOLVERS.items():
        if host.endswith("." + domain):
            return fn
    return None


async def bypass(url: str) -> str:
    """Resolve any supported shortlink to its final destination."""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    fn = get_resolver(url)
    if fn is None:
        raise ValueError(
            f"Unsupported site '{_host(url)}'. Supported: {', '.join(SUPPORTED)}"
        )
    if inspect.iscoroutinefunction(fn):
        return await fn(url)
    return await asyncio.to_thread(fn, url)
