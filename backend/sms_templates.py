"""Every automatic (non-bulk) SMS the system sends, in one place.

main.py renders these with `render(key, **values)` at the send sites, and `GET /admin/sms/templates` prices the very
same builders for the SMS tab calculator. Because both use one function, the calculator can never drift from what is
really sent. Wording here is byte-identical to the strings that used to live inline in main.py
(tests/test_sms_templates.py pins every one).

Pure module: no I/O, no imports from main.
"""
from __future__ import annotations

TEST_MESSAGE = "SMS Connection Verified for BallotBox!"

STATUS_LINK_PATH = "/status/"


def contact_change_text(change_type: str, org: str, when: str, id_noun: str, reach: str) -> str:
    """Notice to the number that just lost control of a record (no code inside)."""
    what = {"phone_change": "The phone number on", "phone_remove": "A phone number on",
            "phone_add": "A phone number was added to", "registration_number_change": f"The {id_noun} on"}[change_type]
    tail = " was changed" if change_type in ("phone_change", "registration_number_change") else (
        " was removed" if change_type == "phone_remove" else "")
    contact = f" If this was not you, contact {reach}." if reach else " If this was not you, contact the Electoral Commission."
    return f"{what} the {org} voting register{tail} at {when}.{contact}"


def _otp(v):
    return (f"Hello {v['first_name']}, your {v['org']} voting code is {v['code']}. "
            f"Your vote is secret. Do not share it. Your voice, your power!")


def _temp_password(v):
    return (f"Hello {v['full_name']}, your temporary {v['role']} login code "
            f"for the {v['org']} Election Portal is {v['temp_password']}. "
            f"You will be asked to set a new password on first login. "
            f"Do not share this code with anyone.")


def _approved(v):
    return (f"{v['org']}: Congratulations! Your nomination for {v['position']} has been approved. "
            f"Your name will appear on the ballot.")


def _denied(v):
    return f"{v['org']}: Your nomination for {v['position']} was not approved by the Electoral Commission."


def _finance_cleared(v):
    return (f"{v['org']}: Your payment has been confirmed. You are invited for nomination/vetting for {v['position']}"
            + (f" on {v['when']}." if v.get("when") else " — the date will be communicated once the timeline is set."))


def _finance_rejected(v):
    return (f"{v['org']}: Your nomination for {v['position']} was rejected because of your payment: {v['reason']}."
            + (f" The required amount is {v['fee']}; incomplete payments are not accepted." if v.get("fee") else "")
            + " If you think this is a mistake, contact the Finance office.")


def _finance_reversed(v):
    return (f"{v['org']}: The payment confirmation for your {v['position']} nomination has been withdrawn while Finance "
            f"reviews it. Please contact the Finance office.")


def _reinstated_cleared(v):
    return f"{v['org']}: Your payment issue is resolved and your nomination for {v['position']} is back under review."


def _reinstated_reopened(v):
    return (f"{v['org']}: Your nomination for {v['position']} has been reopened and is awaiting payment confirmation "
            f"from Finance.")


def _status_link(v):
    return f"Application received. Check status: {v['link']}"


def _contact(change_type):
    return lambda v: contact_change_text(change_type, v["org"], v["when"], v["id_noun"], v.get("reach", ""))


# key -> label, kind (decides provider routing: only "otp" is priority), when it is sent, variable names, builder.
# `variants` marks entries that are alternative wordings of the same trigger (only one is sent each time).
CATALOG: dict[str, dict] = {
    "otp": dict(label="Voting code (OTP)", kind="otp", group="Voters",
                when="Each time a voter asks for a code. A resend of a still-valid code is billed again.",
                vars=["first_name", "org", "code"], build=_otp),
    "contact_phone_change": dict(label="Phone number changed (to the old number)", kind="notice", group="Voters",
                                 when="When a contact-change request replaces a voter's phone number.",
                                 vars=["org", "when", "id_noun", "reach"], build=_contact("phone_change")),
    "contact_phone_remove": dict(label="Phone number removed (to the removed number)", kind="notice", group="Voters",
                                 when="When a contact-change request removes a phone number.",
                                 vars=["org", "when", "id_noun", "reach"], build=_contact("phone_remove")),
    "contact_phone_add": dict(label="Phone number added (to the existing number)", kind="notice", group="Voters",
                              when="When a contact-change request adds a phone number.",
                              vars=["org", "when", "id_noun", "reach"], build=_contact("phone_add")),
    "contact_regno_change": dict(label="Registration number changed (to the existing number)", kind="notice", group="Voters",
                                 when="When a contact-change request changes the registration number.",
                                 vars=["org", "when", "id_noun", "reach"], build=_contact("registration_number_change")),
    "status_link": dict(label="Application received: status link", kind="candidate_status_link", group="Applicants",
                        when="First application of a round, and every time an admin re-sends the status link.",
                        vars=["link"], build=_status_link),
    "approved": dict(label="Nomination approved", kind="notice", group="Applicants",
                     when="When an application is approved (panel decision or superadmin override).",
                     vars=["org", "position"], build=_approved),
    "denied": dict(label="Nomination not approved", kind="notice", group="Applicants",
                   when="When an application is denied by the panel.",
                   vars=["org", "position"], build=_denied),
    "finance_cleared": dict(label="Payment confirmed, vetting date set", kind="notice", group="Applicants",
                            when="When Finance clears a payment and the vetting date is known.",
                            vars=["org", "position", "when"], build=_finance_cleared, variants="finance_cleared"),
    "finance_cleared_undated": dict(label="Payment confirmed, no vetting date yet", kind="notice", group="Applicants",
                                    when="When Finance clears a payment before the vetting date is set.",
                                    vars=["org", "position"], build=_finance_cleared, variants="finance_cleared"),
    "finance_rejected": dict(label="Payment rejected (with required amount)", kind="notice", group="Applicants",
                             when="When Finance rejects a payment for a position that has an application fee.",
                             vars=["org", "position", "reason", "fee"], build=_finance_rejected, variants="finance_rejected"),
    "finance_rejected_no_fee": dict(label="Payment rejected (no amount)", kind="notice", group="Applicants",
                                    when="When Finance rejects a payment for a position with no fee.",
                                    vars=["org", "position", "reason"], build=_finance_rejected, variants="finance_rejected"),
    "finance_reversed": dict(label="Payment confirmation withdrawn", kind="notice", group="Applicants",
                             when="When Finance reverses an earlier clearance.",
                             vars=["org", "position"], build=_finance_reversed),
    "reinstated_cleared": dict(label="Payment issue resolved", kind="notice", group="Applicants",
                               when="When Finance reinstates a payment as cleared.",
                               vars=["org", "position"], build=_reinstated_cleared, variants="reinstated"),
    "reinstated_reopened": dict(label="Nomination reopened, awaiting payment", kind="notice", group="Applicants",
                                when="When Finance reopens an application to awaiting payment.",
                                vars=["org", "position"], build=_reinstated_reopened, variants="reinstated"),
    "temp_password": dict(label="Temporary login code (staff)", kind="admin", group="Staff",
                          when="When a superadmin creates or resets an IT admin, commissioner, panel member, finance controller or overseer.",
                          vars=["full_name", "role", "org", "temp_password"], build=_temp_password),
    "connection_test": dict(label="Connection test", kind="test", group="Staff",
                            when="Each time the Test button in SMS settings is used.",
                            vars=[], build=lambda v: TEST_MESSAGE),
}


def render(key: str, **values) -> str:
    """The exact text the system sends for `key`."""
    return CATALOG[key]["build"](values)


def pattern(key: str) -> str:
    """The same text with {placeholders} instead of values, for display."""
    entry = CATALOG[key]
    return entry["build"]({name: "{" + name + "}" for name in entry["vars"]})
