"""Unit tests for database.py against a per-test temp SQLite file."""
from datetime import date, datetime, timedelta, timezone

import pytest

import database as db


def _d(days_ago):
    """ISO date string N days before today."""
    return (db.get_today() - timedelta(days=days_ago)).isoformat()


# ── calc_sleep_hours ──────────────────────────────────────────

@pytest.mark.parametrize(
    "bed,wake,expected",
    [
        ("23:00", "07:00", 8.0),     # overnight wraparound
        ("22:30", "06:15", 7.75),    # wraparound with minutes
        ("01:00", "09:30", 8.5),     # same-day (bed after midnight)
        ("00:00", "00:00", 0),       # equal times -> 0, not 24
        ("23:59", "00:00", 0.02),    # one minute, rounded to 2 decimals
    ],
)
def test_calc_sleep_hours(bed, wake, expected):
    assert db.calc_sleep_hours(bed, wake) == expected


@pytest.mark.parametrize("bed,wake", [("25:00", "07:00"), ("nope", "07:00"), (None, "07:00"), ("23:00", "")])
def test_calc_sleep_hours_unparseable_returns_zero(bed, wake):
    assert db.calc_sleep_hours(bed, wake) == 0


# ── CRUD round-trip ───────────────────────────────────────────

def test_add_get_update_delete_round_trip():
    db.add_record("2026-07-01", "23:00", "07:00", 4, "first")
    records = db.get_records()
    assert len(records) == 1
    rec = records[0]
    assert rec["date"] == "2026-07-01"
    assert rec["bedtime"] == "23:00"
    assert rec["wake"] == "07:00"  # wake_time column mapped to "wake"
    assert rec["quality"] == 4
    assert rec["notes"] == "first"
    assert rec["hours"] == 8.0
    assert isinstance(rec["id"], int)

    assert db.update_record(rec["id"], "2026-07-02", "22:30", "06:15", 5, "edited") is True
    updated = db.get_records()[0]
    assert updated["date"] == "2026-07-02"
    assert updated["hours"] == 7.75
    assert updated["quality"] == 5
    assert updated["notes"] == "edited"

    db.delete_record(rec["id"])
    assert db.get_records() == []


def test_update_record_unknown_id_returns_false():
    assert db.update_record(99999, "2026-07-01", "23:00", "07:00", 3, "") is False


def test_get_records_limit_and_order():
    for i in range(5):
        db.add_record(_d(i), "23:00", "07:00", 3, "")
    records = db.get_records(limit=3)
    assert len(records) == 3
    # Newest date first
    assert [r["date"] for r in records] == [_d(0), _d(1), _d(2)]


def test_get_all_records_ascending():
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    db.add_record(_d(2), "23:00", "07:00", 3, "")
    db.add_record(_d(1), "23:00", "07:00", 3, "")
    assert [r["date"] for r in db.get_all_records()] == [_d(2), _d(1), _d(0)]


def test_clear_all_records():
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    db.add_record(_d(1), "23:00", "07:00", 3, "")
    db.clear_all_records()
    assert db.get_all_records() == []


# ── get_stats ─────────────────────────────────────────────────

def test_stats_empty_db():
    stats = db.get_stats()
    assert stats["total"] == 0
    assert stats["avg_hours"] == 0
    assert stats["avg_quality"] == 0
    assert stats["current_streak"] == 0
    assert stats["best_streak"] == 0
    series = stats["series"]
    assert len(series) == 30
    assert all(p["hours"] is None and p["quality"] is None for p in series)
    # Ascending, ending today
    assert series[-1]["date"] == db.get_today().isoformat()
    assert series[0]["date"] == _d(29)
    assert [p["date"] for p in series] == sorted(p["date"] for p in series)


def test_stats_values_and_series():
    db.add_record(_d(0), "23:00", "07:00", 4, "")   # 8.0h today
    db.add_record(_d(1), "22:30", "06:15", 2, "")   # 7.75h yesterday
    stats = db.get_stats()
    assert stats["total"] == 2
    assert stats["avg_hours"] == round((8.0 + 7.75) / 2, 2)  # 7.88
    assert stats["avg_quality"] == 3.0
    series = stats["series"]
    assert series[-1] == {"date": _d(0), "hours": 8.0, "quality": 4}
    assert series[-2] == {"date": _d(1), "hours": 7.75, "quality": 2}
    assert series[-3]["hours"] is None


def test_series_duplicate_date_takes_highest_id():
    db.add_record(_d(0), "23:00", "07:00", 3, "older")
    db.add_record(_d(0), "22:00", "07:00", 5, "newer")  # higher id, 9.0h
    series = db.get_stats()["series"]
    assert series[-1]["hours"] == 9.0
    assert series[-1]["quality"] == 5


# ── Streaks ───────────────────────────────────────────────────

def test_current_streak_ending_today():
    for i in (0, 1, 2):
        db.add_record(_d(i), "23:00", "07:00", 3, "")
    stats = db.get_stats()
    assert stats["current_streak"] == 3
    assert stats["best_streak"] == 3
    assert db.get_streak() == 3


def test_current_streak_ending_yesterday_still_counts():
    db.add_record(_d(1), "23:00", "07:00", 3, "")
    db.add_record(_d(2), "23:00", "07:00", 3, "")
    assert db.get_stats()["current_streak"] == 2


def test_current_streak_zero_when_latest_older_than_yesterday():
    db.add_record(_d(2), "23:00", "07:00", 3, "")
    db.add_record(_d(3), "23:00", "07:00", 3, "")
    stats = db.get_stats()
    assert stats["current_streak"] == 0
    assert stats["best_streak"] == 2


def test_best_streak_across_gaps():
    # Old 4-day run
    for i in (20, 19, 18, 17):
        db.add_record(_d(i), "23:00", "07:00", 3, "")
    # Current 2-day run
    for i in (1, 0):
        db.add_record(_d(i), "23:00", "07:00", 3, "")
    stats = db.get_stats()
    assert stats["best_streak"] == 4
    assert stats["current_streak"] == 2


def test_streak_duplicate_dates_count_once():
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    db.add_record(_d(0), "22:00", "06:00", 4, "")
    db.add_record(_d(1), "23:00", "07:00", 3, "")
    stats = db.get_stats()
    assert stats["current_streak"] == 2
    assert stats["best_streak"] == 2


def test_future_records_do_not_create_a_streak():
    future = (db.get_today() + timedelta(days=1)).isoformat()
    db.add_record(future, "23:00", "07:00", 3, "")
    stats = db.get_stats()
    assert stats["current_streak"] == 0
    assert stats["best_streak"] == 0


# ── Analytics helpers ─────────────────────────────────────────

def test_weekly_averages_empty():
    assert db.get_weekly_averages() == []


def test_weekly_averages_shape_and_values():
    db.add_record(_d(0), "23:00", "07:00", 4, "")   # 8.0h
    db.add_record(_d(1), "22:30", "06:15", 3, "")   # 7.75h
    weeks = db.get_weekly_averages(12)
    assert len(weeks) == 12
    assert all(set(w) == {"label", "avg_hours", "avg_quality", "count"} for w in weeks)
    this_week = weeks[-1]  # oldest-first, so current week is last
    assert this_week["label"] == "This week"
    assert this_week["count"] == 2
    assert this_week["avg_hours"] == round((8.0 + 7.75) / 2, 1)  # 7.9
    assert this_week["avg_quality"] == 3.5
    # Empty weeks zero-filled
    assert weeks[0]["count"] == 0
    assert weeks[0]["avg_hours"] == 0


def test_day_of_week_stats():
    db.add_record(_d(0), "23:00", "07:00", 4, "")
    result = db.get_day_of_week_stats()
    assert [r["day"] for r in result] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    today_abbr = db.get_today().strftime("%a")
    by_day = {r["day"]: r for r in result}
    assert by_day[today_abbr] == {"day": today_abbr, "avg_hours": 8.0, "avg_quality": 4, "count": 1}
    for day, r in by_day.items():
        if day != today_abbr:
            assert r == {"day": day, "avg_hours": 0, "avg_quality": 0, "count": 0}


def test_consistency_score():
    assert db.get_consistency_score() == 0  # empty
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    assert db.get_consistency_score() == 0  # < 2 records
    db.add_record(_d(1), "23:00", "07:00", 3, "")
    db.add_record(_d(2), "23:00", "07:00", 3, "")
    assert db.get_consistency_score() == 100  # identical durations
    db.clear_all_records()
    db.add_record(_d(0), "23:00", "07:00", 3, "")  # 8h
    db.add_record(_d(1), "23:00", "01:00", 3, "")  # 2h -> std dev 3.0 -> score 0
    assert db.get_consistency_score() == 0


def test_monthly_trend():
    db.add_record(_d(0), "23:00", "07:00", 4, "")
    trend = db.get_monthly_trend(6)
    assert len(trend) == 6
    assert all(set(m) == {"label", "avg_hours", "count"} for m in trend)
    current = trend[-1]
    assert current["label"] == db.get_today().strftime("%b %Y")
    assert current["count"] == 1
    assert current["avg_hours"] == 8.0
    assert trend[0]["count"] == 0


def test_best_worst_nights():
    db.add_record(_d(0), "23:00", "07:00", 3, "")  # 8h
    db.add_record(_d(1), "23:00", "05:00", 3, "")  # 6h
    db.add_record(_d(2), "22:00", "07:30", 3, "")  # 9.5h
    result = db.get_best_worst_nights(2)
    assert set(result) == {"best", "worst"}
    assert len(result["best"]) == 2
    assert len(result["worst"]) == 2
    assert result["best"][0]["hours"] == 9.5
    assert result["worst"][0]["hours"] == 6.0


def test_best_worst_nights_empty():
    assert db.get_best_worst_nights() == {"best": [], "worst": []}


# ── Settings ──────────────────────────────────────────────────

def test_settings_get_set_upsert_and_defaults():
    assert db.get_setting("missing", "fallback") == "fallback"
    db.set_setting("sleep_goal", "8.0")
    assert db.get_setting("sleep_goal") == "8.0"
    db.set_setting("sleep_goal", "6.5")  # upsert overwrites
    assert db.get_setting("sleep_goal") == "6.5"
    settings = db.get_all_settings()
    assert settings["sleep_goal"] == 6.5
    assert settings["bedtime_goal"] == "23:00"  # default


def test_settings_default_sleep_goal_matches_sleep_debt():
    assert db.get_all_settings()["sleep_goal"] == 8.0
    assert db.get_stats()["sleep_debt"]["need"] == 8.0


def test_export_data_matches_all_records():
    db.add_record(_d(1), "23:00", "07:00", 3, "a")
    db.add_record(_d(0), "22:00", "06:00", 4, "b")
    assert db.export_data() == db.get_all_records()


def test_add_records_is_atomic():
    records = [
        {
            "date": _d(1),
            "bedtime": "23:00",
            "wake": "07:00",
            "quality": 4,
            "notes": "valid",
        },
        {
            "date": _d(0),
            "bedtime": "23:00",
            "wake": "07:00",
            "quality": 9,
            "notes": "invalid",
        },
    ]
    with pytest.raises(Exception):
        db.add_records(records)
    assert db.get_all_records() == []


def test_get_today_uses_configured_timezone(monkeypatch):
    monkeypatch.setenv("SLEEP_TIMEZONE", "America/New_York")
    instant = datetime(2026, 7, 31, 1, 30, tzinfo=timezone.utc)
    assert db.get_today(instant) == date(2026, 7, 30)


def test_get_today_handles_dst_boundary(monkeypatch):
    monkeypatch.setenv("SLEEP_TIMEZONE", "America/New_York")
    before_midnight = datetime(2026, 3, 8, 4, 30, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 3, 8, 5, 30, tzinfo=timezone.utc)
    assert db.get_today(before_midnight) == date(2026, 3, 7)
    assert db.get_today(after_midnight) == date(2026, 3, 8)
