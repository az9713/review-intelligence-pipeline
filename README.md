# Review Intelligence Pipeline

Turns customer reviews scattered across Google Maps and Yelp into a single evidence-based report of what customers love, what's getting worse, and what to fix next. One Python script scrapes the reviews (via Apify), stores them in a local database, and computes insights where every claim cites the actual reviews behind it.

This repo ships with a real working example — `analysis.json`/`dashboard.html` show real output from a real local bakery and cafe's 960 reviews. The business's identity is intentionally withheld from everything published here; see [`docs/privacy-design.md`](docs/privacy-design.md) for what that means and its limits. `config.json` (gitignored) is where you'd point this at a business of your own.

### 🔴 [Live dashboard →](https://az9713.github.io/review-intelligence-pipeline/dashboard.html)

Hosted on GitHub Pages, built from this repo's `dashboard.html` — no download required. GitHub's own README renderer strips `<iframe>`/`<script>` from markdown for security, so this can't be embedded inline on this page; the link above opens the real, live, interactive page instead.

**Status: dashboard built and live.** See [Current status](#current-status).

---

## Contents

| Section | Who it's for |
|---------|--------------|
| [Why this exists](#why-this-exists) | Everyone — the business case |
| [How it works](#how-it-works) | Everyone — the mental model |
| [Files in this folder](#files-in-this-folder) | Everyone |
| [Running the pipeline](#running-the-pipeline) | Operators — quickstart; full mechanics in [`docs/running-the-pipeline.md`](docs/running-the-pipeline.md) |
| [Cost and budget guardrails](#cost-and-budget-guardrails) | Operators |
| [Troubleshooting](#troubleshooting) | Operators |
| [Provenance](#provenance) | Everyone |
| [Current status](#current-status) | Everyone |
| [`docs/running-the-pipeline.md`](docs/running-the-pipeline.md) | Anyone who wants the full step-by-step mechanics of a scrape run, and why Apify's async API needs polling |
| [`docs/scrape-results.md`](docs/scrape-results.md) | Everyone — what the live July 2026 scrape actually returned, including the Yelp data-quality deep-dive |
| [`docs/reference.md`](docs/reference.md) | Power users — Apify/SQLite background, the data model, analysis methodology, `analysis.json`'s exact shape, and a glossary |
| [`docs/scheduling-design.md`](docs/scheduling-design.md) | Operators — the plan for automated recurring runs, not yet built |
| [`docs/privacy-design.md`](docs/privacy-design.md) | Everyone, before this repo goes public — implemented and verified |
| [`CHANGELOG.md`](CHANGELOG.md) | Everyone — detailed write-up of every bug found and fixed, with code and verification |
| [`DEVELOPMENT_JOURNEY.md`](DEVELOPMENT_JOURNEY.md) | Everyone — the narrative story of how this project was built, start to finish |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | New contributors — setup, extension points, the testing rule |

---

## Why this exists

A business with hundreds of reviews is sitting on a dataset it usually reads one anecdote at a time. Individually, a review is an opinion. In aggregate, reviews are data: recurring themes, trends over time, and gaps (like never responding to complaints) that individual reading can't reveal.

This pipeline answers three questions for any specific business it's pointed at (see `config.json`):

1. **What do customers consistently praise or complain about?** (themes, with counts)
2. **What is getting worse over time?** (rating trends, per theme)
3. **What should be fixed first?** (ranked actions, each citing the reviews that justify it)

The design principle, first written down in this project's original requirements spec (kept locally, not published — see [`docs/privacy-design.md`](docs/privacy-design.md)): **every insight must be evidence-based** — backed by a computation and citations to specific review IDs, never a vibe.

The same pattern also works as a consulting lead magnet: run it against a prospect's business, show them their pain points, and pitch the fix.

## How it works

```
DISCOVER          SCRAPE              STORE            ANALYZE            PRESENT
find listing  →   Apify actors    →   SQLite       →   analysis.json  →   dashboard.html
URLs               fetch reviews       reviews.db       KPIs, themes,
                  (Google, Yelp)      (deduplicated)   actions + cites
```

Five stages, run in order via `pipeline.py`'s four commands (see [Running the pipeline](#running-the-pipeline)).

1. **Discover** — resolve exactly which online listings belong to the business in `config.json`. For the business behind this repo's real example data: the Yelp page (~521 reviews) and an address-pinned Google Maps search query resolved the one correct listing. Neither URL is published here, per [`docs/privacy-design.md`](docs/privacy-design.md).
2. **Scrape** — two rented cloud scrapers ("actors", see [Apify](docs/reference.md#apify)) fetch up to 500 of the newest reviews from each source and return them as JSON.
3. **Store** — reviews from both sources are normalized into one shape and written into a local SQLite database. Each review gets a source-prefixed ID (`google:abc123`), and inserts are *upserts* — re-running the scrape updates rows instead of duplicating them.
4. **Analyze** — pure local computation (no AI, no network): rating KPIs, quarterly trends, keyword-based themes, deterioration signals, owner-response gaps, and a ranked action list. Output is `analysis.json`, where every theme and action carries the IDs and quotes of supporting reviews.
5. **Present** — a self-contained `dashboard.html` rendering the analysis, built around the real scraped data rather than guesses about it. `python pipeline.py render` re-embeds the latest `analysis.json` into it after any `analyze` re-run.

## Files in this folder

| File | What it is |
|------|-----------|
| `PRD.md` | *(local-only, gitignored)* Product requirements document — the spec this build follows. Written for one specific real business deployment, not templated; kept local rather than published, since it can't be genericized without losing its own point. See [`docs/privacy-design.md`](docs/privacy-design.md). |
| `pipeline.py` | The entire system: scrape, store, analyze, render, and selfcheck commands. Business-agnostic — reads all business/source identity from `config.json`. |
| `config.json` | *(local-only, gitignored)* Business identity and source config (name, address, actor IDs, listing URLs) for whichever business you point this at. Real URLs by definition name that business, so it's not published — see [`docs/privacy-design.md`](docs/privacy-design.md). Copy `config.example.json` to create yours. |
| `config.example.json` | Blank template for `config.json` — copy it to point the pipeline at a different business. |
| `.env` | Your Apify API token (`APIFY_API_TOKEN=...`). Secret — **never commit or share**; excluded via `.gitignore`. |
| `.env.example` | Template for `.env` — copy it and fill in your own token. |
| `.gitignore` | Excludes `.env` (secret) and local/transient artifacts (`__pycache__/`, selfcheck temp files, the future scheduling log). Everything else, including the scraped data, is tracked — see [Provenance](#provenance) for why. |
| `README.md` | This document. |
| `CHANGELOG.md` | Detailed write-up of every bug found and fixed, with code and verification. |
| `CONTRIBUTING.md` | Setup for new contributors, the extension-points guide (new sources, theme customization, action rules), and the one testing rule (`selfcheck` must pass). |
| `DEVELOPMENT_JOURNEY.md` | The narrative development story, start to finish — same fully-anonymized treatment as everything else here. |
| `docs/` | Deep-dive reference docs split out of this README to keep it a readable front door — full pipeline mechanics, the July 2026 scrape-results report, the data model/analysis methodology/glossary, the scheduling plan, and the privacy design. See [Contents](#contents) above for links to each. |
| `reviews.db` | *(created by `scrape`, local-only)* SQLite database of all reviews. Contains real reviewer names — excluded via `.gitignore`, never committed. See [`docs/privacy-design.md`](docs/privacy-design.md). |
| `data/raw/` | *(created by `scrape`, local-only)* Raw actor output JSON, timestamped, kept for audit and re-mapping. Same exclusion as `reviews.db`, same reason. |
| `analysis.json` | *(created by `analyze`)* The computed insights, with citations. |
| `dashboard.html` | Self-contained visual report — KPI tiles, rating trend, theme breakdown, ranked actions. Opens directly in a browser, no server. Also served live via [GitHub Pages](https://az9713.github.io/review-intelligence-pipeline/dashboard.html). |
| `.nojekyll` | Empty marker file telling GitHub Pages not to run Jekyll processing over this repo — `dashboard.html` and `analysis.json` are plain static files, not a Jekyll site. |
| `sample-data/` | A clearly-labeled **synthetic** (fake) dataset for new contributors to explore the `reviews.db` shape without needing to run a real scrape first. Never real data — see its own `README.md`. |

## Running the pipeline

**Prerequisite:** Python 3 on PATH, and `.env` containing a valid `APIFY_API_TOKEN` (copy `.env.example` and fill in your token). No packages to install — standard library only. `config.json` is **required** and gitignored — copy `config.example.json` to `config.json` and fill in the business you want to track before running anything, including `selfcheck` (it's loaded at import time).

Four commands, run in order:

| Command | Cost | What it does |
|---|---|---|
| `python pipeline.py selfcheck` | Free, offline | Runs the normalize → upsert → analyze path against 3 fake reviews and asserts the results. Run this first — if it doesn't pass, something in your setup is wrong. |
| `python pipeline.py scrape` | ≈ $0.45 of Apify credit | Fetches up to 500 of the newest reviews per source, saves raw JSON to `data/raw/`, and upserts normalized reviews into `reviews.db`. Safe to re-run — upserts, never duplicates (though Apify bills for each scraped review again). |
| `python pipeline.py analyze` | Free, offline | Reads `reviews.db`, writes `analysis.json`. Deterministic given the database contents — re-run any time. |
| `python pipeline.py render` | Free, offline | Re-embeds the current `analysis.json` into `dashboard.html`. Run any time after `analyze` produces new data. |

**Full mechanics** — expected output for each command, the complete step-by-step sequence a `scrape` run executes (mapped directly onto `scrape()`, `run_actor()`, and `normalize()` in `pipeline.py`), and why Apify's asynchronous API requires polling rather than a single request — are in [`docs/running-the-pipeline.md`](docs/running-the-pipeline.md).

## Cost and budget guardrails

| Guardrail | Value | Where enforced |
|-----------|-------|----------------|
| Reviews per source | 500 newest | Actor input (`maxReviews` / `reviews_limit`) |
| Projected initial run cost | ≈ $0.45 | Pricing published by both actors |
| Hard abort | Cumulative reported cost > $2.00 | `scrape()` checks after each source |
| Available credit | $5.00 (Apify free tier) | Your account |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `No APIFY_API_TOKEN in .env` | Token file missing/renamed | Create `.env` containing `APIFY_API_TOKEN=apify_api_...` (from Apify Console → Settings → API & Integrations) |
| `HTTP 401` from api.apify.com | Token invalid or revoked | Regenerate the token in Apify Console, update `.env` |
| `run ... ended FAILED` / `TIMED-OUT` | Actor-side failure (site change, bad input) | Check the run's log in Apify Console (the run ID is printed); retry once; if persistent, pick an alternative actor from the store |
| `skipped N unmappable` with large N | Actor changed its output field names for `review_id` or `rating` | Inspect the newest file in `data/raw/`, add the new key names to `normalize()`, re-run `analyze` — no re-scrape needed |
| No warning printed, but `date`/`owner_response`/`author` look wrong or empty in `reviews.db` | A non-critical field's actor key isn't in `normalize()`'s candidate list — this fails silently since only a missing ID or rating triggers the "unmappable" warning. Hit and fixed on the July 16, 2026 Yelp run: see [Data quality findings](docs/scrape-results.md#data-quality-findings--fixed-2026-07-16). | Diff the field names in the newest `data/raw/{source}-*.json` against the candidate list in `normalize()`, add the missing key, re-normalize and upsert — no re-scrape needed |
| `reviews.db is empty — run scrape first` | `analyze` before any scrape | Run `python pipeline.py scrape` |
| Very few Google reviews returned | Search URL resolved to the wrong/no listing | Replace the Google `startUrls` entry with the exact place URL (open the listing in Google Maps, copy the URL from the address bar) |
| Scrape cost higher than estimated | Actor pricing changed | The $2 abort still protects you; check current pricing on the actor's store page |

## Provenance

The workflow follows the YouTube video ["Turn Google reviews into business decisions"](https://www.youtube.com/watch?v=rvApCZNxUXU) (Mansel Scheffel) — see `transcript.txt`. Deviations from the video, and why:

| Video | This build | Why |
|-------|-----------|-----|
| Apify via MCP connector, driven conversationally | Apify via REST API from Python | Schedulable without an AI in the loop; fewer moving parts |
| Co-work artifact dashboard | Local static HTML (planned) | Full control, works offline |
| Sources chosen ad hoc | Google + Yelp; TripAdvisor deferred; Trustpilot excluded with rationale | Fit for a single-location bakery |
| No explicit budget control | 500-review caps + $2 abort guardrail | $5 total credit available |

## Current status

- ✅ PRD written (`PRD.md`)
- ✅ Listings resolved (Yelp URL confirmed, ~521 reviews; Google targeted by address)
- ✅ Actors selected and priced (≈ $0.45 for the initial scrape)
- ✅ `pipeline.py` scrape/store/analyze built; offline selfcheck passing
- ✅ **Live scrape run** (2026-07-16): 960 reviews stored — Google 460 (avg 4.17★), Yelp 500/cap (avg 3.35★). Cost: $0.40 of $5.00 credit. Details in [`docs/scrape-results.md`](docs/scrape-results.md).
- ✅ **Data quality gap found and fixed** (2026-07-16): Yelp's `review_date`, `owner_response`, and `author` fields were mismapped in `normalize()`. Fixed, regression-tested (`selfcheck` covers this exact shape), and verified against the live `reviews.db` — Yelp now has real dates (2013–2026), 165 real owner replies, and honest `anonymous` authorship instead of misattributing every review to the business itself. Zero additional Apify cost. See [the fix](docs/scrape-results.md#the-fix--applied-and-verified).
- ✅ **`analyze` run** (2026-07-17): `analysis.json` — 8 themes, 8 actions, from all 960 reviews. Top action: 63.2% of ≤3★ reviews (206/326) have no owner response.
- ✅ **`dashboard.html` built** (2026-07-17): KPI tiles, rating trend, theme breakdown, ranked actions with citations. Verified in-browser — no console errors, both table-view toggles and hover tooltips confirmed working.
- ✅ **Dark-mode text bug found and fixed** (2026-07-17): `dashboard.html`'s CSS custom properties (`--text-primary`, etc.) were scoped to `.viz-root`, but `body`'s `color`/`background` rules referenced them from outside that scope — CSS variables don't inherit upward to ancestors, so `body`'s `var(--text-primary)` silently failed and fell back to black, which then inherited into every element without its own explicit color (stat-tile values, action titles, `h1`) regardless of theme. Fixed by moving the variable definitions to `:root`. Verified via computed-style checks in both themes plus a full screenshot.
- ✅ **Action-threshold gap found and fixed** (2026-07-17): the actions list originally required a theme's negative mentions to exceed 25% of its total, which silently excluded large, clearly-worsening themes whose negative *share* looked moderate only because they also carry a lot of positive mentions — pastry & bread quality (524 mentions, the single largest theme, worsening 3.64★→3.35★) sat at 23% and was excluded entirely. Fixed: `theme_is_actionable()` in `pipeline.py` now also qualifies a theme when it's worsening (>0.2★ drop, recent vs. older) with ≥10 negative mentions, even under the 25% bar. Regression-tested in `selfcheck` (qualifying, floor-guarded, and share-only cases). Re-ran `analyze` + `render`: actions grew from 5 to 8, adding pastry & bread quality, coffee & drinks, and cleanliness & space, all correctly ranked below service & staff and wait & speed by the existing priority formula.
- ✅ **`render` command added** to `pipeline.py`: re-embeds `analysis.json` into `dashboard.html` without a manual injection step, so the dashboard can now be regenerated after every future `analyze` run. See [Render](docs/running-the-pipeline.md#4-render-free-offline).
- ✅ **Destructive `selfcheck` bug found and fixed** (2026-07-17): `analyze()` wrote to a hardcoded `analysis.json` path that `selfcheck()` shared for its own internal test run — since `selfcheck()` deletes that file as cleanup, running `selfcheck` *after* a real `analyze` silently destroyed the real 960-review `analysis.json`. Caught immediately by a sanity check that tried to re-read it. Fixed: `analyze()`/`render()` now read/write a module-level `ANALYSIS_PATH`, and `selfcheck()` redirects it to an isolated `selfcheck-analysis.json` (mirroring the existing `DB` isolation pattern) and restores the real path afterward. Verified: ran `analyze` → `render` → `selfcheck` in sequence and confirmed the real `analysis.json` (960 reviews, 8 themes, 8 actions) survived untouched, with no leftover temp files.
- 📝 **Scheduling designed, not built** (2026-07-17): mechanism (Windows Task Scheduler), the wrapper script, how to register any cadence, and a cost-by-cadence table are all written up in [`docs/scheduling-design.md`](docs/scheduling-design.md) — no `schtasks` command has been run and no script file has been created yet.
- ✅ **Privacy plan implemented** (2026-07-17): found that raw Google scrape data carries live reviewer profile links/photos beyond just names, while `analysis.json`/`dashboard.html` turned out to already be anonymous by construction. Full reasoning and the three parts (`.gitignore` exclusion, `strip_reviewer_pii()`, `sample-data/`) are in [`docs/privacy-design.md`](docs/privacy-design.md) — all three implemented and verified, `selfcheck` passing with a new regression test covering the strip logic.
- ✅ **Extensibility setup** (2026-07-17): business identity extracted from `pipeline.py` into `config.json` (+ a `config.example.json` template) — verified `analyze`/`render` produce identical output afterward. Git repository initialized with `.gitignore` excluding `.env`, local noise, and — per the privacy work above — the scraped data itself (`reviews.db`, `data/raw/`; this superseded an earlier plan to track the data, see [`docs/privacy-design.md`](docs/privacy-design.md)). `.env.example` template added. `CONTRIBUTING.md` added: setup, an extension-points table, the `selfcheck`-must-pass testing rule, and an explicit "what not to add" list.
- ✅ **Pushed to GitHub** (2026-07-17): initial commit (12 files — no `.env`, no `reviews.db`, no `data/raw/`, confirmed against the actual pushed tree, not just what was staged) to the public repo [`az9713/review-intelligence-pipeline`](https://github.com/az9713/review-intelligence-pipeline).
- ✅ **XSS fix found and fixed** (2026-07-17, post-push): an automated background security review caught a script-tag-breakout vulnerability in `render()` within the same session as the push. Full write-up, including the response-timeline judgment call to fix and re-push promptly rather than wait, in [`CHANGELOG.md`, item 7](CHANGELOG.md#7-xss-a-review-quote-could-break-out-of-dashboardhtmls-script-tag).
