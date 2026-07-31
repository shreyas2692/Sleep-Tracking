"""Wave-1 backend tests: schema migration, /import/wearable, /api/series,
and sleep-debt accounting."""
import io
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

import database as db

AJAX = {"X-Requested-With": "XMLHttpRequest"}
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

LEGACY_SCHEMA = """
    CREATE TABLE sleep_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        bedtime TEXT NOT NULL,
        wake_time TEXT NOT NULL,
        quality INTEGER NOT NULL CHECK(quality BETWEEN 1 AND 5),
        notes TEXT DEFAULT ''
    )
"""

NEW_COLUMNS = {
    "source", "deep_minutes", "rem_minutes", "light_minutes",
    "awake_minutes", "efficiency",
}


def _d(days_ago):
    return (db.get_today() - timedelta(days=days_ago)).isoformat()


def _fixture_bytes(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _upload(client, payload, filename="export.zip"):
    return client.post(
        "/import/wearable",
        data={"file": (io.BytesIO(payload), filename)},
        content_type="multipart/form-data",
        headers=AJAX,
    )


def _span_night_xml(wake_dates):
    """Minimal Apple Health XML with one span-only night per wake date."""
    records = []
    for wake_date in wake_dates:
        bed_date = (wake_date - timedelta(days=1)).isoformat()
        records.append(
            f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
            f'value="HKCategoryValueSleepAnalysisAsleepUnspecified" '
            f'startDate="{bed_date} 23:00:00 -0400" '
            f'endDate="{wake_date.isoformat()} 07:00:00 -0400"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="en_US">'
        + "".join(records)
        + "</HealthData>"
    ).encode()


# ── Schema migration ──────────────────────────────────────────

def test_legacy_schema_upgrades_in_place(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute(LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO sleep_records (date, bedtime, wake_time, quality, notes) "
        "VALUES ('2026-07-01', '23:00', '07:00', 4, 'legacy row')"
    )
    conn.commit()
    conn.close()

    records = db.get_all_records()  # triggers migration via get_connection
    assert len(records) == 1
    rec = records[0]
    assert rec["date"] == "2026-07-01"
    assert rec["quality"] == 4
    assert rec["notes"] == "legacy row"
    assert rec["hours"] == 8.0
    assert rec["source"] == "manual"  # backfilled default
    assert rec["stages"] is None
    assert rec["efficiency"] is None

    conn = sqlite3.connect(temp_db)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sleep_records)")}
    conn.close()
    assert NEW_COLUMNS <= columns


def test_migration_is_idempotent(temp_db):
    db.get_connection().close()
    db.get_connection().close()  # second run must not fail or duplicate columns
    conn = sqlite3.connect(temp_db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sleep_records)")]
    conn.close()
    assert len(columns) == len(set(columns))
    assert NEW_COLUMNS <= set(columns)


def test_concurrent_legacy_migration_is_serialized(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute(LEGACY_SCHEMA)
    conn.commit()
    conn.close()

    barrier = threading.Barrier(8)

    def connect_once(_index):
        barrier.wait()
        connection = db.get_connection()
        connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(connect_once, range(8)))

    conn = sqlite3.connect(temp_db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(sleep_records)")]
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert len(columns) == len(set(columns))
    assert NEW_COLUMNS <= set(columns)
    assert version == 1


def test_migration_collapses_legacy_wearable_duplicates(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.execute(LEGACY_SCHEMA)
    conn.execute(
        "ALTER TABLE sleep_records "
        "ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'"
    )
    for notes in ("oldest", "newer"):
        conn.execute(
            "INSERT INTO sleep_records "
            "(date, bedtime, wake_time, quality, notes, source) "
            "VALUES ('2023-11-02', '23:00', '07:00', 3, ?, 'fitbit')",
            (notes,),
        )
    conn.commit()
    conn.close()

    records = db.get_all_records()
    assert len(records) == 1
    assert records[0]["notes"] == "oldest"

    conn = sqlite3.connect(temp_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sleep_records "
            "(date, bedtime, wake_time, quality, notes, source) "
            "VALUES ('2023-11-02', '22:00', '06:00', 2, 'dupe', 'fitbit')"
        )
    conn.close()


def test_fresh_db_has_new_columns_and_manual_defaults():
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    rec = db.get_records()[0]
    assert rec["source"] == "manual"
    assert rec["stages"] is None
    assert rec["efficiency"] is None


# ── Quality derivation ────────────────────────────────────────

@pytest.mark.parametrize(
    "stages,expected",
    [
        (None, 3),                                                # no stage data
        ({"deep": 0, "rem": 0, "light": 0, "awake": 0}, 3),       # zero total
        ({"deep": 35, "rem": 0, "light": 65, "awake": 0}, 5),     # .35 boundary
        ({"deep": 34, "rem": 0, "light": 66, "awake": 0}, 4),     # just under
        ({"deep": 14, "rem": 14, "light": 62, "awake": 10}, 4),   # .28 boundary
        ({"deep": 27, "rem": 0, "light": 73, "awake": 0}, 3),     # just under .28
        ({"deep": 10, "rem": 10, "light": 70, "awake": 10}, 3),   # .20 boundary
        ({"deep": 6, "rem": 6, "light": 78, "awake": 10}, 2),     # .12 boundary
        ({"deep": 11, "rem": 0, "light": 89, "awake": 0}, 1),     # under .12
        ({"deep": 0, "rem": 0, "light": 100, "awake": 0}, 1),
    ],
)
def test_derive_quality(stages, expected):
    import app as app_module

    assert app_module.derive_quality(stages) == expected


# ── POST /import/wearable ─────────────────────────────────────

def test_import_apple_zip_fixture(client):
    resp = _upload(client, _fixture_bytes("apple_export.zip"))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["imported"] == 2
    assert body["replaced"] == 0
    assert body["skipped"] == 0
    assert body["stats"]["total"] == 2
    for rec in body["records"]:
        assert rec["source"] == "apple_health"
        assert set(rec["stages"]) == {"deep", "rem", "light", "awake"}
        assert 1 <= rec["quality"] <= 5


def test_import_apple_raw_xml(client):
    resp = _upload(client, _fixture_bytes("apple_export.xml"), "export.xml")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["imported"] == 2
    assert {r["date"] for r in body["records"]} == {"2023-11-02", "2023-11-03"}


def test_import_fitbit_takeout_zip(client):
    resp = _upload(client, _fixture_bytes("fitbit_takeout.zip"), "takeout.zip")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["imported"] == 3
    sources = {r["source"] for r in body["records"]}
    assert sources == {"fitbit"}
    by_date = {r["date"]: r for r in body["records"]}
    assert by_date["2023-11-05"]["stages"] is None      # classic log
    assert by_date["2023-11-05"]["quality"] == 3        # no stages -> neutral 3
    assert by_date["2023-11-03"]["stages"] is not None  # stages log
    assert by_date["2023-11-03"]["efficiency"] == 90.0


def test_import_fitbit_single_json_file(client):
    resp = _upload(client, _fixture_bytes("fitbit_stages.json"), "sleep.json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["imported"] >= 1
    assert all(r["source"] == "fitbit" for r in body["records"])


def test_reimport_replaces_instead_of_duplicating(client):
    first = _upload(client, _fixture_bytes("apple_export.zip")).get_json()
    assert (first["imported"], first["replaced"]) == (2, 0)

    second = _upload(client, _fixture_bytes("apple_export.zip")).get_json()
    assert second["imported"] == 0
    assert second["replaced"] == 2
    assert second["stats"]["total"] == 2  # no duplicates

    # Row identity (id) is preserved across re-import.
    assert {r["id"] for r in first["records"]} == {r["id"] for r in second["records"]}


def test_different_sources_coexist_for_same_date(client):
    _upload(client, _fixture_bytes("apple_export.zip"))
    body = _upload(client, _fixture_bytes("fitbit_takeout.zip"), "t.zip").get_json()
    # Apple has 2023-11-02/03; Fitbit has 2023-11-02/03/05: 5 rows, 0 replaced.
    assert body["replaced"] == 0
    assert body["stats"]["total"] == 5


def test_wearable_import_does_not_touch_manual_records(client):
    db.add_record("2023-11-02", "22:00", "06:00", 5, "manual entry")
    body = _upload(client, _fixture_bytes("apple_export.zip")).get_json()
    assert body["imported"] == 2
    assert body["replaced"] == 0
    assert body["stats"]["total"] == 3
    manual = [r for r in db.get_all_records() if r["source"] == "manual"]
    assert len(manual) == 1
    assert manual[0]["notes"] == "manual entry"


def test_future_nights_are_skipped_not_rejected(client):
    today = db.get_today()
    xml = _span_night_xml([today - timedelta(days=3), today + timedelta(days=2)])
    resp = _upload(client, xml, "export.xml")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["imported"] == 1
    assert body["skipped"] == 1
    assert body["records"][0]["date"] == (today - timedelta(days=3)).isoformat()


def test_import_wearable_no_file_400(client):
    resp = client.post("/import/wearable", data={}, headers=AJAX)
    assert resp.status_code == 400
    assert "file" in resp.get_json()["error"].lower()


def test_import_wearable_empty_file_400(client):
    resp = _upload(client, b"", "export.xml")
    assert resp.status_code == 400
    assert "empty" in resp.get_json()["error"].lower()


def test_import_wearable_unrecognized_format_400(client):
    resp = _upload(client, b"just some text, neither xml nor json", "notes.txt")
    assert resp.status_code == 400
    assert "unrecognized" in resp.get_json()["error"].lower()


def test_import_wearable_unparseable_xml_400(client):
    resp = _upload(client, b"<NotHealthData></NotHealthData>", "export.xml")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_wearable_corrupt_zip_400(client):
    resp = _upload(client, b"PK\x03\x04corrupt-zip-bytes")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_wearable_over_size_cap_400(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "MAX_WEARABLE_BYTES", 16)
    resp = _upload(client, b"x" * 32, "export.xml")
    assert resp.status_code == 400
    assert "too large" in resp.get_json()["error"].lower()


def test_wearable_upload_exceeding_global_2mib_cap_is_accepted(client):
    """/import/wearable gets its own 1 GiB bound, not the global 2 MiB one."""
    today = db.get_today()
    xml = _span_night_xml([today - timedelta(days=3)])
    padded = xml.replace(
        b"</HealthData>", b"<!--" + b"x" * (3 * 1024 * 1024) + b"--></HealthData>"
    )
    resp = _upload(client, padded, "export.xml")
    assert resp.status_code == 200  # not 413
    assert resp.get_json()["imported"] == 1


def test_csv_import_cap_still_1mib(client):
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "data.csv")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 400
    assert "too large" in resp.get_json()["error"].lower()


def test_import_wearable_requires_auth(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = _upload(client, _fixture_bytes("apple_export.zip"))
    assert resp.status_code == 401


def test_import_wearable_rejects_cross_site(client):
    resp = client.post(
        "/import/wearable",
        data={"file": (io.BytesIO(_fixture_bytes("apple_export.zip")), "e.zip")},
        content_type="multipart/form-data",
        headers={**AJAX, "Origin": "https://attacker.example"},
    )
    assert resp.status_code == 403


# ── GET /api/series ───────────────────────────────────────────

def _seed_series():
    db.add_record(_d(2), "23:00", "07:00", 4, "")
    db.add_record(_d(45), "22:30", "06:15", 3, "")
    db.add_record(_d(200), "23:00", "05:00", 2, "")
    db.add_record(_d(400), "23:00", "07:00", 5, "")


def test_series_ranges_filter_dates(client):
    _seed_series()
    def dates(rng):
        body = client.get(f"/api/series?range={rng}").get_json()
        assert body["range"] == rng
        return [n["date"] for n in body["nights"]]

    assert dates("30d") == [_d(2)]
    assert dates("90d") == [_d(45), _d(2)]
    assert dates("1y") == [_d(200), _d(45), _d(2)]
    assert dates("all") == [_d(400), _d(200), _d(45), _d(2)]


def test_series_shape_start_end_and_default_range(client):
    _seed_series()
    body = client.get("/api/series").get_json()
    assert body["range"] == "30d"
    assert body["start"] == _d(29)
    assert body["end"] == _d(0)
    night = body["nights"][0]
    assert set(night) == {"date", "hours", "quality", "stages", "source"}
    assert night["hours"] == 8.0
    assert night["source"] == "manual"

    all_body = client.get("/api/series?range=all").get_json()
    assert all_body["start"] == _d(400)  # earliest record for 'all'
    assert all_body["end"] == _d(0)


def test_series_only_dates_with_records_and_ascending(client):
    _seed_series()
    nights = client.get("/api/series?range=all").get_json()["nights"]
    assert len(nights) == 4  # no null-filled gap days
    dates = [n["date"] for n in nights]
    assert dates == sorted(dates)


def test_series_duplicate_date_latest_record_wins(client):
    db.add_record(_d(1), "23:00", "07:00", 3, "older")
    db.add_record(_d(1), "22:00", "07:00", 5, "newer")  # higher id, 9h
    nights = client.get("/api/series?range=30d").get_json()["nights"]
    assert len(nights) == 1
    assert nights[0]["hours"] == 9.0
    assert nights[0]["quality"] == 5


def test_series_includes_wearable_stages(client):
    _upload(client, _fixture_bytes("apple_export.zip"))
    nights = client.get("/api/series?range=all").get_json()["nights"]
    assert len(nights) == 2
    assert all(n["source"] == "apple_health" for n in nights)
    assert all(set(n["stages"]) == {"deep", "rem", "light", "awake"} for n in nights)


def test_series_empty_db(client):
    body = client.get("/api/series?range=all").get_json()
    assert body["nights"] == []
    assert body["start"] == body["end"] == _d(0)


@pytest.mark.parametrize("value", ["7d", "2y", "", "ALL", "30D", "30d;drop"])
def test_series_invalid_range_400(client, value):
    resp = client.get(f"/api/series?range={value}")
    assert resp.status_code == 400
    assert "range" in resp.get_json()["error"]


# ── Sleep debt ────────────────────────────────────────────────

def test_sleep_debt_empty_db():
    debt = db.get_stats()["sleep_debt"]
    assert debt == {"need": 8.0, "rolling_14d": [], "total_debt_hours": 0}


def test_sleep_debt_default_need_and_arithmetic():
    db.add_record(_d(0), "23:00", "07:00", 4, "")  # 8h -> debt 0
    db.add_record(_d(1), "23:00", "05:00", 2, "")  # 6h -> debt 2
    debt = db.get_stats()["sleep_debt"]
    assert debt["need"] == 8.0
    assert [(e["date"], e["debt_hours"]) for e in debt["rolling_14d"]] == [
        (_d(1), 2.0),
        (_d(0), 0.0),
    ]
    assert debt["rolling_14d"][-1]["cumulative_debt_hours"] == 2.0
    assert debt["total_debt_hours"] == 2.0


def test_sleep_debt_uses_sleep_goal_setting():
    db.set_setting("sleep_goal", "7.0")
    db.add_record(_d(0), "23:00", "05:00", 3, "")  # 6h -> debt 1 vs 7h need
    debt = db.get_stats()["sleep_debt"]
    assert debt["need"] == 7.0
    assert debt["total_debt_hours"] == 1.0


def test_sleep_debt_invalid_goal_setting_falls_back_to_8():
    db.set_setting("sleep_goal", "not-a-number")
    db.add_record(_d(0), "23:00", "07:00", 3, "")
    assert db.get_stats()["sleep_debt"]["need"] == 8.0


def test_sleep_debt_missing_days_are_skipped():
    db.add_record(_d(0), "23:00", "05:00", 3, "")   # in window
    db.add_record(_d(20), "23:00", "01:00", 3, "")  # outside 14-day window
    debt = db.get_stats()["sleep_debt"]
    assert [e["date"] for e in debt["rolling_14d"]] == [_d(0)]
    assert debt["total_debt_hours"] == 2.0  # the 13 missing days contribute 0


def test_sleep_debt_manual_naps_sum():
    db.add_record(_d(0), "23:00", "07:00", 4, "night")  # 8h
    db.add_record(_d(0), "14:00", "15:00", 3, "nap")    # +1h -> 9h -> debt -1
    debt = db.get_stats()["sleep_debt"]
    assert debt["rolling_14d"] == [
        {"date": _d(0), "debt_hours": -1.0, "cumulative_debt_hours": -1.0}
    ]
    assert debt["total_debt_hours"] == -1.0


def test_sleep_debt_multi_source_same_date_uses_max_not_sum():
    db.add_record(_d(0), "23:00", "05:00", 3, "")  # manual, 6h
    db.upsert_wearable_records([{
        "date": _d(0), "bedtime": "23:00", "wake": "06:00", "quality": 3,
        "notes": "", "source": "apple_health", "stages": None, "efficiency": None,
    }])  # apple_health, 7h
    debt = db.get_stats()["sleep_debt"]
    # max(6, 7) = 7 slept -> 1h debt; sources are never summed together.
    assert debt["total_debt_hours"] == 1.0


def test_oversleep_reduces_cumulative_debt():
    db.add_record(_d(1), "22:00", "04:00", 3, "")  # 6h -> +2
    db.add_record(_d(0), "22:00", "08:00", 4, "")  # 10h -> -2
    debt = db.get_stats()["sleep_debt"]
    assert debt["rolling_14d"][-1]["cumulative_debt_hours"] == 0.0
    assert debt["total_debt_hours"] == 0.0


# ── upsert_wearable_records (db-level) ────────────────────────

def test_upsert_updates_row_in_place_and_rejects_duplicates(temp_db):
    night = {
        "date": "2023-11-02", "bedtime": "23:00", "wake": "07:00", "quality": 3,
        "notes": "v1", "source": "fitbit",
        "stages": {"deep": 50, "rem": 70, "light": 260, "awake": 30},
        "efficiency": 90.0,
    }
    imported, replaced = db.upsert_wearable_records([night])
    assert (imported, replaced) == (1, 0)
    original = db.get_all_records()[0]

    conn = sqlite3.connect(temp_db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sleep_records "
            "(date, bedtime, wake_time, quality, notes, source) "
            "VALUES ('2023-11-02', '22:00', '06:00', 2, 'dupe', 'fitbit')"
        )
    conn.close()

    imported, replaced = db.upsert_wearable_records([{**night, "notes": "v2"}])
    assert (imported, replaced) == (0, 1)
    records = db.get_all_records()
    assert len(records) == 1  # duplicate collapsed
    assert records[0]["id"] == original["id"]  # UPDATE, not delete+insert
    assert records[0]["notes"] == "v2"
    assert records[0]["stages"] == {"deep": 50, "rem": 70, "light": 260, "awake": 30}
    assert records[0]["efficiency"] == 90.0


def test_concurrent_first_upserts_create_one_wearable_row():
    night = {
        "date": "2023-11-02",
        "bedtime": "23:00",
        "wake": "07:00",
        "quality": 3,
        "notes": "concurrent",
        "source": "fitbit",
        "stages": None,
        "efficiency": None,
    }
    barrier = threading.Barrier(8)

    def upsert_once(_index):
        barrier.wait()
        return db.upsert_wearable_records([night])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(upsert_once, range(8)))

    assert sum(imported for imported, _replaced in results) == 1
    assert sum(replaced for _imported, replaced in results) == 7
    records = db.get_all_records()
    assert len(records) == 1
    assert records[0]["source"] == "fitbit"
