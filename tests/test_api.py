"""Route tests for app.py via Flask's test client (no live server)."""
import csv
import io
from datetime import timedelta

import pytest

AJAX = {"X-Requested-With": "XMLHttpRequest"}

VALID = {
    "date": "2026-07-01",
    "bedtime": "23:00",
    "wake": "07:00",
    "quality": "4",
    "notes": "slept fine",
}


def _d(days_ago):
    import database

    return (database.get_today() - timedelta(days=days_ago)).isoformat()


def _add(client, **overrides):
    data = {**VALID, **overrides}
    resp = client.post("/add", data=data, headers=AJAX)
    assert resp.status_code == 200
    return resp.get_json()


# ── POST /add ─────────────────────────────────────────────────

def test_add_ajax_success_payload(client):
    body = _add(client)
    assert body["ok"] is True
    assert len(body["records"]) == 1
    rec = body["records"][0]
    assert rec["date"] == VALID["date"]
    assert rec["bedtime"] == VALID["bedtime"]
    assert rec["wake"] == VALID["wake"]
    assert rec["quality"] == 4
    assert rec["notes"] == VALID["notes"]
    assert rec["hours"] == 8.0
    assert body["stats"]["total"] == 1
    assert len(body["stats"]["series"]) == 30


@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "07/01/2026"),
        ("date", "2026-13-01"),
        ("date", "2026-7-01"),
        ("date", "not-a-date"),
        ("bedtime", "25:00"),
        ("bedtime", "7:00"),
        ("bedtime", "11pm"),
        ("wake", "7:00am"),
        ("wake", "99:99"),
        ("quality", "0"),
        ("quality", "6"),
        ("quality", "great"),
        ("quality", ""),
    ],
)
def test_add_ajax_validation_failure_400(client, field, value):
    resp = client.post("/add", data={**VALID, field: value}, headers=AJAX)
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert body["error"]


def test_add_ajax_missing_fields_are_rejected(client):
    resp = client.post("/add", data={}, headers=AJAX)
    assert resp.status_code == 400
    assert "error" in resp.get_json()
    import database

    assert database.get_all_records() == []


def test_add_non_ajax_redirects(client):
    resp = client.post("/add", data=VALID)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    import database
    assert len(database.get_all_records()) == 1


def test_add_non_ajax_bad_input_redirects_without_saving(client):
    resp = client.post("/add", data={**VALID, "date": "bad"})
    assert resp.status_code == 302
    import database
    assert database.get_all_records() == []


def test_add_notes_over_500_rejected(client):
    resp = client.post(
        "/add", data={**VALID, "notes": "x" * 501}, headers=AJAX
    )
    assert resp.status_code == 400
    assert "500" in resp.get_json()["error"]


def test_add_future_date_rejected(client):
    import database

    future = (database.get_today() + timedelta(days=1)).isoformat()
    resp = client.post(
        "/add", data={**VALID, "date": future}, headers=AJAX
    )
    assert resp.status_code == 400
    assert "future" in resp.get_json()["error"].lower()


# ── POST /edit/<id> ───────────────────────────────────────────

def test_edit_success(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(
        f"/edit/{rec_id}",
        data={**VALID, "bedtime": "22:30", "wake": "06:15", "quality": "5", "notes": "edited"},
        headers=AJAX,
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    rec = body["records"][0]
    assert rec["id"] == rec_id
    assert rec["hours"] == 7.75
    assert rec["quality"] == 5
    assert rec["notes"] == "edited"


def test_edit_unknown_id_404(client):
    resp = client.post("/edit/99999", data=VALID, headers=AJAX)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Record not found."


def test_edit_bad_input_400(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(f"/edit/{rec_id}", data={**VALID, "quality": "9"}, headers=AJAX)
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_edit_notes_over_500_rejected_without_changing_record(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(f"/edit/{rec_id}", data={**VALID, "notes": "y" * 700}, headers=AJAX)
    assert resp.status_code == 400
    import database

    assert database.get_records()[0]["notes"] == VALID["notes"]


# ── POST /delete/<id> ─────────────────────────────────────────

def test_delete_ajax(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(f"/delete/{rec_id}", headers=AJAX)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["records"] == []
    assert body["stats"]["total"] == 0


def test_delete_unknown_id_ajax_still_ok(client):
    # Actual behavior: no existence check; deleting a missing id returns ok.
    resp = client.post("/delete/424242", headers=AJAX)
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_delete_non_ajax_redirects(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(f"/delete/{rec_id}")
    assert resp.status_code == 302
    import database
    assert database.get_all_records() == []


def test_delete_non_ajax_does_not_redirect_to_external_referer(client):
    rec_id = _add(client)["records"][0]["id"]
    resp = client.post(
        f"/delete/{rec_id}", headers={"Referer": "https://attacker.example/path"}
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


# ── GET /api/records ──────────────────────────────────────────

def test_api_records_limit(client):
    for i in range(5):
        _add(client, date=_d(i))
    resp = client.get("/api/records?limit=3")
    assert resp.status_code == 200
    records = resp.get_json()
    assert len(records) == 3
    assert [r["date"] for r in records] == [_d(0), _d(1), _d(2)]  # newest first

    # Default limit (30) returns all 5.
    assert len(client.get("/api/records").get_json()) == 5


@pytest.mark.parametrize("value", ["abc", "0", "-1", "10001", "999999999999999999999"])
def test_api_records_invalid_limit_400(client, value):
    resp = client.get(f"/api/records?limit={value}")
    assert resp.status_code == 400
    assert "limit" in resp.get_json()["error"]


def test_api_records_record_shape(client):
    _add(client)
    rec = client.get("/api/records").get_json()[0]
    assert set(rec) == {
        "id", "date", "bedtime", "wake", "quality", "notes", "hours",
        "source", "stages", "efficiency",
    }
    assert rec["source"] == "manual"
    assert rec["stages"] is None
    assert rec["efficiency"] is None


# ── GET /api/stats ────────────────────────────────────────────

def test_api_stats_shape(client):
    _add(client, date=_d(0))
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    stats = resp.get_json()
    assert set(stats) == {
        "total", "avg_hours", "avg_quality", "current_streak", "best_streak",
        "series", "sleep_debt",
    }
    assert stats["total"] == 1
    assert len(stats["series"]) == 30
    assert set(stats["series"][0]) == {"date", "hours", "quality"}
    import database

    assert stats["series"][-1]["date"] == database.get_today().isoformat()


# ── GET /export.csv ───────────────────────────────────────────

def test_export_csv(client):
    tricky_notes = 'said "great", then left'
    _add(client, notes=tricky_notes)
    resp = client.get("/export.csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment")
    assert "sleep-records.csv" in disposition

    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows[0] == ["date", "bedtime", "wake", "quality", "notes", "hours"]
    assert len(rows) == 2
    # Commas/quotes in notes survive CSV quoting round-trip
    assert rows[1] == [VALID["date"], "23:00", "07:00", "4", tricky_notes, "8.0"]


def test_export_csv_empty_db(client):
    resp = client.get("/export.csv")
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.get_data(as_text=True))))
    assert rows == [["date", "bedtime", "wake", "quality", "notes", "hours"]]


@pytest.mark.parametrize("note", ["=1+1", " +SUM(A1:A2)", "@cmd", "'literal"])
def test_export_csv_neutralizes_spreadsheet_formulas(client, note):
    _add(client, notes=note)
    rows = list(csv.reader(io.StringIO(client.get("/export.csv").get_data(as_text=True))))
    assert rows[1][4].startswith("'")
    assert rows[1][4] != note


# ── Extra endpoints ───────────────────────────────────────────

def test_api_insights_shape(client):
    _add(client, date=_d(0))
    resp = client.get("/api/insights")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body) == {
        "stats", "streak", "consistency", "weekly", "day_of_week", "best_worst", "monthly",
    }
    assert body["streak"] == 1
    assert isinstance(body["consistency"], int)
    assert isinstance(body["weekly"], list)
    assert len(body["day_of_week"]) == 7
    assert set(body["best_worst"]) == {"best", "worst"}
    assert len(body["monthly"]) == 6


def test_api_export(client):
    _add(client)
    resp = client.get("/api/export")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["hours"] == 8.0


# ── Settings routes ───────────────────────────────────────────

def test_settings_update(client):
    resp = client.post(
        "/settings/update", data={"sleep_goal": "8", "bedtime_goal": "22:45"}
    )
    assert resp.status_code == 302
    import database
    settings = database.get_all_settings()
    assert settings["sleep_goal"] == 8.0
    assert settings["bedtime_goal"] == "22:45"


def test_settings_update_invalid_goal_ignored(client):
    resp = client.post("/settings/update", data={"sleep_goal": "not-a-number"})
    assert resp.status_code == 302
    import database
    assert database.get_all_settings()["sleep_goal"] == 8.0  # default kept


@pytest.mark.parametrize("goal", ["nan", "inf", "-1", "0", "25"])
def test_settings_update_rejects_nonfinite_or_out_of_range_goal(client, goal):
    client.post("/settings/update", data={"sleep_goal": goal})
    import database

    assert database.get_all_settings()["sleep_goal"] == 8.0


def test_settings_update_rejects_invalid_bedtime(client):
    client.post("/settings/update", data={"bedtime_goal": "night"})
    import database

    assert database.get_all_settings()["bedtime_goal"] == "23:00"


def test_settings_clear(client):
    _add(client)
    resp = client.post("/settings/clear")
    assert resp.status_code == 302
    import database
    assert database.get_all_records() == []


# ── GET / ──────────────────────────────────────────────────────

def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "window.__INITIAL_RECORDS__" in html
    assert "window.__INITIAL_STATS__" in html
    assert 'id="import-file"' in html
    assert 'id="load-more"' in html
    assert 'id="sleep-goal"' in html
    assert 'id="patterns"' in html
    assert 'id="pattern-year"' in html
    assert 'id="heatmap"' in html
    assert 'id="month-a"' in html
    assert 'id="season-a"' in html


def test_healthz_is_public_when_auth_enabled(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 401


def test_robots_txt_is_public_and_disallows_indexing(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    assert resp.get_data(as_text=True) == "User-agent: *\nDisallow: /\n"


def test_basic_auth_protects_private_routes(client, monkeypatch):
    monkeypatch.setenv("SLEEP_USERNAME", "owner")
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")

    denied = client.get("/api/stats")
    assert denied.status_code == 401
    assert denied.headers["WWW-Authenticate"].startswith("Basic")
    allowed = client.get("/api/stats", auth=("owner", "secret"))
    assert allowed.status_code == 200


# ── session login ──────────────────────────────────────────────

HTML_ACCEPT = {"Accept": "text/html,application/xhtml+xml"}


def test_login_page_renders_without_credentials(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Sign in to your sleep log" in resp.get_data(as_text=True)


def test_browser_navigation_redirects_to_login(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.get("/", headers=HTML_ACCEPT)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")


def test_bare_get_without_accept_still_gets_basic_challenge(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.get("/")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_login_success_establishes_session(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.post(
        "/login", data={"username": "sleep", "password": "secret"}
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    assert client.get("/", headers=HTML_ACCEPT).status_code == 200


def test_login_wrong_credentials_shows_error(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.post(
        "/login", data={"username": "sleep", "password": "nope"}
    )
    assert resp.status_code == 401
    assert "Wrong username or password." in resp.get_data(as_text=True)


@pytest.mark.parametrize(
    "target", ["https://evil.example", "//evil.example"]
)
def test_login_next_param_rejects_open_redirects(client, monkeypatch, target):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    resp = client.post(
        "/login",
        data={"username": "sleep", "password": "secret", "next": target},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_logout_clears_session(client, monkeypatch):
    monkeypatch.setenv("SLEEP_PASSWORD", "secret")
    client.post("/login", data={"username": "sleep", "password": "secret"})
    resp = client.post("/logout")
    assert resp.status_code == 302
    denied = client.get("/", headers=HTML_ACCEPT)
    assert denied.status_code == 302
    assert denied.headers["Location"].startswith("/login")


def test_login_redirects_home_when_auth_disabled(client):
    resp = client.get("/login")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "https://attacker.example"},
    ],
)
def test_cross_site_mutations_rejected(client, headers):
    resp = client.post("/add", data=VALID, headers={**AJAX, **headers})
    assert resp.status_code == 403


def test_security_headers_and_no_store(client):
    resp = client.get("/")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Cache-Control"] == "no-store"
