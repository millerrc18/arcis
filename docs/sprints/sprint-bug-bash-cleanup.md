# Sprint: Bug Bash + Tech Debt Cleanup

> **Priority:** HIGH — #183 blocks v1.0.0, #197 is a security issue
> **Scope:** 1 critical bug, 1 security fix, 5 tech debt items, 2 manual actions
> **Tag as `v0.11.0` after merge.**

**CRITICAL: Run `python -m pytest tests/ -x -q` before AND after.**

---

## Pre-Flight

1. Read `MASTER.md` — current state
2. Read `RELEASES.md` — versioning convention
3. Run `python -m pytest tests/ -x -q` — record baseline pass count

---

## Task 1: Fix LLM Conviction Parsing (#183) — CRITICAL

**This is the #1 bug in the system. Every trade uses default conviction=5 because the parser can't extract conviction from the LLM output.**

**File:** `src/llm/packet_writer.py` — the `_parse_llm_response()` function (~line 215)

The parser expects either:
- XML: `<metadata>Conviction: 7</metadata>`
- Plain text: `CONVICTION: 7`

But 143/145 responses return None. We need to find out what the model ACTUALLY outputs.

**Step 1: Add diagnostic logging.** Before any parsing, log the raw response structure:
```python
# At the top of _parse_llm_response(), BEFORE any parsing:
logger.info("[LLM] Raw response length: %d chars", len(response))
logger.info("[LLM] First 200 chars: %s", response[:200].replace('\n', '\\n'))
logger.info("[LLM] Last 200 chars: %s", response[-200:].replace('\n', '\\n'))
# Log which tags are present
import re
tags_found = re.findall(r'<(\w+)[^>]*>', response)
logger.info("[LLM] XML tags found: %s", list(set(tags_found)))
```

**Step 2: Examine the output and fix the parser.** The model likely outputs one of these:
- `<conviction>7</conviction>` (different tag name than `<metadata>Conviction: 7</metadata>`)
- `**Conviction:** 7` (markdown bold, not XML)
- `Conviction Score: 7/10` (with /10 suffix)
- The conviction is inside a different XML block like `<assessment>` or `<recommendation>`

Add fallback patterns to cover common model output formats:
```python
# After existing XML parsing, add these fallbacks:
if conviction is None:
    # Pattern: <conviction>7</conviction>
    conv_tag = re.search(r'<conviction[^>]*>\s*(\d+)', response, re.IGNORECASE)
    if conv_tag:
        conviction = max(1, min(10, int(conv_tag.group(1))))

if conviction is None:
    # Pattern: Conviction: 7/10 or Conviction Score: 7
    conv_score = re.search(r'conviction\s*(?:score)?[:\s]+(\d+)(?:/10)?', response, re.IGNORECASE)
    if conv_score:
        conviction = max(1, min(10, int(conv_score.group(1))))

if conviction is None:
    # Pattern: **Conviction:** 7 (markdown bold)
    conv_md = re.search(r'\*\*conviction\*\*[:\s]+(\d+)', response, re.IGNORECASE)
    if conv_md:
        conviction = max(1, min(10, int(conv_md.group(1))))
```

**Step 3: Verify the fix works.** After deploying, check the next scan's logs:
```bash
grep "Conviction is None\|llm_conviction\|conviction.*defaulting" logs/arcis.log | tail -20
```

Target: ≥90% conviction parse rate (currently 1%).

---

## Task 2: Fix Finnhub API Key Exposure (#197) — SECURITY

**Files:** `src/data_enrichment/news.py`, `src/data_enrichment/insiders.py`, and any other file that passes the Finnhub key as a URL query parameter.

The Finnhub API uses `?token=API_KEY` in the URL, which gets logged in plaintext by httpx/requests.

**Fix:** Use headers instead of query params where possible. Finnhub supports `X-Finnhub-Token` header:
```python
# FROM:
params = {"symbol": ticker, "token": api_key, ...}
response = requests.get(url, params=params)

# TO:
params = {"symbol": ticker, ...}
headers = {"X-Finnhub-Token": api_key}
response = requests.get(url, params=params, headers=headers)
```

Find ALL instances:
```bash
grep -rn "token.*finnhub\|finnhub.*token\|\"token\".*api_key\|\"token\".*key" src/ --include="*.py"
```

Also check data collectors:
```bash
grep -rn "token" src/data_collection/ --include="*.py" | grep -i "finnhub\|api_key"
```

---

## Task 3: Tech Debt — Close 5 CI/Cosmetic Issues

### #191: reconcile.py exceeds 400-line guardrail
**File:** `src/shadow_trading/reconcile.py` (currently 400 lines — right at the limit)
If it's exactly 400, it passes. If CC's PRs pushed it over, extract the largest function into a helper module. Check: `wc -l src/shadow_trading/reconcile.py`

### #192: schema/validator.py missing docstring header
**File:** `src/schema/validator.py`
Add the standard 5-field docstring header:
```python
"""Schema validator — validates database schema against registry.

Called by: cli.commands, scheduler.watch
Calls: schema.registry
Owns tables: none
Config keys: none
Tests: tests/test_schema.py
"""
```

### #193: False positive 'sql' table in schema/postgres.py
**File:** Check what the guardrail test is flagging. If `schema/postgres.py` uses `CREATE TABLE` for Postgres migrations, it should be whitelisted alongside `schema/registry.py` in the guardrail test.

### #194: test_watch_bootstrap hardcoded table names
**File:** `tests/test_watch_bootstrap.py`
Update the test to read expected table names from the schema registry instead of hardcoding them.

### #82: Silent exception swallowing in council/context.py
**File:** `src/council/context.py`
Find bare `except: pass` or `except Exception: pass` blocks and add `logger.debug()` calls so failures are at least logged.

---

## Task 4: Manual Actions (document, don't code)

Add a comment to these issues noting they require manual action, not code:

**#188 (PFE -14 shares):** "Requires manual position close on Alpaca paper account. Not a code bug — reconciliation backfilled an orphaned short position."

**#187 (44 failed trades — buying power):** "Buying power is checked for live trades but not paper. Low priority — paper account buying power resets, and the system gracefully logs failures."

---

## Task 5: Update MASTER.md + RELEASES.md

After all changes:
- Update MASTER.md Section 2 (volatile) with current issue count
- Add entry to RELEASES.md for v0.11.0
- Update v1.0.0 path table with current status

---

## Acceptance Criteria

### Conviction Parsing (#183)
- [ ] Diagnostic logging added — raw response structure visible in logs
- [ ] At least 3 additional fallback patterns added to parser
- [ ] After deploying, monitor next scan — target ≥50% parse rate (up from 1%)
- [ ] If parse rate still <50%, the diagnostic logs will show exactly what format the model uses

### Security (#197)
- [ ] Zero instances of Finnhub API key in URL query parameters
- [ ] All Finnhub calls use `X-Finnhub-Token` header instead
- [ ] `grep -rn "\"token\".*key\|token.*api" src/ --include="*.py"` returns zero Finnhub matches

### Tech Debt
- [ ] #191: reconcile.py ≤400 lines (or extracted)
- [ ] #192: validator.py has standard docstring
- [ ] #193: guardrail test doesn't false-positive on schema/postgres.py
- [ ] #194: test_watch_bootstrap reads from registry
- [ ] #82: No bare `except: pass` in council/context.py

### Zero Regressions
- [ ] All Python tests pass
- [ ] Pass count ≥ baseline recorded in pre-flight

### Release
- [ ] Tagged `v0.11.0` on main after merge
- [ ] GitHub Release created (pre-release)
- [ ] RELEASES.md updated
