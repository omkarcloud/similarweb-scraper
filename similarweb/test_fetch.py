"""Offline tests for the Similarweb transport (similarweb/fetch.py): the
empty-cookie curl path, and the minted-token fallback — mint on the exit
the WAF challenged, replay over curl with the token on that same exit,
reuse it for the rest of its calls (identity_pool.Pool, the budget charged
when a call takes it), retire it on a block. curl sessions and
browser_client.mint are stubbed; no box, no network.

    python -m pytest similarweb/test_fetch.py -q
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client  # noqa: E402
import config  # noqa: E402
from similarweb import fetch as F  # noqa: E402
from scraper_utils.testing import hosted_only

OK = (200, '{"domain": "x.com"}')
CHALLENGE = (202, "")
HARD = (403, "<html>Request blocked</html>")
CAPTCHA = (405, "<html>captcha</html>")
RATE = (429, "")


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _reset_pools():
    F._pool.clear()
    F._identities.clear()
    F._identities._mint_times.clear()


@pytest.fixture
def world(monkeypatch):
    """`answers` is consumed per curl GET; `log` records (port, cookie) per
    GET; `mints` records the proxy of every box mint. Exits are minted as
    ports 10001, 10002, ..."""
    log, answers, mints, ports = [], [], [], iter(range(10001, 10999))

    class _Sess:
        def __init__(self, proxy):
            self.proxy = proxy

        def get(self, url, headers=None, cookies=None, **kw):
            log.append((self.proxy.rsplit(":", 1)[-1], (cookies or {}).get("aws-waf-token")))
            return _Resp(*(answers.pop(0) if answers else OK))

        def close(self):
            pass

    monkeypatch.setattr(F, "_session", lambda ex: _Sess(ex.proxy))
    monkeypatch.setattr(F, "_drop_session", lambda key: None)
    monkeypatch.setattr(config, "similarweb_proxy", lambda: f"http://u:p@gw:{next(ports)}")
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_EXIT", None)     # the residential path alone; the gateway has its own tests below
    monkeypatch.setattr(config, "SIMILARWEB_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(config, "SIMILARWEB_REQUESTS_PER_EXIT", 5)
    monkeypatch.setattr(config, "SIMILARWEB_TOKEN_CALLS", 3)
    monkeypatch.setattr(config, "SIMILARWEB_BROWSER_FALLBACK", True)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)

    def mint(site, proxy=None, variant=""):
        assert site == "similarweb"
        mints.append(proxy.rsplit(":", 1)[-1])
        return {"tokens": {"aws-waf-token": f"tok-{proxy.rsplit(':', 1)[-1]}"}, "expires_at": time.time() + 240}
    monkeypatch.setattr(browser_client, "mint", mint)
    _reset_pools()
    yield log, answers, mints
    _reset_pools()


@hosted_only
def test_the_empty_cookie_path_needs_no_box(world):
    log, _, mints = world
    assert F.api_json("/api/website/x.com") == {"domain": "x.com"}
    assert log == [("10001", "")] and mints == []


@hosted_only
def test_all_challenged_mints_on_the_first_challenged_exit_and_replays_there(world):
    log, answers, mints = world
    answers.extend([CHALLENGE, HARD, CHALLENGE, OK])
    assert F.api_json("/api/website/x.com") == {"domain": "x.com"}
    assert mints == ["10001"]                              # the exit that was only challenged, not the hard-blocked one
    assert log[-1] == ("10001", "tok-10001")               # the replay: same exit, the minted token
    assert F._identities.peek().exit.proxy.endswith(":10001")


@hosted_only
def test_a_minted_identity_serves_its_remaining_calls_first(world):
    log, answers, mints = world
    answers.extend([CHALLENGE, CHALLENGE, CHALLENGE, OK])
    F.api_json("/api/website/a.com")                       # mint + call 1 of 3
    F.api_json("/api/website/b.com")                       # call 2 on the token, no curl attempt
    F.api_json("/api/website/c.com")                       # call 3
    assert log[3:] == [("10001", "tok-10001")] * 3 and mints == ["10001"]
    assert F._identities.peek() is None                    # spent
    F.api_json("/api/website/d.com")                       # back to the empty-cookie pool
    assert log[-1][1] == ""


@hosted_only
def test_a_blocked_identity_is_retired_and_the_call_falls_back_to_curl(world):
    log, answers, mints = world
    answers.extend([CHALLENGE, CHALLENGE, CHALLENGE, OK])
    F.api_json("/api/website/a.com")
    ident = F._identities.peek()
    answers.extend([RATE, OK])
    assert F.api_json("/api/website/b.com") == {"domain": "x.com"}
    assert log[-2] == ("10001", "tok-10001") and log[-1][1] == ""
    assert F._identities.peek() is None and ident.retired and mints == ["10001"]


@hosted_only
def test_no_challenged_exit_mints_on_a_fresh_one(world):
    log, answers, mints = world
    answers.extend([HARD, CAPTCHA, HARD, OK])
    F.api_json("/api/website/x.com")
    assert mints == ["10004"] and log[-1] == ("10004", "tok-10004")


@hosted_only
def test_a_refused_mint_is_blocked(world, monkeypatch):
    _, answers, _ = world
    answers.extend([CHALLENGE] * 3)

    def refuse(site, proxy=None, variant=""):
        raise browser_client.BoxRefused("similarweb: unchallenged on this exit, no token to mint")
    monkeypatch.setattr(browser_client, "mint", refuse)
    with pytest.raises(F.SimilarwebBlocked, match="minted token"):
        F.api_json("/api/website/x.com")
    assert F._identities.peek() is None and F._identities.stats()["minting"] == 0


@hosted_only
def test_a_minted_replay_that_is_blocked_too_raises_blocked(world):
    _, answers, mints = world
    answers.extend([CHALLENGE, CHALLENGE, CHALLENGE, CAPTCHA])
    with pytest.raises(F.SimilarwebBlocked):
        F.api_json("/api/website/x.com")
    assert mints == ["10001"] and F._identities.peek() is None


@hosted_only
def test_not_found_passes_through_the_minted_replay(world):
    _, answers, _ = world
    answers.extend([CHALLENGE, CHALLENGE, CHALLENGE, (404, "")])
    with pytest.raises(F.SimilarwebNotFound):
        F.api_json("/api/website/nosuch.example")


@hosted_only
def test_an_expired_identity_is_not_used(world):
    log, answers, mints = world
    answers.extend([CHALLENGE, CHALLENGE, CHALLENGE, OK])
    F.api_json("/api/website/a.com")
    F._identities.peek().expires_at = time.time() - 1
    F.api_json("/api/website/b.com")
    assert log[-1][1] == "" and F._identities.peek() is None


@hosted_only
def test_the_mint_budget_pauses_mints_as_blocked(world, monkeypatch):
    _, answers, mints = world
    monkeypatch.setattr(F._identities, "mints_per_minute", 1)
    answers.extend([CHALLENGE] * 3 + [OK])
    F.api_json("/api/website/a.com")                       # the one mint of this minute
    F._identities.peek().expires_at = time.time() - 1      # gone: the next call must mint again
    answers.extend([CHALLENGE] * 3)
    with pytest.raises(F.SimilarwebBlocked, match="minted token"):
        F.api_json("/api/website/b.com")
    assert mints == ["10001"]


@hosted_only
def test_transport_errors_do_not_mint(world, monkeypatch):
    _, _, mints = world

    def broken(ex):
        class _S:
            def get(self, *a, **k):
                raise ConnectionError("tunnel reset")
        return _S()
    monkeypatch.setattr(F, "_session", broken)
    with pytest.raises(F.SimilarwebUpstreamError):
        F.api_json("/api/website/x.com")
    assert mints == []


# ---- the gateway exit in front of the exit pool (config.SIMILARWEB_GATEWAY_EXIT) ----------

RATE_LIMITED = (429, "Rate limit exceeded. Please try again later.")


@pytest.fixture
def gateway(world, monkeypatch):
    """`world` with the gateway knob on and a fake gateway session: `sent`
    records the Cookie header of each gateway GET, `gw_answers` is consumed
    per GET (default OK), `jar` counts how often the cookie jar was emptied."""
    log, answers, mints = world
    sent, gw_answers, jar = [], [], {"cleared": 0}

    class _Jar:
        def clear(self):
            jar["cleared"] += 1

    class _Gateway:
        cookies = _Jar()

        def get(self, url, headers=None, **kw):
            assert "cookies" not in kw             # on a gateway session that kwarg is curl's cookie for the hop to the gateway
            sent.append(headers.get("cookie"))
            return _Resp(*(gw_answers.pop(0) if gw_answers else OK))

        def close(self):
            pass

    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_EXIT", "gateway")
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_ATTEMPTS", 2)
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_FAILURES", 3)
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_PAUSE", 120)
    monkeypatch.setattr(F, "_gateway_session", lambda: _Gateway())
    F._gateway_state.update(failed=0, paused_until=0.0)
    yield log, answers, mints, sent, gw_answers, jar
    F._gateway_state.update(failed=0, paused_until=0.0)


@hosted_only
def test_the_gateway_serves_a_call_statelessly_and_spends_no_exit(gateway):
    log, _, mints, sent, _, jar = gateway
    assert config.similarweb_gateway_exit() == "gateway"
    assert F.api_json("/api/website/x.com") == {"domain": "x.com"}
    assert F.api_json("/api/website/y.com") == {"domain": "x.com"}
    assert sent == ["aws-waf-token=", "aws-waf-token="]    # the empty token cookie, as a header
    assert jar["cleared"] == 2                             # never an earlier answer's sgID: the rate rule counts it
    assert log == [] and mints == []


@hosted_only
def test_a_refused_gateway_falls_through_to_the_residential_exits(gateway):
    log, _, mints, sent, gw_answers, _ = gateway
    gw_answers.extend([CHALLENGE, RATE_LIMITED])
    assert F.api_json("/api/website/x.com") == {"domain": "x.com"}
    assert len(sent) == 2 and log == [("10001", "")] and mints == []


@hosted_only
def test_the_sites_own_answer_on_the_gateway_is_final(gateway):
    log, _, _, sent, gw_answers, _ = gateway
    gw_answers.append((404, ""))
    with pytest.raises(F.SimilarwebNotFound):
        F.api_json("/api/website/nope.example")
    assert len(sent) == 1 and log == []


@hosted_only
def test_a_gateway_that_keeps_failing_is_skipped_for_a_while(gateway, monkeypatch):
    log, _, _, sent, gw_answers, _ = gateway
    gw_answers.extend([CHALLENGE] * 6)                     # 3 calls x 2 tries
    for _ in range(3):
        F.api_json("/api/website/x.com")
    assert len(sent) == 6 and len(log) == 3
    F.api_json("/api/website/x.com")                       # paused: straight to a residential exit
    assert len(sent) == 6 and len(log) == 4
    F._gateway_state["paused_until"] = 0.0                 # the pause is over: the gateway is tried again
    F.api_json("/api/website/x.com")
    assert len(sent) == 7 and len(log) == 4


@hosted_only
def test_no_gateway_knob_no_gateway_try(gateway, monkeypatch):
    log, _, _, sent, _, _ = gateway
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_EXIT", None)
    F.api_json("/api/website/x.com")
    assert sent == [] and log == [("10001", "")]


@hosted_only
def test_the_real_gateway_session_is_an_gateway_one(monkeypatch):
    monkeypatch.setattr(config, "SIMILARWEB_GATEWAY_EXIT", "gateway")
    F._local.gateway = None
    sess = F._gateway_session()
    try:
        assert getattr(sess, "via_exit_gateway", False) and sess.country == "us"
        assert sess.headers["accept-language"].startswith("en-US")
        assert F._gateway_session() is sess                # one per thread
    finally:
        F._local.gateway = None
        sess.close()
