"""Similarweb transport: plain curl_cffi (Chrome TLS) through rotating
residential exits, with a headful patchright load as the last resort.

Surfaces (all logged-out, validated 2026-09-25):

  api_json(path, params)   www.similarweb.com/api/* — the site's own JSON API:
                           website/<domain>, gettopwebsites(+trends), topapps
                           (+trends), marketshare, get-shopper-data, universal
                           (autocomplete), autocomplete/apps-sites-preview
                           (search), ai-traffic/prompts/<domain>
  page_data(path)          an SSR page -> window.__APP_DATA__.layout.data, for
                           the pages with no JSON twin: /app/<store>/<id>/,
                           /company/<domain>/, /ai-traffic/<domain>/,
                           /website/<domain>/competitors/, /technology/<slug>/,
                           /top-websites/ (filter lists), /serp/
  similarsites(domain)     www.similarsites.com/api/site/<domain> (no WAF)

AWS WAF (CloudFront) sits in front of www.similarweb.com:
  * no `aws-waf-token` cookie -> HTTP 202 + challenge.js (gokuProps);
    an EMPTY `aws-waf-token=` cookie passes, on every path above.
  * a rate rule allows ~6 requests per exit IP whatever the pacing, then
    answers 202; an IP that keeps hammering gets a hard 403 ("Request
    blocked", 919 bytes) for hours; a stale token gets 405 (CAPTCHA).
So each call takes an exit from a small shared pool of sticky residential
ports, and an exit is retired after config.SIMILARWEB_REQUESTS_PER_EXIT
calls or on its first 202 / 403 / 405. A call is retried on fresh exits up
to config.SIMILARWEB_MAX_ATTEMPTS times; when every attempt was challenged,
one headful patchright Chrome on a fresh exit solves the challenge on an
open page and repeats the call as an in-page fetch.

Not usable: data.similarweb.com/api/v1/data (the legacy extension JSON)
answers 403 to curl and to a real Chrome from every exit tried.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  SimilarwebUpstreamError  transport failure / 5xx / unexpected body — retryable
  SimilarwebBlocked        WAF challenge / block on every exit        — retryable
  SimilarwebBadRequest     upstream 400 (unknown filter combination)  — never retried
  SimilarwebNotFound       upstream 404 / "We Have No Data" page      — never retried
"""
import json
import os
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.similarweb.com"
SIMILARSITES = "https://www.similarsites.com"
IMPERSONATE = "chrome"
TIMEOUT = (10, 35)          # (connect, read): a dead exit fails fast

JSON_HEADERS = {"accept": "application/json, text/plain, */*", "accept-language": "en-US,en;q=0.9",
                "referer": SITE + "/"}
PAGE_HEADERS = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9"}
# The whole bypass: an empty token cookie is not challenged, a missing one is.
WAF_COOKIES = {"aws-waf-token": ""}

STATE_ANCHOR = "window.__APP_DATA__"
NO_DATA_MARKER = "<title>We Have No Data"
BLOCK_STATUSES = (202, 403, 405)
BROWSER_WARMUP_PATH = "/top-websites/"      # an open page to clear the challenge on
BROWSER_SETTLE_TIMEOUT = 25


class SimilarwebUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected body — retryable."""


class SimilarwebBlocked(SimilarwebUpstreamError, Blocked):
    """AWS WAF challenge (202), CAPTCHA (405) or block (403) — retryable on a new exit."""


class SimilarwebBadRequest(BadRequest):
    """Similarweb answered 400 (a filter combination it does not serve)."""


class SimilarwebNotFound(NotFound):
    """Similarweb has no data for the entity — never retried."""


def dump_debug(name, text):
    """Write a raw response to $SIMILARWEB_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("SIMILARWEB_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


# ---- exit pool ---------------------------------------------------------------------
# A shared pool of sticky exits, each with a use budget. Any thread may take
# any exit that still has budget; an exit leaves the pool when spent or on its
# first block. curl handles are per thread (never shared), keyed by proxy URL.

class _Exit:
    """One exit: its proxy URL and a serial `key` for its curl sessions, so
    a new exit always opens a new tunnel — even when every exit shares ONE
    rotating-proxy URL (a fresh tunnel = a fresh IP there)."""
    __slots__ = ("proxy", "used", "key")
    _serial = 0
    _serial_lock = threading.Lock()

    def __init__(self, proxy):
        self.proxy = proxy
        self.used = 0
        with _Exit._serial_lock:
            _Exit._serial += 1
            self.key = f"{_Exit._serial}:{proxy or 'direct'}"


_pool_lock = threading.Lock()
_pool = []          # exits with budget left
_local = threading.local()


def _budget():
    return max(1, int(config.SIMILARWEB_REQUESTS_PER_EXIT))


def _take_exit(fresh=False):
    """An exit with budget left (reserving one use), or a new one."""
    with _pool_lock:
        if not fresh:
            for ex in _pool:
                if ex.used < _budget():
                    ex.used += 1
                    if ex.used >= _budget():
                        _pool.remove(ex)
                    return ex
        ex = _Exit(config.similarweb_proxy())
        ex.used = 1
        if _budget() > 1:
            _pool.append(ex)
        return ex


def _retire(ex):
    with _pool_lock:
        if ex in _pool:
            _pool.remove(ex)
    _drop_session(ex.key)


def _sessions():
    store = getattr(_local, "sessions", None)
    if store is None:
        store = _local.sessions = OrderedDict()
    return store


def _session(ex):
    """The calling thread's curl session for one exit (small LRU per thread)."""
    from curl_cffi import requests as curl_requests
    store = _sessions()
    key, proxy = ex.key, ex.proxy
    sess = store.get(key)
    if sess is None:
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        store[key] = sess
        while len(store) > 4:
            _, old = store.popitem(last=False)
            try:
                old.close()
            except Exception:
                pass
    else:
        store.move_to_end(key)
    return sess


def _drop_session(key):
    sess = _sessions().pop(key, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


# ---- classification ------------------------------------------------------------------

def classify(status, text, label):
    """Raise the failure a response represents, or return its text."""
    text = text or ""
    if status in BLOCK_STATUSES and len(text) < 5000:
        dump_debug("blocked", text)
        raise SimilarwebBlocked(f"HTTP {status} (AWS WAF) on {label}")
    if status in (204, 404) or NO_DATA_MARKER in text[:3000]:
        raise SimilarwebNotFound(f"similarweb has no data for {label}")
    if status == 400:
        raise SimilarwebBadRequest(f"similarweb does not serve this filter combination ({label})")
    if status == 429:
        raise SimilarwebBlocked(f"HTTP 429 on {label}")
    if status != 200:
        raise SimilarwebUpstreamError(f"HTTP {status} on {label}")
    return text


def _curl_once(url, headers, label, fresh):
    ex = _take_exit(fresh=fresh)
    sess = _session(ex)
    try:
        resp = sess.get(url, headers=headers, cookies=WAF_COOKIES, timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        _retire(ex)
        raise SimilarwebUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
    try:
        return classify(resp.status_code, resp.text, label)
    except SimilarwebBlocked:
        _retire(ex)
        raise


# ---- browser fallback ----------------------------------------------------------------

_browser_slots = threading.BoundedSemaphore(max(1, int(config.SIMILARWEB_BROWSER_CONCURRENCY)))


def _browser_get(url, headers, label):
    """One headful patchright Chrome on a fresh exit: load an open page (the
    WAF challenge.js runs and mints a real token), then GET `url` as an
    in-page fetch with that token. Returns the body text."""
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    driver = None
    with _browser_slots:
        try:
            with create_scope():
                driver = PatchrightDriver(proxy_url=config.similarweb_proxy(), headless=False)
            driver.nav(SITE + BROWSER_WARMUP_PATH, mode="blocked", challenge_markers=("gokuProps",))
            deadline = time.monotonic() + BROWSER_SETTLE_TIMEOUT
            while time.monotonic() < deadline:
                if any(c.get("name") == "aws-waf-token" and c.get("value") for c in driver.cookies()):
                    break
                time.sleep(1.0)
            resp = driver.get(url, headers={k: v for k, v in headers.items() if k != "referer"},
                              referrer=SITE + "/")
            if resp.error and not resp.status_code:
                raise SimilarwebUpstreamError(f"browser fetch failed on {label}: {resp.error}")
            return classify(resp.status_code, resp.text, label)
        finally:
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    pass


# ---- public fetchers -------------------------------------------------------------------

def get_text(path, params=None, headers=None, label=None):
    """GET a www.similarweb.com path through the exit pool -> body text."""
    from urllib.parse import urlencode
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    url = SITE + path + (("?" + urlencode(query)) if query else "")
    label = label or path
    headers = headers or JSON_HEADERS
    last = None
    blocked_only = True
    attempts = max(1, int(config.SIMILARWEB_MAX_ATTEMPTS))
    for attempt in range(1, attempts + 1):
        try:
            return _curl_once(url, headers, label, fresh=attempt > 1)
        except SimilarwebBlocked as e:
            last = e
        except SimilarwebUpstreamError as e:
            last = e
            blocked_only = False
        print(f"similarweb: attempt {attempt}/{attempts} on {label} failed: {last}")
        if attempt < attempts:
            time.sleep(0.3 * attempt)
    if blocked_only and config.SIMILARWEB_BROWSER_FALLBACK:
        print(f"similarweb: every curl attempt on {label} was challenged; trying a browser")
        try:
            return _browser_get(url, headers, label)
        except (SimilarwebNotFound, SimilarwebBadRequest):
            raise
        except Exception as e:
            print(f"similarweb: browser fallback failed on {label}: {type(e).__name__}: {e}")
            raise SimilarwebBlocked(f"{label}: challenged on {attempts} exits and in a browser") from e
    raise last


def api_json(path, params=None, label=None):
    """GET /api/<path> -> parsed JSON."""
    label = label or path
    text = get_text(path, params, headers=JSON_HEADERS, label=label)
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        dump_debug("non_json", text)
        raise SimilarwebUpstreamError(f"non-JSON body on {label}")


def extract_state(html):
    """window.__APP_DATA__ = {...} -> the parsed object (None when absent)."""
    i = (html or "").find(STATE_ANCHOR)
    if i < 0:
        return None
    eq = html.find("=", i)
    if eq < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[eq + 1:].lstrip())
    except ValueError:
        return None
    return obj


def page_data(path, label=None):
    """GET an SSR page -> window.__APP_DATA__.layout.data. A page whose
    state reports statusCode 404 is a SimilarwebNotFound."""
    label = label or path
    html = get_text(path, headers=PAGE_HEADERS, label=label)
    state = extract_state(html)
    if not isinstance(state, dict):
        dump_debug("no_state", html)
        raise SimilarwebUpstreamError(f"no page state on {label} (layout changed?)")
    data = (state.get("layout") or {}).get("data")
    if not isinstance(data, dict):
        raise SimilarwebUpstreamError(f"empty page state on {label}")
    if data.get("statusCode") in (404, 410) or set(data) == {"statusCode"}:
        raise SimilarwebNotFound(f"similarweb has no page for {label}")
    return data


def similarsites(domain):
    """www.similarsites.com/api/site/<domain> -> parsed JSON (direct egress;
    one retry through a residential exit on failure)."""
    from curl_cffi import requests as curl_requests
    url = f"{SIMILARSITES}/api/site/{domain}"
    label = f"similarsites {domain}"
    last = None
    for proxy in (config.similarweb_similarsites_proxy(), config.similarweb_proxy()):
        try:
            resp = curl_requests.get(url, impersonate=IMPERSONATE, headers=JSON_HEADERS | {"referer": SIMILARSITES + "/"},
                                     timeout=TIMEOUT, proxies={"https": proxy, "http": proxy} if proxy else None)
        except Exception as e:
            last = SimilarwebUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
            continue
        if resp.status_code == 404:
            raise SimilarwebNotFound(f"similarsites.com has no data for {domain}")
        if resp.status_code != 200:
            last = SimilarwebUpstreamError(f"HTTP {resp.status_code} on {label}")
            continue
        text = resp.text or ""
        if not text.strip() or text.strip() in ("null", "{}"):
            raise SimilarwebNotFound(f"similarsites.com has no data for {domain}")
        try:
            return json.loads(text)
        except ValueError:
            last = SimilarwebUpstreamError(f"non-JSON body on {label}")
    raise last


# ---- memo + fan-out ------------------------------------------------------------------------
# Several routes read ONE upstream answer (the website JSON feeds details,
# traffic, rankings, audience, keywords, referrals, ads, social and
# technologies); this memo + the response cache let them share one fetch.
_memo = OrderedDict()
_memo_lock = threading.Lock()
MEMO_TTL = 600
MEMO_MAX = 256


def memoized(key, fn, ttl=MEMO_TTL):
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < ttl:
            _memo.move_to_end(key)
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return value


def shared_raw(name, params, build, ttl):
    """A raw upstream payload shared by several routes: in-process memo, then
    the response cache (pods share it), then build()."""
    from cache import cached_call
    seconds = ttl.total_seconds() if hasattr(ttl, "total_seconds") else ttl
    key = (name, json.dumps(params, sort_keys=True))
    return memoized(key, lambda: cached_call(f"similarweb.raw.{name}", params, lambda **_: build(), ttl),
                    ttl=min(seconds, MEMO_TTL))


def run_parallel(fns, workers):
    """Run zero-arg callables in parallel; results align with `fns`. Each
    result is ("ok", value) or ("error", exception)."""
    def guard(fn):
        try:
            return ("ok", fn())
        except Exception as e:
            return ("error", e)
    if not fns:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(fns)))) as ex:
        return list(ex.map(guard, fns))


if __name__ == "__main__":
    # Smoke test: python similarweb/fetch.py [domain]
    dom = sys.argv[1] if len(sys.argv) > 1 else "github.com"
    body = api_json(f"/api/website/{dom}")
    print(dom, (body or {}).get("overview", {}).get("globalRank"))
