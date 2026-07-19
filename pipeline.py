"""Review intelligence pipeline -- business identity and sources come from config.json.

Usage:
    python pipeline.py scrape      # run Apify actors, upsert into reviews.db (SPENDS CREDIT)
    python pipeline.py analyze     # reviews.db -> analysis.json
    python pipeline.py render      # analysis.json -> embedded into dashboard.html
    python pipeline.py selfcheck   # offline sanity check, no network

Setup: copy config.example.json to config.json and fill in your business's details.
"""
import json, os, re, sqlite3, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "reviews.db")
ANALYSIS_PATH = os.path.join(HERE, "analysis.json")
RAW_DIR = os.path.join(HERE, "data", "raw")


def load_config():
    path = os.path.join(HERE, "config.json")
    if not os.path.exists(path):
        sys.exit("config.json not found -- copy config.example.json to config.json and fill in your business's details")
    return json.load(open(path, encoding="utf-8"))


CONFIG = load_config()
BUSINESS_NAME = CONFIG["business"]["full_name"]
MAX_REVIEWS_PER_SOURCE = CONFIG.get("max_reviews_per_source", 500)

SOURCES = {
    "google": {
        "actor": CONFIG["sources"]["google"]["actor"],
        "input": {
            "startUrls": [{"url": "https://www.google.com/maps/search/"
                + urllib.parse.quote(CONFIG["sources"]["google"]["search_query"])}],
            "maxReviews": MAX_REVIEWS_PER_SOURCE,
            "reviewsSort": "newest",
            "language": "en",
        },
        "listing_url": CONFIG["sources"]["google"]["listing_url"],
    },
    "yelp": {
        "actor": CONFIG["sources"]["yelp"]["actor"],
        "input": {
            "biz_urls": [CONFIG["sources"]["yelp"]["biz_url"]],
            "reviews_limit": MAX_REVIEWS_PER_SOURCE,
            "reviews_sort": "newest",
        },
        "listing_url": CONFIG["sources"]["yelp"]["listing_url"],
    },
}


def token():
    with open(os.path.join(HERE, ".env")) as f:
        for line in f:
            k, _, v = line.strip().partition("=")
            if k in ("APIFY_API_TOKEN", "APIFY_TOKEN") and v:
                return v
    sys.exit("No APIFY_API_TOKEN in .env")


def api(url, payload=None):
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"},
                                 data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def run_actor(actor, actor_input, tok):
    run = api(f"https://api.apify.com/v2/acts/{actor}/runs?token={tok}", actor_input)["data"]
    run_id = run["id"]
    print(f"  {actor}: run {run_id} started")
    for _ in range(90):  # up to 15 min
        time.sleep(10)
        run = api(f"https://api.apify.com/v2/actor-runs/{run_id}?token={tok}")["data"]
        if run["status"] not in ("READY", "RUNNING"):
            break
        print(f"  ... {run['status']}")
    if run["status"] != "SUCCEEDED":
        sys.exit(f"  run {run_id} ended {run['status']} — aborting")
    items = api(f"https://api.apify.com/v2/datasets/{run['defaultDatasetId']}/items?token={tok}&clean=true&format=json")
    print(f"  {len(items)} items, cost ${run.get('usageTotalUsd', 0):.2f}")
    return items, run.get("usageTotalUsd", 0)


def first(item, *keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_date(v):
    if not v:
        return None
    v = str(v)
    m = re.search(r"\d{4}-\d{2}-\d{2}", v)
    if m:
        return m.group(0)
    for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(v.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def normalize(source, listing_url, item):
    """Map one raw actor item to our schema. Tolerant to key naming across actors."""
    rid = first(item, "reviewId", "review_id", "id", "reviewUrl", "url")
    rating = first(item, "stars", "rating", "review_rating", "score")
    text = first(item, "text", "review_text", "comment", "reviewText") or ""
    if isinstance(text, dict):  # yelp sometimes nests {"text": ...}
        text = text.get("text", "")
    date = parse_date(first(item, "publishedAtDate", "reviewDate", "review_date", "date", "created_at", "localizedDate"))
    owner = first(item, "responseFromOwnerText", "owner_response", "business_owner_replies", "ownerResponse")
    if owner is None and isinstance(item.get("publicReply"), dict):
        owner = item["publicReply"].get("text")
    if isinstance(owner, (list, dict)):
        owner = json.dumps(owner)
    if source == "yelp":
        # ponytail: this actor's `name` key is the business, not the reviewer, and its
        # nested author.name is always empty in practice -- "anonymous" is honest, not a bug.
        author = (item.get("author") or {}).get("name") or "anonymous"
    else:
        author = first(item, "name", "reviewer_name", "user_name", "author") or "anonymous"
    if rid is None or rating is None:
        return None
    try:
        rating = float(rating)
    except (TypeError, ValueError):
        return None
    return (f"{source}:{rid}", source, listing_url, str(author), rating, str(text), date, owner,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS reviews (
        review_id TEXT PRIMARY KEY, source TEXT, listing_url TEXT, author TEXT,
        rating REAL, text TEXT, review_date TEXT, owner_response TEXT, scraped_at TEXT)""")
    return con


def upsert(con, rows):
    con.executemany("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()


# Dropped before raw JSON ever touches disk: these two point directly at a specific
# person (their live profile page, their photo) and nothing downstream uses either.
# reviewUrl (links to the REVIEW, not the reviewer), reviewerNumberOfReviews, and
# isLocalGuide are deliberately kept -- see README "Privacy design" Part 2 for why.
PII_FIELDS_TO_STRIP = ("reviewerUrl", "reviewerPhotoUrl")


def strip_reviewer_pii(items):
    for it in items:
        for field in PII_FIELDS_TO_STRIP:
            it.pop(field, None)
    return items


def scrape():
    tok = token()
    os.makedirs(RAW_DIR, exist_ok=True)
    con = db()
    total_cost = 0.0
    for source, cfg in SOURCES.items():
        print(f"[{source}] scraping via {cfg['actor']} (cap {MAX_REVIEWS_PER_SOURCE})")
        items, cost = run_actor(cfg["actor"], cfg["input"], tok)
        items = strip_reviewer_pii(items)
        total_cost += cost
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        with open(os.path.join(RAW_DIR, f"{source}-{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        rows = [r for r in (normalize(source, cfg["listing_url"], it) for it in items) if r]
        skipped = len(items) - len(rows)
        upsert(con, rows)
        print(f"  upserted {len(rows)} reviews" + (f", skipped {skipped} unmappable" if skipped else ""))
        if total_cost > 2.0:
            sys.exit(f"Cost ${total_cost:.2f} exceeded $2 guardrail — stopping before next source")
    n = con.execute("SELECT COUNT(*), MIN(review_date), MAX(review_date) FROM reviews").fetchone()
    print(f"DONE: {n[0]} reviews in db ({n[1]} .. {n[2]}), total run cost ${total_cost:.2f}")


# --- analysis -----------------------------------------------------------------
THEMES = {  # ponytail: keyword lexicon; refine after seeing real data
    "pastry & bread quality": ["pastry", "pastries", "bread", "croissant", "bake", "baked", "cake", "dessert", "bun", "loaf"],
    "coffee & drinks": ["coffee", "latte", "drink", "tea", "espresso", "boba", "smoothie"],
    "service & staff": ["service", "staff", "employee", "rude", "friendly", "helpful", "cashier", "attitude"],
    "wait & speed": ["wait", "slow", "line", "queue", "long", "quick", "fast"],
    "price & value": ["price", "expensive", "overpriced", "value", "cheap", "cost", "worth"],
    "freshness": ["fresh", "stale", "dry", "soggy", "old"],
    "cleanliness & space": ["clean", "dirty", "table", "seating", "space", "restroom", "bathroom"],
    "parking & access": ["parking", "park", "location", "access"],
}


def sentiment(rating):
    return "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"


def quarter(d):
    return f"{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}" if d else None


def theme_is_actionable(t):
    """A theme becomes a recommended action if EITHER: negative mentions are a large
    share of its total (>25%, the original signal), OR it's worsening (recent avg
    down >0.2* from older avg) with enough negative volume (>=10) to not be noise --
    this second branch catches large themes whose negative share looks moderate only
    because they also have a lot of positive mentions (e.g. a big theme sliding from
    great to mediocre reads as "worsening", not "mostly negative")."""
    worsening = (t["avg_rating_recent"] is not None and t["avg_rating_older"] is not None
                 and t["avg_rating_recent"] < t["avg_rating_older"] - 0.2)
    high_negative_share = t["negative"] >= 3 and t["negative"] / t["mentions"] > 0.25
    return high_negative_share or (worsening and t["negative"] >= 10), worsening


def analyze():
    con = db()
    rows = con.execute("SELECT review_id, source, rating, text, review_date, owner_response FROM reviews").fetchall()
    con.close()
    if not rows:
        sys.exit("reviews.db is empty — run scrape first")
    reviews = [dict(zip(["id", "source", "rating", "text", "date", "owner"], r)) for r in rows]

    kpis = {
        "total_reviews": len(reviews),
        "avg_rating": round(sum(r["rating"] for r in reviews) / len(reviews), 2),
        "pct_1_2_star": round(100 * sum(r["rating"] <= 2 for r in reviews) / len(reviews), 1),
        "by_source": {},
    }
    for s in sorted({r["source"] for r in reviews}):
        sub = [r for r in reviews if r["source"] == s]
        kpis["by_source"][s] = {"count": len(sub), "avg_rating": round(sum(r["rating"] for r in sub) / len(sub), 2)}

    trend = {}
    for r in reviews:
        q = quarter(r["date"])
        if q:
            trend.setdefault(q, []).append(r["rating"])
    kpis["trend"] = [{"quarter": q, "avg_rating": round(sum(v) / len(v), 2), "count": len(v)}
                     for q, v in sorted(trend.items())]

    themes = []
    dated = sorted([r for r in reviews if r["date"]], key=lambda r: r["date"])
    cutoff = dated[-1]["date"][:4] + "-01-01" if dated else None  # current-ish year vs before
    for name, words in THEMES.items():
        pat = re.compile(r"\b(" + "|".join(words) + r")\w*", re.I)
        hits = [r for r in reviews if pat.search(r["text"])]
        if len(hits) < 3:
            continue
        neg = [r for r in hits if sentiment(r["rating"]) == "negative"]
        pos = [r for r in hits if sentiment(r["rating"]) == "positive"]
        recent = [r for r in hits if r["date"] and r["date"] >= cutoff]
        older = [r for r in hits if r["date"] and r["date"] < cutoff]
        theme = {
            "theme": name, "mentions": len(hits),
            "positive": len(pos), "negative": len(neg),
            "avg_rating": round(sum(r["rating"] for r in hits) / len(hits), 2),
            "avg_rating_recent": round(sum(r["rating"] for r in recent) / len(recent), 2) if recent else None,
            "avg_rating_older": round(sum(r["rating"] for r in older) / len(older), 2) if older else None,
            "worst_quotes": [{"id": r["id"], "rating": r["rating"], "date": r["date"],
                              "quote": r["text"][:300]} for r in sorted(neg, key=lambda x: x["rating"])[:3]],
            "best_quotes": [{"id": r["id"], "rating": r["rating"], "date": r["date"],
                             "quote": r["text"][:300]} for r in sorted(pos, key=lambda x: -x["rating"])[:2]],
        }
        # computed once here, from the same theme_is_actionable() used for the actions
        # list below, so the "worsening" badge dashboard.html shows can never drift from
        # which themes actually qualify as worsening -- no second, JS-side copy of the
        # 0.2* threshold to keep in sync.
        theme["worsening"] = theme_is_actionable(theme)[1]
        themes.append(theme)
    themes.sort(key=lambda t: -t["mentions"])

    neg_reviews = [r for r in reviews if r["rating"] <= 3]
    no_resp = [r for r in neg_reviews if not r["owner"]]
    response_gap = {
        "negative_reviews": len(neg_reviews),
        "unanswered": len(no_resp),
        "pct_unanswered": round(100 * len(no_resp) / len(neg_reviews), 1) if neg_reviews else 0,
        "examples": [{"id": r["id"], "rating": r["rating"], "date": r["date"], "quote": r["text"][:200]}
                     for r in sorted(no_resp, key=lambda x: x["date"] or "", reverse=True)[:3]],
    }

    actions = []
    for t in themes:
        qualifies, worsening = theme_is_actionable(t)
        if qualifies:
            actions.append({
                "action": f"Address '{t['theme']}'",
                "evidence": f"{t['negative']}/{t['mentions']} mentions are 1-2★ (theme avg {t['avg_rating']}★"
                            + (f", worsening: {t['avg_rating_older']}→{t['avg_rating_recent']}★" if worsening else "") + ")",
                "priority": round(t["negative"] / t["mentions"] * t["mentions"] ** 0.5, 2),
                "cited_reviews": [q["id"] for q in t["worst_quotes"]],
            })
    if response_gap["pct_unanswered"] > 50:
        actions.append({
            "action": "Start responding to negative reviews",
            "evidence": f"{response_gap['pct_unanswered']}% of ≤3★ reviews ({response_gap['unanswered']}/{response_gap['negative_reviews']}) have no owner response",
            "priority": 99,
            "cited_reviews": [e["id"] for e in response_gap["examples"]],
        })
    actions.sort(key=lambda a: -a["priority"])

    out = {"business": BUSINESS_NAME,
           "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "kpis": kpis, "themes": themes, "response_gap": response_gap, "actions": actions}
    path = ANALYSIS_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {path}: {len(themes)} themes, {len(actions)} actions from {len(reviews)} reviews")


DASHBOARD_START = "const ANALYSIS = "
DASHBOARD_END = ";\n\nconst root = document.querySelector('.viz-root');"


def json_for_script_tag(data):
    """json.dumps() never escapes '<', so a review containing the literal text
    "</script>" would otherwise close the dashboard's <script> tag early and let
    arbitrary HTML/JS run in the browser. \\u003c is valid inside a JS string literal
    (parses back to '<') but contains no literal '<' byte, so the HTML tokenizer that
    looks for the closing tag can never mistake it for one."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def render():
    """Re-embed analysis.json into dashboard.html's `const ANALYSIS = ...;` line.
    Locates the JSON blob by exact surrounding markers (not brace-matching) since a
    review quote could itself contain the characters '};'."""
    if not os.path.exists(ANALYSIS_PATH):
        sys.exit("analysis.json not found -- run analyze first")
    data = json.load(open(ANALYSIS_PATH, encoding="utf-8"))
    payload = json_for_script_tag(data)

    dash_path = os.path.join(HERE, "dashboard.html")
    html = open(dash_path, encoding="utf-8").read()
    try:
        start = html.index(DASHBOARD_START) + len(DASHBOARD_START)
        end = html.index(DASHBOARD_END, start)
    except ValueError:
        sys.exit("could not find the ANALYSIS embed markers in dashboard.html -- did the script structure change?")
    new_html = html[:start] + payload + html[end:]
    with open(dash_path, "w", encoding="utf-8") as f:
        f.write(new_html)
    print(f"dashboard.html updated with analysis from {data['generated_at']} "
          f"({len(data['themes'])} themes, {len(data['actions'])} actions)")


def selfcheck():
    global DB, ANALYSIS_PATH
    real_db, real_analysis_path = DB, ANALYSIS_PATH
    DB = os.path.join(HERE, "selfcheck.db")
    ANALYSIS_PATH = os.path.join(HERE, "selfcheck-analysis.json")
    if os.path.exists(DB):
        os.remove(DB)
    con = db()
    fake = [
        {"reviewId": "a", "stars": 5, "text": "Amazing croissants, so fresh!", "publishedAtDate": "2026-05-01T10:00:00Z", "name": "A"},
        {"reviewId": "b", "stars": 1, "text": "Waited 30 minutes in line, slow service and rude staff", "publishedAtDate": "2026-06-01", "name": "B"},
        {"review_id": "c", "rating": "2", "review_text": "Stale bread, overpriced", "date": "May 3, 2025", "reviewer_name": "C"},
    ]
    rows = [r for r in (normalize("google", "url", f) for f in fake) if r]
    assert len(rows) == 3, rows
    upsert(con, rows)
    upsert(con, rows)  # idempotent
    assert con.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 3, "upsert not idempotent"
    assert rows[2][6] == "2025-05-03", rows[2][6]

    # regression test: real Yelp actor shape (reviewDate, nested publicReply/author) --
    # this exact shape is what slipped through undetected on the 2026-07-16 live run.
    yelp_fake = {
        "reviewId": "y1", "rating": 5, "text": "Great cakes",
        "reviewDate": "2026-05-20T09:57:17-07:00",
        "name": "Some Business",  # business name -- must NOT be used as author
        "author": {"name": None},
        "publicReply": {"text": "Thank you for your review!", "role": "OWNER"},
    }
    yrow = normalize("yelp", "url", yelp_fake)
    assert yrow[3] == "anonymous", f"yelp author should fall back to anonymous, got {yrow[3]!r}"
    assert yrow[6] == "2026-05-20", f"yelp reviewDate not parsed, got {yrow[6]!r}"
    assert yrow[7] == "Thank you for your review!", f"yelp publicReply.text not captured, got {yrow[7]!r}"
    con.close()
    analyze()
    a = json.load(open(ANALYSIS_PATH))
    assert a["kpis"]["total_reviews"] == 3
    assert any(t["theme"] == "wait & speed" for t in a["themes"]) is False  # only 1 hit, below min 3
    os.remove(DB)
    os.remove(ANALYSIS_PATH)
    DB, ANALYSIS_PATH = real_db, real_analysis_path

    # regression test: theme_is_actionable's two branches, independent of the pipeline run above.
    # A big theme sliding from great to mediocre (worsening) but with plenty of positive
    # mentions keeping its negative SHARE under 25% must still surface as an action --
    # this is the pastry & bread quality gap found on the 2026-07-17 live run (23% negative
    # share, 524 mentions, clearly worsening, originally excluded).
    worsening_low_share = {"negative": 15, "mentions": 200, "avg_rating_recent": 2.5, "avg_rating_older": 3.5}
    assert theme_is_actionable(worsening_low_share)[0] is True, "worsening high-volume theme should qualify despite low negative share"
    # A worsening theme with too little negative volume (noise) must NOT qualify via the new branch.
    worsening_low_volume = {"negative": 5, "mentions": 200, "avg_rating_recent": 2.0, "avg_rating_older": 4.0}
    assert theme_is_actionable(worsening_low_volume)[0] is False, "worsening theme under the negative-volume floor should not qualify"
    # High negative share still qualifies on its own (original branch), worsening or not.
    high_share_stable = {"negative": 40, "mentions": 100, "avg_rating_recent": 3.0, "avg_rating_older": 3.0}
    assert theme_is_actionable(high_share_stable)[0] is True, "high negative share should qualify regardless of trend"

    # regression test: strip_reviewer_pii drops only the two profile-linking fields,
    # keeps everything else (including reviewUrl, which links to the REVIEW not the reviewer).
    pii_item = {
        "reviewId": "z1", "stars": 5, "text": "ok",
        "reviewerUrl": "https://www.google.com/maps/contrib/12345",
        "reviewerPhotoUrl": "https://lh3.googleusercontent.com/a-/fake-photo",
        "reviewUrl": "https://www.google.com/maps/reviews/data=fake",
        "reviewerNumberOfReviews": 24,
        "isLocalGuide": True,
    }
    stripped = strip_reviewer_pii([dict(pii_item)])[0]
    assert "reviewerUrl" not in stripped and "reviewerPhotoUrl" not in stripped, "profile-linking fields should be dropped"
    assert stripped["reviewUrl"] == pii_item["reviewUrl"], "reviewUrl (links to the review, not the reviewer) must survive"
    assert stripped["reviewerNumberOfReviews"] == 24 and stripped["isLocalGuide"] is True, "non-identifying fields must survive"
    # must not crash on items that don't have the fields at all (e.g. Yelp's shape)
    assert strip_reviewer_pii([{"reviewId": "z2", "stars": 3}])[0] == {"reviewId": "z2", "stars": 3}

    # regression test: a review quoting "</script>" must not be able to break out of
    # dashboard.html's <script> tag -- found by an automated security review after the
    # first public push. The embedded payload must contain no literal '<' byte at all,
    # and must still round-trip to the original string once a JS engine parses it.
    evil = {"quote": "nice place </script><script>alert(1)</script> great coffee"}
    escaped = json_for_script_tag(evil)
    assert "<" not in escaped, f"escaped payload must contain no literal '<': {escaped!r}"
    assert json.loads(escaped.replace("\\u003c", "<")) == evil, "escaping must be reversible back to the original data"

    print("selfcheck OK")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"scrape": scrape, "analyze": analyze, "render": render, "selfcheck": selfcheck}.get(cmd, lambda: sys.exit(__doc__))()
