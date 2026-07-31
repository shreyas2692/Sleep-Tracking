"""Parser for Apple Health exports (export.xml / export.zip).

Streams the XML with Expat (exports can be hundreds of MB), keeps only
``HKCategoryTypeIdentifierSleepAnalysis`` records, clusters them into nights
(gap < 4h = same night), de-duplicates overlapping per-stage intervals from
multiple devices, and returns normalized night dicts (see importers.__init__).
Each public night summary also carries private ``_sessions`` metadata so the
database can preserve exact elapsed time and same-date naps.

Stage mapping:
    AsleepDeep -> deep, AsleepREM -> rem, AsleepCore -> light, Awake -> awake.
    InBed and legacy Asleep / AsleepUnspecified records extend the night's
    bedtime/wake span but carry no stage breakdown; a night with only those
    gets ``stages: None``.

Apple never exports an efficiency figure, so ``efficiency`` is always None.
Times are displayed in the local wall-clock time recorded at each endpoint.
Elapsed durations preserve timezone offsets, including daylight-saving changes.

When sources assign different stages to the same instant, precedence is
``awake > deep > rem > light``. This is a deterministic conflict tie-breaker,
not a physiological inference, and prevents overlapping stage minutes.
"""

import zipfile
from datetime import datetime, timedelta
from xml.parsers import expat

from importers._common import (
    READ_CHUNK_SIZE,
    fmt_minutes,
    is_zip,
    merge_intervals,
    open_binary,
    open_zip,
    require_stream_size,
    validate_zip_member,
    zip_infos,
)

SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"

STAGE_BY_VALUE = {
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAsleepCore": "light",
    "HKCategoryValueSleepAnalysisAwake": "awake",
}
# Records that define the night span but have no stage breakdown.
SPAN_ONLY_VALUES = {
    "HKCategoryValueSleepAnalysisInBed",
    "HKCategoryValueSleepAnalysisAsleep",            # legacy (pre-iOS 16)
    "HKCategoryValueSleepAnalysisAsleepUnspecified",  # iOS 16+ non-staged
}

MAX_GAP = timedelta(hours=4)
MIN_NIGHT_DURATION = timedelta(minutes=30)
MAX_NIGHT_DURATION = timedelta(hours=36)
MAX_INPUT_BYTES = 1024 * 1024 * 1024
MAX_SLEEP_RECORDS = 500_000
MAX_NORMALIZED_NIGHTS = 20_000
MAX_XML_DEPTH = 64
STAGE_PRECEDENCE = ("awake", "deep", "rem", "light")


def parse_apple_health(file_or_path):
    """Parse an Apple Health export.xml or export.zip into night records.

    Accepts a filesystem path or a seekable binary file-like object.
    Raises ValueError if the input is unreadable or contains no sleep records.
    """
    try:
        with open_binary(file_or_path) as stream:
            require_stream_size(stream, MAX_INPUT_BYTES, "Apple Health input")
            if is_zip(stream):
                with open_zip(stream) as zf:
                    member = _find_export_xml(zf)
                    validate_zip_member(
                        member, MAX_INPUT_BYTES, "Apple Health export.xml"
                    )
                    with zf.open(member) as xml_stream:
                        records = _collect_sleep_records(xml_stream)
            else:
                records = _collect_sleep_records(stream)
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
        raise ValueError(f"unable to read Apple Health export: {exc}") from exc

    if not records:
        raise ValueError("no sleep records found in Apple Health export")

    nights = _select_main_nights(_cluster_nights(records))
    if not nights:
        raise ValueError("no qualifying sleep nights found in Apple Health export")
    return nights


def _find_export_xml(zf):
    """Locate the single canonical export.xml inside export.zip."""
    matches = []
    for info in zip_infos(zf):
        base = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not info.is_dir() and base == "export.xml":
            matches.append(info)
    if len(matches) > 1:
        raise ValueError("zip archive contains multiple export.xml files")
    if matches:
        return matches[0]
    raise ValueError("no export.xml found inside zip archive")


def _collect_sleep_records(xml_stream):
    """Stream-parse the XML, returning [(start, end, value), ...].

    Malformed Record elements are skipped. XML syntax errors, entity
    declarations, external or unexpected DTDs, excessive nesting, and
    oversized documents fail the entire import. Apple exports include an
    internal HealthData DTD, so inert ELEMENT/ATTLIST declarations are allowed.
    """
    records = []
    parser = expat.ParserCreate()
    depth = 0
    root_seen = False
    total_bytes = 0

    def start_doctype(name, system_id, public_id, _has_internal_subset):
        if name != "HealthData" or system_id is not None or public_id is not None:
            raise ValueError(
                "Apple Health XML contains an external or unsupported DTD"
            )

    def reject_entity_declaration(*_args):
        raise ValueError("Apple Health XML must not contain entity declarations")

    def reject_notation(*_args):
        raise ValueError("Apple Health XML must not contain notation declarations")

    def reject_external_entity(*_args):
        raise ValueError("Apple Health XML must not reference external entities")

    def start_element(name, attrs):
        nonlocal depth, root_seen
        depth += 1
        if depth > MAX_XML_DEPTH:
            raise ValueError(
                f"Apple Health XML exceeds the maximum depth of {MAX_XML_DEPTH}"
            )
        if not root_seen:
            root_seen = True
            if name != "HealthData":
                raise ValueError("Apple Health XML root must be HealthData")
        if name != "Record" or attrs.get("type") != SLEEP_TYPE:
            return
        parsed = _parse_record(attrs)
        if parsed is not None:
            records.append(parsed)
            if len(records) > MAX_SLEEP_RECORDS:
                raise ValueError(
                    "Apple Health export contains too many sleep records"
                )

    def end_element(_name):
        nonlocal depth
        depth -= 1

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.StartDoctypeDeclHandler = start_doctype
    parser.EntityDeclHandler = reject_entity_declaration
    parser.UnparsedEntityDeclHandler = reject_entity_declaration
    parser.NotationDeclHandler = reject_notation
    parser.ExternalEntityRefHandler = reject_external_entity

    try:
        while True:
            chunk = xml_stream.read(READ_CHUNK_SIZE)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise ValueError("Apple Health XML must contain binary data")
            total_bytes += len(chunk)
            if total_bytes > MAX_INPUT_BYTES:
                raise ValueError(
                    f"Apple Health XML exceeds the {MAX_INPUT_BYTES}-byte size limit"
                )
            parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise ValueError(f"not a valid Apple Health XML export: {exc}") from exc
    return records


def _parse_record(elem):
    """One <Record> -> (start_dt, end_dt, value) or None if malformed."""
    value = elem.get("value")
    if value not in STAGE_BY_VALUE and value not in SPAN_ONLY_VALUES:
        return None
    start = _parse_dt(elem.get("startDate"))
    end = _parse_dt(elem.get("endDate"))
    if (
        start is None
        or end is None
        or end <= start
        or end - start > MAX_NIGHT_DURATION
    ):
        return None
    return (start, end, value)


def _parse_dt(text):
    """Parse a complete Apple timestamp while preserving its UTC offset."""
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _cluster_nights(records):
    """Group records into nights: contiguous clusters with gaps < 4 hours."""
    records.sort(key=lambda r: (r[0], r[1]))
    clusters = []
    current = []
    current_end = None
    for rec in records:
        start, end, _ = rec
        if current and start - current_end >= MAX_GAP:
            clusters.append(current)
            current = []
            current_end = None
        current.append(rec)
        current_end = end if current_end is None else max(current_end, end)
    if current:
        clusters.append(current)
    return clusters


def _select_main_nights(clusters):
    """Summarize each wake date while retaining every qualifying session."""
    by_date = {}
    for cluster in clusters:
        bedtime = min(r[0] for r in cluster)
        wake = max(r[1] for r in cluster)
        duration = wake - bedtime
        if not (MIN_NIGHT_DURATION <= duration <= MAX_NIGHT_DURATION):
            continue
        date_str = wake.strftime("%Y-%m-%d")
        by_date.setdefault(date_str, []).append(
            (duration.total_seconds(), bedtime, wake, cluster)
        )
        if len(by_date) > MAX_NORMALIZED_NIGHTS:
            raise ValueError("Apple Health export contains too many sleep nights")

    nights = []
    for date_str in sorted(by_date):
        candidates = by_date[date_str]
        main = max(candidates, key=lambda item: item[0])
        night = _build_night(main[3])
        sessions = []
        for candidate in candidates:
            duration, bedtime, wake, _cluster = candidate
            sessions.append(
                _session_payload(
                    bedtime,
                    wake,
                    elapsed_seconds=duration,
                    main=candidate is main,
                )
            )
        night["_sessions"] = sessions
        nights.append(night)
    return nights


def _session_payload(start, end, elapsed_seconds, main):
    """Private exact interval metadata persisted by the database layer."""
    return {
        "start_local": start.replace(tzinfo=None).isoformat(timespec="seconds"),
        "end_local": end.replace(tzinfo=None).isoformat(timespec="seconds"),
        "start_utc": int(round(start.timestamp())),
        "end_utc": int(round(end.timestamp())),
        "elapsed_seconds": int(round(elapsed_seconds)),
        "main": main,
    }


def _subtract_intervals(intervals, blockers):
    """Remove blockers from intervals; both inputs may overlap internally."""
    result = []
    blockers = merge_intervals(blockers)
    for start, end in merge_intervals(intervals):
        cursor = start
        for block_start, block_end in blockers:
            if block_end <= cursor:
                continue
            if block_start >= end:
                break
            if block_start > cursor:
                result.append((cursor, min(block_start, end)))
            cursor = max(cursor, block_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def _round_stage_minutes(exclusive):
    """Round exclusive stage seconds while conserving their combined total."""
    seconds = {
        stage: sum((end - start).total_seconds() for start, end in intervals)
        for stage, intervals in exclusive.items()
    }
    minutes = {stage: int(value // 60) for stage, value in seconds.items()}
    rounded_total = int(sum(seconds.values()) / 60 + 0.5)
    remaining = rounded_total - sum(minutes.values())
    stage_rank = {stage: index for index, stage in enumerate(STAGE_PRECEDENCE)}
    by_remainder = sorted(
        seconds,
        key=lambda stage: (-(seconds[stage] % 60), stage_rank[stage]),
    )
    for stage in by_remainder[:remaining]:
        minutes[stage] += 1
    return minutes


def _build_night(cluster):
    """One cluster of records -> normalized night dict."""
    bedtime = min(r[0] for r in cluster)
    wake = max(r[1] for r in cluster)

    stage_intervals = {"deep": [], "rem": [], "light": [], "awake": []}
    has_stage_data = False
    for start, end, value in cluster:
        stage = STAGE_BY_VALUE.get(value)
        if stage is not None:
            stage_intervals[stage].append((start, end))
            has_stage_data = True

    if has_stage_data:
        exclusive = {}
        claimed = []
        for stage in STAGE_PRECEDENCE:
            exclusive[stage] = _subtract_intervals(stage_intervals[stage], claimed)
            claimed = merge_intervals(claimed + exclusive[stage])
        stages = _round_stage_minutes(exclusive)
        notes = (
            f"Imported from Apple Health "
            f"({fmt_minutes(stages['deep'])} deep, {fmt_minutes(stages['rem'])} REM)"
        )
    else:
        stages = None
        notes = "Imported from Apple Health"

    return {
        "date": wake.strftime("%Y-%m-%d"),
        "bedtime": bedtime.strftime("%H:%M"),
        "wake": wake.strftime("%H:%M"),
        "source": "apple_health",
        "stages": stages,
        "efficiency": None,
        "notes": notes,
    }
