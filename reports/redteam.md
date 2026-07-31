# Red-team assessment — sleep-tracker

**Agent:** Grok (adversarial QA)  
**Date:** 2026-07-31  
**Target:** isolated instances only  
- Unauthenticated: `http://127.0.0.1:5010` (`SLEEP_DB_PATH=/tmp/redteam-sleep.db`)  
- Authenticated: `http://127.0.0.1:5011` (`SLEEP_PASSWORD=test123`, `SLEEP_DB_PATH=/tmp/redteam-auth-sleep.db`)  
**Scope rules honored:** no edits outside this file; did not touch port 5002, project `sleep.db`, or `~/Desktop/apple_health_export/`.

**Method:** static review of `app.py`, `database.py`, `importers/*`, then live attacks via curl/Python against the isolated Gunicorn workers. Scale/logic tests also used in-process Flask client + direct SQLite against `/tmp/redteam-*.db` only.

---

## Severity summary

| Severity | Confirmed | Notes |
|----------|-----------|--------|
| Critical | 2 | `/api/ingest` hard-broken (500); unauth destructive CSRF when password unset |
| High     | 2 | Ingest quality/stages contract broken; unlimited manual duplicate nights |
| Medium   | 4 | Default secret/bind, missing CSP, insights cost at scale, weak source validation path |
| Low      | 4 | Zero-hour nights, year-1900 dates, no-auth LAN exposure class, incomplete stage KeyError theory |

---

## Confirmed findings

### C1 — CRITICAL: `POST /api/ingest` 500s on every valid night

**Observed:** Any well-formed night that passes field validation crashes the worker:

```bash
curl -sS -X POST http://127.0.0.1:5010/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{"date":"2021-06-01","bedtime":"23:00","wake":"07:00","quality":4,"source":"apple_health"}'
# → 500 Internal Server Error
```

**Trace (gunicorn error log):**

```
File "app.py", line 373, in api_ingest
  imp, rep = upsert_wearable_records(accepted)
File "database.py", line 194, in upsert_wearable_records
  night["wake"],
KeyError: 'wake'
```

**Root cause:** `api_ingest` builds dicts with key `wake_time` and flattened stage columns (`deep_minutes`, …). `upsert_wearable_records` expects the wearable-night shape: `wake` plus nested `stages: {deep,rem,light,awake}`.

**Expected:** 200 `{ok, imported, replaced, skipped, stats}` and a persisted row.  
**Also broken:** stage-derived quality path never runs for missing `quality` because `_parse_record_values` requires quality 1–5 first:

```bash
curl -sS -X POST http://127.0.0.1:5010/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{"date":"2021-06-02","bedtime":"23:00","wake":"07:00","stages":{"deep":90,"rem":100,"light":200,"awake":20}}'
# → 200 {"errors":[{"index":0,"error":"Quality must be an integer from 1 to 5."}], "imported":0, ...}
```

Malformed JSON / wrong content-type / 101-night cap *do* return 400 as intended.

**Suggested fix (lane: Cline / app.py):** Build the same night dict shape as `/import/wearable` (`wake`, nested `stages`, call `derive_quality` *before* or *instead of* requiring quality in `_parse_record_values` for this route). Do not invent a parallel upsert.

---

### C2 — CRITICAL (when `SLEEP_PASSWORD` unset): state-changing POSTs with no Origin / no Sec-Fetch-Site succeed

**Observed:** Cross-site headers are rejected, but a bare POST (what a classic HTML form, many scripts, and non-browser clients send) is allowed:

```bash
# blocked
curl -sS -X POST http://127.0.0.1:5010/add \
  -H 'Origin: https://evil.example' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'date=2020-03-01&bedtime=23:00&wake=07:00&quality=3'
# → 403 {"error":"Cross-site request rejected."}

# allowed — wiped the entire redteam DB during testing
curl -sS -X POST http://127.0.0.1:5010/settings/clear \
  -H 'Content-Type: application/x-www-form-urlencoded'
# → 200 redirect; subsequent GET /api/stats → total: 0
```

Also accepted: evil `Referer` only (no Origin check on Referer), and missing Origin entirely.

**Expected (for a browser-exposed app without auth):** mutations should require a CSRF token or at least SameSite session + non-GET confirmation for `clear`.  
**With Basic Auth set:** browsers do not auto-attach `Authorization` on cross-origin form posts, so risk drops sharply — still relevant for LAN no-password deployments (`python app.py` defaults to `0.0.0.0`).

**Suggested fix:** Require CSRF token for cookie/session browser forms; treat API clients (Shortcuts) via explicit token or Basic Auth only; never expose `settings/clear` without auth on a shared network. Force `SLEEP_PASSWORD` in production docs/deploy config.

---

### H1 — HIGH: unlimited duplicate rows for the same calendar night (manual source)

**Observed:** 50 parallel `POST /add` for `date=2022-01-15` all returned 200; SQLite contained **50 rows** with `(date, source) = (2022-01-15, manual)`.

```text
duplicate (date,source) groups: [('2022-01-15', 'manual', 50), ...]
```

There is **no UNIQUE(date, source)** constraint. Wearable upsert dedups in application code; manual insert does not.

**Impact:** streaks count unique *dates* (OK), but `avg_hours` / `avg_quality` / nap-summing sleep debt treat each row independently — parallel submits or double-clicks inflate averages; series “latest id wins” hides earlier rows without deleting them.

**Concurrent wearable upsert** of the same `(date, source)` under 50 threads collapsed to **1 row** (no lost-update errors observed) — application-level SELECT/UPDATE/INSERT held up under SQLite serialization in this test.

**Suggested fix:** UNIQUE index on `(date, source)` for wearables; for manual, either allow intentional multi-row naps (document) or dedupe UI double-submit; always use transactions + unique constraints where identity is claimed.

---

### H2 — HIGH: `/api/ingest` is unusable for its stated purpose (Shortcuts / Health Auto Export)

Beyond C1’s 500:

| Case | Result |
|------|--------|
| Valid night + quality | 500 KeyError |
| Stages only, no quality | 200 with per-item error (quality required) |
| Partial array (1 bad, 2 good) | 500 before any commit (valid items not applied) |
| 101 nights | 400 Too many records (OK) |
| Malformed JSON | 400 (OK) |
| Wrong Content-Type | 400 (OK) |
| ~1 MiB+ body | connection drop / size reject (global 2 MiB + app check) |

**Expected (product contract):** partial-failure arrays apply valid items; stage-derived quality; upsert on `(date, source)`.

**Suggested fix:** same as C1; add tests in `tests/test_ingest.py` (Cline lane).

---

### M1 — MEDIUM: default `SECRET_KEY` and bind-all host

```python
SECRET_KEY=os.environ.get("SECRET_KEY", "sleep-tracker-dev-key")
# __main__:
app.run(host=os.environ.get("HOST", "0.0.0.0"), ...)
```

**Impact:** predictable session signing if anything session-backed is added; flash messages forgeable today (low). Binding `0.0.0.0` without password exposes the app on the LAN.

**Suggested fix:** refuse to start in non-debug without `SECRET_KEY` + `SLEEP_PASSWORD`; default host `127.0.0.1`.

---

### M2 — MEDIUM: no Content-Security-Policy

Security headers present: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy`, `Cache-Control: no-store`.  
**Missing:** `Content-Security-Policy`.

XSS in HTML seed currently mitigated by JSON escaping (`\u003c` etc. in `window.__INITIAL_RECORDS__`). CSP would be defense-in-depth if a future template regresses escaping.

**Suggested fix:** strict CSP (`default-src 'self'; script-src 'self' 'unsafe-inline'` only if inline seeds remain; prefer nonce).

---

### M3 — MEDIUM: `/api/insights` cost grows poorly with history

On a **50,000-night** synthetic DB (`/tmp/redteam-scale.db`):

| Endpoint | Time | Notes |
|----------|------|-------|
| `get_stats()` | **0.38 s** | full table scan + Python |
| `GET /api/series?range=all` | **0.25 s** | ~3.9 MB JSON |
| `GET /api/export` | **0.25 s** | ~7.8 MB |
| `GET /export.csv` | **0.24 s** | ~1.8 MB |
| `GET /api/insights` | **3.10 s** | multiple full `get_all_records()` passes |
| `GET /` | **0.39 s** | OK |

Does not fall over at 50k; insights is the first soft DoS if an authenticated (or open) client hammers it.

**Suggested fix:** single-pass aggregates; SQL-side GROUP BY; cache.

---

### M4 — MEDIUM: CSV formula injection — prior fix largely holds

Notes starting with `=`, `+`, `-`, `@`, tab, or leading space are exported with a leading `'`:

```text
2018-02-01,22:00,06:00,4,'=1+1,8.0
2018-02-02,22:00,06:00,4,'+cmd|'/c calc'!A0,8.0
2018-02-05,22:00,06:00,4,'	=1+1,8.0
2018-02-07,22:00,06:00,4,' =1+1,8.0
```

CR/LF-leading notes are also prefixed. **Verified held** for common spreadsheet vectors. Residual risk is spreadsheet-specific interpretation of escaped quotes inside fields — not broken in Excel-style leading-formula sense.

---

### L1 — LOW: zero-duration and absurdly short nights accepted

```text
bedtime == wake → hours 0.0 (accepted)
23:59 → 00:01 → hours 0.03 (accepted)
```

**Suggested fix:** reject `hours < 0.25` (or similar) for manual entry; allow wearable short segments only after clustering.

---

### L2 — LOW: historical dates to year 1900 accepted

`date=1900-01-01` stored successfully. Future dates rejected. Invalid calendar dates (`2020-02-30`) rejected. Good enough for import; optional floor (e.g. 1990) is product taste.

---

### L3 — LOW: auth timing differences are small / not a practical oracle

Against `/api/records?limit=1` on the passworded instance (n=30):

| Credential | mean ± sd |
|------------|-----------|
| correct `sleep:test123` | 0.51 ± 0.10 ms |
| wrong last char (same length) | 0.36 ± 0.03 ms |
| wrong first char | 0.36 ± 0.02 ms |
| short password | 0.34 ± 0.01 ms |
| wrong user | 0.35 ± 0.02 ms |

Code uses `hmac.compare_digest` for both user and password — good. Residual delta is dominated by 200 vs 401 response work, not a clean byte-oracle. **Not filed as exploitable.**

---

### L4 — LOW: `derive_quality` throws on incomplete stage dicts

```python
derive_quality({"rem": 10, "light": 10, "awake": 0})  # KeyError: 'deep'
derive_quality({"deep": "x", "rem": 1, "light": 1, "awake": 1})  # TypeError
```

Wearable parsers always emit full int maps, so production path is safe today. Any future caller (ingest) must validate before calling.

---

## Attack surface results (what we tried and could NOT break)

### Injection

| Vector | Result |
|--------|--------|
| SQL via `limit`, `range`, dates, notes, settings | **Not injectable** — parameterized SQL; limit/range validated by regex/allowlist |
| Path traversal via upload filename (`../../etc/passwd`) | **No write** — filename only used for `.csv` suffix check / display; no filesystem open by client name |
| XXE / billion laughs / external DTD on Apple XML | **Blocked** — entity decls rejected; external DTD rejected |
| Nested XML depth | **Blocked** at 64 |
| Zip bombs (10–50 MB zeros, ~1000:1 ratio) | **Blocked** at 500:1 compression ratio |
| Fitbit NaN/Infinity JSON | **Blocked** |
| Fitbit wrong types / null required fields | skipped → “no sleep logs” |
| Stage minutes exceeding night span (Fitbit) | log rejected |

### Auth (`SLEEP_PASSWORD=test123`)

| Route | Unauthenticated |
|-------|-----------------|
| `/`, `/api/*`, `/export.csv`, `/static/*`, `/api/ingest` | **401** |
| `/healthz` | **200** (intentional public readiness) |
| Wrong user/password / empty Basic | **401** |
| Correct Basic | **200** |

Static assets are behind auth (stricter than many apps). Good for private deploy; note Shortcuts/CSS need credentials if UI is passworded.

### CSRF / cross-site (mutations)

| Header set | Result |
|------------|--------|
| `Sec-Fetch-Site: cross-site` | **403** |
| `Origin: https://evil.example` | **403** |
| Same-origin Origin | **200** |
| No Origin / no Sec-Fetch-Site | **200** (see C2) |
| Evil Referer only | **200** (Referer not checked) |

### XSS

Notes containing `<script>alert(1)</script>` and `"><img src=x onerror=alert(1)>` are stored and returned in JSON/export **raw** (API honesty), but page seed serializes with Unicode escapes (`\u003c`, …). **No raw script tag execution observed in `GET /` HTML.** DOM sink behavior in `static/app.js` was **not** re-audited line-by-line (frontend owned by another agent; do not edit). Residual XSS risk if client inserts `notes` via `innerHTML` — flag for orchestrator frontend review.

### Resource limits

| Cap | Behavior |
|-----|----------|
| CSV > 1 MiB | 400 |
| CSV > 10_000 rows | 400 |
| CSV 10_000 historical rows | **200 in 0.14 s** |
| Global body ~3 MiB non-wearable | connection reset / 413 path |
| Wearable empty / unknown magic | 400 |
| `limit` outside 1..10000 | 400 |
| Ingest > 100 nights | 400 |
| range=all @ 50k nights | **~0.25 s**, healthy |

### Data integrity / logic (correct behavior observed)

| Check | Result |
|-------|--------|
| Hours wraparound 23:00→07:00 | 8.0 |
| 23:59→00:01 | 0.03 |
| Sleep debt multi-source (manual naps sum vs apple max) | max wins; debt −1.0 for 9 h vs need 8 |
| Streak across month/year boundary | 4 nights Dec30–Jan2 continuous |
| Streak ending yesterday | current=5 |
| Series latest-per-date | highest id / later row wins; multi-source shows one |
| Wearable re-import identity | application upsert (when shape correct) |
| Delete unknown id | `{ok: true}` idempotent |
| Quality thresholds | unit-checked against documented cutovers |
| Settings goal `0`, `25`, `NaN`, `Infinity`, SQL-ish string | rejected / ignored; need stays 8.0 |

### Parser abuse (Apple / Fitbit)

Truncated XML, wrong root, mismatched tags, empty HealthData, lying extensions (sniffed by content), encrypted/ratio bombs — all fail closed with 400. Minimal valid Apple + Fitbit classic fixtures import successfully; quality 5 for all-deep night matches `derive_quality`.

---

## Scale numbers (copy for the board)

```
50,000 synthetic nights in /tmp/redteam-scale.db
  bulk insert:           0.07 s
  get_stats:             0.380 s
  series 30d/90d/1y:     ≤0.001 s (0 nights in window for 1880-start data)
  series all:            0.227 s  (50,000 nights)
  GET /api/stats:        0.390 s
  GET /api/series?all:   0.253 s  (~3.9 MB)
  GET /api/export:       0.254 s  (~7.8 MB)
  GET /export.csv:       0.240 s  (~1.8 MB)
  GET /api/insights:     3.097 s  ← outlier
  GET /:                 0.389 s
CSV import 10k rows:     0.136 s
50× concurrent POST /add same date: 50 rows stored (no unique constraint)
50× concurrent wearable upsert same identity: 1 row remains
```

---

## Priority fix assignment (for orchestrator)

| ID | Owner lane | Fix |
|----|------------|-----|
| C1, H2 | **Cline** (`app.py` ingest only) | Night dict shape + quality derivation; tests |
| C2 | **Claude / app.py** | CSRF tokens or mandatory auth for mutations; document LAN risk |
| H1 | **database.py** (Claude) | UNIQUE / policy for manual multi-row |
| M1 | Deploy / app boot | Require SECRET_KEY + password in prod |
| M2 | app.py headers | Add CSP |
| M3 | database.py insights | Single-pass queries |
| L1–L4 | backlog | Product validation polish |

---

## Explicit non-actions

- No source, test, template, static, or iOS files modified.  
- Redteam Gunicorn processes were started with `--daemon` PIDs in `/tmp/redteam.pid` and `/tmp/redteam-auth.pid` and should be killed after master verification.  
- Shared port **5002** and project DB were not contacted.  
- Findings are **not** fixed here by design.

---

## Reproduction quickstart (master)

```bash
cd /Users/shreyasmusuku/sleep-tracker
# if servers already dead:
SLEEP_DB_PATH=/tmp/redteam-sleep.db .venv/bin/gunicorn app:app \
  --bind 127.0.0.1:5010 --workers 2 --pid /tmp/redteam.pid

# C1
curl -sS -D- -X POST http://127.0.0.1:5010/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{"date":"2021-06-01","bedtime":"23:00","wake":"07:00","quality":4}'

# C2
curl -sS -X POST http://127.0.0.1:5010/settings/clear
curl -sS http://127.0.0.1:5010/api/stats   # total should be 0 if clear worked

# H1
for i in $(seq 1 20); do
  curl -sS -X POST http://127.0.0.1:5010/add \
    -H 'X-Requested-With: XMLHttpRequest' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d 'date=2022-01-15&bedtime=23:00&wake=07:00&quality=3&notes=dup' &
done; wait
sqlite3 /tmp/redteam-sleep.db "SELECT COUNT(*) FROM sleep_records WHERE date='2022-01-15';"

# cleanup
kill $(cat /tmp/redteam.pid) $(cat /tmp/redteam-auth.pid) 2>/dev/null
```

---

*End of report. All items above are either live-reproduced on the isolated target or measured on disposable `/tmp` databases. Theoretical-only notes are labeled as such (L4, frontend DOM XSS residual).*
