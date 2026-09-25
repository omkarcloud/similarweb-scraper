"""/similarweb/top-websites*, /similarweb/market-share/*, /similarweb/serp-volatility.

  top_websites        /api/gettopwebsites: the 50 highest-traffic sites
                      worldwide or in a country, optionally in a category /
                      subcategory
  trending_websites   /api/gettopwebsitestrends: rising, falling, new, dropped
  website_filters     the /top-websites/ page's country + category lists
  browsers / devices  /api/marketshare (browsers, platforms): current leaders,
                      12-month history, per-country leaders (worldwide only)
  serp_volatility     the /serp/ page: Similarweb's daily Google SERP risk
                      index (90 days, desktop + mobile)
"""
from similarweb import fetch
from similarweb import parsers as P
from similarweb import refdata
from similarweb import shared as S

PLATFORMS = {"desktop": "desktop", "mobile": "mobilephone", "tablet": "tablet"}


def _website_params(country, category):
    params = {"country": S.country_url_code(country, refdata.WEBSITE_COUNTRIES, "top-website rankings")}
    if category:
        params["category"] = category["category"]
        params["subcategory"] = category.get("subcategory")
    return params


def top_websites(country=None, category=None):
    data = fetch.api_json("/api/gettopwebsites", _website_params(country, category), label="top websites")
    return P.top_websites(data)


def trending_websites(country=None, category=None):
    data = fetch.api_json("/api/gettopwebsitestrends", _website_params(country, category), label="trending websites")
    return P.trending_websites(data)


def website_filters():
    return P.website_filters(fetch.page_data("/top-websites/", label="top websites filters"))


def browsers(country=None, platform=None):
    if platform and not country:
        raise ValueError("platform needs a country (Similarweb splits browser share by platform per country only).")
    params = {"market": "browsers",
              "country": S.country_url_code(country, refdata.MARKET_SHARE_COUNTRIES, "browser market share"),
              "platform": PLATFORMS.get(platform) if platform else None}
    out = P.market_share(fetch.api_json("/api/marketshare", params, label="browser market share"), "browsers")
    return {"country": S.country(country) if country else None, "platform": platform, **out}


def devices(country=None):
    params = {"market": "platforms",
              "country": S.country_url_code(country, refdata.MARKET_SHARE_COUNTRIES, "device market share")}
    out = P.market_share(fetch.api_json("/api/marketshare", params, label="device market share"), "devices")
    return {"country": S.country(country) if country else None, **out}


def serp_volatility():
    return P.serp_volatility(fetch.page_data("/serp/", label="serp volatility"))
