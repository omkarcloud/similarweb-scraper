# 📊 Similarweb Scraper

Similarweb Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Similarweb data for free.

## ✨ What Can I Get?

- 📊 **Full traffic report for any website** — 3 months of visits, global, country & category rank, bounce rate, traffic sources, top countries & audience
- 🥊 **10 competitors & 20 similar sites** — affinity, ranks & engagement, plus AI-chatbot traffic from ChatGPT, Gemini & Claude
- 🏆 **Top 50 websites in 66 countries** — plus top app charts across 153 App Store & 96 Google Play countries, with trending risers
- 🛒 **Amazon's top brands in 15 marketplaces** — revenue, conversion rate & best-sellers, plus company profiles, tech stacks & market share

## 🎥 Example: A Full Similarweb Website Report

```json
{
  "domain": "amazon.com",
  "link": "https://amazon.com",
  "category": { "id": "e-commerce-and-shopping/marketplace", "name": "E-commerce and Shopping > Marketplace" },
  "company": {
    "name": "Amazon.com, Inc.",
    "year_founded": 1994,
    "employees": { "min": 10001, "max": null },
    "headquarters": { "city": "Seattle", "state": "Washington", "country": { "code": "US", "name": "United States" } }
  },
  "ranks": { "global_rank": 9, "country_rank": 3, "category_rank": 1 },
  "traffic": {
    "visits": 2753558451,
    "bounce_rate": 0.3054,
    "pages_per_visit": 9.26,
    "avg_visit_duration_seconds": 355,
    "monthly_visits": [
      { "month": "2026-07", "visits": 2725897801, "change": 0.0127 },
      { "month": "2026-08", "visits": 2753558451, "change": 0.0101 }
    ]
  },
  "traffic_sources": [{ "source": "direct", "rank": 1, "share": 0.5385 }],
  "geography": { "countries_count": 111, "top_countries": [{ "country": { "code": "US", "name": "United States" }, "share": 0.8506 }] },
  "demographics": { "gender": { "male": 0.4944, "female": 0.5056 } },
  "similar_sites": [{ "domain": "ebay.com", "category_rank": 4, "affinity": 1.0 }],
  "keywords": { "keywords_count": 7131847, "top_keywords": [{ "keyword": "amazon prime", "cpc": 0.26 }] },
  "snapshot_date": "2026-08-01"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Similarweb Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/similarweb-scraper
cd similarweb-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/websites/details?website=amazon.com"
```

```json
{
  "domain": "amazon.com",
  "link": "https://amazon.com",
  "similarweb_link": "https://www.similarweb.com/website/amazon.com/",
  "category": { "id": "e-commerce-and-shopping/marketplace", "name": "E-commerce and Shopping > Marketplace" },
  "ranks": { "global_rank": 9, "country_rank": 3, "category_rank": 1 },
  "traffic": {
    "visits": 2753558451,
    "visits_change": 0.0101,
    "bounce_rate": 0.3054,
    "pages_per_visit": 9.26,
    "avg_visit_duration_seconds": 355,
    "monthly_visits": [
      { "month": "2026-06", "visits": 2691704102, "change": 0.0157 },
      { "month": "2026-07", "visits": 2725897801, "change": 0.0127 },
      { "month": "2026-08", "visits": 2753558451, "change": 0.0101 }
    ]
  },
  "traffic_sources": [{ "source": "direct", "rank": 1, "share": 0.5385 }],
  "snapshot_date": "2026-08-01"
}
```

All 29 endpoints are now live at `http://localhost:8000`.

Similarweb allows about 6 requests per IP address. For more, set `SIMILARWEB_PROXY` to a rotating residential proxy before `python run.py` and the scraper switches to a fresh IP every 5 calls:

```bash
SIMILARWEB_PROXY="http://user:pass@host:port" python run.py
```

## 📚 Endpoints

29 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Website Details | `/websites/details` | The full traffic report for one website in a single call |
| Website Traffic | `/websites/traffic` | 3 months of visits, engagement, traffic sources, top countries |
| Compare Websites | `/websites/compare` | Up to 10 websites side by side |
| Website Competitors / Similar Sites | `/websites/competitors`, `/websites/similar-sites` | 10 competitors with engagement; 20 similar sites with related apps |
| AI Traffic | `/websites/ai-traffic` | Visits from ChatGPT, Gemini, Claude and more, plus top prompts |
| Rankings / Audience / Keywords | `/websites/rankings`, `/websites/audience`, `/websites/keywords` | Rank history, age and gender split, top search keywords |
| Referrals / Social / Ads / Technologies | `/websites/referrals`, `/websites/social`, `/websites/ads`, `/websites/technologies` | Where traffic comes from and goes, ads and tech stack |
| Company Details | `/companies/details` | Revenue, employees, HQ, ticker, traffic, competitors, news |
| Top / Trending Websites | `/top-websites`, `/top-websites/trending`, `/top-websites/filters` | Top 50 by country and category, risers and fallers |
| Autocomplete / Search | `/search/autocomplete`, `/search` | Find websites, apps and companies by name |
| App Details | `/apps/details` | Store and usage ranks, 28-day history, competitors |
| Top / Trending Apps | `/apps/top`, `/apps/trending`, `/apps/filters` | Google Play and App Store charts in 150+ countries |
| Browser / Device Market Share | `/market-share/browsers`, `/market-share/devices` | Leaders with 12-month history, per country |
| Technology Details | `/technologies/details` | Install base, top websites and alternatives for any web tech |
| Amazon Top Brands / Categories | `/amazon/top-brands`, `/amazon/categories` | Revenue, top brands and best-sellers in 15 marketplaces |
| SERP Volatility | `/serp-volatility` | Daily Google volatility index for 90 days |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-similarweb-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-similarweb-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-similarweb-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/websites/details",
    params={"website": "amazon.com"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Similarweb Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Similarweb%20Scraper%20API.)

[![Ask Us by Email about Similarweb Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Similarweb%20Scraper%20API&body=I%20need%20help%20using%20the%20Similarweb%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/similarweb-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/similarweb-scraper)
