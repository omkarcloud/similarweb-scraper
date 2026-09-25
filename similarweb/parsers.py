"""Pure parsers: raw Similarweb JSON / page state -> clean API dicts. No
network here; every parser tolerates a partial payload (a missing block
yields null / []) and never raises on odd values. Fixtures live in
similarweb/fixtures/ (captured 2026-09-25).

Response conventions: snake_case, `link` for URLs (a website's own home page;
`similarweb_link` for its Similarweb page), `is_*` booleans, ISO dates
(YYYY-MM-DD), shares as 0-1 fractions (4 decimals), durations in seconds,
counts as ints, null for missing values.

Fields intentionally NOT exposed (and why):
  website    companyFeedbackRecaptcha / feedbackRecaptcha (the site's reCAPTCHA
             site key), compareCompetitor (always null logged-out),
             graphVisitsGrade ('<1B' chart axis) and history.percentageValue
             (chart-scaled values; exact monthly visits are rebuilt from
             visitsTotalCount + percentageChange instead),
             visitsAvgDurationFormatted (turned into seconds),
             countryUrlCode / countryAlpha2CodeRaw (duplicates of the ISO code),
             trafficSources[].isHigher (always null), competitors[].invalidTrafficData
             and referral rows' isAvailable (always true), topAdsSites /
             topReferralSites domain + icon when isLocked (Similarweb blanks them:
             the row is kept with its share and is_locked true).
  traffic    traffic.competitors (the same domains as ranking neighbours,
             without numbers).
  apps       countries[] (the store's whole country list, served by
             /similarweb/apps/filters), storeId / modeId echoes, alpha2CodeRaw.
  company    revenueRanges (the site's static filter buckets), overview.twitter /
             facebook / linkedin / email when null (kept when present).
  top lists  isBlackListed (always false in public lists), filterOptions
             (served by the /filters routes), orderBy echoes.
  amazon     the category tree of every marketplace (served by
             /similarweb/amazon/categories), siteToCountryMap, urlCode/urlName
             duplicates of the id.
  search     screenshots[] of apps and the relative /app/... url (rebuilt as
             similarweb_link), store 0/1 flags (turned into "google"/"apple").
"""
from similarweb import refs
from similarweb import shared as S

# ---- building blocks ------------------------------------------------------------------


def _list(value):
    return value if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


def website_ref(domain, icon=None):
    """The short website object every list uses."""
    domain = S.text(domain)
    if not domain:
        return None
    return {
        "domain": domain,
        "link": refs.site_link(domain),
        "similarweb_link": refs.website_link(domain),
        "favicon": S.blank_to_none(icon),
    }


def screenshots(desktop, mobile):
    out = {"desktop": S.blank_to_none(desktop), "mobile": S.blank_to_none(mobile)}
    return out if any(out.values()) else None


def rank_block(rank, change=None, previous=None):
    return {
        "rank": S.positive_int(rank),
        "change": S.to_int(change),
        "previous": S.positive_int(previous),
    }


def rank_history(rows):
    return [{"date": S.iso_date(r.get("date")), "rank": S.positive_int(r.get("rank"))}
            for r in _list(rows) if isinstance(r, dict)]


def neighbours(rows):
    """Ranking neighbours: the sites ranked just above / below."""
    out = []
    for r in _list(rows):
        site = website_ref(_dict(r).get("domain"), r.get("icon"))
        if site:
            out.append({"rank": S.positive_int(r.get("rank")), **site})
    return out


def locked_site(row):
    """A referral / ad site row; Similarweb blanks the top rows logged-out."""
    row = _dict(row)
    is_locked = bool(row.get("isLocked")) or not S.text(row.get("domain"))
    site = None if is_locked else website_ref(row.get("domain"), row.get("icon"))
    return {
        "domain": site["domain"] if site else None,
        "link": site["link"] if site else None,
        "similarweb_link": site["similarweb_link"] if site else None,
        "favicon": site["favicon"] if site else None,
        "share": S.share(row.get("visitsShare")),
        "is_locked": is_locked,
    }


def share_categories(rows):
    return [{"category": S.category(r.get("category")), "share": S.share(r.get("visitsShare"))}
            for r in _list(rows) if isinstance(r, dict)]


def company_from_website(overview):
    """The company block embedded in the website overview."""
    o = _dict(overview)
    out = {
        "name": S.text(o.get("companyName")),
        "domain": S.text(o.get("companyParentDomain")),
        "similarweb_link": refs.company_link(S.text(o.get("companyParentDomain"))),
        "category": S.category(o.get("companyCategoryId")),
        "year_founded": S.positive_int(o.get("companyYearFounded")),
        "employees": S.value_range(o.get("companyEmployeesMin"), o.get("companyEmployeesMax")),
        "annual_revenue": S.value_range(o.get("companyRevenueMin"), o.get("companyRevenueMax"),
                                        currency=o.get("companyRevenueCurrency") or ("USD" if o.get("companyRevenueMin") else None)),
        "headquarters": S.headquarters(o.get("companyHeadquarterCity"), o.get("companyHeadquarterCountryCode"),
                                       o.get("companyHeadquarterStateCode")),
    }
    return out if out["name"] or out["domain"] else None


def monthly_visits(traffic):
    """Exact visits for the last 3 months: the current month is
    visitsTotalCount; each earlier month is rebuilt from the month-over-month
    percentageChange of the month after it."""
    t = _dict(traffic)
    history = [h for h in _list(t.get("history")) if isinstance(h, dict)]
    current = S.num(t.get("visitsTotalCount"))
    if not history:
        return []
    history = sorted(history, key=lambda h: str(h.get("date")))
    visits = [None] * len(history)
    visits[-1] = current
    for i in range(len(history) - 1, 0, -1):
        change = S.num(history[i].get("percentageChange"))
        if visits[i] is None or change is None or change <= -100:
            break
        visits[i - 1] = visits[i] / (1 + change / 100.0)
    return [{"month": (S.iso_date(h.get("date")) or "")[:7] or None,
             "visits": S.to_int(v),
             "change": S.rounded(S.num(h.get("percentageChange")) / 100.0, S.SHARE_DIGITS)
             if S.num(h.get("percentageChange")) is not None else None}
            for h, v in zip(history, visits)]


def traffic_sources(rows):
    """All 10 channels in Similarweb's order of importance. Logged-out only
    the top channel carries its share and the top 3 carry a rank."""
    out = []
    for r in _list(rows):
        if not isinstance(r, dict):
            continue
        out.append({"source": S.source_name(r.get("source")),
                    "rank": S.positive_int(r.get("rank")),
                    "share": S.share(r.get("percentage"))})
    return sorted(out, key=lambda s: (s["rank"] is None, s["rank"] or 0))


# ---- website sections --------------------------------------------------------------------

def website_identity(raw):
    raw = _dict(raw)
    o = _dict(raw.get("overview"))
    domain = S.text(raw.get("domain"))
    return {
        "domain": domain,
        "link": refs.site_link(domain),
        "similarweb_link": refs.website_link(domain),
        "description": S.text(o.get("description")),
        "category": S.category(raw.get("categoryId")),
        "favicon": S.blank_to_none(raw.get("icon")),
        "screenshots": screenshots(raw.get("previewDesktop"), raw.get("previewMobile")),
    }


def website_meta(raw):
    raw = _dict(raw)
    return {
        "snapshot_date": S.iso_date(raw.get("snapshotDate")),
        "is_data_from_google_analytics": bool(raw.get("isDataFromGa")),
        "is_google_analytics_highly_discrepant": bool(raw.get("isDataFromGaHighlyDiscrepant")),
        "is_invalid_traffic_data": bool(raw.get("isInvalidTrafficData")),
    }


def website_ranking(raw):
    raw = _dict(raw)
    r = _dict(raw.get("ranking"))
    o = _dict(raw.get("overview"))
    code = r.get("countryAlpha2Code") or o.get("countryAlpha2Code")
    return {
        "global": {**rank_block(r.get("globalRank", o.get("globalRank")),
                                r.get("globalRankChange", o.get("globalRankChange")), r.get("globalRankPrev")),
                   "history": rank_history(r.get("globalRankHistory")),
                   "neighbours": neighbours(r.get("globalRankCompetitors"))},
        "country": {"country": S.country(code),
                    **rank_block(r.get("countryRank", o.get("countryRank")),
                                 r.get("countryRankChange", o.get("countryRankChange")), r.get("countryRankPrev")),
                    "history": rank_history(r.get("countryRankHistory")),
                    "neighbours": neighbours(r.get("countryRankCompetitors"))},
        "category": {"category": S.category(raw.get("categoryId")),
                     **rank_block(r.get("categoryRank", o.get("categoryRank")),
                                  r.get("categoryRankChange", o.get("categoryRankChange")), r.get("categoryRankPrev")),
                     "history": rank_history(r.get("categoryRankHistory")),
                     "neighbours": neighbours(r.get("categoryRankCompetitors"))},
    }


def website_ranks_short(raw):
    """Global / country / category rank without histories (details + compare)."""
    full = website_ranking(raw)
    return {
        "global_rank": full["global"]["rank"],
        "global_rank_change": full["global"]["change"],
        "country": full["country"]["country"],
        "country_rank": full["country"]["rank"],
        "country_rank_change": full["country"]["change"],
        "category_rank": full["category"]["rank"],
        "category_rank_change": full["category"]["change"],
    }


def website_engagement(raw):
    raw = _dict(raw)
    t = _dict(raw.get("traffic"))
    o = _dict(raw.get("overview"))
    return {
        "visits": S.to_int(t.get("visitsTotalCount", o.get("visitsTotalCount"))),
        "visits_change": S.share(t.get("visitsTotalCountChange")),
        "bounce_rate": S.share(t.get("bounceRate", o.get("bounceRate"))),
        "pages_per_visit": S.rounded(t.get("pagesPerVisit", o.get("pagesPerVisit"))),
        "avg_visit_duration_seconds": S.duration_seconds(
            t.get("visitsAvgDurationFormatted") or o.get("visitsAvgDurationFormatted")),
        "monthly_visits": monthly_visits(t),
    }


def website_geography(raw):
    g = _dict(_dict(raw).get("geography"))
    return {
        "countries_count": S.to_int(g.get("countriesTotalCount")),
        "top_countries": [{"country": S.country(c.get("countryAlpha2Code")),
                           "share": S.share(c.get("visitsShare")),
                           "share_change": S.share(c.get("visitsShareChange"))}
                          for c in _list(g.get("topCountriesTraffics")) if isinstance(c, dict)],
    }


def website_demographics(raw):
    d = _dict(_dict(raw).get("demographics"))
    gender = _dict(d.get("genderDistribution"))
    ages = []
    for a in _list(d.get("ageDistribution")):
        if not isinstance(a, dict):
            continue
        low, high = S.to_int(a.get("minAge")), S.to_int(a.get("maxAge"))
        ages.append({"age_range": f"{low}-{high}" if high else f"{low}+",
                     "min_age": low, "max_age": high, "share": S.share(a.get("value"))})
    if not any(a["share"] for a in ages):
        ages = []       # small sites: Similarweb reports every bucket as 0
    male, female = S.share(gender.get("male")), S.share(gender.get("female"))
    return {
        "gender": {"male": male, "female": female} if male is not None or female is not None else None,
        "age": ages,
    }


def website_interests(raw):
    i = _dict(_dict(raw).get("interests"))
    return {
        "categories": [S.category(c) for c in _list(i.get("topInterestedCategories")) if c],
        "topics": [S.text(t) for t in _list(i.get("topInterestedTopics")) if S.text(t)],
        "websites": [w for w in (website_ref(_dict(s).get("domain"), _dict(s).get("icon"))
                                 for s in _list(i.get("topInterestedWebsites"))) if w],
        "websites_count": S.to_int(i.get("interestedWebsitesTotalCount")),
    }


def website_similar(raw):
    """The overview's 10 most similar sites (affinity 0-1)."""
    out = []
    for c in _list(_dict(_dict(raw).get("competitors")).get("topSimilarityCompetitors")):
        site = website_ref(_dict(c).get("domain"), c.get("icon"))
        if not site:
            continue
        out.append({**site, "category": S.category(c.get("categoryId")),
                    "category_rank": S.positive_int(c.get("categoryRank")),
                    "affinity": S.share(c.get("affinity")),
                    "is_data_from_google_analytics": bool(c.get("isDataFromGa"))})
    return out


def website_keywords(raw):
    s = _dict(_dict(raw).get("searchesSource"))
    return {
        "organic_share": S.share(s.get("organicSearchShare")),
        "paid_share": S.share(s.get("paidSearchShare")),
        "keywords_count": S.to_int(s.get("keywordsTotalCount")),
        "top_keywords": [{"keyword": S.text(k.get("name")),
                          "cpc": S.rounded(k.get("cpc")),
                          "search_volume": S.to_int(k.get("volume")),
                          "estimated_value": S.rounded(k.get("estimatedValue"))}
                         for k in _list(s.get("topKeywords")) if isinstance(k, dict) and S.text(k.get("name"))],
    }


def website_referrals(raw):
    raw = _dict(raw)
    inc = _dict(raw.get("incomingReferrals"))
    out = _dict(raw.get("outgoingReferrals"))
    return {
        "incoming": {
            "sites_count": S.to_int(inc.get("referralSitesTotalCount")),
            "top_sites": [locked_site(r) for r in _list(inc.get("topReferralSites"))],
            "top_categories": share_categories(inc.get("topIncomingCategories")),
        },
        "outgoing": {
            "sites_count": S.to_int(out.get("outgoingSitesTotalCount")),
            "top_sites": [locked_site(r) for r in _list(out.get("topOutgoingSites"))],
            "top_categories": share_categories(out.get("topOutgoingCategories")),
        },
    }


def website_social(raw):
    s = _dict(_dict(raw).get("socialNetworksSource"))
    return {
        "networks_count": S.to_int(s.get("socialNetworksTotalCount")),
        "top_networks": [{"name": S.text(n.get("name")), "share": S.share(n.get("visitsShare")),
                          "icon": S.blank_to_none(n.get("icon"))}
                         for n in _list(s.get("topSocialNetworks")) if isinstance(n, dict)],
    }


def website_ads(raw):
    raw = _dict(raw)
    a = _dict(raw.get("adsSource"))
    recent = _dict(raw.get("recentAds"))
    return {
        "publishers_count": S.to_int(a.get("adsSitesTotalCount")),
        "ad_networks_count": S.to_int(a.get("adsNetworksTotalCount")),
        "top_publishers": [locked_site(r) for r in _list(a.get("topAdsSites"))],
        "recent_ads": [{"id": S.text(c.get("creativeId")),
                        "image": S.blank_to_none(c.get("preview")),
                        "width": S.to_int(c.get("width")),
                        "height": S.to_int(c.get("height")),
                        "active_days": S.to_int(c.get("activeDays"))}
                       for c in _list(recent.get("recentAds")) if isinstance(c, dict)],
        "has_more_ads": bool(recent.get("isMoreAds")),
    }


def website_technologies(raw):
    t = _dict(_dict(raw).get("technologies"))
    return {
        "technologies_count": S.to_int(t.get("technologiesTotalCount")),
        "categories_count": S.to_int(t.get("categoriesTotalCount")),
        "categories": [{"category": S.category(c.get("categoryId")),
                        "technologies_count": S.to_int(c.get("technologiesTotalCount")),
                        "top_technology": {"name": S.text(c.get("topTechName")),
                                           "icon": S.blank_to_none(c.get("topTechIconUrl"))}}
                       for c in _list(t.get("categories")) if isinstance(c, dict)],
    }


def website_details(raw):
    """Everything the logged-out website analysis carries, grouped."""
    raw = _dict(raw)
    return {
        **website_identity(raw),
        "company": company_from_website(raw.get("overview")),
        "ranks": website_ranks_short(raw),
        "traffic": website_engagement(raw),
        "traffic_sources": traffic_sources(raw.get("trafficSources")),
        "geography": website_geography(raw),
        "demographics": website_demographics(raw),
        "interests": website_interests(raw),
        "similar_sites": website_similar(raw),
        "keywords": website_keywords(raw),
        "referrals": website_referrals(raw),
        "social": website_social(raw),
        "ads": website_ads(raw),
        "technologies": website_technologies(raw),
        **website_meta(raw),
    }


def website_summary(raw):
    """The compact per-site row of /websites/compare."""
    raw = _dict(raw)
    engagement = website_engagement(raw)
    sources = traffic_sources(raw.get("trafficSources"))
    geo = website_geography(raw)
    return {
        **website_identity(raw),
        "company_name": (company_from_website(raw.get("overview")) or {}).get("name"),
        **website_ranks_short(raw),
        **engagement,
        "top_traffic_source": sources[0] if sources and sources[0]["share"] is not None else None,
        "top_country": geo["top_countries"][0] if geo["top_countries"] else None,
        "snapshot_date": S.iso_date(raw.get("snapshotDate")),
    }


# ---- competitors page ------------------------------------------------------------------------

def _competitor_row(c):
    c = _dict(c)
    site = website_ref(c.get("domain"), c.get("icon"))
    if not site:
        return None
    return {
        **site,
        "description": S.text(c.get("description")),
        "category": S.category(c.get("categoryId")),
        "company_name": S.text(c.get("companyName")),
        "affinity": S.share(c.get("affinity")),
        "global_rank": S.positive_int(c.get("globalRank")),
        "global_rank_change": S.to_int(c.get("globalRankChange")),
        "country": S.country(c.get("countryAlpha2Code")),
        "country_rank": S.positive_int(c.get("countryRank")),
        "country_rank_change": S.to_int(c.get("countryRankChange")),
        "category_rank": S.positive_int(c.get("categoryRank")),
        "category_rank_change": S.to_int(c.get("categoryRankChange")),
        "bounce_rate": S.share(c.get("bounceRate")),
        "pages_per_visit": S.rounded(c.get("pagesPerVisit")),
        "avg_visit_duration_seconds": S.duration_seconds(c.get("visitsAvgDurationFormatted")),
        "screenshots": screenshots(c.get("previewDesktop"), c.get("previewMobile")),
        "is_data_from_google_analytics": bool(c.get("isDataFromGa")),
    }


def competitors_page(data):
    data = _dict(data)
    me = _competitor_row(data) or {}
    me.pop("affinity", None)
    return {
        "website": me or None,
        "competitors": [r for r in (_competitor_row(c) for c in _list(data.get("competitors"))) if r],
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


# ---- AI traffic ------------------------------------------------------------------------------

def ai_traffic(data, prompts=None):
    data = _dict(data)
    traffic = _dict(data.get("traffic"))
    dist = _dict(traffic.get("distribution"))
    ranks = {S.text(s.get("name")): S.positive_int(s.get("rank")) for s in _list(traffic.get("split"))
             if isinstance(s, dict)}
    shares = {S.text(c.get("name")): S.percent_to_share(c.get("value")) for c in _list(dist.get("chatbots"))
              if isinstance(c, dict)}
    history = {}
    for c in _list(dist.get("chart")):
        if isinstance(c, dict):
            history[S.text(c.get("name"))] = sorted(
                ({"month": (S.iso_date(h.get("date")) or "")[:7] or None, "share": S.percent_to_share(h.get("value"))}
                 for h in _list(c.get("history")) if isinstance(h, dict)), key=lambda h: h["month"] or "")
    chatbots = []
    icons = {S.text(s.get("name")): s.get("icon") for s in _list(traffic.get("split")) if isinstance(s, dict)}
    for name in sorted(set(ranks) | set(shares), key=lambda n: (ranks.get(n) is None, ranks.get(n) or 0, -(shares.get(n) or 0))):
        if not name:
            continue
        chatbots.append({"name": name, "link": refs.site_link(name), "rank": ranks.get(name),
                         "share": shares.get(name), "icon": S.blank_to_none(icons.get(name)),
                         "share_history": history.get(name, [])})
    domain = S.text(data.get("domain"))
    o = _dict(data.get("overview"))
    return {
        "domain": domain,
        "link": refs.site_link(domain),
        "similarweb_link": f"{refs.SITE}/ai-traffic/{domain}/" if domain else None,
        "description": S.text(o.get("description")),
        "favicon": S.blank_to_none(data.get("icon")),
        "ai_visits": S.to_int(data.get("totalVisits")),
        "ai_share_of_traffic": S.share(data.get("referralTraffic")),
        "ai_visits_range": S.text(dist.get("boundary")),
        "chatbots": chatbots,
        "top_prompts": [S.text(p) for p in _list(prompts) if S.text(p)],
        "company": {
            "name": S.text(o.get("companyName")),
            "category": S.category(o.get("companyCategoryId")),
            "year_founded": S.positive_int(o.get("companyYearFounded")),
            "employees": S.value_range(o.get("companyEmployeesMin"), o.get("companyEmployeesMax")),
            "annual_revenue": S.value_range(o.get("companyRevenueMin"), o.get("companyRevenueMax"),
                                            currency="USD" if o.get("companyRevenueMin") else None),
            "headquarters": S.headquarters(o.get("headquarterCity"), o.get("headquarterCountryCode"),
                                           o.get("headquarterStateCode")),
        } if o.get("companyName") else None,
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


# ---- similarsites.com -----------------------------------------------------------------------

def similar_sites(data, domain):
    data = _dict(data)
    sites = []
    for s in _list(data.get("SimilarSites")):
        site = website_ref(_dict(s).get("Site"))
        if not site:
            continue
        sites.append({
            "rank": S.positive_int(s.get("SimilarityRank")),
            **site,
            "description": S.text(s.get("Description")),
            "category": S.category(s.get("Category")),
            "similarity": S.share(s.get("Grade")),
            "visits": S.to_int(s.get("TotalVisits")),
            "top_country_rank": S.positive_int(s.get("TopCountryRank")),
            "screenshot": S.blank_to_none(s.get("Thumbnail")),
        })
    sites.sort(key=lambda s: (s["rank"] is None, s["rank"] or 0))
    apps = []
    for a in _list(data.get("RelatedApps")):
        a = _dict(a)
        store = {"ANDROID": "google", "IOS": "apple", "IPHONE": "apple"}.get(str(a.get("Type") or "").upper())
        link = S.blank_to_none(a.get("Url"))
        app_id = None
        if link:
            try:
                app_id = refs.resolve_app(link)["id"]
            except ValueError:
                app_id = None
        apps.append({"rank": S.positive_int(a.get("Ranking")), "id": app_id, "name": S.text(a.get("Title")),
                     "store": store, "link": link, "icon": S.blank_to_none(a.get("Icon")),
                     "similarweb_link": refs.app_link(store, app_id) if store and app_id else None})
    redirect = S.text(data.get("Redirect"))
    return {
        "domain": domain,
        "link": refs.site_link(domain),
        "title": S.text(data.get("Title")),
        "description": S.text(data.get("Description")),
        "category": S.category(data.get("Category")),
        "category_rank": S.positive_int(data.get("CategoryRank")),
        "visits": S.to_int(data.get("TotalVisits")),
        "tags": [S.text(t.get("Tag")) for t in _list(data.get("Tags")) if isinstance(t, dict) and S.text(t.get("Tag"))],
        "favicon": S.blank_to_none(data.get("Favicon")),
        "screenshot": S.blank_to_none(data.get("Thumbnail")),
        "redirects_to": redirect if redirect and redirect != domain else None,
        "similar_sites": sites,
        "related_apps": apps,
    }


# ---- companies --------------------------------------------------------------------------------

def _history_map(mapping, value_fn):
    rows = []
    for date, value in sorted(_dict(mapping).items()):
        rows.append({"month": (S.iso_date(date) or "")[:7] or None, **value_fn(value)})
    return rows


def company(data):
    data = _dict(data)
    domain = S.text(data.get("domain"))
    o = _dict(data.get("overview"))
    visits = _dict(data.get("visitsHistory")).get(domain) or next(iter(_dict(data.get("visitsHistory")).values()), {})
    durations = _dict(data.get("averageDurationHistory")).get(domain) or {}
    pages = _dict(data.get("pagesPerVisitHistory")).get(domain) or {}
    months = sorted(set(_dict(visits)) | set(_dict(durations)) | set(_dict(pages)))
    traffic = [{"month": (S.iso_date(m) or "")[:7] or None,
                "visits": S.to_int(_dict(visits).get(m)),
                "avg_visit_duration_seconds": S.duration_seconds(_dict(durations).get(m)),
                "pages_per_visit": S.rounded(_dict(pages).get(m))} for m in months]
    competitors = []
    for c in _list(_dict(data.get("competitors")).get(domain)) or \
            [x for rows in _dict(data.get("competitors")).values() for x in _list(rows)]:
        c = _dict(c)
        cd = S.text(c.get("domain"))
        if not cd:
            continue
        competitors.append({
            "name": S.text(c.get("name")),
            **website_ref(cd, c.get("icon")),
            "company_domain": S.text(c.get("parentDomain")),
            "category": S.category(c.get("categoryId")),
            "visits": S.to_int(c.get("totalVisits")),
            "employees": S.value_range(c.get("employeesMin"), c.get("employeesMax")),
            "annual_revenue": S.value_range(c.get("revenueMin"), c.get("revenueMax"),
                                            currency=c.get("revenueCurrency") or ("USD" if c.get("revenueMin") else None)),
            "headquarters": S.headquarters(c.get("headquarterCity"), c.get("headquarterCountryCode"),
                                           c.get("headquarterStateCode")),
        })
    tickers = [{"symbol": S.text(t.get("symbol")), "exchange": S.text(t.get("exchangeName")),
                "exchange_code": S.text(t.get("exchangeCode")), "country": S.text(t.get("country"))}
               for t in _list(_dict(data.get("stocks")).get("tickers")) if isinstance(t, dict)]
    revenue = [{"year": S.to_int(year), "revenue": S.to_int(value)}
               for rows in _dict(data.get("revenue")).values() for year, value in sorted(_dict(rows).items())]
    tech = _dict(_dict(data.get("technologies")).get(domain))
    social = {k: S.blank_to_none(o.get(k)) for k in ("twitter", "facebook", "linkedin")}
    return {
        "name": S.text(data.get("name")),
        "domain": domain,
        "link": refs.site_link(domain),
        "similarweb_link": refs.company_link(domain),
        "type": S.text(data.get("type")),
        "description": S.text(o.get("description")),
        "logo": S.blank_to_none(data.get("icon")),
        "category": S.category(data.get("categoryId")),
        "year_founded": S.positive_int(o.get("yearFounded")),
        "employees": S.value_range(o.get("employeesMin"), o.get("employeesMax")),
        "annual_revenue": S.value_range(o.get("revenueMin"), o.get("revenueMax"),
                                        currency=o.get("revenueCurrency") or ("USD" if o.get("revenueMin") else None)),
        "revenue_by_year": revenue,
        "headquarters": S.headquarters(o.get("headquarterCity"), o.get("headquarterCountryCode"),
                                       o.get("headquarterStateCode")),
        "contact": {"phone": S.text(o.get("phone")), "email": S.text(o.get("email"))},
        "social_profiles": social if any(social.values()) else None,
        "stock_tickers": tickers,
        "is_public": bool(tickers) or (S.text(data.get("type")) or "").lower() == "public",
        "websites": [w for w in (website_ref(_dict(s).get("domain"), _dict(s).get("icon"))
                                 for s in _list(data.get("subsidiaries"))) if w],
        "traffic": traffic,
        "competitors": competitors,
        "news": [{"title": S.text(n.get("title")), "description": S.text(n.get("description")),
                  "link": S.blank_to_none(n.get("link")), "date": S.iso_date(n.get("date"))}
                 for n in _list(data.get("signals")) if isinstance(n, dict)],
        "technologies": website_technologies({"technologies": tech}) if tech else None,
        "category_benchmarks": {
            "total_visits": S.to_int(data.get("categoryTotalVisits")),
            "pages_per_visit": S.rounded(data.get("categoryPagesPerVisit")),
            "top_companies": [{**website_ref(_dict(t).get("domain"), t.get("icon")),
                               "visits": S.to_int(t.get("visits"))}
                              for t in _list(data.get("topCompaniesInCategory"))
                              if isinstance(t, dict) and S.text(t.get("domain"))],
        },
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


# ---- apps -------------------------------------------------------------------------------------

def app_ref(store, app_id, name=None, icon=None, publisher=None):
    app_id = S.text(app_id)
    if not app_id:
        return None
    return {"id": app_id, "name": S.text(name), "store": store,
            "link": refs.store_link(store, app_id), "similarweb_link": refs.app_link(store, app_id),
            "icon": S.blank_to_none(icon), "publisher": S.text(publisher)}


def _country_ranks(rows):
    return [{"country": S.country(r.get("countryAlpha2Code")), "rank": S.positive_int(r.get("rank")),
             "change": S.to_int(r.get("rankChange"))} for r in _list(rows) if isinstance(r, dict)]


def app_details(data):
    data = _dict(data)
    store = "apple" if str(data.get("storeId") or "").lower() in ("apple", "1") else "google"
    o = _dict(data.get("overview"))
    ranking = _dict(data.get("ranking"))
    geo = _dict(data.get("geographyRanking"))
    base = app_ref(store, data.get("id"), data.get("name"), data.get("icon"), o.get("author")) or {}
    interests = []
    for c in _list(_dict(data.get("interests")).get("topInterestedCategories")):
        c = _dict(c)
        interests.append({"category": S.app_category(c.get("categoryId")),
                          "affinity": S.share(c.get("affinity")),
                          "apps_count": S.to_int(c.get("categoryAppsTotalCount")),
                          "top_apps": [{**(app_ref(store, a.get("id"), a.get("name"), a.get("icon")) or {}),
                                        "affinity": S.share(a.get("affinity"))}
                                       for a in _list(c.get("topApps")) if isinstance(a, dict) and a.get("id")]})
    return {
        **base,
        "description": S.text(o.get("description")),
        "category": S.app_category(data.get("categoryId")),
        "rating": S.rounded(o.get("rating")),
        "last_release_date": S.iso_date(o.get("lastReleaseDate")),
        "preview": S.blank_to_none(o.get("preview")),
        "country": S.country(data.get("countryAlpha2Code")),
        "store_rank": S.positive_int(data.get("storeRank")),
        "category_store_rank": S.positive_int(data.get("categoryStoreRank")),
        "category_store_rank_change": S.to_int(ranking.get("categoryStoreRankChange")),
        "usage_rank": S.positive_int(data.get("usageRank")),
        "category_usage_rank": S.positive_int(data.get("categoryUsageRank")),
        "rank_history": [{"date": S.iso_date(h.get("date")),
                          "store_rank": S.positive_int(h.get("storeRank")),
                          "category_store_rank": S.positive_int(h.get("categoryStoreRank")),
                          "usage_rank": S.positive_int(h.get("usageRank")),
                          "category_usage_rank": S.positive_int(h.get("categoryUsageRank"))}
                         for h in _list(ranking.get("history")) if isinstance(h, dict)],
        "top_countries": {
            "store_rank": _country_ranks(geo.get("storeRanking")),
            "category_store_rank": _country_ranks(geo.get("categoryStoreRanking")),
            "usage_rank": _country_ranks(geo.get("usageRanking")),
            "category_usage_rank": _country_ranks(geo.get("categoryUsageRanking")),
        },
        "audience_interests": interests,
        "competitors": [r for r in (app_ref(store, c.get("id"), c.get("name"), c.get("icon"), c.get("author"))
                                    for c in _list(data.get("competitors")) if isinstance(c, dict)) if r],
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


def app_chart_row(a, store, position):
    a = _dict(a)
    base = app_ref(store, a.get("id"), a.get("name"), a.get("favicon"), a.get("publisher"))
    if not base:
        return None
    return {
        "position": position,
        **base,
        "category": S.app_category(a.get("categoryId")),
        "store_rank": S.positive_int(a.get("storeRank")),
        "store_rank_change": S.to_int(a.get("storeRankChange")),
        "is_new_in_store_rank": bool(a.get("isStoreRankNew")),
        "usage_rank": S.positive_int(a.get("usageRank")),
        "usage_rank_change": S.to_int(a.get("usageRankChange")) if S.positive_int(a.get("usageRank")) else None,
        "is_new_in_usage_rank": bool(a.get("isUsageRankNew")),
    }


def top_apps(data, store):
    data = _dict(data)
    apps = [r for r in (app_chart_row(a, store, i) for i, a in enumerate(_list(data.get("apps")), 1)) if r]
    return {
        "sort": "usage_rank" if data.get("orderBy") == "app-index" else "store_rank",
        "has_usage_rank": not bool(data.get("isUsageRankNoData")) and any(a["usage_rank"] for a in apps),
        "apps": apps,
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


def trending_apps(data, store):
    data = _dict(data)

    def rows(key):
        return [r for r in (app_chart_row(a, store, i) for i, a in enumerate(_list(data.get(key)), 1)) if r]
    return {
        "rising": rows("increasingApps"),
        "falling": rows("decreasingApps"),
        "new_entries": rows("inApps"),
        "dropped_out": rows("outApps"),
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


def app_filters(filter_options):
    out = {}
    for store in ("google", "apple"):
        fo = _dict(_dict(filter_options).get(store))
        out[store] = {
            "countries": [{**(S.country(c.get("alpha2Code")) or {}), "has_usage_rank": bool(c.get("isUsageRankAllowed"))}
                          for c in _list(fo.get("countries")) if isinstance(c, dict) and c.get("alpha2Code")],
            "categories": [{"id": c.get("urlCode"), "name": S.category_label(c.get("urlCode")),
                            "subcategories": [{"id": f"{c.get('urlCode')}/{i.get('urlCode')}",
                                               "name": S.category_label(i.get("urlCode"))}
                                              for i in _list(c.get("items")) if isinstance(i, dict)]}
                           for c in _list(fo.get("categories")) if isinstance(c, dict) and c.get("id") != "*"],
            "chart_types": [m.replace("top-", "") for m in _list(fo.get("modes")) if isinstance(m, str)],
            "devices": [d for d in _list(fo.get("devices")) if isinstance(d, str)],
        }
    return out


# ---- top websites ----------------------------------------------------------------------------------

def top_websites(data):
    data = _dict(data)
    sites = []
    for i, s in enumerate(_list(data.get("sites")), 1):
        site = website_ref(_dict(s).get("domain"), s.get("favicon"))
        if not site:
            continue
        sites.append({"rank": i, **site, "rank_change": S.to_int(s.get("rankChange")),
                      "is_new": bool(s.get("isNewRank")),
                      "category": S.category(s.get("categoryId")),
                      "avg_visit_duration_seconds": S.duration_seconds(s.get("visitsAvgDurationFormatted")),
                      "pages_per_visit": S.rounded(s.get("pagesPerVisit")),
                      "bounce_rate": S.share(s.get("bounceRate"))})
    return {
        "country": S.country(data.get("countryAlpha2Code")),
        "category": S.category(data.get("categoryId")),
        "websites": sites,
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


def trending_websites(data):
    data = _dict(data)

    def rows(key):
        out = []
        for s in _list(data.get(key)):
            site = website_ref(_dict(s).get("domain"), s.get("favicon"))
            if site:
                out.append({**site, "rank": S.positive_int(s.get("rank")), "rank_change": S.to_int(s.get("rankChange")),
                            "is_new": bool(s.get("isTotallyNew"))})
        return out
    return {
        "country": S.country(data.get("countryAlpha2Code")),
        "category": S.category(data.get("categoryId")),
        "rising": rows("increasingWebsites"),
        "falling": rows("decreasingWebsites"),
        "new_entries": rows("inWebsites"),
        "dropped_out": rows("outWebsites"),
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


def website_filters(page):
    page = _dict(page)
    return {
        "countries": [S.country(c.get("alpha2Code")) for c in _list(page.get("countries"))
                      if isinstance(c, dict) and c.get("alpha2Code") not in (None, "*")],
        "categories": [{"id": c.get("urlCode"), "name": S.category_label(c.get("id")),
                        "subcategories": [{"id": f"{c.get('urlCode')}/{i.get('urlCode')}",
                                           "name": S.category_label(i.get("id"))}
                                          for i in _list(c.get("items")) if isinstance(i, dict)]}
                       for c in _list(page.get("categories")) if isinstance(c, dict) and c.get("id") != "*"],
    }


# ---- market share -----------------------------------------------------------------------------------

def _leader_name(name, kind):
    name = S.text(name)
    if kind == "devices":
        return {"mobilephone": "mobile", "desktop": "desktop", "tablet": "tablet"}.get((name or "").lower(), name)
    return name


def market_share(data, kind):
    data = _dict(data)
    leaders = [{"name": _leader_name(l.get("name"), kind), "share": S.share(l.get("value"))}
               for l in _list(data.get("leaders")) if isinstance(l, dict)]
    history = {}
    for row in _list(data.get("leadersHistory")):
        if isinstance(row, dict):
            history[_leader_name(row.get("name"), kind)] = sorted(
                ({"month": (S.iso_date(h.get("date")) or "")[:7] or None, "share": S.share(h.get("value"))}
                 for h in _list(row.get("history")) if isinstance(h, dict)), key=lambda h: h["month"] or "")
    for leader in leaders:
        leader["history"] = history.get(leader["name"], [])
    by_country = {}
    for row in _list(data.get("leadersGeography")):
        if not isinstance(row, dict) or not row.get("alpha2Code"):
            continue
        entry = by_country.setdefault(row["alpha2Code"], {"country": S.country(row["alpha2Code"]), "leaders": []})
        entry["leaders"].append({"name": _leader_name(row.get("name"), kind), "share": S.share(row.get("value"))})
    return {
        "leaders": leaders,
        "by_country": list(by_country.values()),
        "snapshot_date": S.iso_date(data.get("snapshotDate")),
    }


# ---- search ---------------------------------------------------------------------------------------------

def search(data):
    data = _dict(data)

    def apps(rows, store):
        out = []
        for a in _list(rows):
            a = _dict(a)
            base = app_ref(store, a.get("appId"), a.get("name"), a.get("icon"), a.get("author"))
            if base:
                out.append({**base, "category": S.app_category(a.get("categoryId")),
                            "description": S.text(a.get("description"))})
        return out
    websites = []
    for w in _list(data.get("websites")):
        site = website_ref(_dict(w).get("name"), w.get("favicon"))
        if site:
            websites.append({**site, "description": S.text(w.get("description")),
                             "category": S.category(w.get("categoryId")),
                             "screenshots": screenshots(w.get("desktopImage"), w.get("mobileImage"))})
    companies = []
    for c in _list(data.get("companies")):
        c = _dict(c)
        domain = S.text(c.get("domain"))
        if domain:
            companies.append({"name": S.text(c.get("name")), "domain": domain, "link": refs.site_link(domain),
                              "similarweb_link": refs.company_link(domain), "logo": S.blank_to_none(c.get("logoUrl")),
                              "category": S.category(c.get("categoryId")), "description": S.text(c.get("description"))})
    return {
        "websites": websites,
        "google_play_apps": apps(data.get("googleApps"), "google"),
        "app_store_apps": apps(data.get("appleApps"), "apple"),
        "companies": companies,
    }


def autocomplete(data):
    data = _dict(data)
    sites = [website_ref(_dict(w).get("name"), w.get("image")) for w in _list(data.get("websites"))]
    apps_block = _dict(data.get("apps"))

    def apps(rows, store):
        out = []
        for a in _list(rows):
            a = _dict(a)
            base = app_ref(store, a.get("id"), a.get("name"), a.get("image"), a.get("publisher"))
            if base:
                out.append({**base, "ratings_count": S.to_int(a.get("ratings"))})
        return out
    return {
        "websites": [s for s in sites if s],
        "google_play_apps": apps(apps_block.get("googlePlay"), "google"),
        "app_store_apps": apps(apps_block.get("appStore"), "apple"),
    }


# ---- technologies -----------------------------------------------------------------------------------------

def technology(data, slug):
    data = _dict(data)
    return {
        "name": S.text(data.get("name")),
        "slug": slug,
        "similarweb_link": refs.technology_link(slug),
        "link": S.blank_to_none(data.get("url")),
        "description": S.text(data.get("description")),
        "category": S.text(data.get("category")),
        "subcategory": S.text(data.get("subCategory")),
        "pricing": S.text(data.get("paymentType")),
        "logo": S.blank_to_none(data.get("logoUrl")),
        "websites_count": S.to_int(data.get("totalSites")),
        "market_share": S.rounded(data.get("marketShare"), 6),
        "top_websites": [{**website_ref(_dict(s).get("name"), s.get("icon")), "share": S.share(s.get("visitsShare"))}
                         for s in _list(data.get("siteTrafficShares"))
                         if isinstance(s, dict) and S.text(s.get("name"))],
        "top_countries": [{"country": S.country(c.get("countryAlpha2Code")), "share": S.share(c.get("visitsShare"))}
                          for c in _list(data.get("technologiesCountryPercentage")) if isinstance(c, dict)],
        "top_website_categories": share_categories(data.get("technologiesCategoryPercentage")),
        "alternatives": [{"name": S.text(t.get("name")), "category": S.text(t.get("category")),
                          "pricing": S.text(t.get("paymentType")), "logo": S.blank_to_none(t.get("logoUrl"))}
                         for t in _list(data.get("topRelatedCategories")) if isinstance(t, dict)],
        "updated_date": S.iso_date(data.get("date")),
    }


# ---- SERP volatility -------------------------------------------------------------------------------------

def serp_volatility(data):
    data = _dict(data)

    def device(block):
        block = _dict(block)
        return {"current_average": S.to_int(block.get("averageCurrent")),
                "previous_average": S.to_int(block.get("averagePrevious")),
                "overall_average": S.to_int(block.get("totalAverage")),
                "daily": [{"date": S.iso_date(i.get("date")), "risk_index": S.to_int(i.get("riskIndex"))}
                          for i in _list(block.get("items")) if isinstance(i, dict)]}
    return {
        "current_average": S.to_int(data.get("averageCurrent")),
        "previous_average": S.to_int(data.get("averagePrevious")),
        "overall_average": S.to_int(data.get("averageTotal")),
        "desktop": device(data.get("desktop")),
        "mobile": device(data.get("mobile")),
    }


# ---- Amazon (shopper intelligence) ----------------------------------------------------------------------

def _amazon_tree(node, depth=0):
    node = _dict(node)
    return {"id": S.text(node.get("urlCode")) or S.text(node.get("id")),
            "name": S.text(node.get("label")),
            "subcategories": [_amazon_tree(c, depth + 1) for c in _list(node.get("items")) if isinstance(c, dict)]}


def amazon_categories(data, marketplace):
    roots = _list(_dict(_dict(data).get("categories")).get(marketplace))
    return {"marketplace": marketplace, "categories": [_amazon_tree(r) for r in roots if isinstance(r, dict)]}


def _units_tree(node):
    node = _dict(node)
    return {"id": S.text(node.get("id")), "name": S.text(node.get("label")),
            "units_sold": S.to_int(node.get("unitsSold")),
            "subcategories": [_units_tree(c) for c in _list(node.get("items")) if isinstance(c, dict)]}


CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR", "R$": "BRL", "C$": "CAD",
                    "MX$": "MXN", "kr": "SEK", "zł": "PLN", "₺": "TRY"}
MARKETPLACE_CURRENCY = {"amazon.com": "USD", "amazon.ca": "CAD", "amazon.com.mx": "MXN", "amazon.com.br": "BRL",
                        "amazon.it": "EUR", "amazon.de": "EUR", "amazon.fr": "EUR", "amazon.nl": "EUR",
                        "amazon.es": "EUR", "amazon.co.uk": "GBP", "amazon.in": "INR", "amazon.co.jp": "JPY",
                        "amazon.se": "SEK", "amazon.pl": "PLN", "amazon.com.tr": "TRY"}


def amazon_top_brands(data):
    data = _dict(data)
    marketplace = S.text(data.get("site"))
    currency = MARKETPLACE_CURRENCY.get(marketplace) or CURRENCY_SYMBOLS.get(S.text(data.get("currency")) or "")
    cat = _dict(data.get("category"))
    rev = _dict(data.get("revenue"))
    oss = _dict(data.get("oss"))
    return {
        "marketplace": marketplace,
        "category": {"id": S.text(cat.get("urlCode")) if cat.get("urlCode") not in (None, "-1") else None,
                     "name": S.text(cat.get("label"))} if cat else None,
        "month": (S.iso_date(data.get("date")) or "")[:7] or None,
        "revenue": {
            "amount": S.to_int(rev.get("revenue")),
            "currency": currency,
            "change": S.share(rev.get("revenueChange")),
            "first_party_share": S.share(rev.get("onePShare")),
            "first_party_share_change": S.share(rev.get("onePShareChange")),
            "third_party_share": S.share(rev.get("threePShare")),
            "third_party_share_change": S.share(rev.get("threePShareChange")),
        } if rev else None,
        "search_share": {"organic": S.share(oss.get("organicShare")), "paid": S.share(oss.get("paidShare"))} if oss else None,
        "top_brands": [{"rank": i, "name": S.text(b.get("brandName")),
                        "revenue_share": S.share(b.get("revenueShare")),
                        "revenue_share_change": S.share(b.get("revenueShareChangePp")),
                        "product_views": S.to_int(b.get("productViews")),
                        "product_views_change": S.share(b.get("productViewsChangePp")),
                        "conversion_rate": S.share(b.get("cvr")),
                        "conversion_rate_change": S.share(b.get("cvrChangeYoy")),
                        "average_price": {"amount": S.rounded(b.get("asp")), "currency": currency},
                        "average_price_change": S.share(b.get("aspChangeYoy"))}
                       for i, b in enumerate(_list(data.get("topBrands")), 1) if isinstance(b, dict)],
        "top_products": [{"rank": i, "name": S.text(p.get("productName")), "brand": S.text(p.get("brand")),
                          "category_path": [s.strip() for s in (S.text(p.get("productCategory")) or "").split(">") if s.strip()],
                          "product_views": S.to_int(p.get("productViews")),
                          "product_views_change": S.share(p.get("productViewsChangeYoy")),
                          "image": S.blank_to_none(p.get("logo"))}
                         for i, p in enumerate(_list(data.get("topProducts")), 1) if isinstance(p, dict)],
        "top_subcategories": [_units_tree(c) for c in _list(data.get("topSubCategories")) if isinstance(c, dict)],
    }
