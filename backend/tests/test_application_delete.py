"""Superadmin delete of an application: soft (archive, restorable) and hard (permanent), both audited."""
import pytest
from bson import ObjectId

from tests.test_flows import env  # noqa: F401  (fixture)
from tests.test_security_regressions import _FakeClient  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _position(e, title="President"):
    r = await e.db.positions.insert_one({"org_id": e.org_id, "title": title, "order": 1})
    return str(r.inserted_id)


async def _app(e, sid="v1", name="Ayebale Elizabeth", position_id="p1", **kw):
    r = await e.db.applications.insert_one({
        "org_id": e.org_id, "student_id": sid, "full_name": name, "position_id": position_id,
        "status": "pending", "votes": {}, "removal_votes": {}, "round_id": "round-1",
        "application_snapshot": {"student_id": sid}, **kw})
    return str(r.inserted_id)


async def _audit(e, action):
    return [d async for d in e.db.audit_log.find({"action": action})]


async def test_soft_delete_archives_and_hides_the_application(env):
    aid = await _app(env)
    r = await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                              json={"mode": "soft", "reason": "Duplicate submission"})
    assert r.status_code == 200 and r.json()["status"] == "soft_deleted"
    assert await env.db.applications.count_documents({}) == 0
    arch = await env.db.deleted_applications.find_one({"_id": ObjectId(aid)})
    assert arch["delete_reason"] == "Duplicate submission" and arch["deleted_by"] == "root"
    assert arch["deleted_from_status"] == "pending"
    log = (await _audit(env, "application_soft_deleted"))[0]
    assert log["details"]["reason"] == "Duplicate submission" and log["details"]["student_id"] == "v1"


async def test_hard_delete_needs_the_typed_phrase_and_leaves_no_archive(env):
    aid = await _app(env)
    url = f"/superadmin/applications/{aid}/delete"
    assert (await env.client.post(url, headers=env.sa, json={"mode": "hard", "reason": "Test entry"})).status_code == 400
    assert (await env.client.post(url, headers=env.sa, json={"mode": "hard", "reason": "Test entry",
                                                             "confirm": "delete me"})).status_code == 400
    assert await env.db.applications.count_documents({}) == 1
    r = await env.client.post(url, headers=env.sa, json={"mode": "hard", "reason": "Test entry", "confirm": "DELETE"})
    assert r.status_code == 200 and r.json()["status"] == "hard_deleted"
    assert await env.db.applications.count_documents({}) == 0
    assert await env.db.deleted_applications.count_documents({}) == 0
    log = (await _audit(env, "application_hard_deleted"))[0]
    assert log["details"]["full_name"] == "Ayebale Elizabeth"       # the audit log still says what was removed


async def test_delete_validation_and_superadmin_only(env):
    aid = await _app(env)
    url = f"/superadmin/applications/{aid}/delete"
    assert (await env.client.post(url, headers=env.sa, json={"mode": "maybe", "reason": "whatever"})).status_code == 400
    assert (await env.client.post(url, headers=env.sa, json={"mode": "soft", "reason": " "})).status_code == 400
    assert (await env.client.post(url, headers=env.com1, json={"mode": "soft", "reason": "sneaky"})).status_code in (401, 403)
    missing = f"/superadmin/applications/{ObjectId()}/delete"
    assert (await env.client.post(missing, headers=env.sa, json={"mode": "soft", "reason": "gone"})).status_code == 404
    assert await env.db.applications.count_documents({}) == 1


async def test_delete_approved_removes_candidate_revokes_certificate_and_links(env):
    aid = await _app(env, status="approved", certificate_id="CERT-1")
    await env.db.certificates.insert_one({"certificate_id": "CERT-1", "org_id": env.org_id, "revoked": False})
    await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": aid, "name": "X"})
    await env.db.candidate_tokens.insert_one({"org_id": env.org_id, "student_id": "v1", "token": "t", "round_id": "round-1"})
    r = await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                              json={"mode": "soft", "reason": "Entered by mistake"})
    assert r.status_code == 200 and r.json()["candidate_removed"] is True and r.json()["status_links_revoked"] == 1
    assert await env.db.candidates.count_documents({}) == 0
    assert (await env.db.certificates.find_one({"certificate_id": "CERT-1"}))["revoked"] is True
    assert (await env.db.candidate_tokens.find_one({"token": "t"}))["revoked"] is True


async def test_status_link_kept_while_the_student_has_another_application(env):
    aid = await _app(env, position_id="p1")
    await _app(env, position_id="p2")
    await env.db.candidate_tokens.insert_one({"org_id": env.org_id, "student_id": "v1", "token": "t", "round_id": "round-1"})
    r = await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                              json={"mode": "soft", "reason": "Wrong position"})
    assert r.status_code == 200 and r.json()["status_links_revoked"] == 0
    assert not (await env.db.candidate_tokens.find_one({"token": "t"})).get("revoked")


async def test_delete_is_refused_once_votes_were_cast(env):
    aid = await _app(env, status="approved")
    cand = await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": aid, "name": "Y"})
    await env.db.vote_events.insert_one({"org_id": env.org_id, "candidate_id": cand.inserted_id})
    for mode in ("soft", "hard"):
        r = await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                                  json={"mode": mode, "reason": "has votes", "confirm": "DELETE"})
        assert r.status_code == 409
    assert await env.db.applications.count_documents({}) == 1 and await env.db.candidates.count_documents({}) == 1
    assert await env.db.deleted_applications.count_documents({}) == 0


async def test_hard_delete_removes_the_nomination_record(env):
    aid = await _app(env, nomination_form={"upload_id": "up1", "filename": "form.pdf"})
    await env.db.nomination_uploads.insert_one({"org_id": env.org_id, "upload_id": "up1", "key": "k", "status": "attached"})
    r = await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                              json={"mode": "hard", "reason": "Remove everything", "confirm": "DELETE"})
    assert r.status_code == 200
    assert await env.db.nomination_uploads.count_documents({}) == 0


async def test_soft_delete_keeps_the_nomination_record_for_a_restore(env):
    aid = await _app(env, nomination_form={"upload_id": "up1", "filename": "form.pdf"})
    await env.db.nomination_uploads.insert_one({"org_id": env.org_id, "upload_id": "up1", "key": "k", "status": "attached"})
    await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                          json={"mode": "soft", "reason": "Might come back"})
    assert await env.db.nomination_uploads.count_documents({}) == 1


async def test_list_and_restore_a_soft_deleted_application_as_pending(env):
    pid = await _position(env)
    aid = await _app(env, position_id=pid, status="approved", superadmin_override=True, votes={"com1": "approve"})
    await env.db.candidates.insert_one({"org_id": env.org_id, "application_id": aid, "name": "X"})
    await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                          json={"mode": "soft", "reason": "Deleted too soon"})
    rows = (await env.client.get("/superadmin/deleted-applications", headers=env.sa)).json()
    assert len(rows) == 1 and rows[0]["_id"] == aid and rows[0]["status"] == "approved"
    assert rows[0]["position_title"] == "President" and rows[0]["had_candidate"] is True

    r = await env.client.post(f"/superadmin/deleted-applications/{aid}/restore", headers=env.sa,
                              json={"reason": "Deleted by mistake"})
    assert r.status_code == 200 and r.json()["candidate_was_on_ballot"] is True
    doc = await env.db.applications.find_one({"_id": ObjectId(aid)})
    assert doc["status"] == "pending" and doc["votes"] == {} and "superadmin_override" not in doc
    assert "deleted_at" not in doc and doc["restore_history"][0]["from_status"] == "approved"
    assert await env.db.deleted_applications.count_documents({}) == 0
    assert await env.db.candidates.count_documents({}) == 0          # the ballot entry is not brought back
    assert (await _audit(env, "application_restored"))[0]["details"]["reason"] == "Deleted by mistake"


async def test_restore_refused_when_the_student_has_applied_again_or_position_is_gone(env):
    pid = await _position(env)
    aid = await _app(env, position_id=pid)
    await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                          json={"mode": "soft", "reason": "Duplicate"})
    await _app(env, position_id=pid)                                  # the student applied again
    url = f"/superadmin/deleted-applications/{aid}/restore"
    assert (await env.client.post(url, headers=env.sa, json={"reason": "Bring it back"})).status_code == 409
    await env.db.applications.delete_many({})
    await env.db.positions.delete_many({})
    assert (await env.client.post(url, headers=env.sa, json={"reason": "Bring it back"})).status_code == 400
    assert await env.db.deleted_applications.count_documents({}) == 1


async def test_purge_needs_the_phrase_and_removes_the_archived_copy(env):
    aid = await _app(env)
    await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                          json={"mode": "soft", "reason": "Archive first"})
    url = f"/superadmin/deleted-applications/{aid}/purge"
    assert (await env.client.post(url, headers=env.sa, json={"reason": "Clear it out"})).status_code == 400
    assert await env.db.deleted_applications.count_documents({}) == 1
    r = await env.client.post(url, headers=env.sa, json={"reason": "Clear it out", "confirm": "DELETE"})
    assert r.status_code == 200 and await env.db.deleted_applications.count_documents({}) == 0
    assert (await _audit(env, "application_purged"))[0]["details"]["reason"] == "Clear it out"
    assert (await env.client.post(url, headers=env.sa, json={"reason": "Again", "confirm": "DELETE"})).status_code == 404


async def test_archive_routes_are_superadmin_only(env):
    aid = await _app(env)
    await env.client.post(f"/superadmin/applications/{aid}/delete", headers=env.sa,
                          json={"mode": "soft", "reason": "Archive first"})
    assert (await env.client.get("/superadmin/deleted-applications", headers=env.com1)).status_code in (401, 403)
    for tail, body in (("restore", {"reason": "sneaky"}), ("purge", {"reason": "sneaky", "confirm": "DELETE"})):
        r = await env.client.post(f"/superadmin/deleted-applications/{aid}/{tail}", headers=env.com1, json=body)
        assert r.status_code in (401, 403)
