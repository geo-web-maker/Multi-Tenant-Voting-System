"""backup_jobs lifecycle: queued -> running -> final, steps/progress, 409-style busy, crash -> failed."""
import asyncio
from datetime import timedelta
import pytest
from mongomock_motor import AsyncMongoMockClient

import backup_jobs as bj

pytestmark = pytest.mark.asyncio


async def _wait(db, run_id, want=("passed", "failed", "warning", "skipped")):
    for _ in range(200):
        doc = await db.backup_jobs.find_one({"_id": run_id})
        if doc["status"] in want: return doc
        await asyncio.sleep(0.01)
    raise AssertionError("job did not finish")


async def test_job_moves_to_passed_with_steps_and_progress():
    db = AsyncMongoMockClient()["j"]
    async def worker(ctx):
        await ctx["step"]("copy", "running", "x", done=1, total=2)
        return {"status": "passed", "n": 1}
    out = await bj.start_job(db, "k1", "manual", "root", {}, worker)
    assert out["status"] == "queued"
    doc = await _wait(db, out["run_id"])
    assert doc["status"] == "passed" and doc["steps"][0]["name"] == "copy"
    assert doc["progress"] == {"done": 1, "total": 2} and doc["finished_at"] is not None


async def test_second_job_of_same_kind_is_busy_while_first_runs():
    db = AsyncMongoMockClient()["j2"]
    gate = asyncio.Event()
    async def slow(ctx): await gate.wait(); return {}
    first = await bj.start_job(db, "k2", "manual", "a", {}, slow)
    with pytest.raises(bj.JobBusy) as e:
        await bj.start_job(db, "k2", "manual", "a", {}, slow)
    assert e.value.run_id == first["run_id"]
    other = await bj.start_job(db, "other_kind", "manual", "a", {}, slow)   # different kind is allowed
    assert other["status"] == "queued"
    gate.set(); await _wait(db, first["run_id"])


async def test_crash_leaves_failed_job_with_redacted_error():
    db = AsyncMongoMockClient()["j3"]
    async def crash(ctx): raise RuntimeError("bad mongodb+srv://u:pw@h.example/ token=abc")
    out = await bj.start_job(db, "k3", "manual", "a", {}, crash)
    doc = await _wait(db, out["run_id"])
    assert doc["status"] == "failed" and "pw@" not in doc["error"] and "abc" not in doc["error"]
    again = await bj.start_job(db, "k3", "manual", "a", {}, crash)       # not stuck busy after failure
    assert again["status"] == "queued"


async def test_stale_running_record_is_failed_not_blocking():
    db = AsyncMongoMockClient()["j4"]
    await db.backup_jobs.insert_one({"_id": "old", "kind": "k4", "status": "running",
                                     "started_at": bj.now_utc() - timedelta(hours=3)})
    async def ok(ctx): return {}
    out = await bj.start_job(db, "k4", "manual", "a", {}, ok)
    assert out["status"] == "queued"
    assert (await db.backup_jobs.find_one({"_id": "old"}))["status"] == "failed"


async def test_ttl_index_is_180_days():
    db = AsyncMongoMockClient()["j5"]
    await bj.ensure_indexes(db)
    info = await db.backup_jobs.index_information()
    assert any(v.get("expireAfterSeconds") == 180 * 86400 for v in info.values())
