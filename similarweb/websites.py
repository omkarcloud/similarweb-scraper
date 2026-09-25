"""/similarweb/websites/* — website traffic & engagement analysis.

Every section route (traffic, rankings, audience, keywords, referrals, ads,
social, technologies) reads the ONE /api/website/<domain> payload, shared
through fetch.shared_raw so a customer walking the sections costs a single
upstream call. Competitors, AI traffic and similar sites have their own
upstreams (the competitors page, the AI-traffic page + prompts API, and
similarsites.com)."""
import config
from similarweb import cache_config as ttl
from similarweb import fetch
from similarweb import parsers as P
from similarweb import shared as S


def raw_website(website):
    """The raw /api/website/<domain> JSON (memo + response cache)."""
    def build():
        data = fetch.api_json(f"/api/website/{website}", label=f"website {website}")
        if not isinstance(data, dict) or not data.get("domain"):
            raise fetch.SimilarwebNotFound(f"similarweb has no data for {website}")
        return data
    return fetch.shared_raw("website", {"website": website}, build, ttl.WEBSITE_RAW_CACHE)


def _section(website, build):
    raw = raw_website(website)
    return {**P.website_identity(raw), **build(raw), "snapshot_date": S.iso_date(raw.get("snapshotDate"))}


def details(website):
    return P.website_details(raw_website(website))


def traffic(website):
    return _section(website, lambda raw: {
        **P.website_engagement(raw),
        "traffic_sources": P.traffic_sources(raw.get("trafficSources")),
        "top_countries": P.website_geography(raw)["top_countries"],
        "countries_count": P.website_geography(raw)["countries_count"],
    })


def rankings(website):
    return _section(website, lambda raw: {"ranks": P.website_ranking(raw)})


def audience(website):
    return _section(website, lambda raw: {
        "demographics": P.website_demographics(raw),
        "geography": P.website_geography(raw),
        "interests": P.website_interests(raw),
    })


def keywords(website):
    return _section(website, lambda raw: {"keywords": P.website_keywords(raw)})


def referrals(website):
    return _section(website, lambda raw: {"referrals": P.website_referrals(raw)})


def ads(website):
    return _section(website, lambda raw: {"ads": P.website_ads(raw)})


def social(website):
    return _section(website, lambda raw: {"social": P.website_social(raw)})


def technologies(website):
    return _section(website, lambda raw: {"technologies": P.website_technologies(raw)})


def competitors(website):
    """The /website/<domain>/competitors/ page: 10 competitors with their
    engagement and ranks, merged with the overview's similarity list."""
    data = fetch.page_data(f"/website/{website}/competitors/", label=f"competitors {website}")
    out = P.competitors_page(data)
    if not out["competitors"]:
        # small sites have no competitors page rows; fall back to the overview list
        out["competitors"] = P.website_similar(raw_website(website))
    return out


def ai_traffic(website):
    """AI-chatbot referral traffic (/ai-traffic/<domain>/) + the top prompts
    that surface the site (/api/ai-traffic/prompts/<domain>)."""
    results = fetch.run_parallel([
        lambda: fetch.page_data(f"/ai-traffic/{website}/", label=f"ai traffic {website}"),
        lambda: fetch.api_json(f"/api/ai-traffic/prompts/{website}", label=f"ai prompts {website}"),
    ], workers=2)
    status, page = results[0]
    if status == "error":
        raise page
    prompts = results[1][1] if results[1][0] == "ok" else []
    return P.ai_traffic(page, prompts if isinstance(prompts, list) else [])


def similar_sites(website):
    """similarsites.com: 20 similar sites with similarity scores, visits and
    related apps."""
    return P.similar_sites(fetch.similarsites(website), website)


def compare(websites):
    """Side-by-side summary of up to 10 websites (one lookup each, in
    parallel). A site Similarweb has no data for is listed in `failed`."""
    results = fetch.run_parallel([lambda w=w: raw_website(w) for w in websites],
                                 workers=config.SIMILARWEB_COMPARE_WORKERS)
    rows, failed = [], []
    for website, (status, value) in zip(websites, results):
        if status == "ok":
            rows.append(P.website_summary(value))
        else:
            reason = "not_found" if isinstance(value, fetch.SimilarwebNotFound) else "failed"
            failed.append({"domain": website, "reason": reason, "error": str(value)})
    if not rows and failed and all(f["reason"] != "not_found" for f in failed):
        raise fetch.SimilarwebBlocked("every lookup failed: " + "; ".join(f["error"] for f in failed))
    return {"websites": rows, "failed": failed}
