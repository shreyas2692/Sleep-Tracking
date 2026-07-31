import csv
import hmac
import io
import math
import os
import re
from datetime import datetime
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
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
    get_stats,
    get_streak,
    get_today,
    get_weekly_averages,
    set_setting,
    update_record,
    upsert_wearable_records,
)
from importers import parse_apple_health, parse_fitbit_takeout

MAX_NOTES_LEN = 500
MAX_CSV_BYTES = 1024 * 1024
MAX_CSV_ROWS = 10_000
MAX_RECORD_LIMIT = 10_000
MAX_WEARABLE_BYTES = 1024 * 1024 * 1024  # 1 GiB (Apple Health exports are huge)
WEARABLE_MULTIPART_SLACK = 4 * 1024 * 1024
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
)


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
    """Allow up to ~1 GiB for /import/wearable only.

    Every other route keeps the global 2 MiB MAX_CONTENT_LENGTH bound.
    Werkzeug enforces this while parsing and spools multipart file parts to a
    temp file (memory use stays bounded regardless of upload size).
    """
    if request.endpoint == "import_wearable":
        request.max_content_length = MAX_WEARABLE_BYTES + WEARABLE_MULTIPART_SLACK


@app.before_request
def protect_private_routes():
    if request.endpoint == "healthz":
        return None

    password = os.environ.get("SLEEP_PASSWORD", "")
    if password:
        auth = request.authorization
        username = os.environ.get("SLEEP_USERNAME", "sleep")
        if (
            auth is None
            or not hmac.compare_digest(auth.username or "", username)
            or not hmac.compare_digest(auth.password or "", password)
        ):
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

# ------------------------------------------------------------
# JSON ingest endpoint for automated sync (Apple Shortcuts, etc.)
# ------------------------------------------------------------
@app.route('/api/ingest', methods=['POST'])
def api_ingest():
    # Ensure request is JSON
    if not request.is_json:
        return _json_error('Invalid content type, expected application/json')

    # Enforce payload size limit (1 MiB)
    max_bytes = 1024 * 1024
    if request.content_length is not None and request.content_length > max_bytes:
        return _json_error('Payload too large')

    try:
        payload = request.get_json()
    except Exception:
        return _json_error('Malformed JSON')

    # Normalize to list of records
    records = payload if isinstance(payload, list) else [payload]
    if len(records) > 100:
        return _json_error('Too many records (max 100)')

    imported = replaced = skipped = 0
    errors = []
    accepted = []

    for idx, rec in enumerate(records):
        # Required fields check
        missing = [k for k in ('date', 'bedtime', 'wake') if k not in rec]
        if missing:
            errors.append({"index": idx, "error": f"Missing field(s) {', '.join(missing)}"})
            continue

        # Validate core fields using existing helper (returns parsed dict or None + error)
        parsed, err = _parse_record_values(
            rec['date'], rec['bedtime'], rec['wake'], rec.get('quality'), rec.get('notes', '')
        )
        if not parsed:
            errors.append({"index": idx, "error": err})
            continue

        source = rec.get('source') or 'apple_health'
        stages = rec.get('stages')
        efficiency = rec.get('efficiency')
        quality = parsed.get('quality')
        if not quality and stages:
            try:
                quality = derive_quality(stages)
            except Exception as e:
                errors.append({"index": idx, "error": f"Quality derivation failed: {e}"})
                continue

        # Build a night dict matching the shape expected by ``upsert_wearable_records``.
        record_dict = {
            'date': parsed['date'],
            'bedtime': parsed['bedtime'],
            # The DB column is ``wake_time``, but the upsert helper expects the key ``wake``.
            'wake': parsed['wake'],
            'quality': int(quality) if quality else None,
            'notes': parsed.get('notes', ''),
            'source': source,
            # Stage minutes – may be omitted (None) when not provided.
            'deep_minutes': stages.get('deep') if stages else None,
            'rem_minutes': stages.get('rem') if stages else None,
            'light_minutes': stages.get('light') if stages else None,
            'awake_minutes': stages.get('awake') if stages else None,
            # Efficiency is a float between 0‑100 or ``None``.
            'efficiency': float(efficiency) if efficiency is not None else None,
        }
        accepted.append(record_dict)

    if accepted:
        imp, rep = upsert_wearable_records(accepted)
        imported += imp
        replaced += rep

    stats = get_stats()
    resp = {
        'ok': True,
        'imported': imported,
        'replaced': replaced,
        'skipped': skipped,
        'stats': stats,
    }
    if errors:
        resp['errors'] = errors
    return jsonify(resp)


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
