"""GET /api/summary — Claude weekly summary endpoint (Anthropic client mocked).

No test in this file may reach the network: the module's client factory
(`ai_summary._make_client`) is monkeypatched everywhere a key is present, and
an autouse fixture strips ANTHROPIC_API_KEY and points the module's .env
lookup at a nonexistent file so the developer's real key can never leak in.
"""

from types import SimpleNamespace

import anthropic
import httpx
import pytest

import ai_summary
import database

TEST_KEY = "sk-ant-test-secret-key-000"


@pytest.fixture(autouse=True)
def no_real_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        ai_summary, "_PROJECT_ENV_PATH", str(tmp_path / "absent.env")
    )


def _seed_nights(n=8, start_day=1):
    for i in range(n):
        database.add_record(f"2026-06-{start_day + i:02d}", "23:00", "07:00", 4)


def _response(text="You slept a steady week.", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


class FakeClient:
    """Stands in for anthropic.Anthropic; records messages.create calls."""

    def __init__(self, result):
        self.result = result
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _install(monkeypatch, fake):
    monkeypatch.setattr(ai_summary, "_make_client", lambda key, env: fake)


def _rate_limit_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None
    )


# ── No key ────────────────────────────────────────────────────

def test_no_key_reports_unavailable_and_builds_no_client(client, monkeypatch):
    def forbidden(key, env):
        raise AssertionError("client must not be constructed without a key")

    monkeypatch.setattr(ai_summary, "_make_client", forbidden)
    response = client.get("/api/summary")
    assert response.status_code == 200
    assert response.get_json() == {"available": False, "reason": "no_api_key"}


# ── Success + caching ─────────────────────────────────────────

def test_success_then_cache_hit_calls_api_once(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()
    fake = FakeClient(_response("A calm, consistent week of sleep."))
    _install(monkeypatch, fake)

    first = client.get("/api/summary").get_json()
    assert first["available"] is True
    assert first["summary"] == "A calm, consistent week of sleep."
    assert first["cached"] is False
    assert first["generated_at"]

    second = client.get("/api/summary").get_json()
    assert second["available"] is True
    assert second["summary"] == first["summary"]
    assert second["cached"] is True
    assert len(fake.calls) == 1  # reload served from the settings cache

    # Model invocation follows the pinned contract.
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["max_tokens"] == 2048
    assert "temperature" not in call and "thinking" not in call


def test_key_from_env_file_when_env_var_unset(client, tmp_path, monkeypatch):
    env_file = tmp_path / "dot.env"
    env_file.write_text(
        "# Local secrets — never commit\n"
        f"ANTHROPIC_API_KEY={TEST_KEY}\n"
    )
    monkeypatch.setattr(ai_summary, "_PROJECT_ENV_PATH", str(env_file))
    _seed_nights()
    fake = FakeClient(_response())
    seen = {}

    def factory(key, from_env):
        seen["key"] = key
        seen["from_env"] = from_env
        return fake

    monkeypatch.setattr(ai_summary, "_make_client", factory)
    body = client.get("/api/summary").get_json()
    assert body["available"] is True
    assert seen == {"key": TEST_KEY, "from_env": False}


def test_fingerprint_change_regenerates(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()
    fake = FakeClient(_response())
    _install(monkeypatch, fake)

    assert client.get("/api/summary").get_json()["cached"] is False
    assert len(fake.calls) == 1

    database.add_record("2026-06-20", "22:30", "06:30", 5)  # data changed
    body = client.get("/api/summary").get_json()
    assert body["cached"] is False
    assert len(fake.calls) == 2


# ── Failure paths ─────────────────────────────────────────────

def test_refusal_stop_reason_is_api_error(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()
    _install(monkeypatch, FakeClient(_response(stop_reason="refusal")))

    response = client.get("/api/summary")
    assert response.status_code == 200
    assert response.get_json() == {"available": False, "reason": "api_error"}


def test_rate_limit_error_is_api_error(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()
    _install(monkeypatch, FakeClient(_rate_limit_error()))

    response = client.get("/api/summary")
    assert response.status_code == 200
    assert response.get_json() == {"available": False, "reason": "api_error"}


def test_api_error_does_not_poison_the_cache(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()
    failing = FakeClient(_rate_limit_error())
    _install(monkeypatch, failing)
    assert client.get("/api/summary").get_json()["reason"] == "api_error"

    working = FakeClient(_response("Recovered."))
    _install(monkeypatch, working)
    body = client.get("/api/summary").get_json()
    assert body == {
        "available": True,
        "summary": "Recovered.",
        "generated_at": body["generated_at"],
        "cached": False,
    }


# ── Key hygiene ───────────────────────────────────────────────

def test_key_never_appears_in_response_body(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", TEST_KEY)
    _seed_nights()

    _install(monkeypatch, FakeClient(_response()))
    assert TEST_KEY not in client.get("/api/summary").get_data(as_text=True)

    _install(monkeypatch, FakeClient(_rate_limit_error()))
    # Force a regenerate attempt despite the cached success: new data.
    database.add_record("2026-06-21", "23:15", "07:15", 3)
    assert TEST_KEY not in client.get("/api/summary").get_data(as_text=True)
