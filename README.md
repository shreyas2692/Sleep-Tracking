# Sleep Tracker

**Import everything. Merge it. Keep it forever. Analyze years, not weeks.  
No subscription, no account, no cloud.**

A self-hosted sleep history app: Flask + SQLite on the server, vanilla JS in
the browser, and an optional SwiftUI companion for iPhone. Bring years of
Apple Watch / Fitbit data on day one — then chart stages, sleep debt, and
multi-year trends without a paywall.

| | |
|--|--|
| **Stack** | Python 3.13, Flask, Gunicorn, SQLite |
| **UI** | Single-page vanilla JS + CSS (no CDNs, no frameworks) |
| **iOS** | SwiftUI app (iOS 17+) talking to your server + HealthKit |
| **Deploy** | Docker locally or [Render](render.yaml) Blueprint |
| **Tests** | `pytest` — run with `.venv/bin/python -m pytest tests` |

---

## Why this exists

Wearable apps are great at *collecting* sleep and mediocre at *keeping* it:
history is paywalled, multi-year views are rare, and data is siloed per brand.
Sleep Tracker is the opposite:

- **Years, not weeks** — range selector: 30d / 90d / 1y / all
- **Your export is the product** — Apple Health `export.zip`, Fitbit Takeout
- **No account** — optional HTTP Basic password for when you put it on a network
- **Export always** — CSV + JSON out; the SQLite file is yours

Product strategy notes: [`PRODUCT.md`](PRODUCT.md).

---

## Features

### Logging & history
- Manual log, edit, delete (bedtime, wake, quality 1–5, notes)
- Overnight wraparound (23:00 → 07:00 = 8h)
- CSV export/import (spreadsheet-safe formula escaping; 1 MiB / 10k rows)
- Full JSON export

### Wearable import
- **Apple Health** `export.zip` / `export.xml` (primary path)
- **Fitbit** Google Takeout sleep JSON / zip
- Up to **1 GiB** uploads; format sniffed from content
- Dedup identity **(date, source)** — re-import updates in place
- Stages: deep / REM / light / awake minutes + provisional quality 1–5
- Future-dated nights skipped (counted in `skipped`), not rejected

### Analytics
- Averages, streaks, 30-day dashboard chart
- Multi-year series API (`30d` | `90d` | `1y` | `all`)
- Rolling **sleep debt** vs personal need (default 8h; oversleep is negative debt)
- Extended insights endpoint (weekly, day-of-week, best/worst, consistency)

### Security (production-minded)
- Optional HTTP Basic (`SLEEP_PASSWORD`) — `/healthz` stays public
- Cross-site mutation rejection (Origin / `Sec-Fetch-Site`)
- XSS-safe page seeds; CSV formula prefix neutralization
- Non-root Docker image

### iOS companion (`ios/`)
- Tabs: Today · Trends · Nights · Settings
- HealthKit read + optional push to your server
- App Store plan, mockups, and 6.7" screenshots under [`docs/app-store/`](docs/app-store/)

---

## Quick start (local)

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python app.py
```

Open [http://localhost:5000](http://localhost:5000).  
Use `FLASK_DEBUG=1` only for local auto-reload.

### Docker (recommended for a “real” run)

```bash
docker build -t sleep-tracker .
docker volume create sleep-tracker-data
docker run --rm -p 8080:10000 \
  -v sleep-tracker-data:/data \
  -e SECRET_KEY='generate-a-long-random-string' \
  -e SLEEP_PASSWORD='pick-a-strong-password' \
  -e SLEEP_USERNAME=sleep \
  sleep-tracker
```

Open [http://localhost:8080](http://localhost:8080) and sign in as `sleep` /
your password. More ops notes: [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SLEEP_DB_PATH` | `./sleep.db` (Docker: `/data/sleep.db`) | SQLite path |
| `SLEEP_TIMEZONE` | `America/New_York` | “Today” for forms and stats |
| `SLEEP_USERNAME` | `sleep` | HTTP Basic username |
| `SLEEP_PASSWORD` | *unset* | When set, protects every route except `/healthz` |
| `SECRET_KEY` | dev default | Flask session signing — **set in production** |
| `SESSION_COOKIE_SECURE` | unset | Set `1` behind HTTPS |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `5000` local / `10000` Docker | Listen port |

---

## Deploy to Render

[`render.yaml`](render.yaml) defines a Docker web service, 1 GB persistent
disk at `/var/data`, health check on `/healthz`, generated `SECRET_KEY`, and a
required `SLEEP_PASSWORD`.

1. Push this repo to GitHub.
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**.
3. Select the repo; set a strong `SLEEP_PASSWORD` when prompted.
4. Apply — open the service URL and log in as `sleep`.

---

## API overview

### Record

```text
{
  id, date, bedtime, wake, quality, notes, hours,
  source,          // manual | apple_health | fitbit
  stages,          // {deep, rem, light, awake} minutes, or null
  efficiency       // 0–100 or null
}
```

`hours` is computed with overnight wraparound.  
`source` + `date` form the wearable dedup key.

### Stats

```text
{
  total, avg_hours, avg_quality, current_streak, best_streak,
  series,          // last 30 calendar days; missing days have hours: null
  sleep_debt       // {need, rolling_14d, total_debt_hours}
}
```

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/` | HTML app; seeds `window.__INITIAL_*__` |
| `POST` | `/add` | Form fields; AJAX → `{ok, records, stats}` |
| `POST` | `/edit/<id>` | AJAX only |
| `POST` | `/delete/<id>` | Idempotent (unknown id still `{ok: true}`) |
| `POST` | `/import` | CSV multipart `file` (all-or-nothing) |
| `POST` | `/import/wearable` | Apple/Fitbit export; `{imported, replaced, skipped, …}` |
| `POST` | `/api/ingest` | JSON night or array for Shortcuts / auto-sync |
| `GET` | `/api/series?range=` | `30d` \| `90d` \| `1y` \| `all` |
| `GET` | `/api/records?limit=` | 1–10,000 |
| `GET` | `/api/stats` | Stats object |
| `GET` | `/api/insights` | Extended analytics |
| `GET` | `/api/export` | All records as JSON |
| `GET` | `/export.csv` | CSV download |
| `GET` | `/healthz` | Public readiness `{ok}` |
| `POST` | `/settings/update` | Sleep / bedtime goals |
| `POST` | `/settings/clear` | Delete all records |

**Validation:** zero-padded `YYYY-MM-DD` / `HH:MM`, no future dates, quality
1–5, notes ≤ 500 characters.

**Ingest** (`POST /api/ingest`) accepts `Content-Type: application/json` —
one night object or an array (max 100). Partial success returns per-item
`errors` while applying valid rows. Prefer Basic Auth when the server is
passworded. Recipe notes live under `docs/` when present.

Full multi-agent API contract: [`AGENTS.md`](AGENTS.md).

---

## Project layout

```text
app.py                 Flask routes + validation
database.py            SQLite access, stats, series, sleep debt
importers/             Apple Health + Fitbit parsers (pure functions)
templates/             HTML (SPA shell)
static/                app.js, style.css
tests/                 pytest suite + fixtures
ios/                   SwiftUI companion (XcodeGen project.yml)
docs/
  DEPLOY.md            Docker / Render ops
  app-store/           App Store plan, mockups, screenshots
Dockerfile             Non-root Gunicorn image
render.yaml            Render Blueprint
.github/workflows/     CI (pytest on push/PR)
PRODUCT.md             Positioning + roadmap
AGENTS.md              Fleet / API contract for agents
```

---

## Development

```bash
# tests
.venv/bin/python -m pytest tests -q

# optional: regenerate iOS Xcode project
cd ios && xcodegen generate
```

CI runs the same pytest suite on every push (see `.github/workflows/ci.yml`).

---

## Privacy & principles

- No mandatory cloud account; data lives in *your* SQLite file or HealthKit.
- Optional server connection is user-controlled (self-host or Render).
- Not a medical device — visualizes data your devices already collected.
- Draft privacy copy for App Store: [`docs/app-store/PRIVACY_POLICY_DRAFT.md`](docs/app-store/PRIVACY_POLICY_DRAFT.md).

---

## License

Private / personal project unless you add a license file. Add one before a
public GitHub release if you want others to use or fork the code.
