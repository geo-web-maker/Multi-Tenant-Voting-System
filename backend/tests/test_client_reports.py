"""Voter-side problem reports: public beacon route, privacy scrubbing, rate limit, alert threshold, superadmin summary."""
import pytest

import main
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio

CHROME = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    main._CLIENT_REPORT_IP_HITS.clear()
    yield
    main._CLIENT_REPORT_IP_HITS.clear()


def _h(env, ua=CHROME):
    return {"X-Org-Slug": "t1", "User-Agent": ua}


async def test_report_is_stored_without_personal_data(env):
    r = await env.client.post("/client-report", headers=_h(env), json={
        "kind": "js_error", "code": "TypeError", "step": "voter_identity",
        "detail": "bad id 2021012345 and phone 0772123456"})
    assert r.status_code == 202
    d = await env.db.client_reports.find_one({})
    assert d["org_id"] == env.org_id and d["browser"] == "Chrome 120" and d["step"] == "voter_identity"
    assert "2021012345" not in d["detail"] and "0772123456" not in d["detail"]


async def test_unknown_kind_and_bad_step_are_handled_quietly(env):
    assert (await env.client.post("/client-report", headers=_h(env), json={"kind": "hack"})).status_code == 202
    assert await env.db.client_reports.count_documents({}) == 0
    await env.client.post("/client-report", headers=_h(env), json={"kind": "blank_screen", "step": "<script>"})
    assert (await env.db.client_reports.find_one({}))["step"] == "other"


async def test_one_ip_cannot_flood_the_collection(env):
    for _ in range(main._CLIENT_REPORT_IP_MAX + 15):
        await env.client.post("/client-report", headers=_h(env), json={"kind": "js_error", "code": "x"})
    assert await env.db.client_reports.count_documents({}) == main._CLIENT_REPORT_IP_MAX


async def test_threshold_sends_one_alert(env, monkeypatch):
    sent = []

    async def fake(subject, body, cooldown_s=None):
        sent.append(subject)
        return True
    monkeypatch.setattr(main, "alert_warning", fake)
    # Blank screens alert at 3 reports in 10 minutes (post-election plan 9: one stuck voter is not an outage).
    for _ in range(2):
        await env.client.post("/client-report", headers=_h(env), json={"kind": "blank_screen"})
    assert len(sent) == 0
    await env.client.post("/client-report", headers=_h(env), json={"kind": "blank_screen"})
    assert len(sent) == 1
    for i in range(3):
        await env.client.post("/client-report", headers=_h(env), json={"kind": "js_error", "code": f"e{i}"})
    assert len(sent) == 1                                   # below the js_error threshold


async def test_summary_is_superadmin_only_and_counts(env):
    for k in ("captcha_script_failed", "captcha_script_failed", "js_error"):
        await env.client.post("/client-report", headers=_h(env), json={"kind": k, "step": "voter_identity"})
    r = await env.client.get("/superadmin/client-reports", headers=env.sa)
    assert r.status_code == 200
    j = r.json()
    assert j["total"] == 3 and j["by_kind"][0] == {"kind": "captcha_script_failed", "count": 2, "alert_at": 10}
    assert j["top_browsers"][0]["browser"] == "Chrome 120"
    assert (await env.client.get("/superadmin/client-reports", headers=env.it)).status_code == 403


def test_browser_family_parsing():
    f = main._browser_family
    assert f("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1") == "Safari 17"
    assert f("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/118.0 Mobile Safari/537.36 SamsungBrowser/23.0") == "Samsung 23"
    assert f("") == "Other"
