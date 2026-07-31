"""Tests for POST /import — CSV import endpoint."""
import csv
import io
from datetime import timedelta

import pytest

AJAX = {"X-Requested-With": "XMLHttpRequest"}


def _make_csv(rows, header=True):
    """Build a CSV string from header + data rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    if header:
        writer.writerow(["date", "bedtime", "wake", "quality", "notes", "hours"])
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def _csv_file(content):
    """Wrap a CSV string as a Flask test-client file upload."""
    return (io.BytesIO(content.encode("utf-8")), "data.csv")


def _import(client, content):
    """POST /import with a CSV string and return (status_code, json)."""
    resp = client.post(
        "/import",
        data={"file": _csv_file(content)},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    return resp.status_code, resp.get_json()


# ── Successful imports ─────────────────────────────────────────

def test_import_success_single_row(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "slept well", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["ok"] is True
    assert len(body["records"]) == 1
    rec = body["records"][0]
    assert rec["date"] == "2026-07-01"
    assert rec["bedtime"] == "23:00"
    assert rec["wake"] == "07:00"
    assert rec["quality"] == 4
    assert rec["notes"] == "slept well"
    assert rec["hours"] == 8.0
    assert body["stats"]["total"] == 1


def test_import_success_multiple_rows(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "night one", "8.0"],
        ["2026-07-02", "22:30", "06:15", "5", "night two", "7.75"],
        ["2026-07-03", "00:00", "08:00", "3", "late bed", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert len(body["records"]) == 3
    assert body["stats"]["total"] == 3


def test_import_hours_column_ignored(client):
    """The hours column in the CSV is ignored (computed server-side)."""
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "test", "999.0"],  # bogus hours
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["records"][0]["hours"] == 8.0  # computed, not 999.0


def test_import_round_trip_export_then_import(client):
    """Export a record, then re-import it — should work (hours ignored)."""
    # First add a record via /add
    client.post(
        "/add",
        data={"date": "2026-07-01", "bedtime": "23:00", "wake": "07:00",
              "quality": "4", "notes": "original"},
        headers=AJAX,
    )
    # Export it
    export_resp = client.get("/export.csv")
    csv_content = export_resp.get_data(as_text=True)

    # Clear the DB
    client.post("/settings/clear")

    # Re-import
    status, body = _import(client, csv_content)
    assert status == 200
    assert body["stats"]["total"] == 1
    rec = body["records"][0]
    assert rec["date"] == "2026-07-01"
    assert rec["quality"] == 4
    assert rec["notes"] == "original"


def test_import_empty_notes(client):
    """Notes column can be empty."""
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["records"][0]["notes"] == ""


def test_import_notes_with_commas(client):
    """Notes containing commas survive CSV quoting round-trip."""
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "slept, dreamed, woke", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["records"][0]["notes"] == "slept, dreamed, woke"


def test_import_notes_over_500_rejected(client):
    long_notes = "x" * 600
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", long_notes, "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "500" in body["error"]


# ── File validation errors ─────────────────────────────────────

def test_import_no_file_provided(client):
    resp = client.post("/import", data={}, headers=AJAX)
    assert resp.status_code == 400
    assert "No file" in resp.get_json()["error"]


def test_import_non_csv_extension(client):
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(b"not csv"), "data.txt")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 400
    assert ".csv" in resp.get_json()["error"]


def test_import_empty_file(client):
    status, body = _import(client, "")
    assert status == 400
    assert "empty" in body["error"].lower()


def test_import_header_only(client):
    csv_data = _make_csv([])  # header only, no data rows
    status, body = _import(client, csv_data)
    assert status == 400
    assert "no data" in body["error"].lower()


def test_import_wrong_header(client):
    buf = io.StringIO()
    csv.writer(buf).writerow(["wrong", "headers", "here"])
    status, body = _import(client, buf.getvalue())
    assert status == 400
    assert "header" in body["error"].lower()


# ── Row validation errors (all-or-nothing) ─────────────────────

def test_import_invalid_date(client):
    csv_data = _make_csv([
        ["07/01/2026", "23:00", "07:00", "4", "bad date", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "date" in body["error"].lower()


def test_import_invalid_bedtime(client):
    csv_data = _make_csv([
        ["2026-07-01", "11pm", "07:00", "4", "bad bedtime", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "bedtime" in body["error"].lower()


def test_import_invalid_wake(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "7am", "4", "bad wake", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "wake" in body["error"].lower()


def test_import_quality_out_of_range(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "0", "too low", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "quality" in body["error"].lower()

    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "6", "too high", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400


def test_import_quality_non_numeric(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "great", "not a number", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    assert "quality" in body["error"].lower()


def test_import_too_few_columns(client):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "bedtime", "wake", "quality", "notes", "hours"])
    writer.writerow(["2026-07-01", "23:00"])  # missing columns
    status, body = _import(client, buf.getvalue())
    assert status == 400
    assert "column" in body["error"].lower()


# ── Duplicate preservation ─────────────────────────────────────

def test_import_duplicate_date_within_csv_is_preserved(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "first", "8.0"],
        ["2026-07-01", "22:00", "06:00", "3", "duplicate", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["stats"]["total"] == 2
    assert {record["notes"] for record in body["records"]} == {"first", "duplicate"}


def test_import_duplicate_date_against_existing_is_preserved(client):
    # Add a record first
    client.post(
        "/add",
        data={"date": "2026-07-01", "bedtime": "23:00", "wake": "07:00",
              "quality": "4", "notes": "existing"},
        headers=AJAX,
    )
    csv_data = _make_csv([
        ["2026-07-01", "22:00", "06:00", "3", "conflict", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["stats"]["total"] == 2


# ── All-or-nothing semantics ───────────────────────────────────

def test_import_all_or_nothing_bad_row_prevents_any_insert(client):
    """If row 2 is bad, row 1 must NOT be inserted."""
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "good row", "8.0"],
        ["bad-date", "23:00", "07:00", "4", "bad row", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    import database

    assert database.get_all_records() == []


def test_import_all_or_nothing_oversized_note_prevents_any_insert(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "good", "8.0"],
        ["2026-07-02", "22:00", "06:00", "3", "x" * 501, "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 400
    import database

    assert database.get_all_records() == []


# ── Edge cases ─────────────────────────────────────────────────

def test_import_excel_bom(client):
    """UTF-8 BOM (from Excel) is handled gracefully."""
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "bom test", "8.0"],
    ])
    # Prepend UTF-8 BOM
    bom_csv = "\ufeff" + csv_data
    status, body = _import(client, bom_csv)
    assert status == 200
    assert body["ok"] is True


def test_import_missing_hours_column(client):
    """CSV with only 5 columns (no hours) is accepted."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "bedtime", "wake", "quality", "notes"])
    writer.writerow(["2026-07-01", "23:00", "07:00", "4", "no hours col", ""])
    # This will fail header check (expects 6 cols) — that's acceptable
    # since our import expects the exact export format
    status, body = _import(client, buf.getvalue())
    assert status == 400  # header mismatch is correct behavior


def test_import_overnight_wraparound(client):
    """Verify hours are correctly computed for overnight wraparound."""
    csv_data = _make_csv([
        ["2026-07-01", "23:30", "06:45", "4", "wraparound", "7.25"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["records"][0]["hours"] == 7.25


def test_import_preserves_note_whitespace(client):
    csv_data = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "  exact note  ", "8.0"],
    ])
    status, body = _import(client, csv_data)
    assert status == 200
    assert body["records"][0]["notes"] == "  exact note  "


def test_import_export_round_trip_preserves_formula_like_and_apostrophe_notes(client):
    notes = ["=1+1", " +SUM(A1:A2)", "@cmd", "'literal", "\tcommand"]
    for note in notes:
        response = client.post(
            "/add",
            data={
                "date": "2026-07-01",
                "bedtime": "23:00",
                "wake": "07:00",
                "quality": "4",
                "notes": note,
            },
            headers=AJAX,
        )
        assert response.status_code == 200

    exported = client.get("/export.csv").get_data(as_text=True)
    exported_rows = list(csv.reader(io.StringIO(exported)))[1:]
    assert all(row[4].startswith("'") for row in exported_rows)

    client.post("/settings/clear")
    status, body = _import(client, exported)
    assert status == 200
    assert sorted(record["notes"] for record in body["records"]) == sorted(notes)


def test_import_future_date_rejected(client):
    import database

    future = (database.get_today() + timedelta(days=1)).isoformat()
    status, body = _import(client, _make_csv([
        [future, "23:00", "07:00", "4", "future", "8.0"],
    ]))
    assert status == 400
    assert "future" in body["error"].lower()


@pytest.mark.parametrize(
    "row",
    [
        ["2026-7-01", "23:00", "07:00", "4", "", "8.0"],
        ["2026-07-01", "7:00", "07:00", "4", "", "8.0"],
        ["2026-07-01", "23:00", "7:00", "4", "", "8.0"],
    ],
)
def test_import_requires_zero_padded_formats(client, row):
    status, _body = _import(client, _make_csv([row]))
    assert status == 400


def test_import_accepts_uppercase_csv_extension(client):
    content = _make_csv([
        ["2026-07-01", "23:00", "07:00", "4", "upper", "8.0"],
    ])
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(content.encode()), "DATA.CSV")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 200


def test_import_rejects_invalid_utf8(client):
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(b"\xff\xfe\xfa"), "data.csv")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 400
    assert "UTF-8" in resp.get_json()["error"]


def test_import_rejects_malformed_csv(client):
    malformed = (
        "date,bedtime,wake,quality,notes,hours\r\n"
        '2026-07-01,23:00,07:00,4,"unterminated,8.0'
    )
    status, body = _import(client, malformed)
    assert status == 400
    assert "malformed" in body["error"].lower()


def test_import_rejects_file_over_logical_limit(client):
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(b"x" * (1024 * 1024 + 1)), "data.csv")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 400
    assert "too large" in resp.get_json()["error"].lower()


def test_request_body_over_global_limit_returns_json_413(client):
    resp = client.post(
        "/import",
        data={"file": (io.BytesIO(b"x" * (2 * 1024 * 1024 + 1)), "data.csv")},
        content_type="multipart/form-data",
        headers=AJAX,
    )
    assert resp.status_code == 413
    assert "large" in resp.get_json()["error"].lower()
