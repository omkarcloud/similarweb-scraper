"""The 29 Similarweb endpoints. Every path is served with and without the
`/similarweb` prefix, so code generated against the hosted API (paths like
/websites/details) runs unchanged against this server.

Each route validates its query with the marshmallow schema in
similarweb/schemas.py (one param per input: a domain OR any link on it, an
app id OR a store link, ...) and calls the function that returns the JSON."""
import json

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from similarweb import amazon, apps, companies, rankings, search, technologies, websites
from similarweb import schemas as S


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate, run, and map errors: bad params -> 400, no data -> 404,
    blocked / transport failure -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(fn(**data))
    except ValueError as e:                # a param value Similarweb does not serve
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:                # upstream rejected the filter combination
        return json_response({"error": f"similarweb rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"similarweb {label} failed: {e}"}, 500)


# public path -> (schema, function), in the documented order
ENDPOINTS = [
    ("/websites/details", S.WebsiteSchema, websites.details),
    ("/websites/traffic", S.WebsiteSchema, websites.traffic),
    ("/websites/compare", S.CompareSchema, websites.compare),
    ("/websites/competitors", S.WebsiteSchema, websites.competitors),
    ("/websites/similar-sites", S.WebsiteSchema, websites.similar_sites),
    ("/websites/ai-traffic", S.WebsiteSchema, websites.ai_traffic),
    ("/websites/rankings", S.WebsiteSchema, websites.rankings),
    ("/websites/audience", S.WebsiteSchema, websites.audience),
    ("/websites/keywords", S.WebsiteSchema, websites.keywords),
    ("/websites/referrals", S.WebsiteSchema, websites.referrals),
    ("/websites/social", S.WebsiteSchema, websites.social),
    ("/websites/ads", S.WebsiteSchema, websites.ads),
    ("/websites/technologies", S.WebsiteSchema, websites.technologies),
    ("/companies/details", S.CompanySchema, companies.details),
    ("/top-websites", S.TopWebsitesSchema, rankings.top_websites),
    ("/top-websites/trending", S.TopWebsitesSchema, rankings.trending_websites),
    ("/top-websites/filters", S.EmptySchema, rankings.website_filters),
    ("/search/autocomplete", S.AutocompleteSchema, search.autocomplete),
    ("/search", S.SearchSchema, search.search),
    ("/apps/details", S.AppSchema, apps.details),
    ("/apps/top", S.TopAppsSchema, apps.top),
    ("/apps/trending", S.TrendingAppsSchema, apps.trending),
    ("/apps/filters", S.EmptySchema, apps.filters),
    ("/market-share/browsers", S.BrowsersSchema, rankings.browsers),
    ("/market-share/devices", S.DevicesSchema, rankings.devices),
    ("/technologies/details", S.TechnologySchema, technologies.details),
    ("/amazon/top-brands", S.AmazonTopBrandsSchema, amazon.top_brands),
    ("/amazon/categories", S.AmazonCategoriesSchema, amazon.categories),
    ("/serp-volatility", S.EmptySchema, rankings.serp_volatility),
]


def mount(path, schema, fn):
    """Serve one endpoint at /path and /similarweb/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "similarweb_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/similarweb" + path, method="GET")(handler)


for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
