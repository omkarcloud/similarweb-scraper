"""/similarweb/search* — find websites, apps and companies.

  search        /api/autocomplete/apps-sites-preview?pattern= (the site's
                search results page): up to 30 websites, 30 Google Play apps,
                30 App Store apps and 30 companies, with descriptions
  autocomplete  /api/universal?term=&dataKeys= (the search box): 10 websites
                and/or apps per store, apps with their ratings count
"""
from similarweb import fetch
from similarweb import parsers as P

AUTOCOMPLETE_TYPES = {"all": "websites,apps", "websites": "websites", "apps": "apps"}


def search(query):
    data = fetch.api_json("/api/autocomplete/apps-sites-preview", {"pattern": query}, label="search")
    return {"query": query, **P.search(data)}


def autocomplete(query, type=None):
    data = fetch.api_json("/api/universal", {"term": query, "dataKeys": AUTOCOMPLETE_TYPES[type or "all"]},
                          label="autocomplete")
    out = P.autocomplete(data)
    if type == "websites":
        out.pop("google_play_apps"), out.pop("app_store_apps")
    elif type == "apps":
        out.pop("websites")
    return {"query": query, **out}
