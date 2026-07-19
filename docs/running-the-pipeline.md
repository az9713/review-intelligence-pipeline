# Running the pipeline

Full command reference and mechanics for all four `pipeline.py` commands. See [`README.md`](../README.md) for the project overview, or jump straight to a command below.

**Prerequisite:** Python 3 on PATH, and `.env` containing a valid `APIFY_API_TOKEN` (copy `.env.example` and fill in your token). No packages to install — standard library only. `config.json` is **required** and gitignored — copy `config.example.json` to `config.json` and fill in the business you want to track before running anything, including `selfcheck` (it's loaded at import time).

## 1. Selfcheck (free, offline — already passing)

```powershell
python pipeline.py selfcheck
```

Expected output:

```
wrote ...analysis.json: 0 themes, 1 actions from 3 reviews
selfcheck OK
```

Runs the normalize → upsert → analyze path against 3 fake reviews and asserts the results (including that inserting twice doesn't duplicate). Touches no network and spends nothing.

## 2. Scrape (spends ≈ $0.45 of Apify credit)

```powershell
python pipeline.py scrape
```

For each source: starts the actor run, polls every 10 seconds (typically 1–5 minutes per source), saves raw JSON to `data/raw/`, and upserts normalized reviews into `reviews.db`. Prints per-source counts and cost, and aborts before the next source if cumulative cost passes $2 (it won't, at these caps).

Expected output shape:

```
[google] scraping via compass~Google-Maps-Reviews-Scraper (cap 500)
  compass~Google-Maps-Reviews-Scraper: run Xy3... started
  ... RUNNING
  500 items, cost $0.30
  upserted 500 reviews
[yelp] ...
DONE: 987 reviews in db (2019-03-12 .. 2026-07-14), total run cost $0.44
```

Re-running is safe and cheap-ish: it re-fetches the newest reviews up to the caps and upserts, so the database never duplicates (but Apify charges for each scraped review again — weekly, not hourly, cadence is appropriate).

### What actually happens, step by step

This is the full sequence executed by `python pipeline.py scrape`, with no steps skipped. It maps directly onto the `scrape()`, `run_actor()`, and `normalize()` functions in `pipeline.py`.

**Setup (once, before either source runs)**

1. `token()` opens `.env` and reads the line starting with `APIFY_API_TOKEN=` (or `APIFY_TOKEN=`). If neither key is found, the script exits immediately with `No APIFY_API_TOKEN in .env` — no network call is made, so nothing is charged.
2. `os.makedirs(RAW_DIR, exist_ok=True)` creates `data/raw/` if it doesn't already exist.
3. `db()` opens (or creates, if this is the first run) `reviews.db` and issues `CREATE TABLE IF NOT EXISTS reviews (...)`. If the file and table already exist, this is a no-op — existing rows are untouched at this point.
4. A running total, `total_cost`, is initialized to `0.0`. This is what the $2 abort guardrail checks after each source.

**Per source (Google, then Yelp) — `run_actor()`**

5. **Start the run.** The script sends `POST https://api.apify.com/v2/acts/{actor}/runs?token=...` with the source's input JSON as the request body (for Google: the address-pinned search URL, `maxReviews: 500`, `reviewsSort: newest`; for Yelp: the direct business URL, `reviews_limit: 500`, `reviews_sort: newest`). Apify responds *immediately* — typically well under a second — with a run object containing a `run_id` and a status of `READY`. **At this point, no scraping has happened yet.** This immediate-but-incomplete response is the reason polling exists; see [why polling is needed](#why-polling-is-needed-apifys-asynchronous-run-model) below.
6. **Poll loop.** The script enters a loop that runs at most 90 times: sleep 10 seconds, then `GET https://api.apify.com/v2/actor-runs/{run_id}?token=...` to fetch the run's current status. It exits the loop as soon as the status is anything other than `READY` or `RUNNING` (i.e., the run has reached a terminal state), or after 90 iterations (15 minutes) if it never does. Each iteration prints the current status (e.g. `... RUNNING`) so progress is visible in the terminal.
   - In practice, Apify's cloud workers pick up the run within a few seconds (moving it from `READY` to `RUNNING`), then the actor itself spends anywhere from ~30 seconds to several minutes actually navigating Google Maps or Yelp and extracting review data, depending on how many reviews exist and current site/actor load.
7. **Check the outcome.** If the final status is not exactly `SUCCEEDED` (e.g. `FAILED`, `TIMED-OUT`, `ABORTED`), the script exits with an error naming the run ID — nothing is written to the database, and you can look up that run ID in the [Apify Console](https://console.apify.com) to see its log and diagnose why. If it never leaves `READY`/`RUNNING` after 15 minutes, the same abort happens (the run may still be executing in Apify's cloud — check the Console).
8. **Fetch the results.** On success, the script reads `run["defaultDatasetId"]` from the run object and calls `GET https://api.apify.com/v2/datasets/{dataset_id}/items?token=...&clean=true&format=json`. This downloads every scraped review as a JSON array — `clean=true` strips Apify's internal bookkeeping fields, leaving just the review data the actor produced.
9. **Report cost.** The run object also carries `usageTotalUsd` — what Apify actually billed for this specific run (this can differ slightly from the pre-estimate, since it's based on the actual number of reviews scraped, which may be less than the 500 cap if the listing has fewer reviews). This is printed (`N items, cost $X.XX`) and added to `total_cost`.

**Back in `scrape()`, after each source returns**

10. **Save raw output.** The full JSON array from step 8 is written unmodified to `data/raw/{source}-{YYYYMMDD-HHMMSS}.json`. This is the permanent audit trail — if a later mapping bug is found, this file lets you re-derive `reviews.db` rows without paying to re-scrape.
11. **Normalize.** Each item in the JSON array is passed to `normalize()`, which extracts `review_id`, `rating`, `text`, `date`, `owner_response`, and `author` using an ordered list of candidate field names per source (see [Data model](reference.md#data-model)). Items missing an ID or a parseable rating are dropped and counted as "unmappable" rather than causing a crash.
12. **Upsert into SQLite.** The normalized rows are written with `INSERT OR REPLACE INTO reviews VALUES (...)`, keyed on `review_id`. Because the primary key is source-prefixed (`google:...` / `yelp:...`) and the row is fully replaced (not merged), running this twice on the same data leaves the database in an identical state — no duplicate rows, no double-counted reviews in later analysis.
13. **Print the per-source summary** — how many rows were upserted, and how many were skipped as unmappable, if any.
14. **Check the budget guardrail.** If `total_cost` (cumulative across sources processed so far) exceeds `$2.00`, the script exits immediately, *before* starting the next source's run. This is a hard stop, not a warning — at the current caps (500 reviews × 2 sources ≈ $0.45 total) it should never trigger, but it exists as a backstop against actor pricing changes or a misconfigured cap.

**After both sources complete**

15. The script queries `reviews.db` for the total row count and the min/max `review_date`, and prints the final summary line: `DONE: N reviews in db (earliest .. latest), total run cost $X.XX`.

At no point does this script call any AI model, send data anywhere other than Apify's API, or write outside this project folder.

### Why polling is needed: Apify's asynchronous run model

The short version: **starting an actor run and finishing an actor run are two separate API calls, separated by an unpredictable amount of real-world scraping time**, and the only way to find out when the second event has happened is to keep asking.

Here's the full reasoning:

**Starting a run is fire-and-forget by design.** `POST /v2/acts/{actor}/runs` is Apify's *asynchronous* run endpoint. It hands your input to Apify's infrastructure, queues a container to execute the actor, and returns right away with a run object — before the actor has scraped a single review. The returned status is `READY` (queued, not yet executing) or sometimes already `RUNNING`. This is by design: an actor run scraping 500 reviews can take minutes, and an HTTP request/response cycle isn't built to stay open that long while useful work happens on the other end.

**A run moves through a sequence of states**, and only some of them mean "done":

| Status | Meaning |
|--------|---------|
| `READY` | Queued, waiting for an available worker |
| `RUNNING` | Actively executing (this is where most of the wait time is spent) |
| `SUCCEEDED` | Finished normally — dataset is complete and ready to fetch |
| `FAILED` | Actor errored out — see the run's log in the Apify Console |
| `TIMING-OUT` / `TIMED-OUT` | Exceeded its own internal time budget |
| `ABORTING` / `ABORTED` | Stopped manually or by the platform |

`pipeline.py`'s poll loop treats `READY` and `RUNNING` as "still going" and anything else as "done, one way or another" — which is why the loop condition is `if run["status"] not in ("READY", "RUNNING"): break` rather than checking specifically for `SUCCEEDED`. A `FAILED` run still needs to break the loop so the script can report the failure, rather than polling forever.

**Why not just wait synchronously?** Apify does offer a synchronous variant (`POST /v2/acts/{actor}/run-sync` and `run-sync-get-dataset-items`) that blocks the HTTP request open and returns the finished result directly — no polling code needed. It wasn't used here because its `waitForFinish` window caps out at **60 seconds**: if the run hasn't reached a terminal status by then, the endpoint returns anyway with whatever state the run is currently in (e.g. still `RUNNING`), which pushes the "did it actually finish?" problem right back onto the caller. Since a 500-review scrape routinely takes several minutes — well past 60 seconds — the synchronous endpoint doesn't actually save the polling logic here, it just hides it one layer down and adds a false sense that the call "just works." Explicit async + poll makes the wait, the timeout, and the failure handling visible in the code instead of implicit in a client library.

**Why not use webhooks instead of polling?** Apify also supports webhooks — you can pass a `webhooks` parameter (a base64-encoded JSON array) when starting a run, and Apify will `POST` a notification to a URL you control when the run finishes. This is the more "push" (event-driven) alternative to polling's "pull" (ask-repeatedly) approach, and it's the better choice for a long-running server that's always listening. It wasn't used here because it requires exposing a public HTTP endpoint to receive the callback — this script runs from a local Windows machine with no public URL, so there's nothing for Apify to call back to. Polling needs no inbound network access at all, which is why it's the right fit for a script that runs on-demand from a laptop rather than a deployed server.

**Why 10 seconds specifically, and 90 attempts?** It's a plain trade-off with no single correct answer:
- Too short (e.g. 1 second) wastes API calls and adds negligible responsiveness, since actor runs take at minimum tens of seconds.
- Too long (e.g. 60 seconds) means the script could sit idle for up to a minute after the run actually finishes before noticing and printing the result.
- 10 seconds keeps the terminal output moving (visible progress every 10s) without meaningfully hammering Apify's API — at most ~90 status-check calls per source, which is negligible against Apify's rate limits (and status checks aren't billed the way dataset scraping is).
- 90 attempts × 10 seconds = 15 minutes is a generous ceiling: both actors typically finish in 1–5 minutes for a few hundred reviews, so 15 minutes leaves headroom for a slow day without letting a genuinely stuck run poll forever.

## 3. Analyze (free, offline)

```powershell
python pipeline.py analyze
```

Reads `reviews.db`, writes `analysis.json`. Re-run any time; it's deterministic given the database contents.

## 4. Render (free, offline)

```powershell
python pipeline.py render
```

Re-embeds the current `analysis.json` into `dashboard.html`, replacing the `const ANALYSIS = ...;` line in the page's script. Finds that line by exact surrounding markers rather than brace-matching (a review quote could itself contain the characters `};`, which would break naive JSON-in-JS extraction). Run this any time after `analyze` produces new data — the dashboard file otherwise keeps showing whatever was last embedded.
