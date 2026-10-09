"""SEC audit "Open" items 3, 4, 5: ballot-secrecy timing, per-email login throttling, data minimisation."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

import main
from tests.test_flows import env, tick, Clock  # noqa: F401  (fixture + frozen clock)

pytestmark = pytest.mark.asyncio


# ---- item 5: data minimisation ---------------------------------------------------------------

_APP = {"status": "pending", "finance_cleared": True, "fee_required": 5000,
        "payment_method": "MTN", "payment_proof_url": "https://x/receipt.jpg",
        "finance_clear_note": "ok", "finance_rejection_reason": "blurry",
        "finance_history": [{"action": "clearance_reversed", "reason": "forged"}], "votes": {}}


@pytest.mark.parametrize("role", ["vetting", "overseer", "commission"])
def test_non_finance_roles_get_no_payment_details(role):
    out = main.shape_application_for_role(dict(_APP), role)
    for f in main._FINANCE_ONLY_APPLICATION_FIELDS:
        assert f not in out
    assert out["finance_cleared"] is True and out["fee_required"] == 5000   # dashboards still need these


def test_it_admin_gets_a_whitelisted_stage_only_row():
    out = main.shape_application_for_role(dict(_APP), "it_admin")
    for f in main._FINANCE_ONLY_APPLICATION_FIELDS + ("votes", "fee_required", "finance_cleared"):
        assert f not in out
    assert out["stage"] in main.STAGE_LABELS


@pytest.mark.parametrize("role", ["financial_controller", "superadmin"])
def test_finance_controller_and_superadmin_keep_payment_details(role):
    out = main.shape_application_for_role(dict(_APP), role)
    for f in main._FINANCE_ONLY_APPLICATION_FIELDS:
        assert out[f] == _APP[f]


# ---- item 4: per-email throttling ------------------------------------------------------------

async def test_rotating_ips_cannot_beat_the_per_email_limit(env):  # noqa: F811
    email = "victim@x.org"
    for i in range(main.LOGIN_EMAIL_MAX_ATTEMPTS):
        ip = f"10.0.{i // 250}.{i % 250 + 1}"          # a fresh IP every time: the per-IP limit never trips
        await main.enforce_login_rate_limit(email, env.org_id, ip)
        await main.record_failed_login(email, env.org_id, ip)
    with pytest.raises(HTTPException) as ei:
        await main.enforce_login_rate_limit(email, env.org_id, "203.0.113.99")   # yet another new IP
    assert ei.value.status_code == 429


async def test_per_email_limit_does_not_touch_other_accounts(env):  # noqa: F811
    for i in range(main.LOGIN_EMAIL_MAX_ATTEMPTS):
        await main.record_failed_login("a@x.org", env.org_id, f"10.1.0.{i + 1}")
    await main.enforce_login_rate_limit("b@x.org", env.org_id, "10.9.9.9")        # no raise


async def test_a_successful_login_clears_the_email_counter(env):  # noqa: F811
    for i in range(main.LOGIN_EMAIL_MAX_ATTEMPTS - 1):
        await main.record_failed_login("c@x.org", env.org_id, f"10.2.0.{i + 1}")
    await main.clear_login_attempts("c@x.org", env.org_id, "10.2.0.1")
    await main.record_failed_login("c@x.org", env.org_id, "10.2.1.1")
    await main.enforce_login_rate_limit("c@x.org", env.org_id, "10.2.1.2")        # counter restarted: no raise


async def test_superadmin_email_lock_stays_short(env):  # noqa: F811
    sa = main.SUPER_ADMIN_ID.strip().lower()
    for i in range(main.LOGIN_EMAIL_MAX_ATTEMPTS + 6):
        await main.record_failed_login(sa, env.org_id, f"10.3.0.{i + 1}")
    rec = await env.db.login_attempts.find_one({"key": main._login_email_key(sa, env.org_id)})
    assert rec["locked_until"] - Clock.now <= timedelta(seconds=main.SUPERADMIN_LOCKOUT_SECONDS_CAP + 2)


# ---- item 3: ballot-secrecy timing -----------------------------------------------------------

def test_event_time_is_coarse_and_ids_are_unordered_inside_a_bucket():
    now = datetime(2026, 10, 6, 12, 7, 31, 123456)
    ids, ats = zip(*(main._new_vote_event_stamp(now) for _ in range(50)))
    assert set(ats) == {datetime(2026, 10, 6, 12, 0, 0)}                  # 10-minute bucket, no seconds/micros
    assert len(set(ids)) == 50 and list(ids) != sorted(ids)               # random, not insertion-ordered
    assert all(i.generation_time.replace(tzinfo=None) == datetime(2026, 10, 6, 12, 10, 0) for i in ids)


def test_ids_of_a_later_bucket_always_sort_after_an_earlier_bucket():
    early = main._new_vote_event_stamp(datetime(2026, 10, 6, 12, 9, 59))[0]
    late = main._new_vote_event_stamp(datetime(2026, 10, 6, 12, 10, 0))[0]
    assert early < late


async def _cast(env, when):  # noqa: F811
    oid, at = main._new_vote_event_stamp(when)
    await env.db.vote_events.insert_one({"_id": oid, "org_id": env.org_id, "candidate_id": ObjectId(), "cast_at": at})


def _req(env):  # noqa: F811
    return SimpleNamespace(state=SimpleNamespace(org_id=env.org_id, admin={"sub": "superadmin", "role": "superadmin"}))


async def test_checkpoint_only_seals_ended_buckets_and_chain_still_verifies(env, monkeypatch):  # noqa: F811
    async def _noop(*a, **k): return None
    monkeypatch.setattr(main, "_publish_checkpoint_externally", _noop)
    monkeypatch.setattr(main, "anchor_roster_ledger", _noop)
    now = Clock.now                                                          # env freezes main.datetime
    old = now - timedelta(seconds=main.VOTE_TIME_BUCKET_SECONDS * 3)
    for _ in range(4):
        await _cast(env, old)
    await _cast(env, now)                                                    # still in the open bucket
    req = _req(env)

    cp1 = await main.create_audit_checkpoint(req)
    assert cp1 and cp1["event_count"] == 4                                   # open bucket left out
    assert await main.create_audit_checkpoint(req) is None                   # nothing new is sealed yet
    assert (await main.verify_audit_chain(req))["valid"] is True

    # Time passes: the open bucket seals, and a new event arrives after the first checkpoint.
    tick(seconds=main.VOTE_TIME_BUCKET_SECONDS * 2)
    await _cast(env, Clock.now)
    tick(seconds=main.VOTE_TIME_BUCKET_SECONDS * 2)
    cp2 = await main.create_audit_checkpoint(req)
    assert cp2 and cp2["event_count"] == 2                                   # the earlier open one + the new one
    assert (await main.verify_audit_chain(req))["valid"] is True


async def test_legacy_precise_events_still_checkpoint_and_verify(env, monkeypatch):  # noqa: F811
    async def _noop(*a, **k): return None
    monkeypatch.setattr(main, "_publish_checkpoint_externally", _noop)
    monkeypatch.setattr(main, "anchor_roster_ledger", _noop)
    t = Clock.now - timedelta(hours=2)
    for i in range(3):                                                       # pre-fix shape: ObjectId + exact time
        await env.db.vote_events.insert_one({"_id": ObjectId.from_datetime(t + timedelta(seconds=i)),
                                             "org_id": env.org_id, "candidate_id": ObjectId(),
                                             "cast_at": t + timedelta(seconds=i, microseconds=123)})
    req = _req(env)
    assert (await main.create_audit_checkpoint(req))["event_count"] == 3
    assert (await main.verify_audit_chain(req))["valid"] is True


async def test_vote_cast_audit_entry_carries_only_the_bucket_time(env):  # noqa: F811
    await main.log_action("vote_cast", "v1", {}, org_id=env.org_id, timestamp=main._vote_bucket_start())
    row = await env.db.audit_log.find_one({"action": "vote_cast"})
    assert row["timestamp"].second == 0 and row["timestamp"].microsecond == 0
    assert row["timestamp"].minute % (main.VOTE_TIME_BUCKET_SECONDS // 60) == 0
