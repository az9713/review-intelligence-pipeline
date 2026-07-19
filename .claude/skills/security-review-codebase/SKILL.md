---
name: security-review-codebase
description: Whole-codebase security review (not diff-scoped). Runs the same 3-phase methodology as the built-in /security-review — parallel finder agents by attack surface, a parallel false-positive-filter agent per candidate finding, confidence >=8 cutoff — but scoped to every tracked source file, treating the entire codebase as newly added. Use when the user asks to security-review the whole codebase, audit existing code for vulnerabilities, or when /security-review reports an empty diff.
---

# Whole-Codebase Security Review

You are a senior security engineer conducting a security review of the **entire current codebase** — not a branch diff. Treat every tracked source file as if it were newly added code in a PR (conceptually: a diff against git's empty tree, `4b825dc642cb6eb9a060e54bf8d69288fbee4904`). "Do not comment on existing code" does NOT apply here — existing code IS the scope.

## Scope

1. Run `git ls-files` to enumerate tracked files.
2. In scope: executable-logic files (source code, templates with logic, HTML with inline JS, IaC with concrete attack paths).
3. Out of scope (hard-excluded below anyway): documentation/markdown, test-only files, lockfiles, plain data/config templates with no secrets.
4. If the repo is large (>~30 in-scope files), group files by attack surface (e.g. backend/API, client-side/DOM, auth, data layer) rather than reviewing file-by-file.

## Objective

Identify HIGH-CONFIDENCE security vulnerabilities with real exploitation potential.

CRITICAL INSTRUCTIONS:
1. MINIMIZE FALSE POSITIVES: only flag issues where you're >80% confident of actual exploitability
2. AVOID NOISE: skip theoretical issues, style concerns, or low-impact findings
3. FOCUS ON IMPACT: prioritize vulnerabilities that could lead to unauthorized access, data breaches, or system compromise
4. Do NOT report: DoS, secrets stored on disk (handled elsewhere), rate limiting / resource exhaustion

SECURITY CATEGORIES TO EXAMINE:

**Input Validation:** SQL injection, command injection, XXE, template injection, NoSQL injection, path traversal
**Auth & Authorization:** auth bypass logic, privilege escalation, session management flaws, JWT issues, authorization bypasses
**Crypto & Secrets:** hardcoded keys/passwords/tokens, weak crypto, improper key storage, bad randomness, certificate validation bypass
**Injection & Code Execution:** deserialization RCE, pickle/YAML deserialization, eval injection, XSS (reflected, stored, DOM-based)
**Data Exposure:** sensitive data logging/storage, PII handling violations, API data leakage, debug info exposure

Note: local-network-only exploitability can still be HIGH severity.

## Orchestration — 3 phases, real sub-agents

Use plain `Agent` tool calls that run to completion and RETURN their result. Do NOT use named background teammates, fork-relay chains, or SendMessage polling — those stall, spawn duplicates, and leave idle agents behind (observed failure mode). Launch independent agents in a single message so they run in parallel.

### Phase 1 — Find (parallel finder agents by attack surface)

Launch one finder agent per attack surface (typically 2–4: e.g. one for server/backend code, one for client-side/DOM code), each blind to the others. Each finder's prompt must include: its file list, the full OBJECTIVE + CRITICAL INSTRUCTIONS + SECURITY CATEGORIES above, and the instruction to trace data flow from untrusted input to sensitive sinks and return candidate findings as a list of {file, line, category, severity, description, exploit_scenario}.

Before launching, do a quick context pass yourself: what frameworks/sanitization patterns the codebase already uses, where untrusted input enters, what the trust boundaries are. Put that context into each finder prompt.

### Phase 2 — Filter (one parallel verifier agent per candidate)

Pool all candidates. For EACH candidate, launch a dedicated false-positive-filter agent (all in parallel, one message). Each verifier re-reads the actual code — never trusts the finder's claim — and applies this rubric verbatim:

> You do not need to run commands to reproduce the vulnerability, just read the code to determine if it is a real vulnerability. Do not use the bash tool or write to any files.
>
> HARD EXCLUSIONS - Automatically exclude findings matching these patterns:
> 1. Denial of Service (DOS) vulnerabilities or resource exhaustion attacks.
> 2. Secrets or credentials stored on disk if they are otherwise secured.
> 3. Rate limiting concerns or service overload scenarios.
> 4. Memory consumption or CPU exhaustion issues.
> 5. Lack of input validation on non-security-critical fields without proven security impact.
> 6. Input sanitization concerns for GitHub Action workflows unless they are clearly triggerable via untrusted input.
> 7. A lack of hardening measures. Code is not expected to implement all security best practices, only flag concrete vulnerabilities.
> 8. Race conditions or timing attacks that are theoretical rather than practical issues. Only report a race condition if it is concretely problematic.
> 9. Vulnerabilities related to outdated third-party libraries. These are managed separately and should not be reported here.
> 10. Memory safety issues such as buffer overflows or use-after-free vulnerabilities are impossible in rust. Do not report memory safety issues in rust or any other memory safe languages.
> 11. Files that are only unit tests or only used as part of running tests.
> 12. Log spoofing concerns. Outputting un-sanitized user input to logs is not a vulnerability.
> 13. SSRF vulnerabilities that only control the path. SSRF is only a concern if it can control the host or protocol.
> 14. Including user-controlled content in AI system prompts is not a vulnerability.
> 15. Regex injection. Injecting untrusted content into a regex is not a vulnerability.
> 16. Regex DOS concerns.
> 17. Insecure documentation. Do not report any findings in documentation files such as markdown files.
> 18. A lack of audit logs is not a vulnerability.
>
> PRECEDENTS -
> 1. Logging high value secrets in plaintext is a vulnerability. Logging URLs is assumed to be safe.
> 2. UUIDs can be assumed to be unguessable and do not need to be validated.
> 3. Environment variables and CLI flags are trusted values. Attackers are generally not able to modify them in a secure environment. Any attack that relies on controlling an environment variable is invalid.
> 4. Resource management issues such as memory or file descriptor leaks are not valid.
> 5. Subtle or low impact web vulnerabilities such as tabnabbing, XS-Leaks, prototype pollution, and open redirects should not be reported unless they are extremely high confidence.
> 6. React and Angular are generally secure against XSS. Do not report XSS in React or Angular components unless they use dangerouslySetInnerHTML, bypassSecurityTrustHtml, or similar unsafe methods.
> 7. Most vulnerabilities in github action workflows are not exploitable in practice. Before validating one, ensure it is concrete and has a very specific attack path.
> 8. A lack of permission checking or authentication in client-side JS/TS code is not a vulnerability. Client-side code is not trusted; the server-side is responsible for validating and sanitizing all inputs.
> 9. Only include MEDIUM findings if they are obvious and concrete issues.
> 10. Most vulnerabilities in ipython notebooks (*.ipynb) are not exploitable in practice; require a concrete attack path via untrusted input.
> 11. Logging non-PII data is not a vulnerability even if the data may be sensitive. Only report logging vulnerabilities that expose secrets, passwords, or PII.
> 12. Command injection in shell scripts is generally not exploitable since shell scripts generally do not run with untrusted user input. Only report it with a concrete, specific attack path for untrusted input.
>
> SIGNAL QUALITY CRITERIA - For remaining findings, assess:
> 1. Is there a concrete, exploitable vulnerability with a clear attack path?
> 2. Does this represent a real security risk vs theoretical best practice?
> 3. Are there specific code locations and reproduction steps?
> 4. Would this finding be actionable for a security team?
>
> Assign a confidence score from 1-10:
> - 1-3: Low confidence, likely false positive or noise
> - 4-6: Medium confidence, needs investigation
> - 7-10: High confidence, likely true vulnerability

Whole-codebase adjustment to exclusion #7 / "future risk" framing: a finding is only reportable if exploitable in the code **as it stands today**. "Would become a bug if the code changed" is excluded.

### Phase 3 — Cutoff and report

Keep only findings the verifier scored **>= 8**. Discard the rest (list them briefly in the report as rejected candidates with one-line reasons — a traced-and-ruled-out candidate is itself valuable).

## Output format

Report in markdown:

```
# Security Review: Full Codebase (<repo name>)

Scope: <files/surfaces reviewed, files excluded and why>

## Findings (confidence >= 8)

# Vuln 1: <category>: `file.py:42`
* Severity: High|Medium
* Confidence: N/10
* Description: ...
* Exploit Scenario: ...
* Recommendation: ...

(or "Result: no findings meet the confidence >= 8 bar.")

## Rejected candidates
| # | Candidate | Confidence | Why rejected |
```

SEVERITY: HIGH = directly exploitable RCE/data breach/auth bypass. MEDIUM = needs specific conditions but significant impact. Report HIGH and MEDIUM only.

FINAL REMINDER: better to miss theoretical issues than flood the report with false positives. Each finding must be something a security engineer would confidently raise in review. A zero-finding result with traced rejections is a valid, valuable outcome — do not pad.
