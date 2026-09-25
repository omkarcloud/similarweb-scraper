"""Offline tests: refs resolvers, marshmallow schemas, parsers and the
endpoint functions with the transport monkeypatched to serve fixtures
(similarweb/fixtures/*.json.gz, raw payloads captured 2026-09-25) — no
network.

    python -m pytest similarweb/test_parsers.py -q
"""
import gzip
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema_fields import load_query  # noqa: E402
from similarweb import (amazon, apps, fetch, parsers as P, rankings, refs,  # noqa: E402
                        schemas, search, shared as S, websites)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fx(name):
    with gzip.open(os.path.join(FX, name + ".json.gz"), "rt", encoding="utf-8") as f:
        return json.load(f)


# ---- refs --------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [
    "github.com", "GitHub.com", "www.github.com", "https://github.com/features?x=1", "//github.com",
    "https://www.similarweb.com/website/github.com/#overview", "similarweb.com/ai-traffic/github.com/",
    "https://www.similarweb.com/company/github.com/", "https://www.similarsites.com/site/github.com",
])
def test_resolve_website(value):
    assert refs.resolve_website(value) == "github.com"


def test_resolve_website_keeps_subdomains_and_idn():
    assert refs.resolve_website("blog.github.com") == "blog.github.com"
    assert refs.resolve_website("münchen.de") == "xn--mnchen-3ya.de"


@pytest.mark.parametrize("value", ["", "not a domain", "localhost", "127.0.0.1", "https://www.similarweb.com/top-websites/",
                                   "https://www.similarsites.com/"])
def test_resolve_website_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_website(value)


@pytest.mark.parametrize("value,expected", [
    ("com.whatsapp", {"store": "google", "id": "com.whatsapp"}),
    ("310633997", {"store": "apple", "id": "310633997"}),
    ("id310633997", {"store": "apple", "id": "310633997"}),
    ("https://play.google.com/store/apps/details?id=com.whatsapp&hl=en", {"store": "google", "id": "com.whatsapp"}),
    ("https://apps.apple.com/us/app/whatsapp-messenger/id310633997", {"store": "apple", "id": "310633997"}),
    ("https://www.similarweb.com/app/google/com.whatsapp/", {"store": "google", "id": "com.whatsapp"}),
    ("https://www.similarweb.com/app/google-play/com.whatsapp/statistics", {"store": "google", "id": "com.whatsapp"}),
    ("https://www.similarweb.com/app/app-store/310633997/", {"store": "apple", "id": "310633997"}),
])
def test_resolve_app(value, expected):
    assert refs.resolve_app(value) == expected


@pytest.mark.parametrize("value", ["", "whatsapp", "https://play.google.com/store/apps", "https://www.similarweb.com/app/apple/com.whatsapp/"])
def test_resolve_app_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_app(value)


def test_resolve_country_and_category():
    assert refs.resolve_country("US") == "US"
    assert refs.resolve_country("united kingdom") == "GB"
    assert refs.resolve_country("uk") == "GB"
    assert refs.resolve_country("worldwide") is None
    with pytest.raises(ValueError):
        refs.resolve_country("atlantis")
    assert refs.resolve_website_category("E-commerce and Shopping/Marketplace") == \
        {"category": "e-commerce-and-shopping", "subcategory": "marketplace"}
    assert refs.resolve_website_category("marketplace") == {"category": "e-commerce-and-shopping", "subcategory": "marketplace"}
    assert refs.resolve_website_category("https://www.similarweb.com/top-websites/united-states/games/") == \
        {"category": "games", "subcategory": None}
    assert refs.resolve_website_category("all") is None
    with pytest.raises(ValueError):
        refs.resolve_website_category("e-commerce-and-shopping/poker")
    assert refs.resolve_app_category("games/puzzle") == {"category": "games", "subcategory": "puzzle"}
    assert refs.resolve_technology("Google Analytics") == "google-analytics"
    assert refs.resolve_technology("https://www.similarweb.com/technology/shopify/") == "shopify"
    assert refs.resolve_amazon_marketplace("uk") == "amazon.co.uk"
    assert refs.resolve_amazon_marketplace("https://www.amazon.de/dp/B0") == "amazon.de"
    assert refs.resolve_amazon_marketplace("US") == "amazon.com"
    with pytest.raises(ValueError):
        refs.resolve_amazon_marketplace("amazon.cn")


# ---- schemas -------------------------------------------------------------------------------

def test_schemas():
    data, err = load_query(schemas.WebsiteSchema, {"website": "https://www.github.com/x"})
    assert err is None and data == {"website": "github.com"}
    data, err = load_query(schemas.CompareSchema, {"websites": "github.com, gitlab.com,github.com"})
    assert data == {"websites": ["github.com", "gitlab.com"]}
    _, err = load_query(schemas.CompareSchema, {"websites": ",".join(f"site{i}.com" for i in range(11))})
    assert err and "websites" in err["errors"]
    data, err = load_query(schemas.TopAppsSchema, {"store": "Apple", "category": "games/puzzle", "chart_type": "PAID"})
    assert data["store"] == "apple" and data["chart_type"] == "paid" and data["sort"] == "store_rank"
    assert data["category"] == {"category": "games", "subcategory": "puzzle"} and data["country"] is None
    _, err = load_query(schemas.WebsiteSchema, {"website": "github.com", "domain": "x"})
    assert err and "domain" in err["errors"]
    data, _ = load_query(schemas.AmazonTopBrandsSchema, {})
    assert data == {"marketplace": "amazon.com", "category": None}
    _, err = load_query(schemas.SearchSchema, {"query": "a"})
    assert err


# ---- shared helpers ---------------------------------------------------------------------------

def test_shared_helpers():
    assert S.duration_seconds("00:06:02") == 362 and S.duration_seconds(None) is None
    assert S.iso_date("2026-08-01T00:00:00+00:00") == "2026-08-01" and S.iso_date("0001-01-01T00:00:00") is None
    assert S.category("e-commerce_and_shopping/marketplace") == {"id": "e-commerce-and-shopping/marketplace",
                                                                 "name": "E-commerce and Shopping > Marketplace"}
    assert S.category("AI_Chatbots_and_Tools")["name"] == "AI Chatbots and Tools"
    assert S.category("*") is None
    assert S.us_state(84053) == "Washington" and S.us_state(8406) == "California" and S.us_state(2764) is None
    assert S.headquarters("Seattle", "US", 84053) == {"city": "Seattle", "state": "Washington",
                                                     "country": {"code": "US", "name": "United States"}}
    assert S.positive_int(0) is None and S.positive_int(-1) is None and S.share("0.123456") == 0.1235


# ---- parsers ------------------------------------------------------------------------------------

def test_website_details():
    d = P.website_details(fx("website_ebay"))
    assert d["domain"] == "ebay.com" and d["link"] == "https://ebay.com"
    assert d["category"]["id"] == "e-commerce-and-shopping/marketplace"
    assert d["company"]["name"] == "eBay" and d["company"]["headquarters"]["state"] == "California"
    assert d["ranks"]["global_rank"] == 43 and d["ranks"]["country"]["code"] == "US"
    t = d["traffic"]
    assert t["visits"] == 669968323 and t["avg_visit_duration_seconds"] == 362
    assert [m["month"] for m in t["monthly_visits"]] == ["2026-06", "2026-07", "2026-08"]
    assert t["monthly_visits"][-1]["visits"] == 669968323
    # each earlier month = next month / (1 + its change)
    assert abs(t["monthly_visits"][1]["visits"] * 1.000831859 - 669968323) < 5
    assert d["traffic_sources"][0] == {"source": "direct", "rank": 1, "share": 0.4484}
    assert len(d["traffic_sources"]) == 10
    assert d["referrals"]["incoming"]["top_sites"][0]["is_locked"] is True
    assert d["referrals"]["incoming"]["top_sites"][0]["domain"] is None
    assert any(not s["is_locked"] and s["domain"] for s in d["referrals"]["incoming"]["top_sites"])
    assert d["keywords"]["top_keywords"][0]["keyword"] == "ebay" and d["keywords"]["top_keywords"][0]["cpc"] == 1.23
    assert d["ads"]["recent_ads"][0]["image"].startswith("https://")
    assert d["demographics"]["gender"]["male"] > 0.5 and d["demographics"]["age"][0]["age_range"] == "18-24"
    assert d["demographics"]["age"][-1]["age_range"] == "65+"
    assert d["similar_sites"][0]["domain"] == "amazon.com" and d["similar_sites"][0]["affinity"] == 1.0
    assert "companyFeedbackRecaptcha" not in json.dumps(d)
    assert d["snapshot_date"] == "2026-08-01"


def test_website_ranking_and_partial():
    r = P.website_ranking(fx("website_gitlab"))
    assert r["global"]["rank"] == 2361 and r["global"]["previous"] == 2214
    assert len(r["global"]["history"]) == 3 and r["global"]["neighbours"]
    # a partial payload never raises
    d = P.website_details({"domain": "x.com"})
    assert d["domain"] == "x.com" and d["traffic"]["visits"] is None and d["traffic"]["monthly_visits"] == []
    assert d["company"] is None and d["demographics"] == {"gender": None, "age": []}
    assert P.website_details(None)["domain"] is None


def test_competitors_ai_similar_company():
    c = P.competitors_page(fx("competitors_amazon"))
    assert c["website"]["domain"] == "amazon.com" and len(c["competitors"]) == 10
    assert c["competitors"][0]["domain"] == "ebay.com" and c["competitors"][0]["avg_visit_duration_seconds"] == 362
    ai = P.ai_traffic(fx("ai_traffic_amazon"), fx("ai_prompts_amazon"))
    assert ai["ai_visits"] > 1e6 and ai["chatbots"][0]["name"] == "chatgpt.com"
    assert ai["chatbots"][0]["rank"] == 1 and 0 < ai["chatbots"][0]["share"] < 1
    assert len(ai["chatbots"][0]["share_history"]) == 3 and len(ai["top_prompts"]) == 3
    assert ai["company"]["headquarters"]["state"] == "Washington"
    s = P.similar_sites(fx("similarsites_github"), "github.com")
    assert len(s["similar_sites"]) == 20 and s["similar_sites"][0]["rank"] == 1
    assert s["related_apps"][0]["store"] == "google" and s["related_apps"][0]["id"]
    co = P.company(fx("company_amazon"))
    assert co["name"] == "Amazon.com, Inc." and co["is_public"] and co["stock_tickers"][0]["symbol"] == "AMZN"
    assert [m["month"] for m in co["traffic"]] == ["2026-06", "2026-07", "2026-08"]
    assert co["competitors"][0]["domain"] == "ebay.com" and co["competitors"][0]["visits"]
    assert co["headquarters"]["city"] == "Seattle" and co["news"][0]["date"]
    assert "feedbackRecaptcha" not in json.dumps(co)


def test_apps_parsers():
    g = P.app_details(fx("app_google_whatsapp"))
    assert g["store"] == "google" and g["id"] == "com.whatsapp" and g["store_rank"] == 6
    assert g["link"] == "https://play.google.com/store/apps/details?id=com.whatsapp"
    assert len(g["rank_history"]) == 28 and g["competitors"] and g["audience_interests"]
    a = P.app_details(fx("app_apple_whatsapp"))
    assert a["store"] == "apple" and a["usage_rank"] is None and a["link"].endswith("id310633997")
    top = P.top_apps(fx("top_apps_apple_games_paid_ipad"), "apple")
    assert top["apps"][0]["position"] == 1 and top["apps"][0]["usage_rank"] is None
    tr = P.trending_apps(fx("top_apps_trends_apple_us"), "apple")
    assert tr["rising"] and tr["falling"] and tr["new_entries"] and tr["dropped_out"]
    f = P.app_filters(fx("top_apps_trends_apple_us")["filterOptions"])
    assert f["apple"]["chart_types"] == ["free", "paid", "grossing"] and f["apple"]["devices"] == ["iphone", "ipad"]
    games = next(c for c in f["google"]["categories"] if c["id"] == "games")
    assert games["subcategories"] and games["subcategories"][0]["id"].startswith("games/")


def test_rankings_search_misc_parsers():
    t = P.top_websites(fx("top_websites_marketplace"))
    assert t["websites"][0]["rank"] == 1 and t["websites"][0]["domain"] == "amazon.com"
    assert t["category"]["id"] == "e-commerce-and-shopping/marketplace" and t["country"] is None
    tr = P.trending_websites(fx("top_websites_trends_india"))
    assert tr["country"]["code"] == "IN" and tr["rising"][0]["rank_change"] > 0
    wf = P.website_filters(fx("top_websites_page"))
    assert len(wf["categories"]) == 25 and wf["countries"][0]["code"]
    ms = P.market_share(fx("market_share_browsers"), "browsers")
    assert ms["leaders"][0]["name"] == "Chrome" and len(ms["leaders"][0]["history"]) == 12 and ms["by_country"]
    dev = P.market_share(fx("market_share_platforms_india"), "devices")
    assert {l["name"] for l in dev["leaders"]} == {"mobile", "desktop", "tablet"}
    s = P.search(fx("search_nike"))
    assert s["websites"][0]["domain"] == "nike.com" and s["companies"][0]["similarweb_link"]
    assert s["app_store_apps"][0]["store"] == "apple"
    ac = P.autocomplete(fx("autocomplete_amaz"))
    assert ac["websites"][0]["domain"] == "amazon.com" and ac["google_play_apps"][0]["ratings_count"]
    tech = P.technology(fx("technology_shopify"), "shopify")
    assert tech["name"] == "Shopify" and tech["websites_count"] == 4824410 and tech["top_countries"]
    serp = P.serp_volatility(fx("serp"))
    assert len(serp["desktop"]["daily"]) == 90 and serp["desktop"]["daily"][0]["risk_index"] is not None
    amz = P.amazon_top_brands(fx("shopper_health_household"))
    assert amz["marketplace"] == "amazon.com" and amz["revenue"]["currency"] == "USD"
    assert amz["top_brands"][0]["average_price"]["currency"] == "USD" and amz["top_products"][0]["category_path"]
    cats = P.amazon_categories(fx("shopper_health_household"), "amazon.de")
    assert cats["categories"] and cats["categories"][0]["id"].isdigit()


# ---- endpoint functions (transport monkeypatched) ---------------------------------------------------

@pytest.fixture
def no_network(monkeypatch):
    """shared_raw straight to build() (no cache), and a transport that fails loudly."""
    monkeypatch.setattr(fetch, "shared_raw", lambda name, params, build, ttl: build())

    def boom(*a, **k):
        raise AssertionError(f"unexpected network call {a}")
    monkeypatch.setattr(fetch, "get_text", boom)
    return monkeypatch


def test_website_endpoints(no_network):
    no_network.setattr(fetch, "api_json", lambda path, params=None, label=None: fx("website_ebay"))
    assert websites.traffic("ebay.com")["monthly_visits"]
    assert websites.rankings("ebay.com")["ranks"]["global"]["rank"] == 43
    assert websites.audience("ebay.com")["geography"]["top_countries"]
    out = websites.compare(["ebay.com", "ebay.com"])
    assert len(out["websites"]) == 2 and out["failed"] == []


def test_website_not_found(no_network):
    def api(path, params=None, label=None):
        raise fetch.SimilarwebNotFound("no data")
    no_network.setattr(fetch, "api_json", api)
    with pytest.raises(fetch.SimilarwebNotFound):
        websites.details("nothing.example")
    out = websites.compare(["nothing.example"])
    assert out["websites"] == [] and out["failed"][0]["reason"] == "not_found"


def test_app_country_merge(no_network):
    no_network.setattr(fetch, "page_data", lambda path, label=None: fx("app_google_whatsapp"))
    no_network.setattr(fetch, "api_json", lambda path, params=None, label=None: {
        "countryAlpha2Code": "DE", "storeRank": 2, "usageRank": 2, "categoryStoreRank": 1, "categoryUsageRank": 1,
        "ranking": {"history": []}})
    out = apps.details({"store": "google", "id": "com.whatsapp"}, country="DE")
    assert out["country"]["code"] == "DE" and out["store_rank"] == 2 and out["rank_history"] == []
    assert out["competitors"]      # page-only fields survive the merge
    with pytest.raises(ValueError):
        apps.top("google", device="ipad")
    with pytest.raises(ValueError):
        apps.top("apple", category={"category": "tools", "subcategory": None})


def test_chart_params():
    params = apps._chart_params("apple", "GB", {"category": "games", "subcategory": "puzzle"}, "paid", "ipad", "store_rank")
    assert params == {"store": "apple", "country": "united-kingdom", "category": "games", "subcategory": "puzzle",
                      "mode": "top-paid", "device": "ipad", "orderBy": "store-rank"}
    with pytest.raises(ValueError):
        rankings.browsers(platform="mobile")


def test_amazon_category_resolution(no_network):
    no_network.setattr(fetch, "api_json", lambda path, params=None, label=None: fx("shopper_health_household"))
    assert amazon.resolve_category("amazon.com", "3760901") == "3760901"
    assert amazon.resolve_category("amazon.com", "Health & Household") == "3760901"
    assert amazon.resolve_category("amazon.com", "health-household/baby-child-care") == "10787321"
    with pytest.raises(ValueError):
        amazon.resolve_category("amazon.com", "Spaceships")
    assert amazon.top_brands("amazon.com", "Health & Household")["top_brands"]


def test_search_endpoints(no_network):
    no_network.setattr(fetch, "api_json", lambda path, params=None, label=None: fx("autocomplete_amaz"))
    out = search.autocomplete("amaz", type="apps")
    assert "websites" not in out and out["google_play_apps"]


def test_state_extraction():
    html = '<script>window.__APP_DATA__ = {"layout": {"data": {"a": 1}}, "footer": {}};\nwindow.x = 1;</script>'
    assert fetch.extract_state(html)["layout"]["data"] == {"a": 1}
    assert fetch.extract_state("<html></html>") is None
    with pytest.raises(fetch.SimilarwebBlocked):
        fetch.classify(202, "", "x")
    with pytest.raises(fetch.SimilarwebNotFound):
        fetch.classify(204, "", "x")
    with pytest.raises(fetch.SimilarwebBadRequest):
        fetch.classify(400, "", "x")
    assert fetch.classify(200, "ok", "x") == "ok"
