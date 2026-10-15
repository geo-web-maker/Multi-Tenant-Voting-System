"""sms_templates must produce exactly the wording that used to be inline in main.py. The calculator prices these
same builders, so a changed word here changes both what is sent and what is estimated."""
import sms_bulk
import sms_templates as t


def test_otp():
    assert t.render("otp", first_name="Amy", org="Guild", code="123456") == (
        "Hello Amy, your Guild voting code is 123456. Your vote is secret. Do not share it. "
        "Your voice, your power!")


def test_otp_stays_one_part_with_long_names():
    """Every voter code is billed per part: a long org name or first name must never push it to two."""
    text = t.render("otp", first_name="Namugerwa", org="Accounting Society of Kyambogo University", code="123456")
    assert sms_bulk.count_parts(text)["parts"] == 1 and sms_bulk.count_parts(text)["encoding"] == "GSM-7"
    worst = t.render("otp", first_name="N" * 15, org="O" * 45, code="123456")
    assert sms_bulk.count_parts(worst)["parts"] == 1


def test_temp_password():
    assert t.render("temp_password", full_name="Amy N", role="Commissioner", org="Guild", temp_password="abc") == (
        "Hello Amy N, your temporary Commissioner login code for the Guild Election Portal is abc. "
        "You will be asked to set a new password on first login. Do not share this code with anyone.")


def test_applicant_messages():
    kw = dict(org="Guild", position="Chair")
    assert t.render("approved", **kw) == "Guild: Congratulations! Your nomination for Chair has been approved. Your name will appear on the ballot."
    assert t.render("denied", **kw) == "Guild: Your nomination for Chair was not approved by the Electoral Commission."
    assert t.render("finance_reversed", **kw) == (
        "Guild: The payment confirmation for your Chair nomination has been withdrawn while Finance reviews it. "
        "Please contact the Finance office.")
    assert t.render("reinstated_cleared", **kw) == "Guild: Your payment issue is resolved and your nomination for Chair is back under review."
    assert t.render("reinstated_reopened", **kw) == (
        "Guild: Your nomination for Chair has been reopened and is awaiting payment confirmation from Finance.")


def test_finance_cleared_both_wordings():
    assert t.render("finance_cleared", org="Guild", position="Chair", when="3 Nov 2026") == (
        "Guild: Your payment has been confirmed. You are invited for nomination/vetting for Chair on 3 Nov 2026.")
    assert t.render("finance_cleared_undated", org="Guild", position="Chair") == (
        "Guild: Your payment has been confirmed. You are invited for nomination/vetting for Chair"
        " — the date will be communicated once the timeline is set.")


def test_finance_rejected_both_wordings():
    assert t.render("finance_rejected", org="Guild", position="Chair", reason="short", fee="UGX 50,000") == (
        "Guild: Your nomination for Chair was rejected because of your payment: short. "
        "The required amount is UGX 50,000; incomplete payments are not accepted. "
        "If you think this is a mistake, contact the Finance office.")
    assert t.render("finance_rejected_no_fee", org="Guild", position="Chair", reason="short") == (
        "Guild: Your nomination for Chair was rejected because of your payment: short. "
        "If you think this is a mistake, contact the Finance office.")


def test_status_link_and_test_message():
    assert t.render("status_link", link="https://x.org/status/abc") == "Application received. Check status: https://x.org/status/abc"
    assert t.render("connection_test") == "SMS Connection Verified for BallotBox!"


def test_contact_change_notices():
    f = t.contact_change_text
    assert f("phone_change", "Guild", "14:05 UTC", "student number", "0700") == (
        "The phone number on the Guild voting register was changed at 14:05 UTC. If this was not you, contact 0700.")
    assert f("phone_remove", "Guild", "14:05 UTC", "student number", "") == (
        "A phone number on the Guild voting register was removed at 14:05 UTC. "
        "If this was not you, contact the Electoral Commission.")
    assert f("phone_add", "Guild", "14:05 UTC", "student number", "0700") == (
        "A phone number was added to the Guild voting register at 14:05 UTC. If this was not you, contact 0700.")
    assert f("registration_number_change", "Guild", "14:05 UTC", "student number", "0700") == (
        "The student number on the Guild voting register was changed at 14:05 UTC. If this was not you, contact 0700.")


def test_every_entry_renders_and_patterns_show_placeholders():
    for key, entry in t.CATALOG.items():
        pat = t.pattern(key)
        assert pat and all("{" + v + "}" in pat for v in entry["vars"] if v not in ("id_noun",)), key
        assert sms_bulk.count_parts(pat)["parts"] >= 1
    assert {"otp", "temp_password", "status_link", "approved"} <= set(t.CATALOG)
    assert t.CATALOG["otp"]["kind"] == "otp"
    assert all(e["kind"] != "otp" for k, e in t.CATALOG.items() if k != "otp")


def test_variants_only_use_their_declared_variables():
    """The calculator renders each entry with only its declared vars: the 'no fee' / 'undated' wordings must stay shorter."""
    sample = {"org": "G", "position": "Chair", "reason": "r", "fee": "UGX 1", "when": "1 Jan 2026"}
    pick = lambda k: t.render(k, **{n: v for n, v in sample.items() if n in t.CATALOG[k]["vars"]})
    assert "required amount" in pick("finance_rejected") and "required amount" not in pick("finance_rejected_no_fee")
    assert " on 1 Jan 2026." in pick("finance_cleared") and "date will be communicated" in pick("finance_cleared_undated")
