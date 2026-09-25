"""/similarweb/technologies/* — the /technology/<slug>/ page: a web
technology's install base, market share, top websites using it, country
and category split, and alternatives."""
from similarweb import fetch
from similarweb import parsers as P


def details(technology):
    data = fetch.page_data(f"/technology/{technology}/", label=f"technology {technology}")
    if not data.get("name"):
        raise fetch.SimilarwebNotFound(f"similarweb has no technology page for '{technology}'")
    return P.technology(data, technology)
