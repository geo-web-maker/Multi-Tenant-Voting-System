"""Non-superadmin activity-log views mask student IDs, emails and uploaded-file names."""
from main import _mask_audit_identifiers, _scrub_audit_text


def test_student_id_actor_and_details_are_masked():
    entry = {"actor": "2021/bse/0123/ps", "details": {"student_id": "2020/bit/0456/ps", "sms_notified": True}}
    _mask_audit_identifiers(entry)
    assert "0123" not in entry["actor"] and entry["actor"].startswith("2021/".upper())
    assert "0456" not in entry["details"]["student_id"]
    assert entry["details"]["sms_notified"] is True


def test_role_names_and_panel_ids_are_left_alone():
    for actor in ("vetting", "superadmin", "PM-COM1"):
        entry = {"actor": actor, "details": {}}
        _mask_audit_identifiers(entry)
        assert entry["actor"] == actor


def test_nomination_filename_is_dropped():
    entry = {"actor": "x", "details": {"nomination_form": "John_Doe_signed.pdf", "full_name": "John Doe"}}
    _mask_audit_identifiers(entry)
    assert "nomination_form" not in entry["details"]
    assert entry["details"]["full_name"] == "John Doe"


def test_free_text_reason_is_scrubbed_but_dates_survive():
    out = _scrub_audit_text("reset 2021/bse/0123/ps, mail geo_web@yahoo.com, on 12/05/2026")
    assert "0123" not in out and "geo_web@" not in out and "12/05/2026" in out
