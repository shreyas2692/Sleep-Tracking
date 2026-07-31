import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _db_path():
    """Resolve the DB path at call time so SLEEP_DB_PATH can be set by tests."""
    return os.environ.get(
        "SLEEP_DB_PATH", os.path.join(os.path.dirname(__file__), "sleep.db")
    )


def get_today(now=None):
    """Return today's date in the configured product timezone."""
    zone_name = os.environ.get("SLEEP_TIMEZONE", "America/New_York")
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(zone).date()


# Additive Wave-1 columns (wearable imports). Applied idempotently to both
# fresh and legacy databases in get_connection() via PRAGMA table_info.
_MIGRATION_COLUMNS = (
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("deep_minutes", "INTEGER"),
    ("rem_minutes", "INTEGER"),
    ("light_minutes", "INTEGER"),
    ("awake_minutes", "INTEGER"),
    ("efficiency", "REAL"),
    ("sessions_json", "TEXT"),
)
_SCHEMA_VERSION = 2
_WEARABLE_IDENTITY_INDEX = "uq_sleep_records_wearable_identity"
_MAX_SESSIONS_PER_RECORD = 512
_MAX_SESSION_SECONDS = 36 * 60 * 60

_RECORD_SELECT = (
    "id, date, bedtime, wake_time, quality, notes, "
    "source, deep_minutes, rem_minutes, light_minutes, awake_minutes, efficiency, "
    "sessions_json"
)


def _migrate_schema(conn):
    """Apply the current schema exactly once, serialized across processes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Another process may have completed the migration while this
        # connection waited for the write lock.
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version >= _SCHEMA_VERSION:
            conn.commit()
            return

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sleep_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                bedtime TEXT NOT NULL,
                wake_time TEXT NOT NULL,
                quality INTEGER NOT NULL CHECK(quality BETWEEN 1 AND 5),
                notes TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        existing = {
            row[1] for row in conn.execute("PRAGMA table_info(sleep_records)")
        }
        for name, declaration in _MIGRATION_COLUMNS:
            if name not in existing:
                conn.execute(
                    f"ALTER TABLE sleep_records ADD COLUMN {name} {declaration}"
                )

        # Existing databases may contain duplicates created before the
        # database-level identity invariant existed. Preserve the oldest row,
        # matching the historical in-place update behavior.
        conn.execute("""
            DELETE FROM sleep_records
            WHERE source != 'manual'
              AND id NOT IN (
                  SELECT MIN(id)
                  FROM sleep_records
                  WHERE source != 'manual'
                  GROUP BY date, source
              )
        """)
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_WEARABLE_IDENTITY_INDEX} "
            "ON sleep_records(date, source) WHERE source != 'manual'"
        )
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_connection():
    """Return a DB connection; create tables and apply migrations if needed."""
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < _SCHEMA_VERSION:
            _migrate_schema(conn)
        return conn
    except Exception:
        conn.close()
        raise


def check_database():
    """Return True when the configured SQLite database is reachable."""
    conn = get_connection()
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    finally:
        conn.close()


# ── Sleep duration ────────────────────────────────────────────

def calc_sleep_hours(bedtime_str, wake_time_str):
    """Hours slept bedtime → wake, with overnight wraparound (23:00→07:00 = 8.0).

    Rounded to 2 decimals; 0 if unparseable.
    """
    try:
        bed = datetime.strptime(bedtime_str, "%H:%M")
        wake = datetime.strptime(wake_time_str, "%H:%M")
        diff = (wake - bed).total_seconds() / 3600
        if diff < 0:
            diff += 24
        return round(diff, 2)
    except (ValueError, TypeError):
        return 0


def _wall_session(date_str, bedtime, wake_time):
    """Build one offset-unknown session from the legacy public fields."""
    try:
        wake_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        bed_time = datetime.strptime(bedtime, "%H:%M").time()
        end_time = datetime.strptime(wake_time, "%H:%M").time()
    except (TypeError, ValueError):
        return None

    start = datetime.combine(wake_date, bed_time)
    end = datetime.combine(wake_date, end_time)
    if end < start:
        start -= timedelta(days=1)
    return {
        "start_local": start.isoformat(timespec="seconds"),
        "end_local": end.isoformat(timespec="seconds"),
        "start_utc": None,
        "end_utc": None,
        "elapsed_seconds": int((end - start).total_seconds()),
        "main": True,
    }


def _normalize_session(session):
    """Validate and canonicalize one private session payload."""
    if not isinstance(session, dict) or type(session.get("main")) is not bool:
        raise ValueError("invalid sleep session")
    try:
        start = datetime.fromisoformat(session["start_local"])
        end = datetime.fromisoformat(session["end_local"])
        seconds = float(session["elapsed_seconds"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid sleep session") from exc
    if (
        start.tzinfo is not None
        or end.tzinfo is not None
        or end <= start
        or not math.isfinite(seconds)
        or not 0 < seconds <= _MAX_SESSION_SECONDS
    ):
        raise ValueError("invalid sleep session")
    rounded_seconds = int(round(seconds))
    if rounded_seconds <= 0:
        raise ValueError("invalid sleep session")

    start_utc = session.get("start_utc")
    end_utc = session.get("end_utc")
    if (start_utc is None) != (end_utc is None):
        raise ValueError("invalid sleep session")
    if start_utc is not None:
        if (
            isinstance(start_utc, bool)
            or isinstance(end_utc, bool)
            or not isinstance(start_utc, (int, float))
            or not isinstance(end_utc, (int, float))
            or not math.isfinite(start_utc)
            or not math.isfinite(end_utc)
            or end_utc <= start_utc
        ):
            raise ValueError("invalid sleep session")
        start_utc = int(round(start_utc))
        end_utc = int(round(end_utc))

    return {
        "start_local": start.isoformat(timespec="seconds"),
        "end_local": end.isoformat(timespec="seconds"),
        "start_utc": start_utc,
        "end_utc": end_utc,
        "elapsed_seconds": rounded_seconds,
        "main": session["main"],
    }


def _serialize_sessions(night):
    """Serialize validated private importer sessions, or use legacy fallback."""
    sessions = night.get("_sessions")
    if sessions is None:
        return None
    if (
        not isinstance(sessions, list)
        or not sessions
        or len(sessions) > _MAX_SESSIONS_PER_RECORD
    ):
        raise ValueError("invalid sleep sessions")
    normalized = [_normalize_session(session) for session in sessions]
    if sum(session["main"] for session in normalized) != 1:
        raise ValueError("sleep sessions must contain exactly one main session")
    return json.dumps(
        {"v": 1, "sessions": normalized},
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_sessions(date_str, bedtime, wake_time, payload):
    """Decode private sessions, safely falling back for legacy/corrupt rows."""
    if payload:
        try:
            document = json.loads(payload)
            raw_sessions = document["sessions"]
            if (
                document.get("v") != 1
                or not isinstance(raw_sessions, list)
                or not raw_sessions
                or len(raw_sessions) > _MAX_SESSIONS_PER_RECORD
            ):
                raise ValueError
            sessions = [_normalize_session(session) for session in raw_sessions]
            if sum(session["main"] for session in sessions) != 1:
                raise ValueError
            return sessions
        except (
            KeyError,
            TypeError,
            ValueError,
            RecursionError,
            json.JSONDecodeError,
        ):
            pass
    fallback = _wall_session(date_str, bedtime, wake_time)
    return [fallback] if fallback is not None else []


def _row_to_dict(row):
    """Map a sleep_records row to the API record object (wake_time → wake).

    `stages` is None when the row carries no stage data (all four stage
    columns NULL); otherwise a {deep, rem, light, awake} dict of integer
    minutes with NULL individual stages treated as 0.
    """
    (
        rec_id, date_str, bedtime, wake_time, quality, notes,
        source, deep, rem, light, awake, efficiency, sessions_json,
    ) = row
    if deep is None and rem is None and light is None and awake is None:
        stages = None
    else:
        stages = {
            "deep": int(deep or 0),
            "rem": int(rem or 0),
            "light": int(light or 0),
            "awake": int(awake or 0),
        }
    sessions = _decode_sessions(date_str, bedtime, wake_time, sessions_json)
    main_session = next(
        (session for session in sessions if session["main"]),
        None,
    )
    hours = (
        round(main_session["elapsed_seconds"] / 3600, 2)
        if main_session is not None
        else calc_sleep_hours(bedtime, wake_time)
    )
    return {
        "id": rec_id,
        "date": date_str,
        "bedtime": bedtime,
        "wake": wake_time,
        "quality": quality,
        "notes": notes,
        "hours": hours,
        "source": source,
        "stages": stages,
        "efficiency": efficiency,
    }


# ── Records CRUD ──────────────────────────────────────────────

def add_record(date_str, bedtime, wake_time, quality, notes=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO sleep_records (date, bedtime, wake_time, quality, notes) VALUES (?, ?, ?, ?, ?)",
        (date_str, bedtime, wake_time, quality, notes),
    )
    conn.commit()
    conn.close()


def add_records(records):
    """Insert validated record dictionaries in one transaction."""
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO sleep_records "
            "(date, bedtime, wake_time, quality, notes) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    record["date"],
                    record["bedtime"],
                    record["wake"],
                    record["quality"],
                    record.get("notes", ""),
                )
                for record in records
            ],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_wearable_records(nights):
    """Insert or replace imported wearable nights in one transaction.

    (date, source) is the identity for wearable data: re-importing the same
    export UPDATEs the existing row for that date+source instead of creating
    a duplicate. Returns (imported, replaced) counts.

    Each night dict: {date, bedtime, wake, quality, notes, source, stages,
    efficiency} where stages is {deep, rem, light, awake} minutes or None.
    Parsers may also supply private `_sessions`; those are persisted but never
    included in public record objects.
    """
    conn = get_connection()
    imported = replaced = 0
    try:
        # Acquire the write lock before the identity lookup. Without this,
        # concurrent first imports can all observe "missing" and insert the
        # same date+source before any transaction commits.
        conn.execute("BEGIN IMMEDIATE")
        for night in nights:
            stages = night.get("stages") or {}
            sessions_json = _serialize_sessions(night)
            values = (
                night["bedtime"],
                night["wake"],
                night["quality"],
                night.get("notes", ""),
                stages.get("deep"),
                stages.get("rem"),
                stages.get("light"),
                stages.get("awake"),
                night.get("efficiency"),
                sessions_json,
            )
            row = conn.execute(
                "SELECT id FROM sleep_records WHERE date = ? AND source = ? "
                "ORDER BY id LIMIT 1",
                (night["date"], night["source"]),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sleep_records SET bedtime = ?, wake_time = ?, "
                    "quality = ?, notes = ?, deep_minutes = ?, rem_minutes = ?, "
                    "light_minutes = ?, awake_minutes = ?, efficiency = ?, "
                    "sessions_json = ? "
                    "WHERE id = ?",
                    values + (row[0],),
                )
                # Defensive: collapse any legacy duplicates for this identity.
                conn.execute(
                    "DELETE FROM sleep_records WHERE date = ? AND source = ? "
                    "AND id != ?",
                    (night["date"], night["source"], row[0]),
                )
                replaced += 1
            else:
                conn.execute(
                    "INSERT INTO sleep_records (date, bedtime, wake_time, "
                    "quality, notes, source, deep_minutes, rem_minutes, "
                    "light_minutes, awake_minutes, efficiency, sessions_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (night["date"],) + values[:4] + (night["source"],) + values[4:],
                )
                imported += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return imported, replaced


def update_record(record_id, date_str, bedtime, wake_time, quality, notes=""):
    """Update an existing record. Returns False if the id is unknown."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE sleep_records SET date = ?, bedtime = ?, wake_time = ?, "
        "quality = ?, notes = ?, sessions_json = NULL WHERE id = ?",
        (date_str, bedtime, wake_time, quality, notes, record_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_records(limit=30, start_date=None, end_date=None):
    conn = get_connection()
    if start_date and end_date:
        rows = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM sleep_records "
            "WHERE date >= ? AND date <= ? ORDER BY date DESC, id DESC LIMIT ?",
            (start_date, end_date, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM sleep_records "
            "ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_all_records():
    """All records ascending by date (for CSV export)."""
    conn = get_connection()
    rows = conn.execute(
        f"SELECT {_RECORD_SELECT} FROM sleep_records ORDER BY date ASC, id ASC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def delete_record(record_id):
    conn = get_connection()
    conn.execute("DELETE FROM sleep_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def clear_all_records():
    conn = get_connection()
    conn.execute("DELETE FROM sleep_records")
    conn.commit()
    conn.close()


# ── Stats (API contract) ──────────────────────────────────────

def _record_dates(records):
    """Set of date objects for days with at least one record."""
    result = set()
    for r in records:
        try:
            result.add(datetime.strptime(r["date"], "%Y-%m-%d").date())
        except (ValueError, TypeError):
            pass
    return result


def _streaks(record_dates, today):
    """(current_streak, best_streak) over consecutive calendar days."""
    record_dates = {record_date for record_date in record_dates if record_date <= today}
    if not record_dates:
        return 0, 0

    days = sorted(record_dates)
    best = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        best = max(best, run)

    latest = days[-1]
    if (today - latest).days > 1:
        current = 0
    else:
        current = 1
        d = latest
        while d - timedelta(days=1) in record_dates:
            d -= timedelta(days=1)
            current += 1
    return current, best


def _interval_components(sessions):
    """Connected components of overlapping local-time session intervals."""
    components = []
    current = []
    current_end = None
    for session in sorted(sessions, key=lambda item: (item["start"], item["end"])):
        if current and session["start"] >= current_end:
            components.append(current)
            current = []
            current_end = None
        current.append(session)
        current_end = (
            session["end"]
            if current_end is None
            else max(current_end, session["end"])
        )
    if current:
        components.append(current)
    return components


def _merged_span_seconds(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def _source_component_seconds(sessions):
    """Covered seconds for one source without counting its duplicate spans."""
    overlap_groups = _interval_components(sessions)
    total = 0
    for group in overlap_groups:
        if len(group) == 1:
            total += group[0]["elapsed_seconds"]
        elif all(
            session["start_utc"] is not None and session["end_utc"] is not None
            for session in group
        ):
            total += _merged_span_seconds(
                (session["start_utc"], session["end_utc"])
                for session in group
            )
        else:
            epoch = datetime(1970, 1, 1)
            total += _merged_span_seconds(
                (
                    (session["start"] - epoch).total_seconds(),
                    (session["end"] - epoch).total_seconds(),
                )
                for session in group
            )
    return total


def _accounted_hours_by_date(rows, today):
    """Deduplicate overlapping cross-source sessions and retain disjoint naps."""
    window_start = today - timedelta(days=13)
    sessions_by_date = {}
    for row in rows:
        date_str, bedtime, wake_time, source, sessions_json = (
            row[1], row[2], row[3], row[6], row[12]
        )
        try:
            record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        if not window_start <= record_date <= today:
            continue
        sessions_by_date.setdefault(date_str, [])
        for session in _decode_sessions(
            date_str, bedtime, wake_time, sessions_json
        ):
            if session["elapsed_seconds"] <= 0:
                continue
            try:
                start = datetime.fromisoformat(session["start_local"])
                end = datetime.fromisoformat(session["end_local"])
            except (TypeError, ValueError):
                continue
            sessions_by_date.setdefault(date_str, []).append({
                "start": start,
                "end": end,
                "start_utc": session["start_utc"],
                "end_utc": session["end_utc"],
                "elapsed_seconds": session["elapsed_seconds"],
                "source": source,
            })

    result = {}
    for date_str, sessions in sessions_by_date.items():
        accounted_seconds = 0
        for component in _interval_components(sessions):
            by_source = {}
            for session in component:
                by_source.setdefault(session["source"], []).append(session)
            accounted_seconds += max(
                _source_component_seconds(source_sessions)
                for source_sessions in by_source.values()
            )
        result[date_str] = accounted_seconds / 3600
    return result


def _sleep_debt(rows, today):
    """Rolling 14-day sleep debt vs. personal need.

    Accounting choices (kept deliberately simple and transparent):

    - `need` comes from the `sleep_goal` setting when present and valid,
      otherwise 8.0 hours.
    - Each day's debt = need − hours slept that date. Days with no record are
      SKIPPED — a missing day contributes 0 debt rather than a full night of
      debt, because an unlogged night is not evidence of no sleep.
    - Nap-inclusive: disjoint sessions on a date sum. Overlapping sessions form
      a component, and only the largest per-source coverage in that component
      counts, so duplicate device readings are not double-counted.
    - Oversleeping produces negative debt for that day and reduces the total.
    """
    raw_need = get_setting("sleep_goal", "")
    try:
        need = float(raw_need)
    except (TypeError, ValueError):
        need = 8.0
    if not (0 < need <= 24):
        need = 8.0

    hours_by_date = _accounted_hours_by_date(rows, today)

    rolling = []
    total = 0.0
    for i in range(13, -1, -1):
        date_str = (today - timedelta(days=i)).isoformat()
        if date_str not in hours_by_date:
            continue  # missing day: contributes 0 debt
        debt = round(need - hours_by_date[date_str], 2)
        total += debt
        rolling.append({
            "date": date_str,
            "debt_hours": debt,
            "cumulative_debt_hours": round(total, 2),
        })

    return {
        "need": need,
        "rolling_14d": rolling,
        "total_debt_hours": round(total, 2),
    }


def get_stats():
    """Stats object: {total, avg_hours, avg_quality, current_streak,
    best_streak, series, sleep_debt}."""
    conn = get_connection()
    rows = conn.execute(
        f"SELECT {_RECORD_SELECT} FROM sleep_records ORDER BY date ASC, id ASC"
    ).fetchall()
    conn.close()

    records = [_row_to_dict(r) for r in rows]
    today = get_today()
    total = len(records)

    avg_hours = round(sum(r["hours"] for r in records) / total, 2) if total else 0
    avg_quality = round(sum(r["quality"] for r in records) / total, 2) if total else 0

    current_streak, best_streak = _streaks(_record_dates(records), today)

    # Last 30 calendar days ending today, ascending; latest record (highest id)
    # wins when a date has multiple records. Rows are ASC by date,id so later
    # entries overwrite earlier ones.
    by_date = {}
    for r in records:
        by_date[r["date"]] = r
    series = []
    for i in range(29, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        rec = by_date.get(d)
        series.append({
            "date": d,
            "hours": rec["hours"] if rec else None,
            "quality": rec["quality"] if rec else None,
        })

    return {
        "total": total,
        "avg_hours": avg_hours,
        "avg_quality": avg_quality,
        "current_streak": current_streak,
        "best_streak": best_streak,
        "series": series,
        "sleep_debt": _sleep_debt(rows, today),
    }


# ── Multi-year series (GET /api/series) ───────────────────────

SERIES_RANGES = {"30d": 30, "90d": 90, "1y": 365, "all": None}


def get_series(range_key="30d"):
    """Nights series for a range: {range, nights, start, end}.

    One entry per date that has at least one record (missing days are simply
    absent), ascending: {date, hours, quality, stages, source}. When a date
    has multiple records, the latest one (highest id) wins — same rule as the
    30-day stats series. Single SQL query and a single pass over the rows, so
    'all' stays fast for thousands of nights. Future-dated records are
    excluded (the series ends today).
    """
    if range_key not in SERIES_RANGES:
        raise ValueError(f"unknown range {range_key!r}")
    days = SERIES_RANGES[range_key]
    today = get_today()
    end = today.isoformat()

    conn = get_connection()
    if days is None:
        rows = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM sleep_records "
            "WHERE date <= ? ORDER BY date ASC, id ASC",
            (end,),
        ).fetchall()
        start = end
    else:
        start = (today - timedelta(days=days - 1)).isoformat()
        rows = conn.execute(
            f"SELECT {_RECORD_SELECT} FROM sleep_records "
            "WHERE date >= ? AND date <= ? ORDER BY date ASC, id ASC",
            (start, end),
        ).fetchall()
    conn.close()

    by_date = {}
    for row in rows:
        record = _row_to_dict(row)
        by_date[record["date"]] = {
            "date": record["date"],
            "hours": record["hours"],
            "quality": record["quality"],
            "stages": record["stages"],
            "source": record["source"],
        }
    nights = [by_date[date] for date in sorted(by_date)]
    if days is None and nights:
        start = nights[0]["date"]
    return {"range": range_key, "nights": nights, "start": start, "end": end}


# ── Streak (convenience) ──────────────────────────────────────

def get_streak():
    """Consecutive nights logged ending today (or yesterday) = current streak."""
    return get_stats()["current_streak"]


# ── Weekly stats ──────────────────────────────────────────────

def get_weekly_averages(weeks=12):
    """List of {label, avg_hours, avg_quality, count} for the last N weeks."""
    records = get_all_records()
    if not records:
        return []

    today = get_today()
    result = []

    for i in range(weeks):
        week_end = today - timedelta(days=i * 7)
        week_start = week_end - timedelta(days=6)
        week_records = []
        for r in records:
            try:
                rd = datetime.strptime(r["date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if week_start <= rd <= week_end:
                week_records.append(r)

        if week_records:
            label = week_start.strftime("%b %d")
            if i == 0:
                label = "This week"
            elif i == 1:
                label = "Last week"
            result.append({
                "label": label,
                "avg_hours": round(sum(r["hours"] for r in week_records) / len(week_records), 1),
                "avg_quality": round(sum(r["quality"] for r in week_records) / len(week_records), 1),
                "count": len(week_records),
            })
        else:
            result.append({
                "label": week_start.strftime("%b %d"),
                "avg_hours": 0,
                "avg_quality": 0,
                "count": 0,
            })

    result.reverse()  # oldest first (left-to-right on chart)
    return result


# ── Day-of-week heatmap data ──────────────────────────────────

def get_day_of_week_stats():
    """Average hours and quality per day of week."""
    records = get_all_records()
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    buckets = {d: {"hours": [], "quality": []} for d in days}

    for r in records:
        try:
            weekday = datetime.strptime(r["date"], "%Y-%m-%d").strftime("%a")
        except (ValueError, TypeError):
            continue
        buckets[weekday]["hours"].append(r["hours"])
        buckets[weekday]["quality"].append(r["quality"])

    result = []
    for day in days:
        data = buckets[day]
        if data["hours"]:
            result.append({
                "day": day,
                "avg_hours": round(sum(data["hours"]) / len(data["hours"]), 1),
                "avg_quality": round(sum(data["quality"]) / len(data["quality"]), 1),
                "count": len(data["hours"]),
            })
        else:
            result.append({"day": day, "avg_hours": 0, "avg_quality": 0, "count": 0})

    return result


# ── Best / Worst nights ───────────────────────────────────────

def get_best_worst_nights(n=5):
    """Top N longest and shortest nights (record dicts)."""
    records = get_all_records()
    best = sorted(records, key=lambda r: r["hours"], reverse=True)[:n]
    worst = sorted(records, key=lambda r: r["hours"])[:n]
    return {"best": best, "worst": worst}


# ── Consistency score ─────────────────────────────────────────

def get_consistency_score():
    """How consistent is sleep duration? 0-100 score over the last 30 records."""
    hours = [r["hours"] for r in get_records(limit=30)]
    if len(hours) < 2:
        return 0

    mean = sum(hours) / len(hours)
    variance = sum((h - mean) ** 2 for h in hours) / len(hours)
    std_dev = variance ** 0.5

    # Lower std dev = higher score. 0h std dev = 100, 3h std dev = 0
    return max(0, min(100, round(100 - (std_dev / 3) * 100)))


# ── Monthly trend (for line chart) ────────────────────────────

def get_monthly_trend(months=6):
    """Average hours per month for the last N months."""
    records = get_all_records()
    today = get_today()
    result = []

    for i in range(months - 1, -1, -1):
        target_month = today.replace(day=1)
        for _ in range(i):  # step back i months
            target_month = (target_month - timedelta(days=1)).replace(day=1)
        if target_month.month < 12:
            next_month = target_month.replace(month=target_month.month + 1)
        else:
            next_month = target_month.replace(year=target_month.year + 1, month=1)

        month_hours = []
        for r in records:
            try:
                rd = datetime.strptime(r["date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if target_month <= rd < next_month:
                month_hours.append(r["hours"])

        avg = round(sum(month_hours) / len(month_hours), 1) if month_hours else 0
        result.append({
            "label": target_month.strftime("%b %Y"),
            "avg_hours": avg,
            "count": len(month_hours),
        })

    return result


# ── Settings ──────────────────────────────────────────────────

def get_setting(key, default=""):
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else default


def set_setting(key, value):
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?",
        (key, value, value),
    )
    conn.commit()
    conn.close()


def get_all_settings():
    return {
        "sleep_goal": float(get_setting("sleep_goal", "8.0")),
        "bedtime_goal": get_setting("bedtime_goal", "23:00"),
    }


# ── Export ─────────────────────────────────────────────────────

def export_data():
    """All records as a list of record dicts for JSON export."""
    return get_all_records()
