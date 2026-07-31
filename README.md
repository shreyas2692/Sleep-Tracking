# Sleep Tracker

A self-contained Flask and SQLite app for logging nightly sleep, reviewing
30-day trends, and moving records through CSV. The frontend is vanilla
JavaScript with no CDN or runtime dependency.

## Features

- Log, edit, and delete bedtime, wake time, quality, and notes
- Review averages, streaks, a 30-day chart, and extended JSON insights
- Load the full record history without leaving the page
- Export and atomically re-import the same CSV format
- Import Apple Health (`export.zip`/`export.xml`) and Fitbit Google Takeout
  exports via `POST /import/wearable` — full multi-year history, sleep stages,
  and dedup on re-import (one row per date+source)
- Run locally, under Gunicorn, or as a non-root Docker container

CSV exports neutralize spreadsheet formula prefixes while preserving exact
notes when the file is imported again. Imports are UTF-8, all-or-nothing, and
limited to 1 MiB or 10,000 rows.

Wearable imports (up to 1 GiB) are deduplicated on (date, source):
re-importing the same export updates existing rows instead of duplicating
them. Staged nights derive a provisional 1–5 quality from the deep+REM
fraction of stage minutes; nights without stage data get a neutral 3.
Future-dated nights are skipped (reported in the `skipped` count) rather than
failing the import.

## Local Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests
.venv/bin/python app.py
```

Open `http://localhost:5000`. Set `FLASK_DEBUG=1` only for local auto-reload.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SLEEP_DB_PATH` | `./sleep.db` | SQLite file path |
| `SLEEP_TIMEZONE` | `America/New_York` | Calendar date used by forms and stats |
| `SLEEP_USERNAME` | `sleep` | HTTP Basic username |
| `SLEEP_PASSWORD` | unset | Enables HTTP Basic protection when set |
| `SECRET_KEY` | development value | Flask session signing key; set in production |
| `SESSION_COOKIE_SECURE` | unset | Set to `1` behind HTTPS |
| `HOST` | `0.0.0.0` | Development/container bind host |
| `PORT` | `5000` locally, `10000` in Docker | Listening port |

`GET /healthz` stays public for platform health checks. All other routes are
private when `SLEEP_PASSWORD` is set.

## Docker

```bash
docker build -t sleep-tracker .
docker volume create sleep-tracker-data
docker run --rm -p 8080:10000 \
  -v sleep-tracker-data:/data \
  -e SECRET_KEY='replace-me' \
  -e SLEEP_PASSWORD='replace-me' \
  sleep-tracker
```

Open `http://localhost:8080` and authenticate as `sleep`.

## Render

[`render.yaml`](render.yaml) defines a Docker web service, persistent disk,
health check, generated Flask secret, and required `SLEEP_PASSWORD`.

1. Push the repository to GitHub.
2. In Render, create a new Blueprint from the repository.
3. Enter a strong value when Render prompts for `SLEEP_PASSWORD`.
4. Apply the Blueprint.

The persistent disk configuration uses Render's `starter` plan and mounts the
SQLite database at `/var/data/sleep.db`.

## API

Record objects contain:

```text
{id, date, bedtime, wake, quality, notes, hours, source, stages, efficiency}
```

`source` is `manual`, `apple_health`, or `fitbit`. `stages` is
`{deep, rem, light, awake}` in minutes, or `null` when the record has no
stage data. `efficiency` is a 0–100 float or `null`.

Stats objects contain:

```text
{total, avg_hours, avg_quality, current_streak, best_streak, series, sleep_debt}
```

`sleep_debt` is `{need, rolling_14d, total_debt_hours}`: `need` comes from the
sleep-goal setting (8.0 when unset), and `rolling_14d` lists
`{date, debt_hours, cumulative_debt_hours}` for each of the last 14 days that
has a record — days without records are skipped and contribute zero debt.
Manual naps on the same date sum; when several sources cover one date, the
highest per-source total counts once (never summed across devices).

| Endpoint | Behavior |
|---|---|
| `GET /` | Render the app and seed its initial records/stats |
| `POST /add` | Add a validated record; AJAX returns current state |
| `POST /edit/<id>` | Edit a record; AJAX JSON |
| `POST /delete/<id>` | Idempotently delete a record |
| `POST /import` | Import an export-format CSV from multipart field `file` |
| `POST /import/wearable` | Import an Apple Health or Fitbit Takeout export (multipart field `file`, up to 1 GiB); format is sniffed; returns `{ok, imported, replaced, skipped, records, stats}` |
| `GET /api/records?limit=N` | Return 1–10,000 newest records |
| `GET /api/series?range=30d\|90d\|1y\|all` | Nights series (only dates with records, ascending): `{range, nights: [{date, hours, quality, stages, source}], start, end}` |
| `GET /api/stats` | Return dashboard stats |
| `GET /api/insights` | Return extended analytics |
| `GET /api/export` | Return all records as JSON |
| `GET /export.csv` | Download all records as CSV |
| `GET /healthz` | Check database readiness |

Dates and times must be zero-padded (`YYYY-MM-DD`, `HH:MM`), dates cannot be
in the future, quality is an integer from 1 to 5, and notes are at most 500
characters.

## Project Layout

```text
app.py                 Flask routes and request validation
database.py            SQLite access and statistics
importers/             Pure Apple Health and Fitbit parsers
templates/index.html   Single-page interface
static/                Vanilla JavaScript and CSS
tests/                 Pytest suite and export fixtures
Dockerfile             Non-root Gunicorn image
render.yaml            Render Blueprint
.github/workflows/     GitHub Actions CI
```
