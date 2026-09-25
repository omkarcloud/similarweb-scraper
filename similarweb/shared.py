"""Value helpers shared by every Similarweb parser: numbers, shares,
durations, dates, category / country naming, headquarters state codes.
Pure functions, no network; every helper tolerates None and junk."""
import html as html_lib
import re

from similarweb import refdata

SHARE_DIGITS = 4        # 0.3884 = 38.84 %
METRIC_DIGITS = 2       # pages per visit, prices


# ---- numbers ---------------------------------------------------------------------

def num(value):
    """int / float / numeric string -> float; bool, junk, NaN -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    try:
        out = float(str(value).strip().replace(",", ""))
    except ValueError:
        return None
    return out if out == out else None


def to_int(value):
    out = num(value)
    return int(round(out)) if out is not None else None


def rounded(value, digits=METRIC_DIGITS):
    out = num(value)
    return round(out, digits) if out is not None else None


def share(value):
    """A 0-1 fraction rounded to SHARE_DIGITS."""
    return rounded(value, SHARE_DIGITS)


def percent_to_share(value):
    """A 0-100 percentage -> a 0-1 fraction."""
    out = num(value)
    return round(out / 100.0, SHARE_DIGITS) if out is not None else None


def positive_int(value):
    """Ranks: 0 / negative (Similarweb's "no rank" markers) -> None."""
    out = to_int(value)
    return out if out and out > 0 else None


def duration_seconds(value):
    """'00:06:02' / '6:02' / 362.4 -> 362."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(value))
    parts = str(value).strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


# ---- text / dates -------------------------------------------------------------------

def text(value):
    """Whitespace-collapsed, HTML-unescaped string; '' -> None."""
    if value is None:
        return None
    out = " ".join(html_lib.unescape(str(value)).replace("\xa0", " ").split())
    return out or None


def iso_date(value):
    """'2026-08-01T00:00:00+00:00' / '2026-08-01' -> '2026-08-01'; the .NET
    zero date '0001-01-01…' -> None."""
    if not value:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value))
    if not match or match.group(1) == "0001":
        return None
    return "-".join(match.groups())


def blank_to_none(value):
    return value if value not in ("", None) else None


# ---- categories ------------------------------------------------------------------------

_SMALL_WORDS = {"and", "or", "of", "the", "in", "for", "to", "a", "on"}
_WORD_FIXES = {"tv": "TV", "ai": "AI", "diy": "DIY", "vpn": "VPN", "ios": "iOS", "seo": "SEO"}


def _title_words(words):
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if low in _WORD_FIXES:
            out.append(_WORD_FIXES[low])
        elif i and low in _SMALL_WORDS:
            out.append(low)
        else:
            out.append(low[:1].upper() + low[1:])
    return " ".join(out)


def category_label(segment):
    """'e-commerce_and_shopping' -> 'E-commerce and Shopping';
    'social-networking' (app url codes) -> 'Social Networking'."""
    segment = (segment or "").strip()
    if not segment:
        return None
    words = segment.split("_") if "_" in segment else segment.split("-")
    return _title_words([w for w in words if w])


def category_id(raw):
    """Similarweb's 'E-commerce_and_Shopping/Marketplace' -> the url-code id
    usable as a `category` param: 'e-commerce-and-shopping/marketplace'."""
    if not raw or raw == "*":
        return None
    return "/".join(p.strip().lower().replace("_", "-") for p in str(raw).split("/") if p.strip())


def category(raw):
    """-> {"id": "e-commerce-and-shopping/marketplace", "name":
    "E-commerce and Shopping > Marketplace"} (a sub equal to its parent is
    shown once); None when absent / 'all'."""
    if not raw or str(raw).strip() in ("*", "unknown"):
        return None
    parts = [p for p in str(raw).split("/") if p.strip()]
    labels = [category_label(p) for p in parts]
    if len(labels) == 2 and labels[0].lower() == labels[1].lower():
        labels = labels[:1]
    return {"id": category_id(raw), "name": " > ".join(labels)}


def app_category(raw):
    """App-store category id ('social-networking', 'games/puzzle') -> {id, name}."""
    return category(raw)


# ---- countries ---------------------------------------------------------------------------

def _country_labels():
    names = {}
    tables = [refdata.MARKET_SHARE_COUNTRIES, refdata.WEBSITE_COUNTRIES] + list(refdata.APP_COUNTRIES.values())
    for table in tables:
        for iso, url_code in table.items():
            names.setdefault(iso, _title_words(url_code.split("-")))
    names.update({"US": "United States", "GB": "United Kingdom", "KR": "South Korea",
                  # url slugs drop accents/apostrophes and flip ISO "X, Y of" names
                  "BO": "Bolivia", "CD": "Congo (Democratic Republic)", "CI": "Côte d'Ivoire",
                  "FM": "Micronesia", "GW": "Guinea-Bissau", "LA": "Laos", "MD": "Moldova",
                  "MK": "North Macedonia", "RE": "Réunion", "TZ": "Tanzania", "VE": "Venezuela",
                  "VG": "British Virgin Islands"})
    return names


COUNTRY_NAMES = _country_labels()


def country(code):
    """ISO alpha-2 -> {"code": "US", "name": "United States"}; None for '*' / junk."""
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return None
    return {"code": code, "name": COUNTRY_NAMES.get(code)}


def country_url_code(iso, table, what):
    """ISO alpha-2 -> Similarweb url code in `table`, or ValueError naming
    the endpoint (`what`) that does not cover the country."""
    if iso is None:
        return None
    code = table.get(iso)
    if not code:
        raise ValueError(f"Similarweb has no {what} for country {iso}.")
    return code


# ---- headquarters ----------------------------------------------------------------------------
# Similarweb encodes a US headquarters state as 840 (ISO numeric USA) followed
# by the state's FIPS code: 8406 = California, 84053 = Washington.
US_STATES_BY_FIPS = {
    1: "Alabama", 2: "Alaska", 4: "Arizona", 5: "Arkansas", 6: "California", 8: "Colorado",
    9: "Connecticut", 10: "Delaware", 11: "District of Columbia", 12: "Florida", 13: "Georgia",
    15: "Hawaii", 16: "Idaho", 17: "Illinois", 18: "Indiana", 19: "Iowa", 20: "Kansas",
    21: "Kentucky", 22: "Louisiana", 23: "Maine", 24: "Maryland", 25: "Massachusetts",
    26: "Michigan", 27: "Minnesota", 28: "Mississippi", 29: "Missouri", 30: "Montana",
    31: "Nebraska", 32: "Nevada", 33: "New Hampshire", 34: "New Jersey", 35: "New Mexico",
    36: "New York", 37: "North Carolina", 38: "North Dakota", 39: "Ohio", 40: "Oklahoma",
    41: "Oregon", 42: "Pennsylvania", 44: "Rhode Island", 45: "South Carolina", 46: "South Dakota",
    47: "Tennessee", 48: "Texas", 49: "Utah", 50: "Vermont", 51: "Virginia", 53: "Washington",
    54: "West Virginia", 55: "Wisconsin", 56: "Wyoming", 72: "Puerto Rico",
}


def us_state(code):
    """840<FIPS> -> state name; anything else -> None."""
    value = str(to_int(code) or "")
    if not value.startswith("840") or len(value) <= 3:
        return None
    return US_STATES_BY_FIPS.get(int(value[3:]))


def headquarters(city, country_code, state_code):
    country_code = (country_code or "").strip().upper() or None
    out = {
        "city": text(city),
        "state": us_state(state_code) if country_code == "US" else None,
        "country": country(country_code) if country_code else None,
    }
    return out if any(out.values()) else None


def value_range(low, high, currency=None):
    """{min, max[, currency]}; None when both ends are unknown."""
    low, high = to_int(low), to_int(high)
    if low is None and high is None:
        return None
    out = {"min": low, "max": high}
    if currency is not None:
        out["currency"] = blank_to_none(currency)
    return out


# ---- traffic sources ----------------------------------------------------------------------------
# Similarweb's channel keys -> readable names.
TRAFFIC_SOURCES = {
    "direct": "direct",
    "organic": "organic_search",
    "paid": "paid_search",
    "referrals": "referrals",
    "social_organic": "organic_social",
    "social_paid": "paid_social",
    "mail": "email",
    "ads": "display_ads",
    "gen_ai": "ai_chatbots",
    "affiliate": "affiliates",
}


def source_name(key):
    key = (key or "").strip().lower()
    return TRAFFIC_SOURCES.get(key, key or None)
