"""Configuration for the Similarweb Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    SIMILARWEB_PROXY  proxy URL for similarweb.com, e.g. http://user:pass@host:port
                      (default: none — direct). Similarweb's firewall allows
                      about 6 requests per IP address, then asks for a
                      challenge. For more than a handful of calls, set this
                      to a ROTATING residential proxy: every new connection
                      gets a new IP, and the scraper opens a new connection
                      every SIMILARWEB_REQUESTS_PER_EXIT calls (or right
                      after a block), so you never hit the limit.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# similarweb.com allows ~6 requests per IP: switch to a new connection (a new
# IP behind a rotating proxy) after this many calls.
SIMILARWEB_REQUESTS_PER_EXIT = int(os.environ.get("SIMILARWEB_REQUESTS_PER_EXIT", "5"))
# New connections tried per call after a block before giving up.
SIMILARWEB_MAX_ATTEMPTS = int(os.environ.get("SIMILARWEB_MAX_ATTEMPTS", "10"))
# The hosted version can fall back to a real browser; this package stays
# plain HTTP (no browser to install), so the fallback is off.
SIMILARWEB_BROWSER_FALLBACK = False
SIMILARWEB_BROWSER_CONCURRENCY = 1
# Parallel lookups in /websites/compare.
SIMILARWEB_COMPARE_WORKERS = 5


def similarweb_proxy():
    """The proxy for similarweb.com requests (None = direct)."""
    return os.environ.get("SIMILARWEB_PROXY") or None


def similarweb_similarsites_proxy():
    """similarsites.com has no firewall: direct first (SIMILARWEB_PROXY is
    the retry)."""
    return None
