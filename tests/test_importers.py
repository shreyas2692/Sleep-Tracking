"""Tests for the pure wearable-export parsers in importers/."""

import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

import importers._common as importer_common
import importers.apple_health as apple_health
import importers.fitbit as fitbit
from importers import parse_apple_health, parse_fitbit_takeout

FIXTURES = Path(__file__).parent / "fixtures"

APPLE_XML = FIXTURES / "apple_export.xml"
APPLE_ZIP = FIXTURES / "apple_export.zip"
FITBIT_STAGES = FIXTURES / "fitbit_stages.json"
FITBIT_CLASSIC = FIXTURES / "fitbit_classic.json"
FITBIT_ZIP = FIXTURES / "fitbit_takeout.zip"


def _public_nights(nights):
    """Parser-private session metadata is not part of the public night shape."""
    return [
        {key: value for key, value in night.items() if key != "_sessions"}
        for night in nights
    ]


def _zip_bytes(entries, compression=zipfile.ZIP_STORED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, payload in entries:
            zf.writestr(name, payload)
    return buf.getvalue()


def _corrupt_first_member(payload):
    raw = bytearray(payload)
    name_len, extra_len = struct.unpack_from("<HH", raw, 26)
    raw[30 + name_len + extra_len] ^= 1
    return bytes(raw)


def _mark_first_member_encrypted(payload):
    raw = bytearray(payload)
    local_flags = struct.unpack_from("<H", raw, 6)[0] | 0x1
    struct.pack_into("<H", raw, 6, local_flags)
    central = raw.index(b"PK\x01\x02")
    central_flags = struct.unpack_from("<H", raw, central + 8)[0] | 0x1
    struct.pack_into("<H", raw, central + 8, central_flags)
    return bytes(raw)


def _fitbit_log(**overrides):
    log = json.loads(FITBIT_STAGES.read_text())[0]
    log.update(overrides)
    return log

APPLE_NIGHT_1 = {
    "date": "2023-11-02",
    "bedtime": "23:00",  # earliest record start (the InBed record)
    "wake": "07:00",
    "source": "apple_health",
    # deep: 01:10-02:10 (Watch) overlaps 01:40-02:20 (iPhone) -> merged 70m,
    # not 100m. Legacy Asleep 23:10-07:00 spans the night but adds no stages.
    "stages": {"deep": 70, "rem": 60, "light": 325, "awake": 15},
    "efficiency": None,
    "notes": "Imported from Apple Health (1h10m deep, 1h REM)",
}
APPLE_NIGHT_2 = {
    "date": "2023-11-03",
    "bedtime": "23:30",
    "wake": "06:45",
    "source": "apple_health",
    "stages": {"deep": 45, "rem": 45, "light": 345, "awake": 0},
    "efficiency": None,
    "notes": "Imported from Apple Health (45m deep, 45m REM)",
}

FITBIT_NIGHT_NOV2 = {
    "date": "2023-11-02",
    "bedtime": "23:12",
    "wake": "07:01",
    "source": "fitbit",
    "stages": {"deep": 65, "rem": 88, "light": 250, "awake": 48},
    "efficiency": 93.0,
    "notes": "Imported from Fitbit (1h5m deep, 1h28m REM)",
}
FITBIT_NIGHT_NOV3 = {
    "date": "2023-11-03",
    "bedtime": "23:45",
    "wake": "06:30",
    "source": "fitbit",
    "stages": {"deep": 50, "rem": 70, "light": 260, "awake": 30},
    "efficiency": 90.0,
    "notes": "Imported from Fitbit (50m deep, 1h10m REM)",
}
FITBIT_NIGHT_NOV5 = {
    "date": "2023-11-05",
    "bedtime": "22:50",
    "wake": "06:20",
    "source": "fitbit",
    "stages": None,  # classic-type log: no stage breakdown
    "efficiency": 88.0,
    "notes": "Imported from Fitbit",
}


# ---------------------------------------------------------------- Apple Health

class TestAppleHealth:
    def test_xml_path_exact_nights(self):
        assert _public_nights(parse_apple_health(str(APPLE_XML))) == [
            APPLE_NIGHT_1, APPLE_NIGHT_2,
        ]

    def test_accepts_pathlib_path_and_file_like(self):
        assert _public_nights(parse_apple_health(APPLE_XML)) == [
            APPLE_NIGHT_1, APPLE_NIGHT_2,
        ]
        with open(APPLE_XML, "rb") as f:
            assert _public_nights(parse_apple_health(f)) == [
                APPLE_NIGHT_1, APPLE_NIGHT_2,
            ]

    def test_zip_path_finds_export_xml_not_cda(self):
        # The zip also contains export_cda.xml, which must be skipped.
        assert _public_nights(parse_apple_health(str(APPLE_ZIP))) == [
            APPLE_NIGHT_1, APPLE_NIGHT_2,
        ]

    def test_zip_file_like(self):
        with open(APPLE_ZIP, "rb") as f:
            assert _public_nights(parse_apple_health(f)) == [
                APPLE_NIGHT_1, APPLE_NIGHT_2,
            ]

    def test_overlapping_deep_intervals_deduplicated(self):
        nights = parse_apple_health(str(APPLE_XML))
        # 60m + 40m raw records, but only 70 unique minutes of deep sleep.
        assert nights[0]["stages"]["deep"] == 70

    def test_malformed_records_skipped_not_raised(self):
        # Fixture contains a Record with no endDate and one with garbage
        # dates; both are silently dropped and both nights still parse.
        nights = parse_apple_health(str(APPLE_XML))
        assert [n["date"] for n in nights] == ["2023-11-02", "2023-11-03"]

    def test_span_only_night_has_stages_none(self):
        xml = (
            '<HealthData>'
            '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisInBed" '
            'startDate="2023-11-01 23:00:00 -0700" endDate="2023-11-02 06:30:00 -0700"/>'
            '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-01 23:05:00 -0700" endDate="2023-11-02 06:30:00 -0700"/>'
            '</HealthData>'
        )
        nights = parse_apple_health(io.BytesIO(xml.encode()))
        assert _public_nights(nights) == [{
            "date": "2023-11-02",
            "bedtime": "23:00",
            "wake": "06:30",
            "source": "apple_health",
            "stages": None,
            "efficiency": None,
            "notes": "Imported from Apple Health",
        }]

    def test_no_sleep_records_raises(self):
        xml = (
            '<HealthData><Record type="HKQuantityTypeIdentifierStepCount" '
            'value="12" startDate="2023-11-01 10:00:00 -0700" '
            'endDate="2023-11-01 10:05:00 -0700"/></HealthData>'
        )
        with pytest.raises(ValueError):
            parse_apple_health(io.BytesIO(xml.encode()))

    def test_garbage_input_raises(self):
        with pytest.raises(ValueError):
            parse_apple_health(io.BytesIO(b"definitely not xml at all"))

    def test_empty_input_raises(self):
        with pytest.raises(ValueError):
            parse_apple_health(io.BytesIO(b""))

    def test_zip_without_export_xml_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "hi")
        buf.seek(0)
        with pytest.raises(ValueError):
            parse_apple_health(buf)

    def test_truncated_xml_after_valid_record_fails_closed(self):
        xml = (
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-01 23:00:00 -0700" '
            'endDate="2023-11-02 07:00:00 -0700"/>'
        )
        with pytest.raises(ValueError, match="valid Apple Health XML"):
            parse_apple_health(io.BytesIO(xml.encode()))

    def test_dtd_and_internal_entity_rejected(self):
        xml = (
            '<!DOCTYPE HealthData [<!ENTITY start "2023-11-01 23:00:00 -0700">]>'
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" startDate="&start;" '
            'endDate="2023-11-02 07:00:00 -0700"/></HealthData>'
        )
        with pytest.raises(ValueError, match="entity declarations"):
            parse_apple_health(io.BytesIO(xml.encode()))

    def test_standard_internal_healthdata_dtd_is_allowed(self):
        xml = (
            '<!DOCTYPE HealthData ['
            '<!ELEMENT HealthData (Record*)>'
            '<!ELEMENT Record EMPTY>'
            '<!ATTLIST Record type CDATA #REQUIRED value CDATA #REQUIRED '
            'startDate CDATA #REQUIRED endDate CDATA #REQUIRED>'
            ']>'
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-01 23:00:00 -0700" '
            'endDate="2023-11-02 07:00:00 -0700"/></HealthData>'
        )
        night = parse_apple_health(io.BytesIO(xml.encode()))[0]
        assert night["date"] == "2023-11-02"
        assert night["stages"] is None

    def test_external_dtd_is_rejected(self):
        xml = (
            '<!DOCTYPE HealthData SYSTEM "file:///etc/passwd">'
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-01 23:00:00 -0700" '
            'endDate="2023-11-02 07:00:00 -0700"/></HealthData>'
        )
        with pytest.raises(ValueError, match="external or unsupported DTD"):
            parse_apple_health(io.BytesIO(xml.encode()))

    def test_dst_fallback_uses_elapsed_time_but_preserves_wall_clock(self):
        xml = (
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleepDeep" '
            'startDate="2023-11-05 00:00:00 -0400" '
            'endDate="2023-11-05 08:00:00 -0500"/>'
            '</HealthData>'
        )
        night = parse_apple_health(io.BytesIO(xml.encode()))[0]
        assert night["bedtime"] == "00:00"
        assert night["wake"] == "08:00"
        assert night["stages"]["deep"] == 540
        assert night["_sessions"][0]["elapsed_seconds"] == 9 * 60 * 60

    def test_dst_spring_forward_preserves_seven_elapsed_hours(self):
        xml = (
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2024-03-10 00:00:00 -0500" '
            'endDate="2024-03-10 08:00:00 -0400"/>'
            '</HealthData>'
        )
        night = parse_apple_health(io.BytesIO(xml.encode()))[0]
        assert night["bedtime"] == "00:00"
        assert night["wake"] == "08:00"
        assert night["_sessions"][0]["elapsed_seconds"] == 7 * 60 * 60

    def test_cross_stage_overlap_uses_precedence_without_double_counting(self):
        records = [
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAsleepDeep" '
                'startDate="2023-11-01 23:00:00 -0700" '
                'endDate="2023-11-02 02:00:00 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAsleepCore" '
                'startDate="2023-11-02 00:00:00 -0700" '
                'endDate="2023-11-02 03:00:00 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAwake" '
                'startDate="2023-11-02 01:00:00 -0700" '
                'endDate="2023-11-02 01:30:00 -0700"/>'
            ),
        ]
        forward = parse_apple_health(
            io.BytesIO(("<HealthData>" + "".join(records) + "</HealthData>").encode())
        )
        reverse = parse_apple_health(
            io.BytesIO(
                ("<HealthData>" + "".join(reversed(records)) + "</HealthData>").encode()
            )
        )
        assert forward == reverse
        assert forward[0]["stages"] == {
            "deep": 150,
            "rem": 0,
            "light": 60,
            "awake": 30,
        }
        assert sum(forward[0]["stages"].values()) == 240

    def test_stage_rounding_conserves_combined_minutes(self):
        records = [
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisInBed" '
                'startDate="2023-11-01 23:00:00 -0700" '
                'endDate="2023-11-01 23:30:00 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAwake" '
                'startDate="2023-11-01 23:00:00 -0700" '
                'endDate="2023-11-01 23:00:31 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAsleepDeep" '
                'startDate="2023-11-01 23:00:31 -0700" '
                'endDate="2023-11-01 23:01:02 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAsleepREM" '
                'startDate="2023-11-01 23:01:02 -0700" '
                'endDate="2023-11-01 23:01:33 -0700"/>'
            ),
            (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                'value="HKCategoryValueSleepAnalysisAsleepCore" '
                'startDate="2023-11-01 23:01:33 -0700" '
                'endDate="2023-11-01 23:02:04 -0700"/>'
            ),
        ]
        xml = "<HealthData>" + "".join(records) + "</HealthData>"
        stages = parse_apple_health(io.BytesIO(xml.encode()))[0]["stages"]
        assert sum(stages.values()) == 2

    def test_longest_cluster_wins_when_two_clusters_share_wake_date(self):
        xml = (
            '<HealthData>'
            '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-02 00:00:00 -0700" '
            'endDate="2023-11-02 03:00:00 -0700"/>'
            '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-02 08:00:00 -0700" '
            'endDate="2023-11-02 10:00:00 -0700"/>'
            '</HealthData>'
        )
        nights = parse_apple_health(io.BytesIO(xml.encode()))
        assert len(nights) == 1
        assert nights[0]["date"] == "2023-11-02"
        assert nights[0]["bedtime"] == "00:00"
        assert nights[0]["wake"] == "03:00"
        assert [session["elapsed_seconds"] for session in nights[0]["_sessions"]] == [
            3 * 60 * 60,
            2 * 60 * 60,
        ]
        assert [session["main"] for session in nights[0]["_sessions"]] == [
            True,
            False,
        ]

    @pytest.mark.parametrize("mutator", [_corrupt_first_member, _mark_first_member_encrypted])
    def test_corrupt_or_encrypted_export_member_is_value_error(self, mutator):
        xml = (
            '<HealthData><Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            'value="HKCategoryValueSleepAnalysisAsleep" '
            'startDate="2023-11-01 23:00:00 -0700" '
            'endDate="2023-11-02 07:00:00 -0700"/></HealthData>'
        )
        archive = _zip_bytes([("apple_health_export/export.xml", xml)])
        with pytest.raises(ValueError):
            parse_apple_health(io.BytesIO(mutator(archive)))

    def test_plain_size_sleep_record_and_normalized_night_limits(self, monkeypatch):
        xml_bytes = APPLE_XML.read_bytes()
        monkeypatch.setattr(apple_health, "MAX_INPUT_BYTES", len(xml_bytes) - 1)
        with pytest.raises(ValueError, match="size limit"):
            parse_apple_health(io.BytesIO(xml_bytes))

        monkeypatch.setattr(apple_health, "MAX_INPUT_BYTES", len(xml_bytes))
        monkeypatch.setattr(apple_health, "MAX_SLEEP_RECORDS", 1)
        with pytest.raises(ValueError, match="too many sleep records"):
            parse_apple_health(io.BytesIO(xml_bytes))

        monkeypatch.setattr(apple_health, "MAX_SLEEP_RECORDS", 100)
        monkeypatch.setattr(apple_health, "MAX_NORMALIZED_NIGHTS", 1)
        with pytest.raises(ValueError, match="too many sleep nights"):
            parse_apple_health(io.BytesIO(xml_bytes))

    def test_archive_member_count_is_bounded(self, monkeypatch):
        monkeypatch.setattr(importer_common, "MAX_ZIP_MEMBERS", 1)
        with pytest.raises(ValueError, match="more than 1 members"):
            parse_apple_health(APPLE_ZIP)


# --------------------------------------------------------------------- Fitbit

class TestFitbit:
    def test_stages_json_exact_main_nights_and_nap_retained_privately(self):
        # Fixture holds two mainSleep logs plus a Nov 2 afternoon nap; the nap
        # does not replace the public main session but remains for accounting.
        nights = parse_fitbit_takeout(str(FITBIT_STAGES))
        assert _public_nights(nights) == [FITBIT_NIGHT_NOV2, FITBIT_NIGHT_NOV3]
        assert [session["main"] for session in nights[0]["_sessions"]] == [
            True, False,
        ]
        assert sum(
            session["elapsed_seconds"] for session in nights[0]["_sessions"]
        ) == 8 * 3600 + 43 * 60 + 30

    def test_classic_log_stages_none_and_lone_nap_kept(self):
        # mainSleep is false but it is the only log for 2023-11-05: keep it.
        nights = parse_fitbit_takeout(str(FITBIT_CLASSIC))
        assert _public_nights(nights) == [FITBIT_NIGHT_NOV5]

    def test_zip_combines_files_sorted_ascending(self):
        nights = parse_fitbit_takeout(str(FITBIT_ZIP))
        assert _public_nights(nights) == [
            FITBIT_NIGHT_NOV2, FITBIT_NIGHT_NOV3, FITBIT_NIGHT_NOV5,
        ]

    def test_zip_file_like(self):
        with open(FITBIT_ZIP, "rb") as f:
            assert _public_nights(parse_fitbit_takeout(f)) == [
                FITBIT_NIGHT_NOV2, FITBIT_NIGHT_NOV3, FITBIT_NIGHT_NOV5,
            ]

    def test_json_file_like(self):
        with open(FITBIT_STAGES, "rb") as f:
            assert _public_nights(parse_fitbit_takeout(f)) == [
                FITBIT_NIGHT_NOV2, FITBIT_NIGHT_NOV3,
            ]

    def test_plain_python_list_accepted(self):
        logs = json.loads(FITBIT_CLASSIC.read_text())
        assert _public_nights(parse_fitbit_takeout(logs)) == [FITBIT_NIGHT_NOV5]

    def test_malformed_logs_skipped(self):
        logs = json.loads(FITBIT_CLASSIC.read_text())
        logs += [
            {"dateOfSleep": "2023-11-06"},           # missing times
            {"dateOfSleep": "nope", "startTime": "2023-11-06T23:00:00.000",
             "endTime": "2023-11-07T07:00:00.000"},  # bad date
            "not even a dict",
            None,
        ]
        assert _public_nights(parse_fitbit_takeout(logs)) == [FITBIT_NIGHT_NOV5]

    def test_duplicate_log_ids_deduplicated(self):
        logs = json.loads(FITBIT_STAGES.read_text())
        nights = parse_fitbit_takeout(logs + logs)  # overlapping export files
        assert _public_nights(nights) == [FITBIT_NIGHT_NOV2, FITBIT_NIGHT_NOV3]
        assert len(nights[0]["_sessions"]) == 2

    def test_empty_array_raises(self):
        with pytest.raises(ValueError):
            parse_fitbit_takeout(io.BytesIO(b"[]"))

    def test_garbage_input_raises(self):
        with pytest.raises(ValueError):
            parse_fitbit_takeout(io.BytesIO(b"totally not json"))

    def test_non_array_json_raises(self):
        with pytest.raises(ValueError):
            parse_fitbit_takeout(io.BytesIO(b'{"sleep": "nope"}'))

    def test_zip_without_sleep_json_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Takeout/Fitbit/steps-2023-11-02.json", "[]")
        buf.seek(0)
        with pytest.raises(ValueError):
            parse_fitbit_takeout(buf)

    def test_zip_with_good_and_malformed_sleep_member_fails_closed(self):
        archive = _zip_bytes([
            ("Takeout/Fitbit/sleep-2023-11-02.json", FITBIT_STAGES.read_bytes()),
            ("Takeout/Fitbit/sleep-2023-11-03.json", b"{not valid json"),
        ])
        with pytest.raises(ValueError, match="not valid Fitbit member"):
            parse_fitbit_takeout(io.BytesIO(archive))

    @pytest.mark.parametrize("mutator", [_corrupt_first_member, _mark_first_member_encrypted])
    def test_corrupt_or_encrypted_sleep_member_is_value_error(self, mutator):
        archive = _zip_bytes([
            ("Takeout/Fitbit/sleep-2023-11-02.json", FITBIT_STAGES.read_bytes()),
        ])
        with pytest.raises(ValueError):
            parse_fitbit_takeout(io.BytesIO(mutator(archive)))

    def test_noncanonical_date_and_inconsistent_timestamps_rejected(self):
        with pytest.raises(ValueError):
            parse_fitbit_takeout([_fitbit_log(dateOfSleep="2023-1-3")])
        with pytest.raises(ValueError):
            parse_fitbit_takeout([
                _fitbit_log(
                    startTime="2023-11-03T08:00:00.000",
                    endTime="2023-11-03T07:00:00.000",
                )
            ])
        with pytest.raises(ValueError):
            parse_fitbit_takeout([
                _fitbit_log(dateOfSleep="2023-11-04")
            ])

    def test_offset_timestamps_preserve_local_times_and_elapsed_duration(self):
        night = parse_fitbit_takeout([
            _fitbit_log(
                dateOfSleep="2023-11-05",
                startTime="2023-11-05T00:00:00-04:00",
                endTime="2023-11-05T08:00:00-05:00",
                duration=9 * 60 * 60 * 1000,
            )
        ])[0]
        assert night["date"] == "2023-11-05"
        assert night["bedtime"] == "00:00"
        assert night["wake"] == "08:00"
        assert night["_sessions"][0]["elapsed_seconds"] == 9 * 60 * 60

    def test_declared_duration_does_not_replace_timestamp_elapsed_time(self):
        night = parse_fitbit_takeout([
            _fitbit_log(
                dateOfSleep="2023-11-05",
                startTime="2023-11-05T00:00:00-04:00",
                endTime="2023-11-05T08:00:00-04:00",
                duration=6 * 60 * 60 * 1000,
            )
        ])[0]
        assert night["_sessions"][0]["elapsed_seconds"] == 8 * 60 * 60

    def test_main_selection_uses_timestamp_elapsed_time(self):
        longer_interval = _fitbit_log(
            logId=1,
            startTime="2023-11-02T22:30:00.000",
            endTime="2023-11-03T06:30:00.000",
            duration=6 * 60 * 60 * 1000,
        )
        shorter_interval = _fitbit_log(
            logId=2,
            startTime="2023-11-02T23:00:00.000",
            endTime="2023-11-03T06:30:00.000",
            duration=9.5 * 60 * 60 * 1000,
        )
        night = parse_fitbit_takeout([longer_interval, shorter_interval])[0]
        assert night["bedtime"] == "22:30"
        assert [session["main"] for session in night["_sessions"]] == [True, False]

    def test_duplicate_logs_without_ids_do_not_duplicate_sessions(self):
        log = _fitbit_log(logId=None)
        night = parse_fitbit_takeout([log, dict(log)])[0]
        assert len(night["_sessions"]) == 1

    @pytest.mark.parametrize(
        "overrides",
        [
            {"efficiency": -1},
            {"efficiency": float("inf")},
            {"duration": -1},
            {"duration": float("inf")},
            {
                "levels": {
                    "summary": {
                        key: {"minutes": -5}
                        for key in ("deep", "rem", "light", "wake")
                    }
                }
            },
            {
                "levels": {
                    "summary": {
                        key: {"minutes": float("inf")}
                        for key in ("deep", "rem", "light", "wake")
                    }
                }
            },
        ],
    )
    def test_nonfinite_or_out_of_range_metrics_rejected_without_crash(
        self, overrides
    ):
        with pytest.raises(ValueError):
            parse_fitbit_takeout([_fitbit_log(**overrides)])

    def test_json_nan_rejected(self):
        payload = json.dumps([_fitbit_log()]).replace('"efficiency": 90', '"efficiency": NaN')
        with pytest.raises(ValueError, match="non-finite JSON number"):
            parse_fitbit_takeout(io.BytesIO(payload.encode()))

    def test_main_sleep_and_log_id_types_are_strict(self):
        with pytest.raises(ValueError):
            parse_fitbit_takeout([_fitbit_log(mainSleep="false")])
        with pytest.raises(ValueError):
            parse_fitbit_takeout([_fitbit_log(logId=[])])

    def test_conflicting_duplicate_log_ids_fail_closed(self):
        original = _fitbit_log()
        conflicting = _fitbit_log(efficiency=91)
        with pytest.raises(ValueError, match="conflicting Fitbit sleep logs"):
            parse_fitbit_takeout([original, conflicting])

    def test_plain_zip_total_log_and_normalized_night_limits(self, monkeypatch):
        raw = FITBIT_STAGES.read_bytes()
        monkeypatch.setattr(fitbit, "MAX_JSON_MEMBER_BYTES", len(raw) - 1)
        with pytest.raises(ValueError, match="size limit"):
            parse_fitbit_takeout(io.BytesIO(raw))

        monkeypatch.setattr(fitbit, "MAX_JSON_MEMBER_BYTES", len(raw))
        monkeypatch.setattr(fitbit, "MAX_SLEEP_LOGS", 1)
        with pytest.raises(ValueError, match="too many sleep logs"):
            parse_fitbit_takeout(io.BytesIO(raw))

        monkeypatch.setattr(fitbit, "MAX_SLEEP_LOGS", 100)
        monkeypatch.setattr(fitbit, "MAX_NORMALIZED_NIGHTS", 1)
        with pytest.raises(ValueError, match="too many sleep nights"):
            parse_fitbit_takeout(io.BytesIO(raw))

        monkeypatch.setattr(fitbit, "MAX_NORMALIZED_NIGHTS", 100)
        monkeypatch.setattr(fitbit, "MAX_TOTAL_JSON_BYTES", 1)
        with pytest.raises(ValueError, match="total uncompressed-size limit"):
            parse_fitbit_takeout(FITBIT_ZIP)
