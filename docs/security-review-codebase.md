# The `security-review-codebase` skill — whole-codebase security review

See [`README.md`](../README.md) for the project overview, and [DEVELOPMENT_JOURNEY.md §16–17](../DEVELOPMENT_JOURNEY.md#16-the-security-review-pass) for the narrative this skill grew out of.

A project-scoped Claude Code skill that lives at [`.claude/skills/security-review-codebase/SKILL.md`](../.claude/skills/security-review-codebase/SKILL.md). It runs the same three-phase methodology as Claude Code's built-in `/security-review`, but scoped to the **entire tracked codebase** instead of a branch diff.

## Origin — why it exists

The built-in `/security-review` command is **diff-scoped by design**: it reviews only what changed on the current branch, computing that scope with `git diff … origin/HEAD…`. During this project that surfaced two limitations, in order:

1. **It failed to run at all.** `origin/HEAD` is a symbolic ref that records "which branch the remote considers its default," and it's created automatically only by `git clone`. This repo was never cloned — it was built with `git init` + `git remote add` + `git push` (twice, because the identity scrub rewrote history with a fresh `git init`), so that pointer never existed locally and the command errored with `ambiguous argument 'origin/HEAD…': unknown revision`. The one-time fix was `git remote set-head origin -a`, which asks the remote for its default branch and writes the missing ref.

2. **Even once fixed, it had nothing to review.** With the local branch fully in sync with `origin/main`, the diff was empty — so the command correctly reported "no changes to review." Every security fix this project had shipped (notably the [XSS defect](../DEVELOPMENT_JOURNEY.md#11-the-xss-vulnerability)) had been caught by reviewing a *recent change*. The **existing** code as a whole had never been through a security review.

Because the built-in command has no scope override (unlike `/code-review`, which accepts a free-text "review the whole codebase" instruction), the only way to get a whole-codebase result was to replicate its methodology by hand — which was done once, manually, with a team of sub-agents. This skill turns that one-off manual replication into a repeatable, committed tool, so the whole-codebase review is a single invocation next time instead of hand-orchestrated agents.

## What it is

A security review that treats **every tracked source file as if it were newly added** — conceptually a diff against git's empty-tree hash (`4b825dc642cb6eb9a060e54bf8d69288fbee4904`), which every git repo shares. That reframing is what makes the whole codebase read as "in scope" while reusing the built-in command's exact finding-and-filtering rubric. It reviews existing code, and it does not depend on `origin/HEAD` existing, so it works on `init`-and-`push` repos where the built-in command can't compute a scope.

It is **not** a general code review — it looks only for concrete, exploitable security vulnerabilities (injection, XSS, auth bypass, path traversal, unsafe deserialization, secrets, sensitive-data exposure), and it deliberately excludes whole categories by design (denial-of-service, secrets-at-rest, rate limiting, "lack of hardening," theoretical races, and more — the full hard-exclusions list is in the skill body).

## How it works — three phases

**Phase 1 — Find (parallel finders, partitioned by attack surface).** After a quick context pass (what frameworks and sanitization patterns the code already uses, where untrusted input enters, where the trust boundaries are), it launches one finder agent per attack surface — typically one for server/backend code and one for client-side/DOM code — each blind to the others. Each traces data flow from untrusted input to sensitive sinks and returns candidate findings.

**Phase 2 — Filter (one verifier per candidate, in parallel).** Every candidate gets its own dedicated agent that **re-reads the actual code** rather than trusting the finder's claim, applies the built-in command's verbatim false-positive rubric (hard exclusions + precedents + signal-quality criteria), and assigns a 1–10 confidence score. This filtering step is the point of the whole exercise: pattern-matching "unescaped data near `innerHTML`" is easy and noisy; tracing each candidate to its real data origin is what separates "looks suspicious" from "is actually exploitable."

**Phase 3 — Cutoff.** Only findings scored **≥ 8** are reported. Everything else is listed briefly as a rejected candidate with a one-line reason — a traced-and-ruled-out candidate is itself a valuable result, not noise to hide.

### Design choices carried over from the manual run

- **Plain `Agent` calls that return their result**, launched in parallel in one message. The manual replication first tried named background "teammates" with fork-relay chains and `SendMessage` polling; that pattern stalled, spawned duplicate finder agents, and left 15 idle agents alive that had to be stopped one by one afterward. The skill explicitly bans that approach.
- **"Exploitable as the code stands today."** A finding framed as "would become a bug if the code later changed" is excluded. In the manual run, two of the five candidates were rejected on exactly this basis — they described risks contingent on future edits, not present holes.

## How to use it

From a Claude Code session in this repo:

```
/security-review-codebase
```

or ask in natural language to "security-review the whole codebase" / "audit the existing code for vulnerabilities." It's also the right fallback when the built-in `/security-review` reports an empty diff but you want coverage of everything already in the repo.

Output is a markdown report: an in-scope summary, any findings at confidence ≥ 8 (file, line, severity, category, description, exploit scenario, recommendation), and a table of rejected candidates.

## What the first whole-codebase run found

Zero findings survived the confidence-≥8 bar. Two independent finders surfaced five candidates across `pipeline.py` and `dashboard.html`; every one scored 2–3/10 and was ruled out by tracing its real data flow (e.g. the Apify token travels only over direct HTTPS from a single-operator local CLI; the dashboard's `date`/`rating`/`source` fields are all pipeline-normalized before rendering, never raw reviewer text). The run also re-confirmed the two real earlier fixes — the `<` XSS escape and scrape-time PII stripping — were still in place. See [DEVELOPMENT_JOURNEY.md §16](../DEVELOPMENT_JOURNEY.md#16-the-security-review-pass) for the full candidate-by-candidate breakdown.
