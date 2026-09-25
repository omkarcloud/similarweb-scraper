"""Cache TTL per /similarweb/* endpoint (cache.py, keyed on the validated
params — marshmallow fills the defaults, so an omitted param and its
default share a row).

Similarweb publishes website, company and market-share data MONTHLY (the
snapshot date is the 1st of last month) and app charts DAILY; search and
filter lists barely move. Website answers carry signed ad-creative image
links valid for 7 days, so no website tier may exceed that."""
from datetime import timedelta

# --- raw upstream payloads shared by several routes (fetch.shared_raw) ----------
WEBSITE_RAW_CACHE = timedelta(days=2)

# --- websites -------------------------------------------------------------------
WEBSITE_CACHE = timedelta(days=2)
COMPETITORS_CACHE = timedelta(days=3)
AI_TRAFFIC_CACHE = timedelta(days=3)
SIMILAR_SITES_CACHE = timedelta(days=7)
COMPARE_CACHE = timedelta(days=2)

# --- companies ------------------------------------------------------------------
COMPANY_CACHE = timedelta(days=3)

# --- apps -----------------------------------------------------------------------
APP_CACHE = timedelta(hours=12)
TOP_APPS_CACHE = timedelta(hours=6)
TRENDING_APPS_CACHE = timedelta(hours=12)

# --- rankings / market share ----------------------------------------------------
TOP_WEBSITES_CACHE = timedelta(days=3)
TRENDING_WEBSITES_CACHE = timedelta(days=3)
MARKET_SHARE_CACHE = timedelta(days=7)
SERP_CACHE = timedelta(hours=6)
FILTERS_CACHE = timedelta(days=7)

# --- search -----------------------------------------------------------------------
SEARCH_CACHE = timedelta(days=3)
AUTOCOMPLETE_CACHE = timedelta(days=3)

# --- technologies / Amazon ----------------------------------------------------------
TECHNOLOGY_CACHE = timedelta(days=7)
AMAZON_CACHE = timedelta(days=3)
AMAZON_CATEGORIES_CACHE = timedelta(days=14)
