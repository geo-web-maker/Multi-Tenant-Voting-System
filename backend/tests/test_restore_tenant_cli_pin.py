"""Pins the restore_tenant CLI behaviour (dry-run, checksum, foreign org, --until, --replace, target required)."""
import sys
import mongomock
import pytest
from bson import ObjectId

import backup
import restore_tenant
from tests._fakes import FakeS3, put_backup, CFG

T = ORG = "org-1"


def _docs(n, org=ORG):
    return [{"_id": ObjectId(), "org_id": org, "n": i} for i in range(n)]


@pytest.fixture
def cli(monkeypatch):
    s3, mongo = FakeS3(), mongomock.MongoClient()
    monkeypatch.setattr(backup, "load_config", lambda: CFG)
    monkeypatch.setattr(backup, "make_client", lambda cfg: s3)
    monkeypatch.setattr(restore_tenant, "MongoClient", lambda *a, **k: mongo)
    def run(*args):
        monkeypatch.setattr(sys, "argv", ["restore_tenant.py", *args])
        restore_tenant.main()
    return s3, mongo, run


def test_dry_run_verifies_and_writes_nothing(cli, capsys):
    s3, mongo, run = cli
    put_backup(s3, f"routine/{T}/full-20261001", T, ORG, {"voters": _docs(2)})
    run("restore", "--tenant", T, "--backup", f"routine/{T}/full-20261001", "--dry-run")
    assert "Dry run" in capsys.readouterr().out
    assert "copy" not in mongo.list_database_names()


def test_checksum_failure_exits_with_message(cli):
    s3, _, run = cli
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(1)}, tamper="checksum")
    with pytest.raises(SystemExit) as e:
        run("restore", "--tenant", T, "--backup", f"routine/{T}/full-1", "--target-db", "copy")
    assert "CHECKSUM" in str(e.value)


def test_foreign_org_doc_is_refused_and_nothing_written(cli):
    s3, mongo, run = cli
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(1, org="evil")})
    with pytest.raises(SystemExit):
        run("restore", "--tenant", T, "--backup", f"routine/{T}/full-1", "--target-db", "copy")
    assert mongo["copy"].list_collection_names() == []


def test_until_excludes_later_incrementals(cli):
    s3, mongo, run = cli
    v = _docs(1)
    put_backup(s3, f"routine/{T}/full-20261001", T, ORG, {"voters": v})
    put_backup(s3, f"routine/{T}/incr-20261005", T, ORG, {"voters": [dict(v[0], n=50)]}, kind="incr")
    with pytest.raises(SystemExit) as e:
        run("restore", "--tenant", T, "--backup", f"routine/{T}/full-20261001", "--until", "20261003", "--target-db", "copy")
    assert e.value.code == 0
    assert mongo["copy"].voters.find_one({"_id": v[0]["_id"]})["n"] == 0


def test_replace_removes_only_this_tenants_stale_docs(cli):
    s3, mongo, run = cli
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(2)})
    mongo["copy"].voters.insert_many([{"_id": "stale", "org_id": ORG}, {"_id": "other", "org_id": "someone"}])
    with pytest.raises(SystemExit) as e:
        run("restore", "--tenant", T, "--backup", f"routine/{T}/full-1", "--target-db", "copy", "--replace")
    assert e.value.code == 0
    ids = {d["_id"] for d in mongo["copy"].voters.find({})}
    assert "stale" not in ids and "other" in ids


def test_target_is_required(cli):
    s3, _, run = cli
    put_backup(s3, f"routine/{T}/full-1", T, ORG, {"voters": _docs(1)})
    with pytest.raises(SystemExit) as e:
        run("restore", "--tenant", T, "--backup", f"routine/{T}/full-1")
    assert "target-db" in str(e.value)
