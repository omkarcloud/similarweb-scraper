"""/similarweb/companies/* — the /company/<domain>/ page: firmographics,
3-month company traffic, competitors with their visits, stock tickers,
news signals and category benchmarks."""
from similarweb import fetch
from similarweb import parsers as P


def details(company):
    data = fetch.page_data(f"/company/{company}/", label=f"company {company}")
    if not data.get("name") and not data.get("domain"):
        raise fetch.SimilarwebNotFound(f"similarweb has no company page for {company}")
    return P.company(data)
