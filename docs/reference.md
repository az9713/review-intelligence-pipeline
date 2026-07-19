# Reference

Background, data shapes, and terminology for this project. See [`README.md`](../README.md) for the project overview.

## Component background

### Apify

[Apify](https://apify.com) is a marketplace of rentable web scrapers. Each scraper is called an **actor** — a program someone else wrote and maintains, which you run in Apify's cloud and pay per use. This matters because scraping Google or Yelp yourself is a losing battle (bot detection, layout changes); actor maintainers fight that battle for you.

You interact with Apify through an **API token** (a password-like string identifying your account, stored here in `.env` and never committed or printed). The workflow: start an actor run with your input (which URL to scrape, how many reviews), poll until it finishes, then download the results from the run's **dataset** (Apify's term for a run's output table).

Two actors were selected, by usage volume, rating, and price:

| Source | Actor ID | Track record | Price |
|--------|----------|--------------|-------|
| Google Maps | `compass~Google-Maps-Reviews-Scraper` | 47,000+ users, 4.8★, 137M runs | $0.0006/review |
| Yelp | `web_wanderer~yelp-reviews-scraper` | 99.9% success over 549K runs/30 days | $0.0003/review |

Both use "pay per event" pricing: you pay per review actually scraped, not for compute time. A full 500+500 review scrape costs **≈ $0.45**.

> **Note:** The original video this build follows (see [Provenance](../README.md#provenance)) connects Apify through MCP, a protocol that lets an AI assistant call Apify conversationally. This build calls Apify's plain REST API from Python instead — fewer moving parts, and the pipeline can run on a schedule without an AI in the loop.

### SQLite

SQLite is a full SQL database in a single local file (`reviews.db`) — no server, no installation, built into Python's standard library. It is the boring, correct choice for a single-user dataset of a few thousand rows. If you can open a file, you can use the database.

### Why scrape at all (instead of official APIs)?

Google and Yelp both have official APIs, but their review access is severely limited (Google's Places API returns only 5 reviews per place; Yelp's similar). Full review history is only available from the public web pages — hence scraping. Review data is public content; the actors fetch what any browser visitor sees.

## Data model

One table, `reviews`:

| Column | Type | Notes |
|--------|------|-------|
| `review_id` | TEXT, primary key | Source-prefixed: `google:ChZDSU...`, `yelp:abc123`. The prefix prevents ID collisions across sites; the primary key makes upserts deduplicate. |
| `source` | TEXT | `google` or `yelp` |
| `listing_url` | TEXT | The listing scraped |
| `author` | TEXT | Reviewer display name, `anonymous` if missing |
| `rating` | REAL | 1–5 stars |
| `text` | TEXT | Review body (may be empty — star-only reviews exist) |
| `review_date` | TEXT | `YYYY-MM-DD`, or NULL if unparseable |
| `owner_response` | TEXT | Business's reply, NULL if none |
| `scraped_at` | TEXT | UTC timestamp of ingestion |

**Normalization:** the two actors name the same fields differently (`stars` vs `rating`, `publishedAtDate` vs `date`). `normalize()` in `pipeline.py` tries an ordered list of candidate keys per field. Items missing an ID or rating are skipped and counted (`skipped N unmappable`); since raw JSON is kept in `data/raw/`, a mapping gap can be fixed and re-ingested **without paying to re-scrape**.

## Analysis methodology

All computed in plain Python from the database — deterministic, auditable, no AI calls.

| Output | How it's computed |
|--------|-------------------|
| KPIs | Count, mean rating, % of 1–2★ reviews — overall and per source. |
| Trend | Mean rating per calendar quarter (reviews without dates excluded). |
| Themes | A keyword lexicon maps 8 themes (pastry & bread quality, coffee & drinks, service & staff, wait & speed, price & value, freshness, cleanliness & space, parking & access) to word stems. A review mentioning a stem counts toward that theme. Themes with fewer than 3 mentions are dropped as noise. |
| Sentiment | Derived from the review's own star rating: ≥4★ positive, ≤2★ negative, 3★ neutral. The reviewer's stars are their sentiment — no text sentiment model needed. |
| Deterioration | Per theme, mean rating of current-year mentions vs. prior mentions; flagged when it drops by >0.2★. |
| Owner-response gap | Share of ≤3★ reviews with no owner reply, with recent examples. |
| Actions | A theme becomes an action when it has ≥3 negative mentions and >25% of its mentions are negative. Priority = `negative_ratio × √mentions` — negativity weighted by volume, damped so one loud theme doesn't drown broad ones. An unanswered-review action is added when >50% of negative reviews have no reply (fixed high priority — it's cheap to fix and visibly signals the business listens). |

Every theme and action carries `cited_reviews` / quote objects with review IDs, ratings, and dates — the acceptance criterion from the PRD.

### Output structure: `analysis.json`

Running `analyze()` produces one JSON file with five top-level keys. This is the complete shape, annotated field by field:

```json
{
  "business": "Example Business, 123 Main St, Anytown CA",
  "generated_at": "2026-07-16T23:40:00Z",

  "kpis": {
    "total_reviews": 960,
    "avg_rating": 3.83,
    "pct_1_2_star": 21.4,
    "by_source": {
      "google": {"count": 460, "avg_rating": 4.17},
      "yelp":   {"count": 500, "avg_rating": 3.35}
    },
    "trend": [
      {"quarter": "2025-Q3", "avg_rating": 4.1, "count": 18},
      {"quarter": "2025-Q4", "avg_rating": 3.9, "count": 22}
    ]
  },

  "themes": [
    {
      "theme": "wait & speed",
      "mentions": 41,
      "positive": 12,
      "negative": 22,
      "avg_rating": 2.6,
      "avg_rating_recent": 2.3,
      "avg_rating_older": 3.1,
      "worst_quotes": [
        {"id": "google:Ci9DQ...", "rating": 1.0, "date": "2026-06-01", "quote": "Waited 25 minutes just to order..."}
      ],
      "best_quotes": [
        {"id": "google:Ci9DQ...", "rating": 5.0, "date": "2026-04-12", "quote": "Quick and friendly even during the morning rush"}
      ]
    }
  ],

  "response_gap": {
    "negative_reviews": 210,
    "unanswered": 118,
    "pct_unanswered": 56.2,
    "examples": [
      {"id": "google:Ci9DQ...", "rating": 1.0, "date": "2026-06-10", "quote": "Nobody ever replies to complaints here..."}
    ]
  },

  "actions": [
    {
      "action": "Address 'wait & speed'",
      "evidence": "22/41 mentions are 1-2★ (theme avg 2.6★, worsening: 3.1→2.3★)",
      "priority": 8.85,
      "cited_reviews": ["google:Ci9DQ...", "google:X8sKp..."]
    }
  ]
}
```

**`kpis`** — headline numbers. `by_source` splits the same metrics per platform, useful for spotting exactly the kind of gap this run surfaced (Google 4.17★ vs. Yelp 3.35★). `trend` is one entry per calendar quarter with ≥1 dated review — read it alongside `count`, since a quarter with 2 reviews is not statistically meaningful.

**`themes`** — one object per topic that cleared the 3-mention floor, sorted by mention count descending. `avg_rating_recent` vs. `avg_rating_older` is what powers the "worsening" language in `actions` — it's a same-theme comparison across dated reviews split at the most recent calendar year, not a fixed time window. `worst_quotes`/`best_quotes` are the actual evidence: real review IDs, star ratings, dates, and a 300-character excerpt — these are what a dashboard would show when a user clicks "why?" on a theme.

**`response_gap`** — a single object, not per-theme. Counts ≤3★ reviews specifically (not just 1★), since a 3★ review often *is* a complaint the owner should see.

**`actions`** — the synthesized to-do list, highest `priority` first. `priority` is not a percentage or a count on its own; it's `negative_ratio × √mentions`, a deliberate blend so a theme with 3/4 negative mentions doesn't outrank one with 15/50 negative mentions just because its ratio looks worse — volume matters too, damped by a square root so it doesn't dominate. `evidence` is a human-readable sentence generated from the same numbers, meant to be quoted directly in a dashboard or a conversation with the business owner.

**Known limits — accepted for v1, not open bugs:**

- The keyword lexicon is a first guess. It will miss themes it has no words for and mis-file sarcasm ("*great* service… not"). Refining it is cheap whenever it matters — raw text stays in the database, so re-analysis is free — but nothing here blocks v1 use.
- Star-rating-as-sentiment misattributes mixed reviews ("food great, service awful, 4★" counts as positive for both themes). Accepted: a real text-sentiment model is a v2-scale addition, not a v1 fix.
- Quarterly trend buckets are noisy at low review volume; read them with the per-bucket `count`. Inherent to any quarterly bucketing at this review volume, not a defect.
- Yelp reviewer names are unavailable from this actor (`author.name` is `null` for all 500 raw items) — every Yelp review shows `anonymous`. Accepted: this is what the actor exposes, not a mapping bug; see [Verification against the real data](scrape-results.md#verification-against-the-real-data).
- Yelp is capped at its 500 most recent reviews (of ~521 total) by the budget guardrail — accepted trade-off for the $5 credit limit; see [Cost and budget guardrails](../README.md#cost-and-budget-guardrails).

**Resolved (fixed and verified, kept here for history):** an earlier version of this dataset had Yelp's `review_date` and `owner_response` entirely `NULL` due to a field-name mapping gap. Fixed and verified 2026-07-16 — see [Data quality findings](scrape-results.md#data-quality-findings--fixed-2026-07-16) and [the fix](scrape-results.md#the-fix--applied-and-verified). `analyze` and `render` have since been re-run against the corrected data; current results are reflected throughout this document and in [Current status](../README.md#current-status).

## Glossary

**Actor** — a rentable scraper program on Apify's marketplace. You supply input (URLs, limits) and get JSON out.

**Apify** — cloud marketplace for web scrapers. You pay per use; the free tier includes $5/month of credit.

**API token** — a secret string that authenticates you to a service's API. Treat like a password.

**Dataset** — Apify's name for an actor run's output table, downloadable as JSON.

**MCP (Model Context Protocol)** — a standard letting AI assistants call external services conversationally. Used in the source video; replaced here by direct API calls.

**PRD (Product Requirements Document)** — the spec describing what to build and why, before building. Here: `PRD.md`.

**Run** — one execution of an actor. Has a status (`RUNNING`, `SUCCEEDED`, `FAILED`), a log, a cost, and a dataset.

**SQLite** — a serverless SQL database stored in one local file. Ships inside Python.

**Upsert** — insert-or-update: write a row, replacing any existing row with the same primary key. Makes re-runs idempotent (safe to repeat).
