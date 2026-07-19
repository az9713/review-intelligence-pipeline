# Contributing

This is a small, dependency-free Python pipeline (scrape → store → analyze → render) plus a static HTML dashboard. This doc covers setup, where to plug in changes, and the one testing rule. For how the system works and why it's built this way, read [`README.md`](README.md) — it's the primary technical reference and this doc doesn't repeat it.

## Setup

1. Python 3 on PATH. No packages to install — standard library only.
2. Copy `.env.example` to `.env` and fill in your own Apify API token (get one at [apify.com](https://apify.com); the free tier includes $5/month of credit).
3. Copy `config.example.json` to `config.json` and fill in the business you want to track (name, address, Google search query, Yelp URL). `config.json` is **required** — `pipeline.py` loads it at startup, so even `selfcheck` needs it present. It's gitignored on purpose (see [Privacy design](docs/privacy-design.md)) — a real business's config isn't committed to this repo, only the blank template is.
4. Run `python pipeline.py selfcheck` — it should print `selfcheck OK`. This touches no network and spends nothing; if it doesn't pass, something in your setup is wrong.
5. `reviews.db` and `data/raw/` are **not** in the repo either — they'd carry real reviewer names. `analysis.json` and `dashboard.html` *are* committed and show real, anonymized output from a real (unnamed) business's review data — see [Privacy design](docs/privacy-design.md) for what "anonymized" means here and its limits. To poke at real per-review data before spending anything, look at `sample-data/` — a small, clearly-labeled **fake** dataset in `reviews.db`'s shape, safe to explore freely. Running your own `python pipeline.py scrape` (a few dollars of Apify credit) against a business of your choice gets you the real thing.

Full command reference (`scrape`, `analyze`, `render`, `selfcheck` — what each does, expected output, cost) is in [`docs/running-the-pipeline.md`](docs/running-the-pipeline.md).

## Extension points

The codebase has a small number of intentional seams. Changes should go through one of these rather than adding new ones — see [What to avoid](#what-to-avoid-adding) below for why.

| Want to... | Edit | Notes |
|---|---|---|
| Point the tool at a different business | `config.json` (copy `config.example.json` to make one) | No code changes needed — business identity and source config are fully externalized. Fill in the business's name and address, its Google search query, Yelp business URL, and listing URLs, then run the pipeline as normal. |
| Add a new review source (e.g. TripAdvisor) | `config.json`'s `sources`, the `SOURCES` dict in `pipeline.py`, and `normalize()`'s candidate key lists | Full worked recipe below in [Adding a review source](#adding-a-review-source-tripadvisor-trustpilot), plus the "actors name the same field differently across sources" gotcha in [`docs/reference.md`'s Data model](docs/reference.md#data-model). |
| Change which topics get detected in review text | the `THEMES` dict in `pipeline.py` (keyword → theme name mapping) | Raw review text stays in `reviews.db`, so re-running `analyze` after editing this costs nothing — no re-scrape needed. Documented as a known v1 trade-off in [`docs/reference.md`'s Analysis methodology](docs/reference.md#analysis-methodology). |
| Change which themes become recommended actions | `theme_is_actionable()` in `pipeline.py` | Deliberately extracted into a standalone function that takes a plain dict, specifically so it's unit-testable without spinning up a database or fake reviews — see the existing tests in `selfcheck()` for the pattern, and [CHANGELOG item 2](CHANGELOG.md#2-action-threshold-gap--large-worsening-themes-were-being-silently-excluded) for why it has two qualification branches instead of one. |
| Build a different presentation layer (not the HTML dashboard) | anything that reads `analysis.json` | Its shape is a stable, documented contract — see [`docs/reference.md`'s Output structure: analysis.json](docs/reference.md#output-structure-analysisjson). You don't need to read `pipeline.py` at all to consume it. |
| Change the dashboard itself | `dashboard.html` directly, then `python pipeline.py render` to re-embed data into it | The dashboard is already built and live (KPI row, rating-trend chart, diverging theme bars, ranked actions with citations; light/dark and table-view toggles). `render()` only replaces the `const ANALYSIS = ...;` data blob (via exact string markers — see the function's docstring) — it never touches the surrounding HTML/CSS/JS, so dashboard layout and styling changes are safe to make by hand. |

### Adding a review source (TripAdvisor, Trustpilot)

To add any source: find a well-rated actor in the [Apify store](https://apify.com/store), add an entry to `config.json`'s `sources` and to the `SOURCES` dict in `pipeline.py` (actor ID, input shape, listing URL), and extend `normalize()`'s candidate keys if its field names differ.

**TripAdvisor** is the planned v2 source — worth adding when a business has a decent TripAdvisor presence and Google + Yelp volume proves thin, though TripAdvisor skews to tourists, so it's marginal for a typical local business. **Trustpilot** was excluded from this repo's example business specifically because that business's Trustpilot presence is brand-level only, not per-location, so its reviews can't be attributed to one location — for a business with per-location pages it would be a straightforward fourth source via the same recipe.

Automated scheduling (recurring runs on any cadence) is designed but not yet built — see [`docs/scheduling-design.md`](docs/scheduling-design.md).

## Testing rule

**`python pipeline.py selfcheck` must pass before any change is submitted.** It's offline, free, and takes a couple seconds — there's no excuse not to run it.

**Any bug fix must add a regression test to `selfcheck`.** This isn't a formality — every fix made to this project so far followed this rule, and each test is what stands between a fixed bug and a silent regression:

- The Yelp field-mapping fix (`reviewDate`, `publicReply`, nested `author`) added a test using the actor's *exact* real JSON shape — the original bug existed specifically because the old test data didn't match real Yelp output.
- The action-threshold fix added three pure unit tests directly against `theme_is_actionable()` — no database needed, since the function takes a plain dict.
- The destructive-`selfcheck`-deletes-real-`analysis.json` bug was caught by a manual verification pass, not a test — a gap worth knowing about: `selfcheck`'s own path-isolation (mirroring how it isolates its test database) doesn't yet have a dedicated regression test proving it stays isolated. A `selfcheck` improvement that adds one would be a welcome first contribution.

Full write-ups of all of the above, including the actual diffs, are in the [CHANGELOG](CHANGELOG.md) — read a couple of those before your first fix to see the level of detail expected.

There's no CI pipeline and no separate test framework (pytest, etc.) — `selfcheck` covers what matters for a project this size. If the project grows enough that this stops being true, that's a discussion to have explicitly, not a default to reach for.

## What to avoid adding

This project follows a "smallest thing that works" discipline on purpose — it started as, and remains, a single ~350-line script with zero dependencies. Before adding any of the following, open an issue/discussion first rather than including it in a PR:

- A new third-party dependency (the whole point of the stdlib-only approach is that setup is three lines)
- A config option for something that's only ever had one value
- An abstraction (interface, base class, plugin registry) for a case that currently has exactly one or two concrete instances — `SOURCES` and `THEMES` being plain dicts *is* the extension mechanism at this scale
- CI, pytest, or other test-framework machinery — see [Testing rule](#testing-rule) above
- Anything that moves business logic into `dashboard.html`'s JavaScript — it's a presentation layer over `analysis.json`, not where analysis should happen

None of these are permanently off the table — they're just not justified by the project's current size, and adding them speculatively is more maintenance burden than the project currently needs.
