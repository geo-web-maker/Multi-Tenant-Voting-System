"""There is no "legacy / no-org" tenant: a missing organization must fail closed, never widen a query.

Covers the removal of org_id=None fallbacks: org_query / org_stamp / _oq raise instead of returning an
unscoped filter, the REQUIRE_ORG_CONTEXT escape hatch is gone, header-less staff logins are refused,
and destructive helpers only ever work on one named tenant.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import main
import backup
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


NO_ORG = {"X-Org-Slug": ""}      # the env client sends X-Org-Slug: t1 by default; blank it per request


def _req(org_id):
    return SimpleNamespace(state=SimpleNamespace(org_id=org_id))


# ---- query / stamp helpers -----------------------------------------------------------------------
def test_org_query_scopes_to_the_tenant():
    assert main.org_query(_req("o1"), {"a": 1}) == {"a": 1, "org_id": "o1"}


@pytest.mark.parametrize("missing", [None, ""])
def test_org_query_refuses_without_a_tenant(missing):
    with pytest.raises(HTTPException) as e:
        main.org_query(_req(missing), {"a": 1})
    assert e.value.status_code == 400


def test_org_query_refuses_when_state_has_no_org_attribute():
    with pytest.raises(HTTPException):
        main.org_query(SimpleNamespace(state=SimpleNamespace()))


def test_org_stamp_stamps_and_refuses():
    assert main.org_stamp(_req("o1"), {"x": 1}) == {"x": 1, "org_id": "o1"}
    with pytest.raises(HTTPException):
        main.org_stamp(_req(None), {"x": 1})


def test_oq_refuses_without_a_tenant():
    assert main._oq("o1", {"a": 1}) == {"a": 1, "org_id": "o1"}
    with pytest.raises(HTTPException):
        main._oq(None)


async def test_org_scoped_helpers_refuse_without_a_tenant():
    with pytest.raises(HTTPException):
        await main.get_commissioner_count(None)
    with pytest.raises(HTTPException):
        await main._resolve_position_title("507f1f77bcf86cd799439011", None)
    with pytest.raises(HTTPException):
        await main._position_fee("507f1f77bcf86cd799439011", None)
    with pytest.raises(HTTPException):
        await main._create_candidate_from_application({"_id": "x"}, None)


def test_the_unscoped_escape_hatch_is_gone():
    assert not hasattr(main, "REQUIRE_ORG_CONTEXT")


# ---- HTTP behaviour -------------------------------------------------------------------------------
async def test_header_less_request_is_rejected(env):
    r = await env.client.get("/candidates", headers=NO_ORG)
    assert r.status_code == 400


async def test_header_less_reset_election_is_rejected_and_wipes_nothing(env):
    await env.db.voters.insert_one({"student_id": "keepme", "org_id": env.org_id, "has_voted": True})
    r = await env.client.post("/admin/reset-election", headers={**env.sa, **NO_ORG})   # superadmin token, no org
    assert r.status_code == 400
    assert (await env.db.voters.find_one({"student_id": "keepme"}))["has_voted"] is True


async def test_non_superadmin_login_without_a_tenant_is_refused(env):
    # Would previously search EVERY client's staff by e-mail.
    await env.db.voters.insert_one({"student_id": "it1", "org_id": env.org_id, "is_it_admin": True,
                                    "it_admin_email": "it@example.com", "it_admin_password_hash": "x"})
    r = await env.client.post("/verify-admin", json={"email": "it@example.com", "password": "whatever"}, headers=NO_ORG)
    assert r.status_code == 400


# ---- destructive helpers are single-tenant ------------------------------------------------------
async def test_pre_destructive_snapshot_requires_an_org():
    with pytest.raises(backup.BackupError):
        await backup.snapshot_before_destructive(object(), None, "reset-election")
    with pytest.raises(TypeError):
        await backup.snapshot_before_destructive(object(), "o1", "x", all_tenants=True)


def test_wipe_script_filters_are_tenant_scoped():
    wipe = pytest.importorskip("wipe_election_data")
    assert wipe.tenant_filter("voters", "o1") == {"org_id": "o1"}
    assert wipe.tenant_filter("sms_usage", "o1") == {"org_key": "o1"}
    assert wipe.tenant_filter("otp_send_state", "o1")["key"]["$regex"].startswith("^o1:")
    assert "ip_send_stats" in wipe.GLOBAL_COLLECTIONS
