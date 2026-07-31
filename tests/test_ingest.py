"""Contract and boundary tests for POST /api/ingest."""

import io
import json
from datetime import date, timedelta

import pytest
from werkzeug.test import EnvironBuilder

import app as app_module
import database


def _record(**overrides):
    record = {
        "date": "2024-01-02",
        "bedtime": "23:00",
        "wake": "07:00",
        "source": "apple_health",
        "stages": {"deep": 60, "rem": 90, "light": 300, "awake": 30},
        "efficiency": 92.5,
        "notes": "synced",
    }
    record.update(overrides)
    return record


def _post(client, payload, **kwargs):
    return client.post("/api/ingest", json=payload, **kwargs)


def test_ingest_single_object_persists_complete_wearable_shape(client):
    response = _post(client, _record(source="fitbit", quality=5))

    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "ok": True,
        "imported": 1,
        "replaced": 0,
        "skipped": 0,
        "stats": body["stats"],
    }
    record = database.get_all_records()[0]
    assert record["date"] == "2024-01-02"
    assert record["bedtime"] == "23:00"
    assert record["wake"] == "07:00"
    assert record["quality"] == 5
    assert record["notes"] == "synced"
    assert record["source"] == "fitbit"
    assert record["stages"] == {
        "deep": 60,
        "rem": 90,
        "light": 300,
        "awake": 30,
    }
    assert record["efficiency"] == 92.5
    assert body["stats"]["total"] == 1


def test_ingest_array_applies_all_valid_records(client):
    response = _post(
        client,
        [
            _record(),
            _record(
                date="2024-01-03",
                source="fitbit",
                stages=None,
                efficiency=None,
                notes="",
            ),
        ],
    )

    assert response.status_code == 200
    body = response.get_json()
    assert (body["imported"], body["replaced"], body["skipped"]) == (2, 0, 0)
    assert body["stats"]["total"] == 2
    assert "errors" not in body


def test_ingest_derives_quality_from_stages(client):
    body = _post(client, _record()).get_json()

    assert body["ok"] is True
    assert database.get_all_records()[0]["quality"] == 4


@pytest.mark.parametrize("quality", [None])
def test_ingest_null_quality_is_treated_as_absent(client, quality):
    body = _post(
        client,
        _record(quality=quality, stages=None, efficiency=None),
    ).get_json()

    assert body["ok"] is True
    assert database.get_all_records()[0]["quality"] == 3


def test_ingest_without_quality_or_stages_gets_neutral_quality(client):
    record = _record()
    record.pop("stages")
    record.pop("efficiency")
    record.pop("source")

    response = _post(client, record)

    assert response.status_code == 200
    stored = database.get_all_records()[0]
    assert stored["quality"] == 3
    assert stored["source"] == "apple_health"
    assert stored["stages"] is None
    assert stored["efficiency"] is None


def test_ingest_reimport_updates_in_place(client):
    first = _post(client, _record(quality=4)).get_json()
    original_id = database.get_all_records()[0]["id"]

    second = _post(
        client,
        _record(quality=5, notes="updated", efficiency=88),
    ).get_json()

    assert (first["imported"], first["replaced"]) == (1, 0)
    assert (second["imported"], second["replaced"]) == (0, 1)
    records = database.get_all_records()
    assert len(records) == 1
    assert records[0]["id"] == original_id
    assert records[0]["quality"] == 5
    assert records[0]["notes"] == "updated"
    assert records[0]["efficiency"] == 88.0


def test_ingest_same_date_from_different_sources_coexists(client):
    first = _post(client, _record(source="apple_health")).get_json()
    second = _post(client, _record(source="fitbit")).get_json()

    assert first["imported"] == second["imported"] == 1
    assert {record["source"] for record in database.get_all_records()} == {
        "apple_health",
        "fitbit",
    }


def test_ingest_partial_batch_applies_valid_items_and_indexes_errors(client):
    response = _post(
        client,
        [
            _record(),
            {**_record(date="2024-01-03"), "quality": 0},
            "not an object",
        ],
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert (body["imported"], body["replaced"], body["skipped"]) == (1, 0, 2)
    assert [error["index"] for error in body["errors"]] == [1, 2]
    assert body["stats"]["total"] == 1
    assert len(database.get_all_records()) == 1


def test_ingest_all_invalid_batch_is_not_reported_as_ok(client):
    response = _post(
        client,
        [{"date": "bad"}, 42, None],
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert (body["imported"], body["replaced"], body["skipped"]) == (0, 0, 3)
    assert len(body["errors"]) == 3
    assert body["stats"]["total"] == 0
    assert database.get_all_records() == []


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/problem+json", "application/octet-stream"],
)
def test_ingest_requires_application_json(client, content_type):
    response = client.post(
        "/api/ingest",
        data=json.dumps(_record()),
        content_type=content_type,
    )

    assert response.status_code == 415
    assert "application/json" in response.get_json()["error"]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"\xff",
        b'{"date": NaN}',
        b'{"efficiency": Infinity}',
    ],
)
def test_ingest_rejects_malformed_or_nonstandard_json(client, raw):
    response = client.post(
        "/api/ingest",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Malformed JSON."


@pytest.mark.parametrize("payload", [None, True, False, 7, 2.5, "record"])
def test_ingest_rejects_non_container_top_level_json(client, payload):
    response = client.post(
        "/api/ingest",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "object or array" in response.get_json()["error"]


def test_ingest_rejects_empty_array(client):
    response = _post(client, [])

    assert response.status_code == 400
    assert "empty" in response.get_json()["error"]


@pytest.mark.parametrize("missing", ["date", "bedtime", "wake"])
def test_ingest_rejects_missing_required_fields(client, missing):
    record = _record()
    record.pop(missing)

    response = _post(client, record)

    assert response.status_code == 400
    error = response.get_json()["errors"][0]["error"]
    assert missing in error


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("date", "2024-1-02", "date"),
        ("date", "2024-02-30", "date"),
        ("bedtime", "9:00", "bedtime"),
        ("bedtime", "24:00", "bedtime"),
        ("wake", "7:00", "wake"),
        ("wake", "07:60", "wake"),
        ("notes", 123, "Notes"),
        ("notes", "x" * 501, "500"),
    ],
)
def test_ingest_rejects_invalid_core_fields(client, field, value, message):
    response = _post(client, _record(**{field: value}))

    assert response.status_code == 400
    assert message in response.get_json()["errors"][0]["error"]


def test_ingest_rejects_future_date(client):
    future = (database.get_today() + timedelta(days=1)).isoformat()

    response = _post(client, _record(date=future))

    assert response.status_code == 400
    assert "future" in response.get_json()["errors"][0]["error"].lower()


@pytest.mark.parametrize("quality", [True, False, 0, 6, 4.0, "4", [], {}])
def test_ingest_rejects_invalid_explicit_quality(client, quality):
    response = _post(client, _record(quality=quality))

    assert response.status_code == 400
    assert "Quality" in response.get_json()["errors"][0]["error"]


@pytest.mark.parametrize(
    "source",
    ["manual", "oura", "", None, 42, True, [], {}],
)
def test_ingest_rejects_non_wearable_source(client, source):
    response = _post(client, _record(source=source))

    assert response.status_code == 400
    assert "Source" in response.get_json()["errors"][0]["error"]


@pytest.mark.parametrize(
    "stages",
    [
        [],
        {"deep": 60, "rem": 90, "light": 330},
        {"deep": 60, "rem": 90, "light": 300, "awake": 30, "other": 0},
    ],
)
def test_ingest_requires_exact_stage_object_shape(client, stages):
    response = _post(client, _record(stages=stages))

    assert response.status_code == 400
    assert "exactly" in response.get_json()["errors"][0]["error"]


@pytest.mark.parametrize(
    ("stage", "value"),
    [
        ("deep", -1),
        ("rem", 1.5),
        ("light", True),
        ("awake", "30"),
        ("deep", None),
    ],
)
def test_ingest_requires_nonnegative_integer_stage_minutes(client, stage, value):
    stages = dict(_record()["stages"])
    stages[stage] = value

    response = _post(client, _record(stages=stages))

    assert response.status_code == 400
    assert stage in response.get_json()["errors"][0]["error"]


def test_ingest_rejects_stage_total_inconsistent_with_interval(client):
    response = _post(
        client,
        _record(stages={"deep": 10, "rem": 10, "light": 10, "awake": 10}),
    )

    assert response.status_code == 400
    assert "expected 480" in response.get_json()["errors"][0]["error"]


def test_ingest_accepts_one_minute_stage_rounding_difference(client):
    response = _post(
        client,
        _record(stages={"deep": 60, "rem": 90, "light": 299, "awake": 30}),
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True


@pytest.mark.parametrize(
    "efficiency",
    [True, False, -0.1, 100.1, "90", [], {}, 10**1000],
)
def test_ingest_rejects_invalid_efficiency(client, efficiency):
    response = _post(client, _record(efficiency=efficiency))

    assert response.status_code == 400
    assert "Efficiency" in response.get_json()["errors"][0]["error"]


def test_ingest_rejects_overflowed_but_valid_json_efficiency(client):
    record = _record()
    record.pop("efficiency")
    raw = json.dumps(record)[:-1] + ',"efficiency":1e309}'

    response = client.post(
        "/api/ingest",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "Efficiency" in response.get_json()["errors"][0]["error"]


@pytest.mark.parametrize("efficiency", [0, 100, 87.25])
def test_ingest_accepts_efficiency_boundaries(client, efficiency):
    response = _post(client, _record(efficiency=efficiency))

    assert response.status_code == 200
    assert database.get_all_records()[0]["efficiency"] == float(efficiency)


def test_ingest_accepts_exactly_one_hundred_records(client):
    start = date(2024, 1, 1)
    records = [
        _record(
            date=(start + timedelta(days=offset)).isoformat(),
            stages=None,
            efficiency=None,
        )
        for offset in range(100)
    ]

    response = _post(client, records)

    assert response.status_code == 200
    assert response.get_json()["imported"] == 100
    assert len(database.get_all_records()) == 100


def test_ingest_rejects_more_than_one_hundred_records(client):
    response = _post(client, [_record()] * 101)

    assert response.status_code == 400
    assert "at most 100" in response.get_json()["error"]
    assert database.get_all_records() == []


def test_ingest_accepts_body_at_exact_byte_limit(client):
    raw = json.dumps(
        _record(stages=None, efficiency=None),
        separators=(",", ":"),
    ).encode()
    raw += b" " * (app_module.MAX_INGEST_BYTES - len(raw))

    response = client.post(
        "/api/ingest",
        data=raw,
        content_type="application/json",
    )

    assert len(raw) == app_module.MAX_INGEST_BYTES
    assert response.status_code == 200


def test_ingest_rejects_body_over_one_mib(client):
    raw = b'{"padding":"' + b"x" * app_module.MAX_INGEST_BYTES + b'"}'

    response = client.post(
        "/api/ingest",
        data=raw,
        content_type="application/json",
    )

    assert response.status_code == 413
    assert "large" in response.get_json()["error"].lower()


def test_ingest_enforces_limit_without_content_length(client):
    raw = b'{"padding":"' + b"x" * app_module.MAX_INGEST_BYTES + b'"}'
    builder = EnvironBuilder(
        path="/api/ingest",
        method="POST",
        input_stream=io.BytesIO(raw),
        content_type="application/json",
    )
    environ = builder.get_environ()
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True

    response = client.open(environ)

    assert response.status_code == 413
    assert "large" in response.get_json()["error"].lower()


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://attacker.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_ingest_preserves_cross_site_mutation_protection(client, headers):
    response = _post(client, _record(), headers=headers)

    assert response.status_code == 403
    assert database.get_all_records() == []


def test_ingest_requires_basic_auth_when_configured(client, monkeypatch):
    monkeypatch.setenv("SLEEP_USERNAME", "sync-user")
    monkeypatch.setenv("SLEEP_PASSWORD", "sync-password")

    missing = _post(client, _record())
    wrong = client.post(
        "/api/ingest",
        json=_record(),
        auth=("sync-user", "wrong"),
    )
    allowed = client.post(
        "/api/ingest",
        json=_record(),
        auth=("sync-user", "sync-password"),
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert len(database.get_all_records()) == 1
