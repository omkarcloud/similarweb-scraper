"""Similarweb transport: plain curl_cffi (Chrome TLS) through the gateway exit
first, then rotating residential exits, with a token minted by a headful
Chrome on the browser box as the last resort.

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
to config.SIMILARWEB_MAX_ATTEMPTS times.

Since 2026-11-11 a call first tries the shared gateway exit
(config.SIMILARWEB_GATEWAY_EXIT = "gateway", _via_gateway: a fresh gateway address
per request, sent stateless because the site's rate rule counts its `sgID`
cookie); the pool above is what a call falls back to when the gateway is
challenged, rate-limited or down, and while it is paused after
config.SIMILARWEB_GATEWAY_FAILURES failed calls in a row.

When every attempt was challenged (the empty cookie stops passing in
bursts: 1,480 of 1,505 attempts on 2026-10-23), the browser box MINTS a real
token (recipes/similarweb.py) on an exit the WAF challenged with a 202, and
the call is replayed over curl with it on that same exit. Measured
2026-10-24: the token works only from the IP that earned it (405 from any
other exit), and the per-IP rule still applies with it — about 3 API calls
after the mint, then 429, then a hard 403 for hours — whether the calls are
curl replays or in-page fetches from the minting browser. So the box never
serves calls: a minted identity serves config.SIMILARWEB_TOKEN_CALLS calls
over curl within the recipe's ttl, later calls use it before spending fresh
exits, and any block retires it. The identity lives in an identity_pool.Pool
(shared mode, one per process, the use budget charged when a call takes
it), so concurrent failing calls share one mint instead of minting one
each. Until then the fallback was one new Chrome per call running the call
as an in-page fetch.

Not usable: data.similarweb.com/api/v1/data (the legacy extension JSON)
answers 403 to curl and to a real Chrome from every exit tried.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  SimilarwebUpstreamError  transport failure / 5xx / unexpected body — retryable
  SimilarwebBlocked        WAF challenge / block on every exit — retryable
  SimilarwebBadRequest     upstream 400 (unknown filter combination)  — never retried
  SimilarwebNotFound       upstream 404 / "We Have No Data" page      — never retried
"""
import json
import fastjson
import os
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
import egress
import identity_pool
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import debug, fanout, memo, sessions

SITE = "https://www.similarweb.com"
SIMILARSITES = "https://www.similarsites.com"
IMPERSONATE = "chrome"
TIMEOUT = (10, 35)          # (connect, read): a dead exit fails fast

JSON_HEADERS = {"accept": "application/json, text/plain, */*",
                "referer": SITE + "/"}
PAGE_HEADERS = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
# The whole bypass: an empty token cookie is not challenged, a missing one is.
WAF_COOKIES = {"aws-waf-token": ""}

STATE_ANCHOR = "window.__APP_DATA__"
NO_DATA_MARKER = "<title>We Have No Data"
BLOCK_STATUSES = (202, 403, 405)


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
    debug.dump("SIMILARWEB_DEBUG_DIR", name, text)


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
    return sessions.thread_store(_local)


def _session(ex):
    """The calling thread's curl session for one exit (small LRU per thread)."""
    from curl_cffi import requests as curl_requests
    store = _sessions()
    key, proxy = ex.key, ex.proxy
    sess = store.get(key)
    if sess is None:
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        sess.headers["accept-language"] = egress.accept_language(proxy)
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
    sessions.drop_keyed(_sessions(), key)


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


def _curl_once(url, headers, label, fresh, cookies=None, ex=None):
    """One GET through `ex` (default: an exit from the pool). A block
    retires the exit and carries it (`.exit`) and the status (`.status`),
    so the caller can mint on an exit the WAF merely challenged."""
    ex = ex or _take_exit(fresh=fresh)
    sess = _session(ex)
    try:
        resp = sess.get(url, headers=headers, cookies=WAF_COOKIES if cookies is None else cookies,
                        timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        _retire(ex)
        raise SimilarwebUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
    try:
        return classify(resp.status_code, resp.text, label)
    except SimilarwebBlocked as e:
        _retire(ex)
        e.exit, e.status = ex, resp.status_code
        raise


# ---- the gateway exit (in front of the exit pool) --------------------------------
# config.SIMILARWEB_GATEWAY_EXIT = "gateway": a call is tried through the shared
# gateway exit (exit_gateway.py, a fresh gateway address per request) before it
# spends a residential exit. Measured 2026-11-11 through the gateway: the
# empty `aws-waf-token=` cookie passes there too (no cookie: 202
# x-amzn-waf-action: challenge), and the site's own rate rule counts the
# `sgID` cookie its first answer sets, not the address: with that cookie kept
# the 4th request is a 429 "Rate limit exceeded" (44 bytes) whether the
# X-Forwarded-For is fixed or random; with no cookie sent back 12 of 12
# passed on ONE fixed X-Forwarded-For. So every gateway request is
# stateless: the session's jar is emptied first and nothing but the empty
# token cookie is sent.
GATEWAY_COOKIE = "; ".join(f"{name}={value}" for name, value in WAF_COOKIES.items())
_gateway_lock = threading.Lock()
_gateway_state = {"failed": 0, "paused_until": 0.0}     # calls in a row the gateway could not serve


def _gateway_exit():
    """'gateway' when the config names the gateway, else None (a config without
    the knob, the open-source kit's, has no gateway)."""
    exit_for = getattr(config, "similarweb_gateway_exit", None)
    return exit_for() if exit_for else None


def _gateway_attempts():
    """How many gateway tries a call gets now: 0 with no gateway configured
    or while it is paused (config.SIMILARWEB_GATEWAY_FAILURES calls in a row
    it could not serve -> skipped for config.SIMILARWEB_GATEWAY_PAUSE s: the
    WAF's challenge-everything bursts hit every address alike)."""
    if not _gateway_exit() or time.monotonic() < _gateway_state["paused_until"]:
        return 0
    return max(1, int(config.SIMILARWEB_GATEWAY_ATTEMPTS))


def _note_gateway(served):
    with _gateway_lock:
        if served:
            _gateway_state["failed"] = 0
            return
        _gateway_state["failed"] += 1
        if _gateway_state["failed"] >= max(1, int(config.SIMILARWEB_GATEWAY_FAILURES)):
            _gateway_state["failed"] = 0
            _gateway_state["paused_until"] = time.monotonic() + float(config.SIMILARWEB_GATEWAY_PAUSE)
            print(f"similarweb: the gateway exit failed {config.SIMILARWEB_GATEWAY_FAILURES} calls in a row; "
                  f"residential exits only for {config.SIMILARWEB_GATEWAY_PAUSE} s")


def _gateway_session():
    """The calling thread's session on the gateway exit (it keeps the
    connection to the gateway; the address the site sees changes per request)."""
    exit = _gateway_exit()
    sess = getattr(_local, "gateway", None)
    if sess is None or getattr(_local, "gateway_exit", None) != exit:
        sess = egress.new_session(exit, impersonate=IMPERSONATE)
        sess.headers["accept-language"] = egress.accept_language(exit)
        _local.gateway, _local.gateway_exit = sess, exit
    return sess


def _gateway_once(url, headers, label):
    """One stateless GET through the gateway exit -> body text (classify's
    errors; a transport failure drops the thread's gateway session)."""
    sess = _gateway_session()
    try:
        sess.cookies.clear()                    # never the sgID of an earlier answer: the rate rule counts it
        # the Cookie header, not cookies=: on a gateway session that kwarg
        # would be curl's cookie for the hop to the gateway
        resp = sess.get(url, headers=dict(headers, cookie=GATEWAY_COOKIE), timeout=TIMEOUT, allow_redirects=True)
    except Exception as e:
        _local.gateway = None
        try:
            sess.close()
        except Exception:
            pass
        raise SimilarwebUpstreamError(f"request failed on {label}: {type(e).__name__}: {e}")
    return classify(resp.status_code, resp.text, label)


def _via_gateway(url, headers, label):
    """The call through the gateway exit, up to _gateway_attempts() tries:
    (True, text) when it answered, (False, None) when the residential exits
    are next. NotFound / BadRequest are the site's answer and propagate."""
    attempts = _gateway_attempts()
    if not attempts:
        return False, None
    for attempt in range(1, attempts + 1):
        try:
            text = _gateway_once(url, headers, label)
        except (SimilarwebNotFound, SimilarwebBadRequest):
            _note_gateway(True)
            raise
        except SimilarwebUpstreamError as e:
            print(f"similarweb: gateway exit attempt {attempt}/{attempts} on {label} failed: {e}")
            continue
        _note_gateway(True)
        return True, text
    _note_gateway(False)
    return False, None


# ---- minted identities (the fallback, on the browser box) ----------------------
# A token minted by the box (recipes/similarweb.py) on one exit, replayed over
# curl on that same exit (the token is IP-bound). One process-wide identity
# in an identity_pool.Pool: `value` is the token, `exit` the _Exit it was
# minted on; the pool charges one of its SIMILARWEB_TOKEN_CALLS uses per
# call that takes it and retires it when spent, at the recipe's expires_at
# or on its first block (retire). Nothing is minted until a call's curl
# attempts all failed (get_text), and then once per process, not per call.

def _mint(key, hint):
    """The pool's mint function: the box earns a token on `hint` (the _Exit
    the WAF challenged, or a fresh one). Box errors propagate (the pool never
    catches; _mint_identity maps them); a box answer without a token is a
    BoxRefused."""
    ex = hint if hint is not None else _Exit(config.similarweb_proxy())
    minted = browser_client.mint("similarweb", proxy=ex.proxy)
    token = (minted.get("tokens") or {}).get("aws-waf-token")
    if not token:
        raise browser_client.BoxRefused("the box returned no aws-waf-token")
    return identity_pool.Identity(token, exit=ex, expires_at=float(minted.get("expires_at") or time.time() + 240))


_identities = identity_pool.Pool("similarweb", _mint, budget=lambda: max(1, int(config.SIMILARWEB_TOKEN_CALLS)),
                                 mints_per_minute=5)


def _take_identity():
    """The live minted identity, with one call charged on it, or None (no
    mint here: a token is minted only after a call's curl attempts failed)."""
    return _identities.get(mint=False)


def _mint_identity(ex, label):
    """The pooled identity, minted on `ex` if the pool has none (a mint in
    flight is shared, not repeated); this call is charged on it."""
    try:
        return _identities.get(hint=ex)
    except browser_client.BoxRefused as e:
        raise SimilarwebBlocked(f"{label}: the browser box could not earn a token on this exit: {e}") from e
    except browser_client.BoxUnavailable as e:
        raise SimilarwebUpstreamError(f"{label}: browser box unavailable: {e}") from e
    except (browser_client.RemintBudgetExceeded, identity_pool.MintBudgetExceeded) as e:
        raise SimilarwebBlocked(f"{label}: token mints paused ({e})") from e


def _replay(ident, url, headers, label):
    """The call over curl with the identity's token on its own exit; a block
    or a transport failure retires the identity (a no-op when another
    thread already did)."""
    try:
        return _curl_once(url, headers, label, fresh=False, cookies={"aws-waf-token": ident.value}, ex=ident.exit)
    except (SimilarwebBlocked, SimilarwebUpstreamError):
        _identities.retire(ident)
        raise


def _exit_label(ex):
    return f"exit port {ex.proxy.rsplit(':', 1)[-1]}" if ex and ex.proxy else "direct egress"


# ---- public fetchers -------------------------------------------------------------------

def get_text(path, params=None, headers=None, label=None):
    """GET a www.similarweb.com path through the exit pool -> body text."""
    from urllib.parse import urlencode
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    url = SITE + path + (("?" + urlencode(query)) if query else "")
    label = label or path
    headers = headers or JSON_HEADERS
    ident = _take_identity()
    if ident is not None:
        # a token minted for an earlier call still has calls left on its exit
        try:
            return _replay(ident, url, headers, label)
        except (SimilarwebNotFound, SimilarwebBadRequest):
            raise
        except (SimilarwebBlocked, SimilarwebUpstreamError) as e:
            print(f"similarweb: minted token on {_exit_label(ident.exit)} failed on {label}: {e}; retired")
    served, text = _via_gateway(url, headers, label)
    if served:
        return text
    last = None
    blocked_only = True
    challenged = None           # the first exit the WAF only challenged (202): the one worth a mint
    attempts = max(1, int(config.SIMILARWEB_MAX_ATTEMPTS))
    for attempt in range(1, attempts + 1):
        try:
            return _curl_once(url, headers, label, fresh=attempt > 1)
        except SimilarwebBlocked as e:
            last = e
            if challenged is None and getattr(e, "status", None) == 202:
                challenged = e.exit
        except SimilarwebUpstreamError as e:
            last = e
            blocked_only = False
        print(f"similarweb: attempt {attempt}/{attempts} on {label} failed: {last}")
        if attempt < attempts:
            time.sleep(0.3 * attempt)
    if blocked_only and config.SIMILARWEB_BROWSER_FALLBACK:
        # no exit was merely challenged (all hard-blocked / CAPTCHA'd): mint on a fresh one
        ex = challenged or _Exit(config.similarweb_proxy())
        print(f"similarweb: every curl attempt on {label} was challenged; minting a token on {_exit_label(ex)}")
        try:
            return _replay(_mint_identity(ex, label), url, headers, label)
        except (SimilarwebNotFound, SimilarwebBadRequest):
            raise
        except Exception as e:
            print(f"similarweb: minted-token fallback failed on {label}: {type(e).__name__}: {e}")
            raise SimilarwebBlocked(f"{label}: challenged on {attempts} exits and with a minted token") from e
    raise last


def api_json(path, params=None, label=None):
    """GET /api/<path> -> parsed JSON."""
    label = label or path
    text = get_text(path, params, headers=JSON_HEADERS, label=label)
    try:
        return fastjson.loads(text) if text.strip() else None
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
            return fastjson.loads(text)
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
    return memo.memoized(_memo, _memo_lock, MEMO_MAX, key, fn, ttl)


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
    return fanout.guarded_per_call(fns, workers)


if __name__ == "__main__":
    # Smoke test: python similarweb/fetch.py [domain]
    dom = sys.argv[1] if len(sys.argv) > 1 else "github.com"
    body = api_json(f"/api/website/{dom}")
    print(dom, (body or {}).get("overview", {}).get("globalRank"))
