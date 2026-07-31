# Sleep Tracker — Agent Instructions

## Product vision (owner's words, 2026-07-31)

**READ `PRODUCT.md` FIRST** — market-research-backed strategy, positioning,
and the ranked feature roadmap (Wave 1–3). It supersedes the rough notes below.
Current build wave: Wave 1 (wearable upload UI, additive stage/source schema,
multi-year trends, sleep debt). Claude's subagents are on schema+import wiring;
frontend trends UI follows. Codex fleet: frontier — your Docker/git/CI queue
items are still open and unblocked; qwen — hold until Wave 1 lands.

The app's purpose: ingest sleep data from wearables — Apple Watch via Apple
Health `export.zip`/`export.xml`, Fitbit via Google Takeout JSON, Oura via its
v2 API with a personal access token (paste-a-token, no OAuth; endpoint
/v2/usercollection/sleep, header "Authorization: Bearer <token>"), and later
Garmin Connect / Whoop / Samsung Health exports — and present it BETTER than
the vendors' own apps (Apple Health, Fitbit app, Oura app).
PRIORITY: the owner's device is an Apple Watch — Apple Health import is the
primary path and gets polish first (upload UI, stage visualization, dedup on
re-import). Fitbit/Oura/others are for future users, build after Apple works
end-to-end with the owner's real export.zip.
Manual entry stays as a fallback. Roadmap: (1) file-based importers — no
accounts, no OAuth, parse the standard export formats users can already
download; (2) richer schema (per-night sleep stages: deep/REM/light/awake
minutes, efficiency, source tag); (3) later, optional Fitbit OAuth live sync.
Phase 1 lives in `importers/` (pure parser functions, normalized night dicts) —
route wiring into app.py happens only after the current /import work lands.

## Fleet roles (multi-agent project — respect file ownership)

Claude Code (Fable 5) is the orchestrator: it owns this contract, runs its own
build subagents, and does final integration + verification. Codex sessions,
check your role here before editing anything:

- **Codex (frontier model, terminal s030)** — staff engineer. Your jobs, in
  order: (1) adversarial review of the integrated app once Claude posts
  "INTEGRATED" in the Status section below — hunt real bugs, don't restyle;
  (2) Docker: build the image, run the container, hit the endpoints — you have
  daemon access, Claude's sandbox doesn't; (3) deploy config (render.yaml or
  fly.toml) + git init, initial commit, GitHub repo, Actions CI running pytest.
  Do NOT edit app.py, database.py, templates/, or static/ before step (1) —
  Claude's subagents are mid-rewrite; you'd be editing files that are about to
  be replaced.
- **Grok** — role: red team / adversarial QA. Runs its OWN app instance
  (port 5010, SLEEP_DB_PATH=/tmp/redteam-sleep.db) and attacks it; never
  touches the shared instance on 5002. Write lane: `reports/redteam.md`
  ONLY — zero source-file edits, findings are reported not fixed (fixes get
  assigned by the orchestrator). Full task spec provided by the owner.
- **Cline** — lane: `POST /api/ingest` JSON auto-sync endpoint in app.py +
  `database.py` reuse (no schema changes), its tests in
  `tests/test_ingest.py` ONLY, and `docs/shortcuts-sync.md`. Do not touch
  templates/, static/, ios/, importers/, other test files, or this file's
  other sections. Full task spec is provided by the owner.
- **Codex (qwen local model, terminal s012)** — STOP editing app.py and
  database.py immediately; your 02:39–02:40 edits collided with an in-flight
  rewrite and will be reconciled or overwritten. Your lane: README/docs polish
  and, after "INTEGRATED", a CSV-import feature behind /import — nothing else.

## Status

- **FRONTIER REVIEW FIXES INTEGRATED** — local test suite: 179 passed
  (`.venv/bin/python -m pytest tests`). CSV import, production authentication,
  timezone-correct dates, strict validation, bounded uploads, spreadsheet-safe
  export, and wearable-parser hardening are integrated. Docker, browser,
  Lighthouse, and remote CI verification are still in progress.
- Deleting an unknown id remains intentionally idempotent and returns
  `{ok: true}`.

Flask + SQLite web app for logging nightly sleep. No frameworks on the frontend
(vanilla JS, inline SVG for charts, no CDNs). Production server is Gunicorn
(see Dockerfile). Coordination between agents happens through this file — read
it before making changes, and keep the API contract below accurate if you
change endpoints.

## Architecture

- `app.py` — Flask routes only (thin; validation + JSON/HTML responses)
- `database.py` — all SQLite access; DB path overridable via `SLEEP_DB_PATH` env var
- `templates/index.html`, `static/style.css`, `static/app.js` — single-page UI
- `tests/` — pytest suite (run with `.venv/bin/python -m pytest`)

## API contract (do not break without updating this file)

Record object: `{id, date, bedtime, wake, quality, notes, hours, source,
stages, efficiency}` — `hours` is computed duration (overnight wraparound:
23:00→07:00 = 8h); `source`: `manual|apple_health|fitbit`; `stages`:
`{deep, rem, light, awake}` minutes or null; `efficiency`: 0–100 float or null.

Stats object: `{total, avg_hours, avg_quality, current_streak, best_streak,
series, sleep_debt}` — `series` is the last 30 days ascending:
`[{date, hours, quality}]` (days with no record have `hours: null`);
`sleep_debt`: `{need, rolling_14d: [{date, debt_hours,
cumulative_debt_hours}], total_debt_hours}` (need from `sleep_goal` setting
else 8.0; only dates with records appear; naps sum; multi-source dates count
the max per-source total once; oversleep is negative debt).

- `GET /` — page render; seeds `window.__INITIAL_RECORDS__` / `__INITIAL_STATS__`
- `POST /add` — form fields `date, bedtime, wake, quality, notes`; with header
  `X-Requested-With: XMLHttpRequest` returns `{ok, records, stats}` JSON
  (400 + `{error}` on bad input); otherwise redirects with a flash
- `POST /edit/<id>` — same fields, AJAX only → `{ok, records, stats}` (404 unknown id)
- `POST /delete/<id>` — AJAX → `{ok, records, stats}`; non-AJAX redirects
- `POST /import` — multipart field `file`; exact export CSV format; UTF-8,
  1 MiB/10,000-row maximum; all-or-nothing → `{ok, records, stats}`
- `POST /import/wearable` — multipart `file`: Apple Health export.zip/xml or
  Fitbit Takeout JSON/zip, sniffed; 1 GiB cap; dedup identity (date, source),
  re-import UPDATEs in place; future nights skipped not rejected →
  `{ok, imported, replaced, skipped, records, stats}`; 400 `{error}`
- `GET /api/series?range=30d|90d|1y|all` (default 30d) → `{range, nights:
  [{date, hours, quality, stages, source}] ascending (only dates having
  records, latest per date), start, end}`; invalid range → 400
- `GET /api/records?limit=N` — record list; `N` must be 1–10,000
- `GET /api/stats` — stats object
- `GET /api/insights` — extended analytics object
- `GET /api/export` — all records as JSON
- `GET /export.csv` — CSV download of all records
- `GET /healthz` — public database readiness check → `{ok}`
- `POST /settings/update` — validate and save sleep/bedtime goals, then redirect
- `POST /settings/clear` — delete all records, then redirect

When `SLEEP_PASSWORD` is set, every route except `/healthz` requires HTTP Basic
authentication (`SLEEP_USERNAME`, default `sleep`). Browser cross-site mutation
requests are rejected.

## Conventions

- Validate all input server-side (zero-padded `YYYY-MM-DD`/`HH:MM`, no future
  dates, quality 1–5, notes at most 500 characters)
- Escape all user-supplied content before inserting into the DOM (XSS)
- No native `confirm()`/`alert()` dialogs in the UI
- Keep everything self-contained: no external fonts, scripts, or styles

## Task queue (pick up the next unchecked item)

- [ ] Verify `docker build` + container run end-to-end (Claude's sandbox can't;
      needs Docker daemon)
- [x] Add a `fly.toml` or `render.yaml` so deploy is one command
- [ ] `git init` + initial commit + GitHub repo, then GitHub Actions CI running pytest
- [x] Add optional CSV import (reverse of /export.csv)
- [ ] Lighthouse pass on the UI (a11y + performance)
