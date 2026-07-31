import os
import sys

import pytest

# Make app.py / database.py importable regardless of how pytest is invoked.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point SLEEP_DB_PATH at a fresh temp file for every test.

    database._db_path() reads the env var at call time (it is not cached at
    import), so monkeypatch.setenv is sufficient -- no module reload needed.
    tmp_path is created and cleaned up per-test by pytest.
    """
    path = tmp_path / "sleep-test.db"
    monkeypatch.setenv("SLEEP_DB_PATH", str(path))
    monkeypatch.setenv("SLEEP_TIMEZONE", "America/New_York")
    monkeypatch.delenv("SLEEP_PASSWORD", raising=False)
    monkeypatch.delenv("SLEEP_USERNAME", raising=False)
    yield str(path)


@pytest.fixture()
def client(temp_db):
    """Flask test client bound to the per-test temp database."""
    import app as app_module

    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c
