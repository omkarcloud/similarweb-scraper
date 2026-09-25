"""Similarweb input parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrLinkField convention — never a sibling `url`/`domain`
pair). Every resolver returns a plain value so the validated params stay
usable as a response-cache key.

  website     github.com | www.github.com | https://github.com/features?x=1
              | https://www.similarweb.com/website/github.com/#overview
              | similarweb.com/ai-traffic/github.com/ | similarweb.com/company/github.com/
              | https://www.similarsites.com/site/github.com | münchen.de (IDN -> punycode)
              -> "github.com" (host, lower-cased, leading www. dropped)
  app         com.whatsapp (Google Play package) | 310633997 / id310633997 (App Store id)
              | https://play.google.com/store/apps/details?id=com.whatsapp
              | https://apps.apple.com/us/app/whatsapp-messenger/id310633997
              | https://www.similarweb.com/app/google/com.whatsapp/ (also google-play / apple / app-store)
              -> {"store": "google" | "apple", "id": "com.whatsapp" | "310633997"}
  technology  shopify | Google Analytics | https://www.similarweb.com/technology/shopify/
              -> "shopify" / "google-analytics"
  country     US | us | United States | united-states -> "US" (ISO alpha-2); see shared.py
              for the url-code tables
  category    e-commerce-and-shopping | e-commerce-and-shopping/marketplace
              | E-commerce and Shopping | e-commerce_and_shopping/marketplace
              | https://www.similarweb.com/top-websites/e-commerce-and-shopping/marketplace/
              -> {"category": "e-commerce-and-shopping", "subcategory": "marketplace" | None}
"""
import ipaddress
import re
from urllib.parse import parse_qs, unquote, urlparse

SITE = "https://www.similarweb.com"
SIMILARWEB_HOSTS = ("similarweb.com", "www.similarweb.com")
SIMILARSITES_HOSTS = ("similarsites.com", "www.similarsites.com")
# similarweb.com paths whose next segment is the analysed domain
_DOMAIN_PAGES = ("website", "ai-traffic", "company")

_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TLD_RE = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_APPLE_ID_RE = re.compile(r"^(?:id)?(\d{5,12})$", re.I)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-._+]{0,99}$")

WEBSITE_HINT = "Must be a domain (github.com) or a link to a page on it (a similarweb.com/website/ link works too)."


def _parse(value):
    candidate = value
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    elif "://" not in candidate:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    return host, parts, parsed


def _is_ip(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _clean_host(host, raw):
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError(f"'{raw}' is not a valid domain name.")
    if host.startswith("www."):
        host = host[4:]
    if _is_ip(host):
        raise ValueError("IP addresses have no Similarweb data; pass a domain name (github.com).")
    labels = host.split(".")
    if len(labels) < 2 or len(host) > 253 or not all(_LABEL_RE.match(label) for label in labels) \
            or not _TLD_RE.match(labels[-1]):
        raise ValueError(f"'{raw}' is not a valid domain (e.g. github.com).")
    return host


def resolve_website(value):
    """A domain, any page link on it, or a similarweb.com / similarsites.com
    link naming one -> the host without a leading `www.`."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError(WEBSITE_HINT)
    try:
        host, parts, _ = _parse(raw)
    except ValueError:
        raise ValueError(f"'{raw}' is not a valid domain or link.")
    if host in SIMILARWEB_HOSTS:
        if len(parts) >= 2 and parts[0] in _DOMAIN_PAGES:
            return resolve_website(parts[1])
        raise ValueError("similarweb.com links must be /website/<domain>/, /ai-traffic/<domain>/ or /company/<domain>/.")
    if host in SIMILARSITES_HOSTS:
        if len(parts) >= 2 and parts[0] == "site":
            return resolve_website(parts[1])
        raise ValueError("similarsites.com links must be /site/<domain>.")
    if not host:
        raise ValueError(WEBSITE_HINT)
    return _clean_host(host, raw)


# ---- apps --------------------------------------------------------------------------

_STORE_ALIASES = {"google": "google", "google-play": "google", "play": "google", "android": "google",
                  "apple": "apple", "app-store": "apple", "appstore": "apple", "ios": "apple", "itunes": "apple"}
APP_HINT = ("Must be a Google Play package (com.whatsapp), an App Store id (310633997) or a "
            "play.google.com / apps.apple.com / similarweb.com/app link.")


def _app_from_id(value):
    value = value.strip()
    match = _APPLE_ID_RE.match(value)
    if match:
        return {"store": "apple", "id": match.group(1)}
    if _PACKAGE_RE.match(value):
        return {"store": "google", "id": value}
    raise ValueError(APP_HINT)


def resolve_app(value):
    """-> {"store": "google" | "apple", "id": package or numeric id}."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError(APP_HINT)
    low = raw.lower()
    if not (low.startswith(("http://", "https://", "//")) or "/" in raw):
        return _app_from_id(raw)
    host, parts, parsed = _parse(raw)
    if host == "play.google.com":
        package = (parse_qs(parsed.query).get("id") or [""])[0]
        if package and _PACKAGE_RE.match(package):
            return {"store": "google", "id": package}
        raise ValueError("Google Play links must carry ?id=<package>.")
    if host in ("apps.apple.com", "itunes.apple.com"):
        for part in reversed(parts):
            match = _APPLE_ID_RE.match(part)
            if match and part.lower().startswith("id"):
                return {"store": "apple", "id": match.group(1)}
        raise ValueError("App Store links must end in /id<number>.")
    if host in SIMILARWEB_HOSTS and len(parts) >= 3 and parts[0] == "app":
        store = _STORE_ALIASES.get(parts[1].lower())
        if store:
            app = _app_from_id(parts[2])
            if app["store"] != store:
                raise ValueError(f"'{parts[2]}' is not a {store} app id.")
            return app
    raise ValueError(APP_HINT)


# ---- technologies ------------------------------------------------------------------------

def slugify(value):
    """'Google Analytics' / 'Google_Analytics' -> 'google-analytics'."""
    text = unquote(value or "").strip().lower()
    text = re.sub(r"[\s_/]+", "-", text)
    text = re.sub(r"[^a-z0-9\-.+]", "", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def resolve_technology(value):
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Must be a technology slug (shopify), its name or a similarweb.com/technology/ link.")
    if raw.lower().startswith(("http://", "https://", "//")) or "similarweb.com" in raw.lower():
        host, parts, _ = _parse(raw)
        if host in SIMILARWEB_HOSTS and len(parts) >= 2 and parts[0] == "technology":
            raw = parts[-1]
        else:
            raise ValueError("Technology links must be similarweb.com/technology/<slug>/.")
    slug = slugify(raw)
    if not _SLUG_RE.match(slug or ""):
        raise ValueError(f"'{value}' is not a technology name or slug (e.g. shopify, google-analytics).")
    return slug


# ---- countries -------------------------------------------------------------------------------

def _country_names():
    """url code / ISO code -> ISO code, over every table Similarweb publishes."""
    from similarweb import refdata
    names = {}
    tables = [refdata.WEBSITE_COUNTRIES, refdata.MARKET_SHARE_COUNTRIES] + list(refdata.APP_COUNTRIES.values())
    for table in tables:
        for iso, url_code in table.items():
            names[url_code] = iso
            names[iso.lower()] = iso
    names.update({"uk": "GB", "great-britain": "GB", "usa": "US", "us": "US", "america": "US",
                  "united-states-of-america": "US", "korea": "KR", "south-korea": "KR"})
    return names


_COUNTRIES = None
WORLDWIDE = ("worldwide", "world", "global", "all", "*", "ww")


def resolve_country(value):
    """ISO code, English name or Similarweb url code -> ISO alpha-2 ("US");
    'worldwide' -> None. Whether a country is served depends on the
    endpoint (checked there against refdata)."""
    global _COUNTRIES
    if _COUNTRIES is None:
        _COUNTRIES = _country_names()
    key = slugify(value)
    if key in WORLDWIDE or (value or "").strip() in WORLDWIDE:
        return None
    iso = _COUNTRIES.get(key)
    if not iso:
        raise ValueError(f"'{value}' is not a country Similarweb ranks (use an ISO code like US, GB, IN, or 'worldwide').")
    return iso


# ---- categories --------------------------------------------------------------------------------

def _category_parts(value):
    """'E-commerce and Shopping/Marketplace', 'e-commerce_and_shopping/marketplace',
    a top-websites / top-apps link -> ['e-commerce-and-shopping', 'marketplace']."""
    raw = (value or "").strip()
    if raw.lower().startswith(("http://", "https://", "//")) or "similarweb.com" in raw.lower():
        _, parts, _ = _parse(raw)
        parts = [p for p in parts if p not in ("top-websites", "top-apps", "google", "apple", "trending")]
        raw = "/".join(parts)
    pieces = [slugify(p.replace("&", "and")) for p in re.split(r"[/>]", raw) if p.strip()]
    return [p for p in pieces if p and p not in ("all", "all-categories", "*")]


def resolve_website_category(value):
    """-> {"category": url code, "subcategory": url code | None}; None for 'all'.
    A top-websites link may carry a country segment first; it is skipped."""
    from similarweb import refdata
    parts = _category_parts(value)
    parts = [p for p in parts if p not in refdata.WEBSITE_COUNTRIES.values() and p != "worldwide"]
    if not parts:
        return None
    category, sub = parts[0], (parts[1] if len(parts) > 1 else None)
    if category not in refdata.WEBSITE_CATEGORIES:
        # a bare subcategory ("marketplace") -> its parent
        parents = [c for c, subs in refdata.WEBSITE_CATEGORIES.items() if category in subs]
        if len(parents) == 1 and sub is None:
            return {"category": parents[0], "subcategory": category}
        raise ValueError(f"'{value}' is not a Similarweb website category (see /similarweb/top-websites/filters).")
    if sub is not None and sub not in refdata.WEBSITE_CATEGORIES[category]:
        raise ValueError(f"'{sub}' is not a subcategory of {category} (see /similarweb/top-websites/filters).")
    return {"category": category, "subcategory": sub}


def resolve_app_category(value):
    """-> {"category": url code, "subcategory": url code | None}; None for
    'all'. Checked against the store's list by the endpoint (the two stores
    use different category sets)."""
    from similarweb import refdata
    countries = {code for table in refdata.APP_COUNTRIES.values() for code in table.values()}
    parts = _category_parts(value)
    parts = [p for p in parts if p not in ("top-free", "top-paid", "top-grossing", "iphone", "ipad")
             and p not in countries]
    if not parts:
        return None
    return {"category": parts[0], "subcategory": parts[1] if len(parts) > 1 else None}


# ---- Amazon marketplaces ------------------------------------------------------------------------

def resolve_amazon_marketplace(value):
    """amazon.co.uk | co.uk | uk | GB | United Kingdom | https://www.amazon.co.uk/dp/…
    -> "amazon.co.uk" (one of the 15 marketplaces Similarweb covers)."""
    from similarweb import refdata
    raw = (value or "").strip().lower()
    if not raw:
        raise ValueError("Must be an Amazon marketplace (amazon.com, amazon.co.uk, uk, de, ...).")
    if "://" in raw or raw.startswith("www.") or "/" in raw:
        host, _, _ = _parse(raw)
        raw = host[4:] if host.startswith("www.") else host
    markets = refdata.AMAZON_MARKETPLACES
    if raw in markets:
        return raw
    if "amazon." + raw in markets:
        return "amazon." + raw
    by_country = {code: site for site, code in markets.items()}
    aliases = {"us": "usa", "united-states": "usa", "gb": "uk", "united-kingdom": "uk", "mx": "mexico",
               "br": "brazil", "ca": "canada", "de": "germany", "fr": "france", "it": "italy", "es": "spain",
               "nl": "netherlands", "in": "india", "jp": "japan", "se": "sweden", "pl": "poland", "tr": "turkey"}
    key = slugify(raw)
    key = aliases.get(key, key)
    if key in by_country:
        return by_country[key]
    raise ValueError(f"'{value}' is not an Amazon marketplace Similarweb covers: {', '.join(sorted(markets))}.")


# ---- links -----------------------------------------------------------------------------------

def website_link(domain):
    return f"{SITE}/website/{domain}/" if domain else None


def site_link(domain):
    return f"https://{domain}" if domain else None


def app_link(store, app_id):
    if not app_id:
        return None
    return f"{SITE}/app/{store}/{app_id}/"


def store_link(store, app_id):
    if not app_id:
        return None
    if store == "google":
        return f"https://play.google.com/store/apps/details?id={app_id}"
    return f"https://apps.apple.com/app/id{app_id}"


def company_link(domain):
    return f"{SITE}/company/{domain}/" if domain else None


def technology_link(slug):
    return f"{SITE}/technology/{slug}/" if slug else None
