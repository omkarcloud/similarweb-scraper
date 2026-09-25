"""/similarweb/amazon/* — Similarweb Shopper Intelligence for Amazon
(/api/get-shopper-data, the data behind /top-amazon-brands/):

  top_brands   a marketplace (optionally one category): category revenue and
               its 1P / 3P split, organic vs paid search share, the top 5
               brands (revenue share, product views, conversion rate,
               average selling price, each with its change), the top 5
               products by views and the best-selling subcategory tree
  categories   the marketplace's category tree (ids for `category`)

Every answer carries the category tree of ALL 15 marketplaces (~380 KB);
it is fetched once per marketplace per AMAZON_CATEGORIES_CACHE and used to
resolve a category NAME to its id.
"""
from similarweb import cache_config as ttl
from similarweb import fetch
from similarweb import parsers as P
from similarweb import refs


def _raw(marketplace, category_id=None):
    params = {"site": marketplace}
    if category_id:
        params["categoryId"] = category_id
    return fetch.api_json("/api/get-shopper-data", params, label=f"amazon {marketplace}")


def categories(marketplace):
    def build():
        return P.amazon_categories(_raw(marketplace), marketplace)
    return fetch.shared_raw("amazon_categories", {"marketplace": marketplace}, build, ttl.AMAZON_CATEGORIES_CACHE)


def _walk(nodes, path=()):
    for node in nodes:
        yield node, path + (node["name"],)
        yield from _walk(node.get("subcategories") or [], path + (node["name"],))


def _norm(name):
    """'Health & Household' / 'health-and-household' / 'health-household' -> 'health-household'."""
    slug = refs.slugify((name or "").replace("&", " "))
    return "-".join(w for w in slug.split("-") if w and w != "and")


def resolve_category(marketplace, category):
    """A numeric Amazon browse-node id passes through; a name ('Health &
    Household', 'health-household', 'Health & Household > Baby & Child Care')
    is looked up in the marketplace's tree."""
    if category is None or category.isdigit():
        return category
    wanted = [_norm(p) for p in category.replace(">", "/").split("/") if p.strip()]
    matches = []
    for node, path in _walk(categories(marketplace)["categories"]):
        slugs = [_norm(p) for p in path]
        if slugs[-len(wanted):] == wanted:
            matches.append(node)
    if not matches:
        raise ValueError(f"'{category}' is not an Amazon category on {marketplace} "
                         f"(see /similarweb/amazon/categories?marketplace={marketplace}).")
    return matches[0]["id"]


def top_brands(marketplace, category=None):
    category_id = resolve_category(marketplace, category)
    data = _raw(marketplace, category_id)
    if not isinstance(data, dict) or (not data.get("topBrands") and not data.get("revenue")):
        raise fetch.SimilarwebNotFound(f"similarweb has no shopper data for {category or 'all categories'} on {marketplace}")
    return P.amazon_top_brands(data)
