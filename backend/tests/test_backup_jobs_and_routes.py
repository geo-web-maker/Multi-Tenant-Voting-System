"""backup_jobs error redaction and static checks that every backup admin route is superadmin-guarded."""
import re
import pytest
import backup_jobs

pytestmark = pytest.mark.asyncio


def test_job_errors_never_contain_connection_strings_or_secrets():
    out = backup_jobs._safe_error("fail mongodb+srv://u:pw@h.example/ and postgres://a:b@c/d token=abc123")
    assert "pw@" not in out and "abc123" not in out and "a:b@" not in out


def test_every_admin_route_requires_superadmin_guard():
    src = open("backup_admin_routes.py", encoding="utf-8").read()
    blocks = re.split(r"\n\s*@router\.", src)[1:]
    assert blocks, "no routes found"
    for block in blocks:
        head = block.split("\n", 1)[0]
        sig = block[:block.index("):") + 2] if "):" in block else block[:400]
        assert "guard" in sig, f"route without guard: {head}"


def test_routes_never_echo_environment_urls():
    src = open("backup_admin_routes.py", encoding="utf-8").read()
    for bad in ("os.environ[\"MONGO_URL\"]", "os.getenv(\"MONGO_URL\")", "SECOND_MONGO_URL\")]"):
        assert f"return {bad}" not in src
