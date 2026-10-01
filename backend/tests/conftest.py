import os, sys
os.environ.setdefault("SUPER_ADMIN_ID", "root")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "x")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("DEBUG_MODE", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


import pytest


@pytest.fixture(autouse=True)
def _reset_org_cache():
    """The 60 s slug->org_id cache would otherwise leak one test's org id into the next
    (every test builds a fresh in-memory DB with a fresh ObjectId under the same slug)."""
    import main
    main._ORG_CACHE.clear()
    yield
    main._ORG_CACHE.clear()


@pytest.fixture(autouse=True)
def _settings_cache_off_by_default(monkeypatch):
    """Tests mutate db.settings directly and expect the next request to see it, so the settings cache is
    disabled unless a test opts in (tests/test_settings_cache.py sets _SETTINGS_TTL itself)."""
    import main
    monkeypatch.setattr(main, "_SETTINGS_TTL", 0.0)
    main.invalidate_settings()
    yield
    main.invalidate_settings()
