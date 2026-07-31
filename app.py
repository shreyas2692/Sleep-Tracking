import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge

from database import (
    SERIES_RANGES,
    add_record,
    add_records,
    check_database,
    clear_all_records,
    delete_record,
    export_data,
    get_all_records,
    get_best_worst_nights,
    get_consistency_score,
    get_day_of_week_stats,
    get_monthly_trend,
    get_records,
    get_series,
    get_setting,
    get_stats,
    get_streak,
    get_today,
    get_weekly_averages,
    set_setting,
    update_record,
    upsert_wearable_records,
)
from ai_summary import generate_summary, summary_available
from importers import parse_apple_health, parse_fitbit_takeout

MAX_NOTES_LEN = 500
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 10_000
MAX_INGEST_BYTES = 1024 * 1024
MAX_INGEST_RECORDS = 100
MAX_RECORD_LIMIT = 10_000
MAX_WEARABLE_BYTES = 1024 * 1024 * 1024  # 1 GiB (Apple Health exports are huge)
WEARABLE_MULTIPART_SLACK = 4 * 1024 * 1024
INGEST_SOURCES = frozenset({"apple_health", "fitbit"})
STAGE_KEYS = frozenset({"deep", "rem", "light", "awake"})
ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
# (deep+rem)/total-stage-minutes fraction → provisional quality 1–5.
QUALITY_THRESHOLDS = ((0.35, 5), (0.28, 4), (0.20, 3), (0.12, 2))
CSV_HEADER = ["date", "bedtime", "wake", "quality", "notes", "hours"]
INVALID_INPUT_MSG = "Invalid input. Use YYYY-MM-DD for date and HH:MM for times."

DATE_RE = re.compile(
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$"
)
TIME_RE = re.compile(r"^(0[0-9]|1[0-9]|2[0-3]):[0-5][0-9]$")


def _env_truthy(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SECRET_KEY=os.environ.get("SECRET_KEY", "sleep-tracker-dev-key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_env_truthy("SESSION_COOKIE_SECURE"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# Reachable without credentials: health probe, the login flow itself (a
# stale session must still be able to log out), and static assets.
AUTH_EXEMPT_ENDPOINTS = frozenset({"healthz", "login", "logout", "static"})


def _is_ajax():
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _json_error(message, status=400):
    return jsonify(error=message), status


def _is_exact_date(value):
    if not DATE_RE.fullmatch(value):
        return False
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False


def _parse_record_values(date_value, bedtime, wake, quality, notes=""):
    date_value = str(date_value or "").strip()
    bedtime = str(bedtime or "").strip()
    wake = str(wake or "").strip()
    quality = str(quality or "").strip()
    notes = str(notes or "")

    if not _is_exact_date(date_value):
        return None, "Invalid date. Use YYYY-MM-DD."
    if datetime.strptime(date_value, "%Y-%m-%d").date() > get_today():
        return None, "Date cannot be in the future."
    if not TIME_RE.fullmatch(bedtime):
        return None, "Invalid bedtime. Use HH:MM."
    if not TIME_RE.fullmatch(wake):
        return None, "Invalid wake time. Use HH:MM."
    if not re.fullmatch(r"[1-5]", quality):
        return None, "Quality must be an integer from 1 to 5."
    if len(notes) > MAX_NOTES_LEN:
        return None, f"Notes must be {MAX_NOTES_LEN} characters or fewer."

    return {
        "date": date_value,
        "bedtime": bedtime,
        "wake": wake,
        "quality": int(quality),
        "notes": notes,
    }, None


def _parse_record_form(form):
    required = ("date", "bedtime", "wake", "quality")
    if any(form.get(field) in (None, "") for field in required):
        return None, INVALID_INPUT_MSG
    return _parse_record_values(
        form.get("date"),
        form.get("bedtime"),
        form.get("wake"),
        form.get("quality"),
        form.get("notes", ""),
    )


def _state_json():
    return jsonify(ok=True, records=get_records(limit=30), stats=get_stats())


def _spreadsheet_formula_risk(note):
    if not note:
        return False
    stripped = note.lstrip(" \t\r\n")
    return note[0] in "\t\r\n" or (
        bool(stripped) and stripped[0] in {"=", "+", "-", "@"}
    )


def _escape_csv_note(note):
    note = str(note or "")
    if note.startswith("'") or _spreadsheet_formula_risk(note):
        return "'" + note
    return note


def _unescape_csv_note(note):
    if note.startswith("'"):
        remainder = note[1:]
        if remainder.startswith("'") or _spreadsheet_formula_risk(remainder):
            return remainder
    return note


@app.before_request
def relax_wearable_upload_limit():
    """Apply endpoint-specific request limits.

    JSON sync is capped at 1 MiB. Wearable multipart uploads allow ~1 GiB and
    Werkzeug spools their file parts to a temp file. Every other route keeps
    the global 2 MiB MAX_CONTENT_LENGTH bound.
    """
    if request.endpoint == "api_ingest":
        request.max_content_length = MAX_INGEST_BYTES
    elif request.endpoint == "import_wearable":
        request.max_content_length = MAX_WEARABLE_BYTES + WEARABLE_MULTIPART_SLACK


def _credentials_match(username, password):
    """Constant-time check against SLEEP_USERNAME/SLEEP_PASSWORD.

    Compares UTF-8 bytes: hmac.compare_digest raises on non-ASCII str, and
    login form input is arbitrary user text.
    """
    expected_user = os.environ.get("SLEEP_USERNAME", "sleep")
    expected_pass = os.environ.get("SLEEP_PASSWORD", "")
    user_ok = hmac.compare_digest(
        str(username or "").encode("utf-8"), expected_user.encode("utf-8")
    )
    pass_ok = hmac.compare_digest(
        str(password or "").encode("utf-8"), expected_pass.encode("utf-8")
    )
    return user_ok and pass_ok


def _basic_auth_ok():
    auth = request.authorization
    return auth is not None and _credentials_match(auth.username, auth.password)


def _safe_next_target(value):
    """Return value only if it is a same-site path; otherwise "/".

    Rejects protocol-relative ("//host"), scheme-carrying, and
    backslash-tricked targets so /login cannot open-redirect.
    """
    value = str(value or "")
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return "/"
    return value


@app.before_request
def protect_private_routes():
    if request.endpoint == "healthz":
        return None

    password = os.environ.get("SLEEP_PASSWORD", "")
    if (
        password
        and request.endpoint not in AUTH_EXEMPT_ENDPOINTS
        and not session.get("authed")
        and not _basic_auth_ok()
    ):
        # Browser navigations get the branded login page; API clients
        # (curl, Shortcuts, the iOS app) keep the Basic challenge.
        if request.method == "GET" and "text/html" in request.headers.get(
            "Accept", ""
        ):
            return redirect(url_for("login", next=request.path))
        return Response(
            "Authentication required.\n",
            401,
            {"WWW-Authenticate": 'Basic realm="Sleep Tracker", charset="UTF-8"'},
            mimetype="text/plain",
        )

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site == "cross-site":
            return _json_error("Cross-site request rejected.", 403)
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            return _json_error("Cross-site request rejected.", 403)
        # Header-less mutations (curl, Shortcuts, Health Auto Export) carry no
        # Origin/Sec-Fetch-Site, so the checks above cannot vouch for them.
        # Accept them only from loopback or when a password gated the request
        # above; otherwise an exposed instance would let any reachable client
        # write or wipe data anonymously.
        if not origin and not fetch_site and not password:
            if request.remote_addr not in {"127.0.0.1", "::1", "localhost"}:
                return _json_error(
                    "Set SLEEP_PASSWORD to allow remote changes.", 403
                )
    return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return _json_error("Request too large.", 413)


@app.route("/healthz")
def healthz():
    try:
        check_database()
    except Exception:
        return jsonify(ok=False), 503
    return jsonify(ok=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    if not os.environ.get("SLEEP_PASSWORD", "") or session.get("authed"):
        return redirect(url_for("index"))

    next_target = _safe_next_target(
        request.form.get("next") or request.args.get("next")
    )
    if request.method == "POST":
        if _credentials_match(
            request.form.get("username"), request.form.get("password")
        ):
            session.clear()
            session["authed"] = True
            session.permanent = True
            return redirect(next_target)
        return (
            render_template(
                "login.html",
                error="Wrong username or password.",
                next_target=next_target,
            ),
            401,
        )
    return render_template("login.html", error=None, next_target=next_target)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.context_processor
def inject_auth_state():
    return {"session_authed": bool(session.get("authed"))}


@app.route("/")
def index():
    today = get_today().isoformat()
    return render_template(
        "index.html",
        records=get_records(limit=30),
        stats=get_stats(),
        today=today,
    )


@app.route("/add", methods=["POST"])
def add():
    fields, error = _parse_record_form(request.form)
    if error:
        if _is_ajax():
            return _json_error(error)
        flash(error, "error")
        return redirect(url_for("index"))

    add_record(
        fields["date"],
        fields["bedtime"],
        fields["wake"],
        fields["quality"],
        fields["notes"],
    )
    if _is_ajax():
        return _state_json()
    flash("Sleep record saved!", "success")
    return redirect(url_for("index"))


@app.route("/edit/<int:record_id>", methods=["POST"])
def edit(record_id):
    fields, error = _parse_record_form(request.form)
    if error:
        return _json_error(error)
    updated = update_record(
        record_id,
        fields["date"],
        fields["bedtime"],
        fields["wake"],
        fields["quality"],
        fields["notes"],
    )
    if not updated:
        return _json_error("Record not found.", 404)
    return _state_json()


@app.route("/delete/<int:record_id>", methods=["POST"])
def delete(record_id):
    delete_record(record_id)
    if _is_ajax():
        return _state_json()
    flash("Record deleted.", "success")
    return redirect(url_for("index"))


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


def _sleep_interval_minutes(bedtime, wake):
    bed_hour, bed_minute = (int(part) for part in bedtime.split(":"))
    wake_hour, wake_minute = (int(part) for part in wake.split(":"))
    return (
        (wake_hour * 60 + wake_minute) - (bed_hour * 60 + bed_minute)
    ) % (24 * 60)


def _reject_json_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def _parse_ingest_record(record):
    if not isinstance(record, dict):
        return None, "Record must be a JSON object."

    missing = [
        field
        for field in ("date", "bedtime", "wake")
        if field not in record or record[field] is None
    ]
    if missing:
        return None, "Missing required field(s): " + ", ".join(missing) + "."

    notes = record.get("notes", "")
    if not isinstance(notes, str):
        return None, "Notes must be a string."

    source = record.get("source", "apple_health")
    if not isinstance(source, str) or source not in INGEST_SOURCES:
        return None, "Source must be apple_health or fitbit."

    stages = record.get("stages")
    if stages is not None:
        if not isinstance(stages, dict) or set(stages) != STAGE_KEYS:
            return (
                None,
                "Stages must contain exactly deep, rem, light, and awake.",
            )
        for name in ("deep", "rem", "light", "awake"):
            value = stages[name]
            if type(value) is not int or value < 0:
                return None, f"Stage {name} must be a nonnegative integer."

    quality = record.get("quality")
    if quality is None:
        quality = derive_quality(stages)
    elif type(quality) is not int or not 1 <= quality <= 5:
        return None, "Quality must be an integer from 1 to 5."

    fields, error = _parse_record_values(
        record["date"],
        record["bedtime"],
        record["wake"],
        quality,
        notes,
    )
    if error:
        return None, error

    if stages is not None:
        interval_minutes = _sleep_interval_minutes(
            fields["bedtime"], fields["wake"]
        )
        stage_minutes = sum(stages.values())
        if abs(stage_minutes - interval_minutes) > 1:
            return (
                None,
                f"Stage minutes total {stage_minutes}; expected "
                f"{interval_minutes} for the sleep interval.",
            )

    efficiency = record.get("efficiency")
    if efficiency is not None:
        if (
            type(efficiency) not in (int, float)
            or (type(efficiency) is float and not math.isfinite(efficiency))
            or not 0 <= efficiency <= 100
        ):
            return None, "Efficiency must be a finite number from 0 to 100."
        efficiency = float(efficiency)

    return {
        **fields,
        "source": source,
        "stages": stages,
        "efficiency": efficiency,
    }, None


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    if request.mimetype != "application/json":
        return _json_error("Content-Type must be application/json.", 415)

    # The per-route max_content_length set in before_request bounds streamed
    # and chunked bodies as they are read, including requests with no
    # Content-Length header.
    raw = request.get_data(cache=False)
    if len(raw) > MAX_INGEST_BYTES:
        raise RequestEntityTooLarge()
    try:
        payload = json.loads(
            raw,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _json_error("Malformed JSON.")

    if isinstance(payload, dict):
        records = [payload]
    elif isinstance(payload, list):
        if not payload:
            return _json_error("Payload array must not be empty.")
        if len(payload) > MAX_INGEST_RECORDS:
            return _json_error(
                f"Payload may contain at most {MAX_INGEST_RECORDS} records."
            )
        records = payload
    else:
        return _json_error("Payload must be a JSON object or array.")

    accepted = []
    errors = []
    for index, record in enumerate(records):
        parsed, error = _parse_ingest_record(record)
        if error:
            errors.append({"index": index, "error": error})
        else:
            accepted.append(parsed)

    imported = replaced = 0
    if accepted:
        imported, replaced = upsert_wearable_records(accepted)

    body = {
        "ok": bool(accepted),
        "imported": imported,
        "replaced": replaced,
        "skipped": len(errors),
        "stats": get_stats(),
    }
    if errors:
        body["errors"] = errors
    return jsonify(body), (200 if accepted else 400)


@app.route("/api/records")
def api_records():
    raw_limit = request.args.get("limit", "30")
    if not re.fullmatch(r"[0-9]+", raw_limit):
        return _json_error(f"limit must be between 1 and {MAX_RECORD_LIMIT}.")
    limit = int(raw_limit)
    if not 1 <= limit <= MAX_RECORD_LIMIT:
        return _json_error(f"limit must be between 1 and {MAX_RECORD_LIMIT}.")
    return jsonify(get_records(limit=limit))


@app.route("/api/insights")
def api_insights():
    return jsonify(
        {
            "stats": get_stats(),
            "streak": get_streak(),
            "consistency": get_consistency_score(),
            "weekly": get_weekly_averages(12),
            "day_of_week": get_day_of_week_stats(),
            "best_worst": get_best_worst_nights(5),
            "monthly": get_monthly_trend(6),
        }
    )


@app.route("/api/summary")
def api_summary():
    """Claude-written weekly narrative. Cached until data changes or a new day."""
    if not summary_available():
        return jsonify({"available": False, "summary": None})

    stats = get_stats()
    if stats["total"] < 7:
        return jsonify({"available": True, "summary": None, "reason": "not_enough_data"})

    digest = {
        "today": str(get_today()),
        "total_nights": stats["total"],
        "avg_hours": stats["avg_hours"],
        "avg_quality": stats["avg_quality"],
        "current_streak": stats["current_streak"],
        "sleep_debt": stats.get("sleep_debt"),
        "consistency_0_100": get_consistency_score(),
        "weekly_averages": get_weekly_averages(12),
        "day_of_week": get_day_of_week_stats(),
    }
    digest_json = json.dumps(digest, sort_keys=True)
    fingerprint = f"{str(get_today())}:{hashlib.sha256(digest_json.encode()).hexdigest()[:16]}"

    if get_setting("ai_summary_fingerprint", "") == fingerprint:
        cached = get_setting("ai_summary_text", "")
        if cached:
            return jsonify({"available": True, "summary": cached, "cached": True})

    try:
        summary = generate_summary(digest_json)
    except Exception as exc:  # network / auth / rate limit
        return jsonify({"available": True, "summary": None, "error": str(exc)}), 502
    if not summary:
        return jsonify({"available": True, "summary": None, "reason": "declined"}), 502

    set_setting("ai_summary_text", summary)
    set_setting("ai_summary_fingerprint", fingerprint)
    return jsonify({"available": True, "summary": summary, "cached": False})


@app.route("/api/export")
def api_export():
    return jsonify(export_data())


@app.route("/export.csv")
def export_csv():
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    for record in get_all_records():
        writer.writerow(
            [
                record["date"],
                record["bedtime"],
                record["wake"],
                record["quality"],
                _escape_csv_note(record["notes"]),
                record["hours"],
            ]
        )
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=sleep-records.csv",
        },
    )


@app.route("/import", methods=["POST"])
def import_csv():
    uploaded = request.files.get("file")
    if uploaded is None:
        return _json_error("No file provided. Upload a CSV file with key 'file'.")
    if not uploaded.filename or not uploaded.filename.lower().endswith(".csv"):
        return _json_error("A .csv file is required.")

    raw = uploaded.stream.read(MAX_CSV_BYTES + 1)
    if not raw:
        return _json_error("CSV file is empty.")
    if len(raw) > MAX_CSV_BYTES:
        return _json_error("CSV file is too large. Maximum size is 1 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return _json_error("CSV must be UTF-8 encoded.")

    parsed = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader, None)
        if header is None:
            return _json_error("CSV file is empty.")
        normalized_header = [column.strip().lower() for column in header]
        if normalized_header != CSV_HEADER:
            return _json_error(
                "Invalid CSV header. Expected " + ",".join(CSV_HEADER) + "."
            )

        for line_number, row in enumerate(reader, start=2):
            if line_number > MAX_CSV_ROWS + 1:
                return _json_error(
                    f"CSV has too many rows. Maximum is {MAX_CSV_ROWS}."
                )
            if len(row) != len(CSV_HEADER):
                return _json_error(
                    f"Row {line_number}: expected {len(CSV_HEADER)} columns, "
                    f"got {len(row)}."
                )
            fields, error = _parse_record_values(
                row[0], row[1], row[2], row[3], _unescape_csv_note(row[4])
            )
            if error:
                return _json_error(f"Row {line_number}: {error}")
            parsed.append(fields)
    except csv.Error as exc:
        return _json_error(f"Malformed CSV: {exc}.")

    if not parsed:
        return _json_error("CSV has a header but no data rows.")

    add_records(parsed)
    return _state_json()


def derive_quality(stages):
    """Provisional 1–5 quality from stage composition.

    (deep+rem)/total-stage-minutes: ≥.35→5, ≥.28→4, ≥.20→3, ≥.12→2, else 1.
    Nights without stage data (or zero total minutes) get a neutral 3.
    """
    if not stages:
        return 3
    total = sum(stages.values())
    if total <= 0:
        return 3
    fraction = (stages["deep"] + stages["rem"]) / total
    for threshold, quality in QUALITY_THRESHOLDS:
        if fraction >= threshold:
            return quality
    return 1


def _sniff_wearable_parser(stream):
    """Pick parser(s) to try from the upload's leading bytes.

    zip magic or an XML declaration → Apple Health first (falling back to
    Fitbit for zips, which may be a Takeout archive of sleep-*.json files);
    JSON array/object → Fitbit Takeout. Returns a list of parsers, or [].
    """
    stream.seek(0)
    head = stream.read(64)
    stream.seek(0)
    if head[:4] in ZIP_MAGICS:
        return [parse_apple_health, parse_fitbit_takeout]
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"<"):
        return [parse_apple_health]
    if stripped[:1] in (b"[", b"{"):
        return [parse_fitbit_takeout]
    return []


@app.route("/import/wearable", methods=["POST"])
def import_wearable():
    uploaded = request.files.get("file")
    if uploaded is None:
        return _json_error(
            "No file provided. Upload a wearable export with key 'file'."
        )

    # Werkzeug has already streamed the part to a spooled temp file; the
    # stream is seekable and never fully resident in memory.
    stream = uploaded.stream
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size == 0:
        return _json_error("Uploaded file is empty.")
    if size > MAX_WEARABLE_BYTES:
        return _json_error("File is too large. Maximum size is 1 GiB.")

    parsers = _sniff_wearable_parser(stream)
    if not parsers:
        return _json_error(
            "Unrecognized file format. Upload an Apple Health export.zip/"
            "export.xml or a Fitbit Google Takeout sleep JSON/zip."
        )

    nights = None
    errors = []
    for parser in parsers:
        stream.seek(0)
        try:
            nights = parser(stream)
            break
        except ValueError as exc:
            errors.append(str(exc))
    if nights is None:
        return _json_error("Could not parse wearable export: " + "; ".join(errors))

    today = get_today()
    skipped = 0
    accepted = []
    for night in nights:
        # Wearable exports are historical: skip (don't reject) future nights.
        if datetime.strptime(night["date"], "%Y-%m-%d").date() > today:
            skipped += 1
            continue
        night["quality"] = derive_quality(night["stages"])
        night["notes"] = night.get("notes", "")[:MAX_NOTES_LEN]
        accepted.append(night)

    imported, replaced = upsert_wearable_records(accepted)
    return jsonify(
        ok=True,
        imported=imported,
        replaced=replaced,
        skipped=skipped,
        records=get_records(limit=30),
        stats=get_stats(),
    )


@app.route("/api/series")
def api_series():
    range_key = request.args.get("range", "30d")
    if range_key not in SERIES_RANGES:
        return _json_error(
            "range must be one of: " + ", ".join(sorted(SERIES_RANGES)) + "."
        )
    return jsonify(get_series(range_key))


@app.route("/settings/update", methods=["POST"])
def update_settings():
    goal = request.form.get("sleep_goal", "").strip()
    bedtime = request.form.get("bedtime_goal", "").strip()
    updates = {}

    if goal:
        try:
            numeric_goal = float(goal)
        except ValueError:
            numeric_goal = math.nan
        if not math.isfinite(numeric_goal) or not 0 < numeric_goal <= 24:
            flash("Sleep goal must be a number between 0 and 24.", "error")
            return redirect(url_for("index"))
        updates["sleep_goal"] = str(numeric_goal)

    if bedtime:
        if not TIME_RE.fullmatch(bedtime):
            flash("Bedtime goal must use HH:MM.", "error")
            return redirect(url_for("index"))
        updates["bedtime_goal"] = bedtime

    for key, value in updates.items():
        set_setting(key, value)
    flash("Settings saved!", "success")
    return redirect(url_for("index"))


@app.route("/settings/clear", methods=["POST"])
def clear_data():
    clear_all_records()
    flash("All records cleared.", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port, debug=debug)
