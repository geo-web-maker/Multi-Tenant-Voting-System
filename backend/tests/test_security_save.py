"""Saving security settings must not report failure for a save that was applied, and must not re-sweep
every open application when the approval policy did not change."""
import pytest

import main
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

URL = "/superadmin/security-settings"


def _other_policy():
    cur = main._SEC_DEFAULTS["approval_policy"]
    return next(p for p in sorted(main.VALID_APPROVAL_POLICIES) if p != cur)


async def test_unchanged_policy_does_not_resweep(env, monkeypatch):
    calls = []

    async def spy(org_id, include_removals=True):
        calls.append(org_id)
    monkeypatch.setattr(main, "_resweep_pending_after_policy_change", spy)
    body = {"reason": "routine save", "turnstile_mode": "on", "approval_policy": main._SEC_DEFAULTS["approval_policy"]}
    r = await env.client.put(URL, headers=env.sa, json=body)
    assert r.status_code == 200 and "warning" not in r.json()
    assert calls == []


async def test_changed_policy_resweeps_once(env, monkeypatch):
    calls = []

    async def spy(org_id, include_removals=True):
        calls.append(org_id)
    monkeypatch.setattr(main, "_resweep_pending_after_policy_change", spy)
    r = await env.client.put(URL, headers=env.sa, json={"reason": "tighten", "approval_policy": _other_policy()})
    assert r.status_code == 200
    assert calls == [env.org_id]


async def test_resweep_failure_is_a_warning_not_a_failed_save(env, monkeypatch):
    async def boom(org_id, include_removals=True):
        raise RuntimeError("resolver blew up")
    monkeypatch.setattr(main, "_resweep_pending_after_policy_change", boom)
    r = await env.client.put(URL, headers=env.sa, json={"reason": "tighten", "approval_policy": _other_policy()})
    assert r.status_code == 200                                  # the settings ARE saved, so no error status
    assert "re-checking" in r.json()["warning"]
    assert r.json()["settings"]["approval_policy"] == _other_policy()
    doc = await env.db.settings.find_one({"name": "security_settings", "org_id": env.org_id})
    assert doc["approval_policy"] == _other_policy()


async def test_sms_routing_save_round_trips(env):
    r = await env.client.put(URL, headers=env.sa, json={"reason": "credit low", "sms_route_otp": "mambosms_first",
                                                         "sms_fallback_on_timeout": True})
    assert r.status_code == 200
    assert r.json()["settings"]["sms_route_otp"] == "mambosms_first"
