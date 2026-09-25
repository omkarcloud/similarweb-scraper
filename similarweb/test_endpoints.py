"""Live endpoint smoke tests: one call per /similarweb/* route against a
running service, with example values proven to return data (2026-09-25).
The listing tooling (derive_facts.py) reads each route's FIRST call from
this file's AST as its working example, so the values stay literals.

Skipped unless SIMILARWEB_BASE points at a running service:

    ONLY_SCRAPER=similarweb python run.py            # or any bottle runner
    SIMILARWEB_BASE=http://127.0.0.1:6002 python -m pytest similarweb/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("SIMILARWEB_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set SIMILARWEB_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=240)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=240).status_code


def test_websites():
    body = call("/similarweb/websites/details", website="amazon.com")
    assert body["domain"] == "amazon.com" and body["traffic"]["visits"] > 1e9
    assert len(body["traffic"]["monthly_visits"]) == 3 and body["ranks"]["global_rank"] < 50
    assert body["company"]["name"] and body["similar_sites"] and body["keywords"]["top_keywords"]
    body = call("/similarweb/websites/traffic", website="https://github.com/features")
    assert body["domain"] == "github.com" and body["traffic_sources"][0]["share"] and body["top_countries"]
    assert call("/similarweb/websites/rankings", website="github.com")["ranks"]["global"]["history"]
    body = call("/similarweb/websites/audience", website="github.com")
    assert body["demographics"]["age"] and body["geography"]["top_countries"]
    assert call("/similarweb/websites/keywords", website="github.com")["keywords"]["top_keywords"]
    assert call("/similarweb/websites/referrals", website="github.com")["referrals"]["incoming"]["top_sites"]
    assert "top_publishers" in call("/similarweb/websites/ads", website="ebay.com")["ads"]
    assert call("/similarweb/websites/social", website="github.com")["social"]["top_networks"]
    assert call("/similarweb/websites/technologies", website="ebay.com")["technologies"]["categories"]


def test_website_extras():
    body = call("/similarweb/websites/competitors", website="amazon.com")
    assert len(body["competitors"]) >= 5 and body["competitors"][0]["global_rank"]
    body = call("/similarweb/websites/ai-traffic", website="amazon.com")
    assert body["ai_visits"] and body["chatbots"][0]["name"] == "chatgpt.com"
    body = call("/similarweb/websites/similar-sites", website="github.com")
    assert len(body["similar_sites"]) >= 10 and body["similar_sites"][0]["similarity"]
    body = call("/similarweb/websites/compare", websites="github.com,gitlab.com,bitbucket.org")
    assert len(body["websites"]) == 3 and all(w["visits"] for w in body["websites"])
    assert status("/similarweb/websites/details", website="not a domain") == 400
    assert status("/similarweb/websites/details", website="thisdomaindoesnotexist-xyz-123.com") == 404


def test_companies():
    body = call("/similarweb/companies/details", company="amazon.com")
    assert body["name"] and body["traffic"] and body["competitors"] and body["stock_tickers"]


def test_apps():
    body = call("/similarweb/apps/details", app="com.whatsapp")
    assert body["store"] == "google" and body["store_rank"] and body["rank_history"]
    body = call("/similarweb/apps/details", app="https://apps.apple.com/us/app/whatsapp-messenger/id310633997", country="DE")
    assert body["store"] == "apple" and body["country"]["code"] == "DE"
    body = call("/similarweb/apps/top", store="apple", country="US", category="games", chart_type="paid", device="ipad")
    assert len(body["apps"]) >= 40 and body["apps"][0]["store_rank"] == 1
    body = call("/similarweb/apps/top", store="google", country="US", sort="usage_rank")
    assert body["sort"] == "usage_rank" and body["apps"][0]["usage_rank"]
    body = call("/similarweb/apps/trending", store="google", country="IN")
    assert body["rising"] and body["falling"]
    body = call("/similarweb/apps/filters")
    assert body["google"]["categories"] and body["apple"]["devices"] == ["iphone", "ipad"]


def test_rankings():
    body = call("/similarweb/top-websites", country="US", category="e-commerce-and-shopping/marketplace")
    assert body["websites"][0]["domain"] == "amazon.com" and body["country"]["code"] == "US"
    assert call("/similarweb/top-websites")["websites"][0]["rank"] == 1
    body = call("/similarweb/top-websites/trending", country="IN")
    assert body["rising"] and body["new_entries"]
    body = call("/similarweb/top-websites/filters")
    assert len(body["categories"]) > 20 and len(body["countries"]) > 50
    body = call("/similarweb/market-share/browsers")
    assert body["leaders"][0]["name"] == "Chrome" and body["by_country"]
    assert call("/similarweb/market-share/browsers", country="US", platform="desktop")["leaders"]
    body = call("/similarweb/market-share/devices", country="IN")
    assert {l["name"] for l in body["leaders"]} == {"mobile", "desktop", "tablet"}
    body = call("/similarweb/serp-volatility")
    assert len(body["desktop"]["daily"]) >= 30 and body["current_average"] is not None


def test_search():
    body = call("/similarweb/search", query="nike")
    assert body["websites"][0]["domain"] == "nike.com" and body["google_play_apps"] and body["companies"]
    body = call("/similarweb/search/autocomplete", query="amaz")
    assert body["websites"] and body["google_play_apps"]
    assert "google_play_apps" not in call("/similarweb/search/autocomplete", query="amaz", type="websites")


def test_technologies_and_amazon():
    body = call("/similarweb/technologies/details", technology="shopify")
    assert body["name"] == "Shopify" and body["websites_count"] > 1e6 and body["top_websites"]
    body = call("/similarweb/amazon/top-brands", marketplace="amazon.com", category="Health & Household")
    assert body["top_brands"] and body["revenue"]["amount"] and body["category"]["name"] == "Health & Household"
    assert call("/similarweb/amazon/top-brands", marketplace="uk")["marketplace"] == "amazon.co.uk"
    assert call("/similarweb/amazon/categories", marketplace="de")["categories"]
