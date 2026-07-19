# ⚠️ Synthetic sample data — not real reviews

Everything in this folder is **fabricated**. No real business, no real customer, no real review. It exists purely so a new contributor can see the shape of `reviews.db`'s data without needing to run a real scrape first (which costs a few dollars and requires your own Apify account — see [`CONTRIBUTING.md`](../CONTRIBUTING.md)).

## How to tell it's fake, at every level

- **The business** — "Example Bakery Co", "Faketown" — doesn't exist.
- **Every reviewer name** is literally `"Sample Reviewer N"` (Google-sourced rows) or `"anonymous"` (Yelp-sourced rows, matching this project's real handling of that source — see [Data quality findings](../docs/scrape-results.md#data-quality-findings--fixed-2026-07-16)).
- **Every row carries `"synthetic": true`** as an explicit field — not part of the real `reviews` table schema, added purely as an unmissable marker so this data can never be mistaken for genuine output even if a row is copied out of context.
- **Every `review_id`** contains the literal string `synthetic-` (e.g. `google:synthetic-0001`) — real review IDs from Google/Yelp never look like this.

## What it's for, and what it isn't

**For:** understanding `reviews.db`'s columns (`review_id`, `source`, `listing_url`, `author`, `rating`, `text`, `review_date`, `owner_response`, `scraped_at`) and seeing a plausible mix of ratings, sources, and review text before you've run the pipeline yourself. The review text deliberately touches several of `pipeline.py`'s `THEMES` categories (pastry quality, coffee, service, wait time, price, freshness, cleanliness, parking) so it's also useful for understanding how theme detection works.

**Not for:** testing `analyze()`, `render()`, or the dashboard against. Use `python pipeline.py selfcheck` (its own tiny built-in fixtures) for that, or run a real `scrape` against a business of your choice. This file was never loaded into `reviews.db` or run through the pipeline — it's illustration only.

## File

`synthetic-reviews-sample.json` — 20 rows, JSON array, one object per synthetic review, in the same shape as a row from the `reviews` table (plus the `synthetic: true` marker described above).
