"""/similarweb/apps/* — Google Play / App Store app intelligence.

  details   the /app/<store>/<id>/[<country>/] page: store + usage ranks,
            28-day rank history, top countries, audience interests,
            competitors
  top       /api/topapps charts (store / country / category / chart type /
            device / sort by store or usage rank / date)
  trending  /api/topappstrends: rising, falling, new and dropped apps
  filters   the filter lists both stores publish (countries with usage-rank
            flag, categories + subcategories, chart types, devices)
"""
from similarweb import fetch
from similarweb import parsers as P
from similarweb import refdata
from similarweb import shared as S

CHART_TYPES = {"free": "top-free", "paid": "top-paid", "grossing": "top-grossing"}
SORTS = {"store_rank": "store-rank", "usage_rank": "app-index"}
DEVICES = ("iphone", "ipad")
STORES = ("google", "apple")
DEFAULT_COUNTRY = "US"


def details(app, country=None):
    """The app page carries the country-independent profile (description,
    rating, competitors, top countries) with US ranks; the page ignores a
    country segment, so for another `country` the ranks, 28-day history and
    audience interests come from /api/appanalysis?country=<url code> and
    replace the page's."""
    store, app_id = app["store"], app["id"]
    label = f"{store} app {app_id}"
    calls = [lambda: fetch.page_data(f"/app/{store}/{app_id}/", label=label)]
    if country and country != DEFAULT_COUNTRY:
        code = S.country_url_code(country, refdata.APP_COUNTRIES[store], f"{store} app data")
        calls.append(lambda: fetch.api_json("/api/appanalysis", {"store": store, "appId": app_id, "country": code},
                                            label=f"{label} in {country}"))
    results = fetch.run_parallel(calls, workers=2)
    status, data = results[0]
    if status == "error":
        raise data
    if not data.get("id") and not data.get("name"):
        raise fetch.SimilarwebNotFound(f"similarweb has no data for {label}")
    if len(results) > 1:
        status, local = results[1]
        if status == "error":
            if isinstance(local, fetch.SimilarwebBadRequest):
                raise fetch.SimilarwebNotFound(f"similarweb has no {country} chart data for {label}")
            raise local
        data = {**data, **{k: v for k, v in (local or {}).items() if v is not None}}
    return P.app_details(data)


def _category_echo(category):
    if not category:
        return None
    path = category["category"] + (f"/{category['subcategory']}" if category.get("subcategory") else "")
    return S.app_category(path)


def _chart_params(store, country, category, chart_type, device, sort=None, date=None):
    country = country or DEFAULT_COUNTRY
    country_code = S.country_url_code(country, refdata.APP_COUNTRIES[store], f"{store} app charts")
    cat, sub = "all", None
    if category:
        cats = refdata.APP_CATEGORIES[store]
        cat = category["category"]
        if cat not in cats:
            raise ValueError(f"'{cat}' is not a {store} app category (see /similarweb/apps/filters).")
        sub = category.get("subcategory")
        if sub and sub not in cats[cat]:
            raise ValueError(f"'{sub}' is not a subcategory of {store} {cat} (see /similarweb/apps/filters).")
    if store == "google" and device:
        raise ValueError("device applies to the App Store only (iphone / ipad).")
    if sort == "usage_rank" and country not in refdata.APP_USAGE_RANK_COUNTRIES[store]:
        raise ValueError(f"Similarweb has no usage rank for {store} apps in {country}; sort by store_rank.")
    params = {"store": store, "country": country_code, "category": cat, "subcategory": sub,
              "mode": CHART_TYPES[chart_type or "free"], "device": (device or "iphone") if store == "apple" else None,
              "orderBy": SORTS[sort or "store_rank"]}
    if date:
        params["date"] = date
    return params


def top(store, country=None, category=None, chart_type=None, device=None, sort=None, date=None):
    params = _chart_params(store, country, category, chart_type, device, sort, date)
    data = fetch.api_json("/api/topapps", params, label=f"top {store} apps")
    out = P.top_apps(data, store)
    return {"store": store, "country": S.country(country or DEFAULT_COUNTRY),
            "category": _category_echo(category), "chart_type": chart_type or "free", "device": params.get("device"), **out}


def trending(store, country=None, category=None, chart_type=None, device=None):
    params = _chart_params(store, country, category, chart_type, device)
    data = fetch.api_json("/api/topappstrends", params, label=f"trending {store} apps")
    out = P.trending_apps(data, store)
    return {"store": store, "country": S.country(country or DEFAULT_COUNTRY),
            "category": _category_echo(category), "chart_type": chart_type or "free", "device": params.get("device"), **out}


def filters():
    data = fetch.api_json("/api/topappstrends", {"store": "google", "country": "united-states", "category": "all",
                                                 "mode": "top-free", "orderBy": "store-rank"},
                          label="app filters")
    return P.app_filters((data or {}).get("filterOptions"))
