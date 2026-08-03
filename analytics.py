"""Statistical sleep-pattern analysis: pure functions + Flask blueprint.

Registration (orchestrator: add this ONE line to app.py after `app = Flask(__name__)`
and its config block):

    from analytics import analytics_bp; app.register_blueprint(analytics_bp)

The app's auth / CSRF / request-limit hooks are registered with
`@app.before_request` on the app object itself, so they run for every request
including blueprint routes — no extra wiring is needed for /insights or
/api/analytics to be password-protected.

Design notes
------------
* Every analysis function is PURE: it takes a list of record dicts (the shape
  produced by database._row_to_dict: {id, date, bedtime, wake, quality, notes,
  hours, source, stages, efficiency}) and returns a JSON-serializable dict.
  Only the blueprint route touches the database.
* Small samples degrade gracefully: each function returns
  {"available": False, "reason": "...", "min_nights": N} instead of raising.
  Minimum nights per analysis are documented on each function.
* When one calendar date has several records (e.g. manual + wearable), the
  latest record wins — the same rule database.get_stats()/get_series() use.
  Records arrive ascending by (date, id) from get_all_records(), so "last one
  in the list per date" is the latest. Stage analysis prefers the latest
  stage-bearing record for a date, since a manual edit without stages should
  not hide wearable stage data.
* Statistics are stdlib-only (statistics, math); OLS, circular statistics,
  Spearman ranks and t-quantiles are implemented by hand below.
"""

import math
from collections import OrderedDict
from datetime import datetime, timedelta
from statistics import fmean, pstdev, stdev

from flask import Blueprint, jsonify, render_template

import database

analytics_bp = Blueprint("analytics", __name__)

MINUTES_PER_DAY = 24 * 60
HALF_DAY = MINUTES_PER_DAY // 2

# Exponential decay applied to accumulated sleep debt per calendar day.
# 0.9/day means last night carries full weight, a night 7 days ago ~48%,
# and a night 14 days ago ~23% (half-life ≈ 6.6 days) — "yesterday matters
# more than two weeks ago".
DEBT_DECAY_PER_DAY = 0.9

# Robustness floors for anomaly z-scores so ultra-consistent baselines do not
# make trivial deviations explode (a 5-minute wobble is not an anomaly).
MIN_DURATION_STD_HOURS = 0.25
MIN_MIDPOINT_STD_MINUTES = 15.0
ANOMALY_Z_THRESHOLD = 2.5

# Approximate adult reference ranges, percent of asleep time (deep+rem+light).
# Presented in the UI as approximate, not diagnostic.
DEEP_REFERENCE = (13.0, 23.0)
REM_REFERENCE = (20.0, 25.0)

DURATION_BINS = (
    ("<6h", None, 6.0),
    ("6-7h", 6.0, 7.0),
    ("7-8h", 7.0, 8.0),
    ("8-9h", 8.0, 9.0),
    (">9h", 9.0, None),
)

# Two-sided 95% Student-t critical values by degrees of freedom (nearest
# lower key is used; df > 30 approximates the normal quantile 1.96).
_T95 = OrderedDict([
    (1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571),
    (6, 2.447), (7, 2.365), (8, 2.306), (9, 2.262), (10, 2.228),
    (12, 2.179), (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042),
])


# ── Record cleaning helpers ───────────────────────────────────

def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_minutes(value):
    """HH:MM → minutes past midnight, or None."""
    try:
        parts = value.split(":")
        hours, minutes = int(parts[0]), int(parts[1])
    except (AttributeError, IndexError, ValueError):
        return None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return hours * 60 + minutes


def _clean_nights(records):
    """One validated night per calendar date, ascending by date.

    Latest record wins per date (input is ASC by date, id). Adds parsed
    fields: _date (date obj), _bed_min, _wake_min, _mid_min (midpoint of
    sleep, minutes past midnight on the wake date's clock, wrapped 0-1439).
    """
    by_date = {}
    for record in records:
        night_date = _parse_date(record.get("date"))
        bed_min = _parse_minutes(record.get("bedtime"))
        wake_min = _parse_minutes(record.get("wake"))
        hours = record.get("hours")
        if night_date is None or bed_min is None or wake_min is None:
            continue
        if not isinstance(hours, (int, float)) or not math.isfinite(hours):
            continue
        if not 0 < hours <= 24:
            continue
        night = dict(record)
        night["_date"] = night_date
        night["_bed_min"] = bed_min
        night["_wake_min"] = wake_min
        night["_mid_min"] = (bed_min + hours * 60 / 2) % MINUTES_PER_DAY
        by_date[night_date] = night
    return [by_date[d] for d in sorted(by_date)]


def _stage_nights(records):
    """Nights with usable stage data (latest stage-bearing record per date)."""
    by_date = {}
    for record in records:
        night_date = _parse_date(record.get("date"))
        stages = record.get("stages")
        if night_date is None or not isinstance(stages, dict):
            continue
        try:
            total = sum(float(stages[k]) for k in ("deep", "rem", "light", "awake"))
        except (KeyError, TypeError, ValueError):
            continue
        if total <= 0:
            continue
        night = dict(record)
        night["_date"] = night_date
        night["_stage_total"] = total
        by_date[night_date] = night
    return [by_date[d] for d in sorted(by_date)]


def _unavailable(reason, min_nights):
    return {"available": False, "reason": reason, "min_nights": min_nights}


# ── Math helpers (stdlib only) ────────────────────────────────

def _t_crit_95(df):
    """Two-sided 95% t critical value, nearest-lower-df table lookup."""
    if df <= 0:
        return None
    if df > 30:
        return 1.96
    crit = _T95[1]
    for key, value in _T95.items():
        if key <= df:
            crit = value
    return crit


def _ols(xs, ys):
    """Simple least squares y = a + b*x.

    Returns (slope, intercept, slope_stderr) — stderr is None when df < 1 or
    the fit is degenerate. Standard error uses the usual normal-errors
    formula se(b) = sqrt(SSE / (n-2) / Sxx).
    """
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    stderr = None
    if n > 2:
        sse = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
        stderr = math.sqrt(max(sse, 0.0) / (n - 2) / sxx)
    return slope, intercept, stderr


def _pearson(xs, ys):
    """Pearson r, or None when either variable is constant."""
    n = len(xs)
    if n < 3:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    sx = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    sy = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    r = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (sx * sy)
    return max(-1.0, min(1.0, r))


def _ranks(values):
    """Fractional ranks (1-based) with average ranks for ties."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs, ys):
    """Spearman rho = Pearson correlation of fractional ranks (tie-safe)."""
    return _pearson(_ranks(xs), _ranks(ys))


def _circular_mean(minutes_list):
    """(mean_minutes, R) for clock times treated as angles on a 24h circle.

    R (resultant length, 0-1) measures concentration: 1 = identical times,
    0 = uniformly scattered. This is what makes 23:30 and 00:30 average to
    ~00:00 rather than 12:00.
    """
    angles = [2 * math.pi * m / MINUTES_PER_DAY for m in minutes_list]
    sin_mean = fmean(math.sin(a) for a in angles)
    cos_mean = fmean(math.cos(a) for a in angles)
    resultant = math.hypot(sin_mean, cos_mean)
    mean_angle = math.atan2(sin_mean, cos_mean) % (2 * math.pi)
    mean_minutes = mean_angle / (2 * math.pi) * MINUTES_PER_DAY
    return mean_minutes, resultant


def _signed_minute_diff(a_minutes, b_minutes):
    """Shortest signed difference a-b on the 24h clock, in (-720, 720]."""
    diff = (a_minutes - b_minutes) % MINUTES_PER_DAY
    if diff > HALF_DAY:
        diff -= MINUTES_PER_DAY
    return diff


def _fmt_minutes(minutes):
    minutes = int(round(minutes)) % MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _round(value, digits=2):
    return None if value is None else round(float(value), digits)


def _strength_label(r):
    magnitude = abs(r)
    if magnitude < 0.1:
        return "negligible"
    if magnitude < 0.3:
        return "weak"
    if magnitude < 0.5:
        return "moderate"
    return "strong"


# ── 1. Duration trend ─────────────────────────────────────────

def sleep_duration_trend(records):
    """Rolling 7-night mean/std, OLS trend (hrs/week ± 95% CI), weekday profile.

    Minimum: 7 nights. The rolling window is the trailing 7 logged nights
    (not calendar days); entries are null until the window fills. The OLS x
    axis is calendar days since the first night, so gaps in logging do not
    compress time. The CI uses a Student-t approximation on the slope's
    standard error.
    """
    nights = _clean_nights(records)
    if len(nights) < 7:
        return _unavailable("Need at least 7 logged nights.", 7)

    first_date = nights[0]["_date"]
    points = []
    window = []
    for night in nights:
        window.append(night["hours"])
        if len(window) > 7:
            window.pop(0)
        full = len(window) == 7
        points.append({
            "date": night["_date"].isoformat(),
            "hours": _round(night["hours"]),
            "rolling_mean": _round(fmean(window)) if full else None,
            "rolling_std": _round(stdev(window)) if full else None,
        })

    xs = [(night["_date"] - first_date).days for night in nights]
    ys = [night["hours"] for night in nights]
    fit = _ols(xs, ys)
    trend = None
    if fit is not None:
        slope_per_day, intercept, stderr = fit
        slope_week = slope_per_day * 7
        ci = None
        significant = None
        crit = _t_crit_95(len(nights) - 2)
        if stderr is not None and crit is not None:
            half_width = crit * stderr * 7
            ci = [_round(slope_week - half_width, 3), _round(slope_week + half_width, 3)]
            significant = bool(ci[0] > 0 or ci[1] < 0)
        trend = {
            "slope_hours_per_week": _round(slope_week, 3),
            "ci95": ci,
            "significant": significant,
            "n": len(nights),
        }

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    buckets = {name: [] for name in day_names}
    for night in nights:
        buckets[day_names[night["_date"].weekday()]].append(night["hours"])
    weekday_profile = [
        {
            "day": name,
            "mean_hours": _round(fmean(buckets[name])) if buckets[name] else None,
            "n": len(buckets[name]),
        }
        for name in day_names
    ]

    return {
        "available": True,
        "n": len(nights),
        "points": points,
        "trend": trend,
        "weekday_profile": weekday_profile,
    }


# ── 2. Bedtime consistency ────────────────────────────────────

def bedtime_consistency(records):
    """Circular bedtime/wake statistics + social jetlag.

    Minimum: 5 nights (social jetlag additionally needs >= 3 weekday and
    >= 2 weekend nights). Consistency score is 100 * R, the circular
    resultant length — 100 means the exact same time every night. "Weekend"
    nights are those whose (wake) date falls on Saturday or Sunday, i.e.
    Friday and Saturday nights. Social jetlag is the shift, in minutes, of
    the circular-mean midpoint of sleep on weekends relative to weekdays;
    positive = later on weekends.
    """
    nights = _clean_nights(records)
    if len(nights) < 5:
        return _unavailable("Need at least 5 logged nights.", 5)

    bed_mean, bed_r = _circular_mean([n["_bed_min"] for n in nights])
    wake_mean, wake_r = _circular_mean([n["_wake_min"] for n in nights])

    weekend = [n for n in nights if n["_date"].weekday() >= 5]
    weekday = [n for n in nights if n["_date"].weekday() < 5]
    if len(weekend) >= 2 and len(weekday) >= 3:
        weekend_mid, _ = _circular_mean([n["_mid_min"] for n in weekend])
        weekday_mid, _ = _circular_mean([n["_mid_min"] for n in weekday])
        social_jetlag = {
            "available": True,
            "shift_minutes": _round(_signed_minute_diff(weekend_mid, weekday_mid), 1),
            "weekend_midpoint": _fmt_minutes(weekend_mid),
            "weekday_midpoint": _fmt_minutes(weekday_mid),
            "n_weekend": len(weekend),
            "n_weekday": len(weekday),
        }
    else:
        social_jetlag = _unavailable(
            "Need at least 3 weekday and 2 weekend nights.", 5
        )

    points = [
        {
            "date": n["_date"].isoformat(),
            "bed_minutes": n["_bed_min"],
            "wake_minutes": n["_wake_min"],
            "weekend": n["_date"].weekday() >= 5,
        }
        for n in nights
    ]

    return {
        "available": True,
        "n": len(nights),
        "bedtime": {
            "mean": _fmt_minutes(bed_mean),
            "resultant": _round(bed_r, 3),
            "score": _round(bed_r * 100, 1),
        },
        "wake": {
            "mean": _fmt_minutes(wake_mean),
            "resultant": _round(wake_r, 3),
            "score": _round(wake_r * 100, 1),
        },
        "consistency_score": _round((bed_r + wake_r) / 2 * 100, 1),
        "social_jetlag": social_jetlag,
        "points": points,
    }


# ── 3. Quality drivers ────────────────────────────────────────

def _driver_entry(name, label, pairs, unit):
    """Correlate quality against one driver over its available pairs."""
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    n = len(pairs)
    pearson = _pearson(xs, ys) if n >= 3 else None
    if pearson is None:
        return {
            "driver": name,
            "label": label,
            "unit": unit,
            "n": n,
            "available": False,
            "reason": "Too few nights, or no variation to correlate.",
        }
    spearman = _spearman(xs, ys)
    return {
        "driver": name,
        "label": label,
        "unit": unit,
        "n": n,
        "available": True,
        "pearson_r": _round(pearson, 3),
        "spearman_rho": _round(spearman, 3),
        "strength": _strength_label(pearson),
        "direction": "positive" if pearson >= 0 else "negative",
        "unreliable": n < 10,
    }


def quality_drivers(records):
    """Pearson + Spearman correlation of quality vs candidate drivers.

    Minimum: 5 nights overall and 3 paired nights per driver, and any driver
    with n < 10 is flagged "unreliable" (correlations on so few nights swing
    wildly and should be read as hints, not findings). Bedtime enters as
    "lateness": the signed circular deviation from the user's own mean
    bedtime, so nights spanning midnight correlate correctly.
    """
    nights = _clean_nights(records)
    if len(nights) < 5:
        return _unavailable("Need at least 5 logged nights.", 5)

    quality = [n["quality"] for n in nights]
    bed_mean, _ = _circular_mean([n["_bed_min"] for n in nights])

    drivers = [
        _driver_entry(
            "duration", "Sleep duration",
            [(n["hours"], q) for n, q in zip(nights, quality)], "hours",
        ),
        _driver_entry(
            "bedtime_lateness", "Bedtime (later than your usual)",
            [
                (_signed_minute_diff(n["_bed_min"], bed_mean) / 60.0, q)
                for n, q in zip(nights, quality)
            ],
            "hours later",
        ),
    ]

    stage_pairs_deep, stage_pairs_rem, efficiency_pairs = [], [], []
    for night in nights:
        stages = night.get("stages")
        if isinstance(stages, dict):
            try:
                asleep = float(stages["deep"]) + float(stages["rem"]) + float(stages["light"])
            except (KeyError, TypeError, ValueError):
                asleep = 0
            if asleep > 0:
                stage_pairs_deep.append((float(stages["deep"]) / asleep * 100, night["quality"]))
                stage_pairs_rem.append((float(stages["rem"]) / asleep * 100, night["quality"]))
        efficiency = night.get("efficiency")
        if isinstance(efficiency, (int, float)) and math.isfinite(efficiency):
            efficiency_pairs.append((float(efficiency), night["quality"]))

    drivers.append(_driver_entry("deep_pct", "Deep sleep %", stage_pairs_deep, "% of sleep"))
    drivers.append(_driver_entry("rem_pct", "REM sleep %", stage_pairs_rem, "% of sleep"))
    drivers.append(_driver_entry("efficiency", "Sleep efficiency", efficiency_pairs, "%"))

    return {"available": True, "n": len(nights), "drivers": drivers}


# ── 4. Duration-quality curve (sweet spot) ────────────────────

def duration_quality_curve(records):
    """Mean quality per duration bin; the best-rated bin is the sweet spot.

    Minimum: 5 nights overall; a bin needs >= 3 nights to be eligible as
    the sweet spot (ties broken toward the longer-duration bin, since equal
    quality on more sleep is the safer recommendation).
    """
    nights = _clean_nights(records)
    if len(nights) < 5:
        return _unavailable("Need at least 5 logged nights.", 5)

    bins = []
    for label, low, high in DURATION_BINS:
        members = [
            n for n in nights
            if (low is None or n["hours"] >= low) and (high is None or n["hours"] < high)
        ]
        bins.append({
            "label": label,
            "low": low,
            "high": high,
            "count": len(members),
            "mean_quality": _round(fmean(m["quality"] for m in members)) if members else None,
        })

    eligible = [b for b in bins if b["count"] >= 3]
    sweet_spot = None
    if eligible:
        best = max(eligible, key=lambda b: (b["mean_quality"], b["low"] or 0))
        sweet_spot = best["label"]

    return {
        "available": True,
        "n": len(nights),
        "bins": bins,
        "sweet_spot": sweet_spot,
        "sweet_spot_min_count": 3,
    }


# ── 5. Anomaly detection ──────────────────────────────────────

def anomaly_detection(records):
    """Z-score outliers on duration and midpoint-of-sleep vs a rolling baseline.

    Minimum: 10 nights. Each night is compared against the trailing window
    of up to 30 PRIOR nights (never itself); at least 8 baseline nights are
    required before a night can be scored. Midpoint deviations use signed
    circular differences from the baseline's circular mean, so a 01:00
    midpoint vs a 23:30 baseline reads as +90 min, not -22.5 h. Baseline
    std is floored (0.25 h duration, 15 min midpoint) so ultra-consistent
    sleepers don't get flagged for trivial wobbles. |z| > 2.5 fires.
    """
    nights = _clean_nights(records)
    if len(nights) < 10:
        return _unavailable("Need at least 10 logged nights.", 10)

    outliers = []
    scored = 0
    for i, night in enumerate(nights):
        baseline = nights[max(0, i - 30):i]
        if len(baseline) < 8:
            continue
        scored += 1

        hours = [b["hours"] for b in baseline]
        mean_hours = fmean(hours)
        std_hours = max(pstdev(hours), MIN_DURATION_STD_HOURS)
        z_duration = (night["hours"] - mean_hours) / std_hours

        mid_mean, _ = _circular_mean([b["_mid_min"] for b in baseline])
        deviations = [_signed_minute_diff(b["_mid_min"], mid_mean) for b in baseline]
        std_mid = max(
            math.sqrt(fmean(d * d for d in deviations)), MIN_MIDPOINT_STD_MINUTES
        )
        mid_dev = _signed_minute_diff(night["_mid_min"], mid_mean)
        z_midpoint = mid_dev / std_mid

        if abs(z_duration) > ANOMALY_Z_THRESHOLD:
            outliers.append({
                "date": night["_date"].isoformat(),
                "metric": "duration",
                "value": _round(night["hours"]),
                "baseline_mean": _round(mean_hours),
                "z": _round(z_duration),
                "direction": "short" if z_duration < 0 else "long",
            })
        if abs(z_midpoint) > ANOMALY_Z_THRESHOLD:
            outliers.append({
                "date": night["_date"].isoformat(),
                "metric": "midpoint",
                "value": _fmt_minutes(night["_mid_min"]),
                "baseline_mean": _fmt_minutes(mid_mean),
                "z": _round(z_midpoint),
                "direction": "earlier" if mid_dev < 0 else "later",
            })

    return {
        "available": True,
        "n": len(nights),
        "nights_scored": scored,
        "threshold": ANOMALY_Z_THRESHOLD,
        "outliers": outliers,
    }


# ── 6. Sleep debt model ───────────────────────────────────────

def sleep_debt_model(records, need_hours=8.0):
    """Exponentially-decaying cumulative sleep debt and a recovery estimate.

    Minimum: 7 nights. Model: walking each calendar day from the first to
    the last logged night, debt_t = decay * debt_{t-1} + (need - hours_t),
    with decay = 0.9 per day (half-life ~6.6 days), floored at 0 — surplus
    sleep clears debt but cannot be banked indefinitely. Days with no
    logged night add no new debt (an unlogged night is not evidence of no
    sleep) but old debt still decays. The recovery estimate simulates
    forward at the user's recent (last <=14 nights) average and reports how
    many such nights would clear the current debt.
    """
    nights = _clean_nights(records)
    if len(nights) < 7:
        return _unavailable("Need at least 7 logged nights.", 7)
    if not (0 < need_hours <= 24):
        need_hours = 8.0

    by_date = {n["_date"]: n for n in nights}
    day = nights[0]["_date"]
    last = nights[-1]["_date"]
    debt = 0.0
    series = []
    while day <= last:
        debt *= DEBT_DECAY_PER_DAY
        night = by_date.get(day)
        if night is not None:
            nightly = need_hours - night["hours"]
            debt = max(0.0, debt + nightly)
            series.append({
                "date": day.isoformat(),
                "nightly_deficit": _round(nightly),
                "cumulative_debt": _round(debt),
            })
        day += timedelta(days=1)

    current_debt = series[-1]["cumulative_debt"]
    recent = nights[-14:]
    recent_avg = fmean(n["hours"] for n in recent)
    nightly_surplus = recent_avg - need_hours

    recovery = {"nights": None, "message": ""}
    if current_debt <= 0.25:
        recovery["nights"] = 0
        recovery["message"] = "No meaningful sleep debt right now."
    elif nightly_surplus <= 0:
        recovery["message"] = (
            "At your recent average of "
            f"{recent_avg:.1f}h you are adding debt, not clearing it — "
            f"nights above {need_hours:.1f}h are what pay it down."
        )
    else:
        simulated = current_debt
        nights_needed = 0
        while simulated > 0.25 and nights_needed < 60:
            simulated = max(0.0, simulated * DEBT_DECAY_PER_DAY - nightly_surplus)
            nights_needed += 1
        recovery["nights"] = nights_needed
        recovery["message"] = (
            f"~{nights_needed} night{'s' if nights_needed != 1 else ''} at your "
            f"recent average surplus (+{nightly_surplus:.1f}h/night) to clear it."
        )

    return {
        "available": True,
        "n": len(nights),
        "need_hours": need_hours,
        "decay_per_day": DEBT_DECAY_PER_DAY,
        "current_debt_hours": current_debt,
        "recent_avg_hours": _round(recent_avg),
        "recovery": recovery,
        "series": series,
    }


# ── 7. Stage composition trend ────────────────────────────────

def _reference_status(value, low, high):
    if value < low:
        return "below"
    if value > high:
        return "above"
    return "within"


def stage_composition_trend(records):
    """Stage percentages over time with 14-night rolling means + references.

    Minimum: 5 nights with stage data. Chart percentages (deep/rem/light/
    awake) are shares of TOTAL recorded stage minutes and sum to 100. The
    reference comparison uses deep% and rem% of ASLEEP time (deep+rem+light,
    the convention the published adult ranges use): deep ~13-23%, REM
    ~20-25% — approximate, not diagnostic.
    """
    nights = _stage_nights(records)
    if len(nights) < 5:
        return _unavailable("Need at least 5 nights with sleep-stage data.", 5)

    keys = ("deep", "rem", "light", "awake")
    points = []
    windows = {k: [] for k in keys}
    deep_sleep_pcts, rem_sleep_pcts = [], []
    for night in nights:
        stages = night["stages"]
        total = night["_stage_total"]
        pcts = {k: float(stages[k]) / total * 100 for k in keys}
        point = {"date": night["_date"].isoformat()}
        for k in keys:
            point[f"{k}_pct"] = _round(pcts[k])
            windows[k].append(pcts[k])
            if len(windows[k]) > 14:
                windows[k].pop(0)
            point[f"{k}_roll"] = (
                _round(fmean(windows[k])) if len(windows[k]) >= 5 else None
            )
        points.append(point)

        asleep = float(stages["deep"]) + float(stages["rem"]) + float(stages["light"])
        if asleep > 0:
            deep_sleep_pcts.append(float(stages["deep"]) / asleep * 100)
            rem_sleep_pcts.append(float(stages["rem"]) / asleep * 100)

    reference = None
    if deep_sleep_pcts and rem_sleep_pcts:
        deep_avg = fmean(deep_sleep_pcts)
        rem_avg = fmean(rem_sleep_pcts)
        reference = {
            "deep": {
                "your_pct": _round(deep_avg, 1),
                "reference_low": DEEP_REFERENCE[0],
                "reference_high": DEEP_REFERENCE[1],
                "status": _reference_status(deep_avg, *DEEP_REFERENCE),
            },
            "rem": {
                "your_pct": _round(rem_avg, 1),
                "reference_low": REM_REFERENCE[0],
                "reference_high": REM_REFERENCE[1],
                "status": _reference_status(rem_avg, *REM_REFERENCE),
            },
            "note": (
                "Reference ranges are approximate adult values as a share of "
                "time asleep; wearable staging itself is an estimate."
            ),
        }

    return {
        "available": True,
        "n": len(nights),
        "points": points,
        "reference": reference,
    }


# ── 8. Weekly report ──────────────────────────────────────────

def _week_headline(nights):
    """Headline stats for the last 7 calendar days ending at the latest night."""
    latest = nights[-1]["_date"]
    week_start = latest - timedelta(days=6)
    prev_start = week_start - timedelta(days=7)
    this_week = [n for n in nights if week_start <= n["_date"] <= latest]
    prev_week = [n for n in nights if prev_start <= n["_date"] < week_start]

    avg_hours = fmean(n["hours"] for n in this_week)
    headline = {
        "week_start": week_start.isoformat(),
        "week_end": latest.isoformat(),
        "nights_logged": len(this_week),
        "avg_hours": _round(avg_hours),
        "avg_quality": _round(fmean(n["quality"] for n in this_week)),
        "delta_hours_vs_prev_week": None,
    }
    if prev_week:
        headline["delta_hours_vs_prev_week"] = _round(
            avg_hours - fmean(n["hours"] for n in prev_week)
        )
    return headline, this_week


def _build_insights(nights, this_week, trend, consistency, curve, anomalies,
                    debt, stages):
    """Rule-generated plain-language insight sentences (most useful first)."""
    insights = []

    if curve.get("available") and curve.get("sweet_spot"):
        spot = next(b for b in curve["bins"] if b["label"] == curve["sweet_spot"])
        hits = [
            n for n in this_week
            if (spot["low"] is None or n["hours"] >= spot["low"])
            and (spot["high"] is None or n["hours"] < spot["high"])
        ]
        insights.append(
            f"Your quality peaks at {spot['label']} of sleep "
            f"(avg {spot['mean_quality']:.1f}/5) — you hit that range "
            f"{len(hits)}/{len(this_week)} nights this week."
        )

    if trend.get("available") and trend.get("trend"):
        t = trend["trend"]
        if t.get("significant"):
            direction = "gaining" if t["slope_hours_per_week"] > 0 else "losing"
            insights.append(
                f"You're {direction} about "
                f"{abs(t['slope_hours_per_week']) * 60:.0f} min of sleep per week "
                "— a real trend, not noise (95% CI excludes zero)."
            )

    if consistency.get("available"):
        score = consistency["consistency_score"]
        if score >= 85:
            insights.append(
                f"Your sleep schedule is very consistent (score {score:.0f}/100) "
                f"— typical bedtime {consistency['bedtime']['mean']}."
            )
        elif score < 60:
            insights.append(
                f"Your sleep timing varies a lot (consistency {score:.0f}/100). "
                "A steadier bedtime is the single easiest lever for better sleep."
            )
        jetlag = consistency.get("social_jetlag", {})
        if jetlag.get("available") and abs(jetlag["shift_minutes"]) >= 60:
            direction = "later" if jetlag["shift_minutes"] > 0 else "earlier"
            insights.append(
                f"Social jetlag: your sleep midpoint shifts "
                f"{abs(jetlag['shift_minutes']) / 60:.1f}h {direction} on weekends "
                "— that Monday grogginess has a cause."
            )

    if debt.get("available"):
        current = debt["current_debt_hours"]
        if current > 2:
            insights.append(
                f"You're carrying about {current:.1f}h of recent sleep debt. "
                + debt["recovery"]["message"]
            )
        elif current <= 0.25:
            insights.append("You're carrying essentially no sleep debt right now.")

    if anomalies.get("available") and this_week:
        week_dates = {n["_date"].isoformat() for n in this_week}
        recent_outliers = [
            o for o in anomalies["outliers"] if o["date"] in week_dates
        ]
        for outlier in recent_outliers[:2]:
            if outlier["metric"] == "duration":
                insights.append(
                    f"{outlier['date']} was unusual: {outlier['value']:.1f}h vs "
                    f"your ~{outlier['baseline_mean']:.1f}h baseline "
                    f"({'short' if outlier['direction'] == 'short' else 'long'} night)."
                )
            else:
                insights.append(
                    f"{outlier['date']} was unusual: sleep midpoint {outlier['value']} "
                    f"vs your usual ~{outlier['baseline_mean']} "
                    f"({outlier['direction']} than normal)."
                )

    if stages.get("available") and stages.get("reference"):
        deep = stages["reference"]["deep"]
        if deep["status"] != "within":
            insights.append(
                f"Your deep sleep averages {deep['your_pct']:.0f}% of time asleep, "
                f"{deep['status']} the approximate adult range of "
                f"{deep['reference_low']:.0f}-{deep['reference_high']:.0f}%. "
                "Wearable staging is an estimate — treat this as a nudge, not a diagnosis."
            )

    if len(nights) < 14:
        insights.append(
            f"Only {len(nights)} nights logged so far — these patterns will "
            "sharpen as you log more."
        )
    return insights


def weekly_report(records, need_hours=8.0):
    """Composed summary: headline stats + rule-generated insight sentences.

    Minimum: 5 nights. Reuses the other analyses; sections that are not yet
    available simply contribute no sentences.
    """
    nights = _clean_nights(records)
    if len(nights) < 5:
        return _unavailable("Need at least 5 logged nights.", 5)

    trend = sleep_duration_trend(records)
    consistency = bedtime_consistency(records)
    curve = duration_quality_curve(records)
    anomalies = anomaly_detection(records)
    debt = sleep_debt_model(records, need_hours)
    stages = stage_composition_trend(records)

    headline, this_week = _week_headline(nights)
    insights = _build_insights(
        nights, this_week, trend, consistency, curve, anomalies, debt, stages
    )

    return {
        "available": True,
        "n": len(nights),
        "headline": headline,
        "insights": insights,
    }


# ── Top level + blueprint ─────────────────────────────────────

def analyze_all(records, need_hours=8.0):
    """Every analysis, keyed by section. Always JSON-serializable."""
    return {
        "n_nights": len(_clean_nights(records)),
        "duration_trend": sleep_duration_trend(records),
        "bedtime_consistency": bedtime_consistency(records),
        "quality_drivers": quality_drivers(records),
        "duration_quality_curve": duration_quality_curve(records),
        "anomalies": anomaly_detection(records),
        "sleep_debt": sleep_debt_model(records, need_hours),
        "stage_composition": stage_composition_trend(records),
        "weekly_report": weekly_report(records, need_hours),
    }


def _need_hours_setting():
    """The user's sleep goal (settings), defaulting to 8.0 like get_stats."""
    try:
        need = float(database.get_setting("sleep_goal", "8.0"))
    except (TypeError, ValueError):
        return 8.0
    return need if 0 < need <= 24 else 8.0


@analytics_bp.route("/insights")
def insights_page():
    return render_template("insights.html")


@analytics_bp.route("/api/analytics")
def api_analytics():
    records = database.get_all_records()
    return jsonify(analyze_all(records, need_hours=_need_hours_setting()))
