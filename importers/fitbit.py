"""Parser for Fitbit Google Takeout sleep exports.

Accepts a single ``sleep-YYYY-MM-DD.json`` file (a JSON array of sleep-log
objects), a zip archive containing any number of such files, or an
already-decoded Python list of log dicts. Returns normalized night dicts
(see importers.__init__), one per calendar night, sorted ascending.

Mapping: date = dateOfSleep, bedtime/wake = HH:MM of startTime/endTime,
efficiency = float(efficiency). Stages come from ``levels.summary`` for
"stages"-type logs (wake -> awake); "classic"-type logs (asleep/restless/
awake summary) get ``stages: None``.

The longest ``mainSleep: true`` log (or longest log when none is marked main)
provides the public night summary. Other same-date logs are retained as
private sessions for nap-inclusive accounting. Duplicate logIds (overlapping
export files in a zip) are de-duplicated.
"""

import json
import math
import re
import zipfile
from datetime import datetime

from importers._common import (
    fmt_minutes,
    is_zip,
    open_binary,
    open_zip,
    read_limited,
    require_stream_size,
    validate_zip_member,
    zip_infos,
)

STAGE_KEYS = ("deep", "rem", "light", "wake")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?$"
)
SLEEP_JSON_RE = re.compile(r"^sleep(?:-[^/]+)?\.json$")

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_JSON_MEMBER_BYTES = 64 * 1024 * 1024
MAX_TOTAL_JSON_BYTES = 256 * 1024 * 1024
MAX_SLEEP_LOGS = 100_000
MAX_NORMALIZED_NIGHTS = 20_000
MAX_NIGHT_SECONDS = 36 * 60 * 60
MAX_DURATION_DISCREPANCY_SECONDS = 2 * 60 * 60
MAX_STAGE_MINUTES = 36 * 60
INVALID = object()


def parse_fitbit_takeout(file_or_path):
    """Parse Fitbit Takeout sleep JSON (file, zip, or decoded list) to nights.

    Raises ValueError for unreadable input or when no usable sleep logs exist.
    """
    try:
        logs = _load_logs(file_or_path)
    except ValueError:
        raise
    except (
        EOFError,
        NotImplementedError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise ValueError(f"unable to read Fitbit export: {exc}") from exc

    parsed = []
    seen_ids = {}
    seen_unidentified = set()
    for log in logs:
        night = _parse_log(log)
        if night is None:
            continue  # malformed log: skip, don't raise
        log_id = night.pop("_log_id")
        if log_id is not None:
            previous = seen_ids.get(log_id)
            if previous is not None:
                if previous != night:
                    raise ValueError(
                        f"conflicting Fitbit sleep logs share logId {log_id!r}"
                    )
                continue
            seen_ids[log_id] = night
        else:
            signature = _log_signature(night)
            if signature in seen_unidentified:
                continue
            seen_unidentified.add(signature)
        parsed.append(night)

    if not parsed:
        raise ValueError("no sleep logs found in Fitbit export")

    by_date = {}
    for night in parsed:
        by_date.setdefault(night["date"], []).append(night)

    nights = []
    for date in sorted(by_date):
        candidates = by_date[date]
        mains = [n for n in candidates if n["_main"]]
        keep = mains if mains else candidates
        best = max(keep, key=lambda n: n["_elapsed"])
        result = {
            key: value
            for key, value in best.items()
            if not key.startswith("_")
        }
        result["_sessions"] = [
            _session_payload(candidate, main=candidate is best)
            for candidate in sorted(
                candidates,
                key=lambda item: (
                    item["_start"].replace(tzinfo=None),
                    item["_end"].replace(tzinfo=None),
                ),
            )
        ]
        nights.append(result)
        if len(nights) > MAX_NORMALIZED_NIGHTS:
            raise ValueError("Fitbit export contains too many sleep nights")
    return nights


def _log_signature(night):
    stages = night["stages"]
    return (
        night["date"],
        night["_start"].isoformat(),
        night["_end"].isoformat(),
        night["_duration"],
        night["_elapsed"],
        night["_main"],
        night["efficiency"],
        tuple(sorted(stages.items())) if stages is not None else None,
    )


def _session_payload(night, main):
    start = night["_start"]
    end = night["_end"]
    aware = start.tzinfo is not None and start.utcoffset() is not None
    return {
        "start_local": start.replace(tzinfo=None).isoformat(timespec="seconds"),
        "end_local": end.replace(tzinfo=None).isoformat(timespec="seconds"),
        "start_utc": int(round(start.timestamp())) if aware else None,
        "end_utc": int(round(end.timestamp())) if aware else None,
        "elapsed_seconds": int(round(night["_elapsed"])),
        "main": main,
    }


def _load_logs(file_or_path):
    """Return the raw list of sleep-log dicts from any accepted input form."""
    if isinstance(file_or_path, list):
        if len(file_or_path) > MAX_SLEEP_LOGS:
            raise ValueError("Fitbit export contains too many sleep logs")
        return file_or_path

    with open_binary(file_or_path) as stream:
        require_stream_size(stream, MAX_INPUT_BYTES, "Fitbit input")
        if is_zip(stream):
            with open_zip(stream) as zf:
                logs = []
                total_json_bytes = 0
                members = []
                for info in zip_infos(zf):
                    base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                    if info.is_dir() or not SLEEP_JSON_RE.fullmatch(base):
                        continue
                    validate_zip_member(
                        info, MAX_JSON_MEMBER_BYTES, f"Fitbit member {info.filename}"
                    )
                    total_json_bytes += info.file_size
                    if total_json_bytes > MAX_TOTAL_JSON_BYTES:
                        raise ValueError(
                            "Fitbit sleep JSON exceeds the total uncompressed-size limit"
                        )
                    members.append(info)
                if not members:
                    raise ValueError("no sleep-*.json files found in zip archive")

                for info in sorted(members, key=lambda item: item.filename):
                    try:
                        with zf.open(info) as member_stream:
                            raw = read_limited(
                                member_stream,
                                MAX_JSON_MEMBER_BYTES,
                                f"Fitbit member {info.filename}",
                            )
                    except (
                        EOFError,
                        NotImplementedError,
                        OSError,
                        RuntimeError,
                        zipfile.BadZipFile,
                    ) as exc:
                        raise ValueError(
                            f"unable to read Fitbit member {info.filename}: {exc}"
                        ) from exc
                    data = _decode_json(raw, f"Fitbit member {info.filename}")
                    if not isinstance(data, list):
                        raise ValueError(
                            f"Fitbit member {info.filename} must contain a JSON array"
                        )
                    if len(logs) + len(data) > MAX_SLEEP_LOGS:
                        raise ValueError("Fitbit export contains too many sleep logs")
                    logs.extend(data)
                if not logs:
                    raise ValueError("Fitbit sleep JSON files contain no logs")
                return logs
        raw = read_limited(stream, MAX_JSON_MEMBER_BYTES, "Fitbit sleep JSON")

    data = _decode_json(raw, "Fitbit sleep JSON")
    if not isinstance(data, list):
        raise ValueError("Fitbit sleep export must be a JSON array of sleep logs")
    if len(data) > MAX_SLEEP_LOGS:
        raise ValueError("Fitbit export contains too many sleep logs")
    return data


def _decode_json(raw, label):
    """Decode strict JSON, including rejection of NaN and Infinity."""
    def reject_constant(value):
        raise ValueError(f"non-finite JSON number {value}")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"not valid {label}: {exc}") from exc


def _parse_log(log):
    """One Fitbit sleep-log dict -> internal night dict, or None if malformed."""
    if not isinstance(log, dict):
        return None
    date = _parse_date(log.get("dateOfSleep"))
    start_dt = _parse_timestamp(log.get("startTime"))
    end_dt = _parse_timestamp(log.get("endTime"))
    if date is None or start_dt is None or end_dt is None:
        return None
    start_aware = start_dt.tzinfo is not None and start_dt.utcoffset() is not None
    end_aware = end_dt.tzinfo is not None and end_dt.utcoffset() is not None
    if start_aware != end_aware or end_dt <= start_dt:
        return None
    elapsed_seconds = (end_dt - start_dt).total_seconds()
    if not (0 < elapsed_seconds <= MAX_NIGHT_SECONDS):
        return None
    if end_dt.date().isoformat() != date:
        return None

    efficiency = log.get("efficiency")
    if efficiency is not None:
        if not _finite_number(efficiency) or not (0 <= efficiency <= 100):
            return None
        efficiency = float(efficiency)

    duration = _parse_duration(log.get("duration"), elapsed_seconds)
    if duration is None:
        return None

    stages = _parse_stages(log, duration)
    if stages is INVALID:
        return None
    if stages is not None:
        notes = (
            f"Imported from Fitbit "
            f"({fmt_minutes(stages['deep'])} deep, {fmt_minutes(stages['rem'])} REM)"
        )
    else:
        notes = "Imported from Fitbit"

    if "mainSleep" in log:
        main = log["mainSleep"]
    elif "isMainSleep" in log:
        main = log["isMainSleep"]
    else:
        main = True
    if type(main) is not bool:
        return None

    log_id = _normalize_log_id(log.get("logId"))
    if log_id is INVALID:
        return None

    return {
        "date": date,
        "bedtime": start_dt.strftime("%H:%M"),
        "wake": end_dt.strftime("%H:%M"),
        "source": "fitbit",
        "stages": stages,
        "efficiency": efficiency,
        "notes": notes,
        "_main": main,
        "_duration": duration,
        "_elapsed": elapsed_seconds,
        "_start": start_dt,
        "_end": end_dt,
        "_log_id": log_id,
    }


def _parse_stages(log, duration_seconds):
    """levels.summary -> stages dict for stages-type logs, else None."""
    levels = log.get("levels")
    if not isinstance(levels, dict):
        return None
    summary = levels.get("summary")
    if not isinstance(summary, dict):
        return None
    if not all(key in summary for key in STAGE_KEYS):
        if any(key in summary for key in STAGE_KEYS):
            return INVALID
        return None  # classic-type (asleep/restless/awake) or partial data
    stages = {}
    for key in STAGE_KEYS:
        entry = summary[key]
        minutes = entry.get("minutes") if isinstance(entry, dict) else None
        if (
            not _finite_number(minutes)
            or minutes < 0
            or minutes > MAX_STAGE_MINUTES
            or not float(minutes).is_integer()
        ):
            return INVALID
        stages["awake" if key == "wake" else key] = int(minutes)
    if sum(stages.values()) > duration_seconds / 60 + 120:
        return INVALID
    return stages


def _parse_timestamp(text):
    """Parse a complete Fitbit local or offset-aware ISO timestamp."""
    if not isinstance(text, str) or not TIMESTAMP_RE.fullmatch(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_date(text):
    if not isinstance(text, str) or not DATE_RE.fullmatch(text):
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    canonical = parsed.isoformat()
    return canonical if canonical == text else None


def _parse_duration(value, elapsed_seconds):
    """Return a bounded duration in seconds, validating Fitbit milliseconds."""
    if value is None:
        return elapsed_seconds
    if not _finite_number(value) or not (0 < value <= MAX_NIGHT_SECONDS * 1000):
        return None
    duration_seconds = float(value) / 1000
    if abs(duration_seconds - elapsed_seconds) > MAX_DURATION_DISCREPANCY_SECONDS:
        return None
    return duration_seconds


def _normalize_log_id(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return INVALID
    normalized = str(value)
    if not normalized or len(normalized) > 128 or normalized.strip() != normalized:
        return INVALID
    return normalized


def _finite_number(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )
