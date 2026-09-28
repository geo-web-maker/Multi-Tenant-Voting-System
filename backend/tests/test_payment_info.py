"""Mobile Money payment details: public read, superadmin-only write with reason + audit trail."""
import pytest

import main  # noqa: F401
from tests.test_flows import env  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def put(e, who=None, **body):
    return await e.client.put("/superadmin/payment-info", headers=who or e.sa,
                              json={"reason": "initial setup", **body})


async def test_public_read_is_empty_until_set(env):
    r = await env.client.get("/payment-info")            # no auth header, like an applicant
    assert r.status_code == 200 and r.json() == {"mobile_money_number": "", "mobile_money_name": ""}


async def test_set_normalises_number_and_is_publicly_readable(env):
    r = await put(env, mobile_money_number="0772 123-456", mobile_money_name="  Kyambogo   Guild  ")
    assert r.status_code == 200, r.text
    assert r.json() == {"mobile_money_number": "256772123456", "mobile_money_name": "Kyambogo Guild"}
    assert (await env.client.get("/payment-info")).json() == r.json()
    log = await env.db.audit_log.find_one({"action": "payment_info_changed"})
    assert log["details"]["reason"] == "initial setup" and log["details"]["old"]["mobile_money_number"] == ""


async def test_validation(env):
    assert (await put(env, mobile_money_number="0772123456")).status_code == 400              # name missing
    assert (await put(env, mobile_money_name="Guild")).status_code == 400                      # number missing
    assert (await put(env, mobile_money_number="abc", mobile_money_name="Guild")).status_code == 400
    assert (await put(env, mobile_money_number="0772123456", mobile_money_name="x" * 61)).status_code == 400
    assert (await env.client.put("/superadmin/payment-info", headers=env.sa,
                                 json={"reason": "", "mobile_money_number": "0772123456",
                                       "mobile_money_name": "Guild"})).status_code == 400
    assert (await put(env)).status_code == 400                                                 # nothing to change


async def test_only_superadmin_can_change_it(env):
    body = {"mobile_money_number": "0772123456", "mobile_money_name": "Guild"}
    for who in (env.it, env.com1, env.over):
        assert (await put(env, who, **body)).status_code == 403
    assert (await env.client.put("/superadmin/payment-info", json={"reason": "x y z", **body})).status_code in (401, 403)
    assert (await env.client.get("/payment-info")).json()["mobile_money_number"] == ""


async def test_clear_hides_it_again(env):
    await put(env, mobile_money_number="0772123456", mobile_money_name="Guild")
    r = await put(env, mobile_money_number="", mobile_money_name="")
    assert r.status_code == 200 and r.json()["mobile_money_number"] == ""
    assert (await env.client.get("/payment-info")).json() == {"mobile_money_number": "", "mobile_money_name": ""}
