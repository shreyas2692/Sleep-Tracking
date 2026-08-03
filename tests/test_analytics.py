"""Pure-function tests for analytics.py (no database required).

Fixtures are deterministic: `make_records` builds N consecutive nights with
per-night control over duration, bedtime, quality, stages and efficiency
(scalars, lists, or callables of the night index).
"""

import json
import os
import sys
from datetime import date, timedelta

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import analytics
from analytics import (
    analyze_all,
    anomaly_detection,
    bedtime_consistency,
    duration_quality_curve,
    quality_drivers,
    sleep_debt_model,
    sleep_duration_trend,
    stage_composition_trend,
    weekly_report,
)

# 2026-01-05 is a Monday — lets tests reason about weekdays exactly.
MONDAY = date(2026, 1, 5)


def _value(spec, i, default):
    if spec is None:
        return default
    if callable(spec):
        return spec(i)
    if isinstance(spec, (list, tuple)):
        return spec[i % len(spec)]
    return spec


def _fmt(minutes):
    minutes = int(round(minutes)) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def make_records(n, start=MONDAY, hours=7.5, bedtime="23:00", quality=3,
                 stages=None, efficiency=None):
    """N consecutive nights. hours/bedtime/quality/stages/efficiency may be
    scalars, lists (cycled), or callables of the night index."""
    records = []
    for i in range(n):
        h = float(_value(hours, i, 7.5))
        bed = _value(bedtime, i, "23:00")
        bed_min = int(bed[:2]) * 60 + int(bed[3:])
        wake_min = (bed_min + round(h * 60)) % 1440
        records.append({
            "id": i + 1,
            "date": (start + timedelta(days=i)).isoformat(),
            "bedtime": bed,
            "wake": _fmt(wake_min),
            "quality": int(_value(quality, i, 3)),
            "notes": "",
            "hours": round(h, 2),
            "source": "manual",
            "stages": _value(stages, i, None),
            "efficiency": _value(efficiency, i, None),
        })
    return records


def stages_for(hours, deep_frac=0.18, rem_frac=0.22, awake_minutes=20):
    """Stage dict whose minutes total the sleep interval."""
    total = round(hours * 60)
    asleep = total - awake_minutes
    deep = round(asleep * deep_frac)
    rem = round(asleep * rem_frac)
    light = asleep - deep - rem
    return {"deep": deep, "rem": rem, "light": light, "awake": awake_minutes}


# ── Duration trend ────────────────────────────────────────────

def test_ols_slope_positive_on_rising_series():
    records = make_records(21, hours=lambda i: 6.0 + 0.05 * i)
    result = sleep_duration_trend(records)
    assert result["available"] is True
    slope = result["trend"]["slope_hours_per_week"]
    assert slope == pytest.approx(0.35, abs=0.01)  # 0.05 h/day * 7
    assert result["trend"]["significant"] is True
    low, high = result["trend"]["ci95"]
    # The fixture is perfectly linear, so the CI may collapse to the slope.
    assert low > 0 and low <= slope <= high


def test_ols_slope_negative_on_falling_series():
    records = make_records(21, hours=lambda i: 8.5 - 0.05 * i)
    result = sleep_duration_trend(records)
    assert result["trend"]["slope_hours_per_week"] < 0


def test_rolling_mean_fills_after_seven_nights():
    records = make_records(10, hours=7.0)
    points = sleep_duration_trend(records)["points"]
    assert all(p["rolling_mean"] is None for p in points[:6])
    assert all(p["rolling_mean"] == pytest.approx(7.0) for p in points[6:])


def test_weekday_profile_counts_cover_all_nights():
    result = sleep_duration_trend(make_records(14))
    profile = result["weekday_profile"]
    assert [d["day"] for d in profile] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert sum(d["n"] for d in profile) == 14


# ── Circular statistics / consistency ─────────────────────────

def test_circular_mean_across_midnight_is_midnight_not_noon():
    # 23:30 and 00:30 must average to ~00:00 — the classic circular-mean bug
    # (a naive arithmetic mean of 1410 and 30 minutes gives 12:00).
    records = make_records(6, bedtime=["23:30", "00:30"])
    result = bedtime_consistency(records)
    assert result["available"] is True
    assert result["bedtime"]["mean"] == "00:00"


def test_consistency_score_tight_beats_scattered():
    tight = bedtime_consistency(make_records(10, bedtime="23:00"))
    scattered = bedtime_consistency(
        make_records(10, bedtime=["21:00", "23:30", "01:45", "20:15", "00:40"])
    )
    assert tight["bedtime"]["score"] == pytest.approx(100.0)
    assert tight["consistency_score"] > scattered["consistency_score"]


def test_social_jetlag_positive_when_weekends_run_late():
    # Sat/Sun dates (weekday >= 5) get a 01:00 bedtime; weekdays 23:00.
    def bedtime(i):
        return "01:00" if (MONDAY + timedelta(days=i)).weekday() >= 5 else "23:00"

    result = bedtime_consistency(make_records(14, bedtime=bedtime))
    jetlag = result["social_jetlag"]
    assert jetlag["available"] is True
    assert jetlag["shift_minutes"] == pytest.approx(120, abs=1)


def test_social_jetlag_negative_when_weekends_run_early():
    def bedtime(i):
        return "21:00" if (MONDAY + timedelta(days=i)).weekday() >= 5 else "23:00"

    jetlag = bedtime_consistency(make_records(14, bedtime=bedtime))["social_jetlag"]
    assert jetlag["shift_minutes"] == pytest.approx(-120, abs=1)


# ── Quality drivers ───────────────────────────────────────────

def _quality_from_hours(i, hours_seq):
    """Quality increases monotonically with duration."""
    h = hours_seq[i % len(hours_seq)]
    return max(1, min(5, int(round((h - 5.0) * 1.2))))


def test_correlation_direction_positive_and_unreliable_flag():
    hours_seq = [5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5]
    small = make_records(
        8, hours=hours_seq, quality=lambda i: _quality_from_hours(i, hours_seq)
    )
    result = quality_drivers(small)
    duration = next(d for d in result["drivers"] if d["driver"] == "duration")
    assert duration["available"] is True
    assert duration["pearson_r"] > 0.5
    assert duration["spearman_rho"] > 0.5
    assert duration["direction"] == "positive"
    assert duration["unreliable"] is True  # n = 8 < 10

    big = make_records(
        21, hours=hours_seq, quality=lambda i: _quality_from_hours(i, hours_seq)
    )
    duration_big = next(
        d for d in quality_drivers(big)["drivers"] if d["driver"] == "duration"
    )
    assert duration_big["unreliable"] is False


def test_correlation_negative_when_less_sleep_scores_higher():
    hours_seq = [5.5, 6.5, 7.5, 8.5]
    records = make_records(
        12, hours=hours_seq,
        quality=lambda i: 6 - _quality_from_hours(i, hours_seq),
    )
    duration = next(
        d for d in quality_drivers(records)["drivers"] if d["driver"] == "duration"
    )
    assert duration["pearson_r"] < -0.5
    assert duration["direction"] == "negative"


def test_constant_quality_driver_degrades_not_crashes():
    result = quality_drivers(make_records(12, quality=3))
    duration = next(d for d in result["drivers"] if d["driver"] == "duration")
    assert duration["available"] is False


def test_stage_and_efficiency_drivers_use_only_nights_with_data():
    records = make_records(
        15,
        hours=7.5,
        stages=lambda i: stages_for(7.5, deep_frac=0.10 + 0.01 * i) if i < 6 else None,
        efficiency=lambda i: 80.0 + i if i < 4 else None,
    )
    drivers = {d["driver"]: d for d in quality_drivers(records)["drivers"]}
    assert drivers["deep_pct"]["n"] == 6
    assert drivers["efficiency"]["n"] == 4


# ── Sweet spot ────────────────────────────────────────────────

def test_sweet_spot_bin_selected_by_mean_quality():
    # 7-8h nights rated 5, everything else rated 2-3; each bin has >= 3 nights.
    hours_seq = [5.5, 6.5, 7.5, 8.5]

    def quality(i):
        return 5 if hours_seq[i % 4] == 7.5 else 2

    result = duration_quality_curve(make_records(16, hours=hours_seq, quality=quality))
    assert result["available"] is True
    assert result["sweet_spot"] == "7-8h"
    spot = next(b for b in result["bins"] if b["label"] == "7-8h")
    assert spot["mean_quality"] == pytest.approx(5.0)
    assert spot["count"] >= 3


def test_sweet_spot_requires_min_count():
    # Only 2 nights in the (top-rated) 7-8h bin → it cannot win.
    records = make_records(10, hours=[6.5] * 8 + [7.5] * 2,
                           quality=[3] * 8 + [5] * 2)
    result = duration_quality_curve(records)
    assert result["sweet_spot"] == "6-7h"


# ── Anomalies ─────────────────────────────────────────────────

def test_anomaly_fires_on_planted_short_night():
    hours = [7.4, 7.6, 7.5, 7.7, 7.3] * 4
    hours[15] = 3.0  # planted outlier with a full 15-night baseline before it
    result = anomaly_detection(make_records(20, hours=hours))
    assert result["available"] is True
    fired = [o for o in result["outliers"] if o["metric"] == "duration"]
    assert any(
        o["date"] == (MONDAY + timedelta(days=15)).isoformat()
        and o["direction"] == "short" and o["z"] < -2.5
        for o in fired
    )


def test_no_anomalies_on_steady_sleep():
    result = anomaly_detection(make_records(20, hours=[7.4, 7.6, 7.5]))
    assert result["available"] is True
    assert result["outliers"] == []


def test_midpoint_anomaly_fires_on_shifted_night():
    bedtimes = ["23:00"] * 20
    bedtimes[15] = "03:30"  # 4.5h later than every baseline night
    result = anomaly_detection(make_records(20, bedtime=bedtimes))
    fired = [o for o in result["outliers"] if o["metric"] == "midpoint"]
    assert any(o["direction"] == "later" for o in fired)


# ── Sleep debt ────────────────────────────────────────────────

def test_debt_accumulates_monotonically_under_constant_deficit():
    result = sleep_debt_model(make_records(14, hours=6.0), need_hours=8.0)
    assert result["available"] is True
    cumulative = [p["cumulative_debt"] for p in result["series"]]
    assert all(b >= a for a, b in zip(cumulative, cumulative[1:]))
    assert cumulative[-1] > 0


def test_debt_decays_and_clears_with_surplus_nights():
    records = make_records(24, hours=[6.0] * 10 + [9.5] * 14)
    result = sleep_debt_model(records, need_hours=8.0)
    cumulative = [p["cumulative_debt"] for p in result["series"]]
    peak = max(cumulative)
    assert cumulative[9] == pytest.approx(peak)  # peak at end of deficit run
    assert cumulative[-1] < peak
    assert cumulative[-1] == 0.0  # long surplus run fully clears (floor at 0)
    assert result["recovery"]["nights"] == 0


def test_recovery_estimate_positive_when_surplus_exists():
    # Deep recent deficit, then a modest surplus pattern in the last 14 nights.
    records = make_records(24, hours=[5.0] * 10 + [8.5] * 14)
    result = sleep_debt_model(records, need_hours=8.0)
    if result["current_debt_hours"] > 0.25:
        assert isinstance(result["recovery"]["nights"], int)
        assert result["recovery"]["nights"] >= 1


def test_recovery_unavailable_when_still_underslept():
    result = sleep_debt_model(make_records(14, hours=6.0), need_hours=8.0)
    assert result["recovery"]["nights"] is None
    assert "adding debt" in result["recovery"]["message"]


def test_debt_yesterday_outweighs_two_weeks_ago():
    # Same single bad night, placed recently vs 2 weeks back: the recent one
    # must leave more current debt (exponential decay).
    early_bad = [4.0] + [8.0] * 14
    late_bad = [8.0] * 14 + [4.0]
    early = sleep_debt_model(make_records(15, hours=early_bad), need_hours=8.0)
    late = sleep_debt_model(make_records(15, hours=late_bad), need_hours=8.0)
    assert late["current_debt_hours"] > early["current_debt_hours"]


# ── Stage composition ─────────────────────────────────────────

def test_stage_percentages_sum_to_100():
    records = make_records(10, stages=lambda i: stages_for(7.5, deep_frac=0.15 + 0.01 * i))
    result = stage_composition_trend(records)
    assert result["available"] is True
    for point in result["points"]:
        total = (point["deep_pct"] + point["rem_pct"]
                 + point["light_pct"] + point["awake_pct"])
        assert total == pytest.approx(100.0, abs=0.05)


def test_stage_reference_status_flags_low_deep():
    records = make_records(8, stages=stages_for(7.5, deep_frac=0.05))
    reference = stage_composition_trend(records)["reference"]
    assert reference["deep"]["status"] == "below"
    records = make_records(8, stages=stages_for(7.5, deep_frac=0.18))
    assert stage_composition_trend(records)["reference"]["deep"]["status"] == "within"


def test_stage_trend_ignores_nights_without_stages():
    records = make_records(12, stages=lambda i: stages_for(7.5) if i % 2 == 0 else None)
    result = stage_composition_trend(records)
    assert result["n"] == 6


# ── Weekly report ─────────────────────────────────────────────

def test_weekly_report_headline_and_sweet_spot_sentence():
    hours_seq = [5.5, 6.5, 7.5, 8.5]

    def quality(i):
        return 5 if hours_seq[i % 4] == 7.5 else 2

    result = weekly_report(make_records(28, hours=hours_seq, quality=quality))
    assert result["available"] is True
    headline = result["headline"]
    assert headline["nights_logged"] == 7
    # Last 7 nights of the 4-cycle: 6.5+7.5+8.5+5.5+6.5+7.5+8.5 = 50.5 / 7.
    assert headline["avg_hours"] == pytest.approx(50.5 / 7, abs=0.01)
    assert any("7-8h" in sentence for sentence in result["insights"])


def test_weekly_report_mentions_debt_when_underslept():
    result = weekly_report(make_records(14, hours=6.0))
    assert any("sleep debt" in s for s in result["insights"])


# ── Graceful degradation ──────────────────────────────────────

ALL_FUNCTIONS = [
    sleep_duration_trend,
    bedtime_consistency,
    quality_drivers,
    duration_quality_curve,
    anomaly_detection,
    sleep_debt_model,
    stage_composition_trend,
    weekly_report,
]


@pytest.mark.parametrize("n", [0, 1, 3])
@pytest.mark.parametrize("func", ALL_FUNCTIONS)
def test_all_functions_degrade_gracefully_on_small_n(func, n):
    result = func(make_records(n))
    assert result["available"] is False
    assert isinstance(result["reason"], str) and result["reason"]
    assert isinstance(result["min_nights"], int)


def test_malformed_records_are_skipped_not_fatal():
    records = make_records(10)
    records.append({"date": "not-a-date", "bedtime": "9pm", "wake": None,
                    "quality": 3, "hours": "eight", "stages": None})
    result = sleep_duration_trend(records)
    assert result["available"] is True
    assert result["n"] == 10


def test_duplicate_dates_keep_latest_record():
    records = make_records(10, hours=7.0)
    override = dict(records[-1])
    override["id"] = 99
    override["hours"] = 5.0
    records.append(override)  # same date, later id — must win
    points = sleep_duration_trend(records)["points"]
    assert len(points) == 10
    assert points[-1]["hours"] == pytest.approx(5.0)


# ── analyze_all + blueprint ───────────────────────────────────

EXPECTED_SECTIONS = {
    "duration_trend", "bedtime_consistency", "quality_drivers",
    "duration_quality_curve", "anomalies", "sleep_debt",
    "stage_composition", "weekly_report",
}


@pytest.mark.parametrize("n", [0, 3, 30])
def test_analyze_all_is_json_serializable(n):
    records = make_records(
        n, stages=lambda i: stages_for(7.5) if i % 2 == 0 else None,
        efficiency=88.0,
    )
    result = analyze_all(records)
    assert EXPECTED_SECTIONS <= set(result)
    assert result["n_nights"] == n
    round_tripped = json.loads(json.dumps(result))
    assert set(round_tripped) == set(result)


def test_blueprint_routes(monkeypatch):
    records = make_records(21, stages=stages_for(7.5))
    monkeypatch.setattr(analytics.database, "get_all_records", lambda: records)
    monkeypatch.setattr(analytics.database, "get_setting", lambda key, default="": "8.0")

    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))
    app.register_blueprint(analytics.analytics_bp)
    client = app.test_client()

    api = client.get("/api/analytics")
    assert api.status_code == 200
    payload = api.get_json()
    assert EXPECTED_SECTIONS <= set(payload)
    assert payload["duration_trend"]["available"] is True

    page = client.get("/insights")
    assert page.status_code == 200
    assert b"Sleep Insights" in page.data
