"""Run the Mongo -> PostgreSQL analytics history copy from the Performance tab.

One job at a time, in the background, paced like the command-line tool (migrate_analytics_to_postgres.py, which
holds the actual copy and verification). It is safe to press again: the import ledger makes every copy add each
old count only once. Progress is in memory; the last result is saved so it survives a restart.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import analytics
from analytics_store import PostgresAnalyticsStore
from migrate_analytics_to_postgres import copy_history

log = logging.getLogger(__name__)
_DOC = "analytics_migration"
_state: dict = {"status": "idle"}
_task: asyncio.Task | None = None


def migration_state() -> dict:
    return dict(_state)


async def load_last_result(db) -> None:
    """Restore the last finished result after a restart (a run that was interrupted shows as idle)."""
    try:
        doc = await db.platform_settings.find_one({"name": _DOC})
    except Exception:
        return
    if doc and doc.get("result") and _state.get("status") == "idle":
        _state.update(doc["result"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(db, store: PostgresAnalyticsStore, cutoff: date, pause: float) -> None:
    global _state
    try:
        code, summary = await copy_history(db, store, cutoff, pause=pause, say=lambda *_: None,
                                           progress=lambda s: _state.update(counts=s))
        _state.update(status="done" if code == 0 else "failed", counts=summary, finished_at=_now(),
                      message=("Copied and verified." if code == 0 else
                               "Copied, but the check found totals that differ. Nothing was removed from MongoDB."))
    except asyncio.CancelledError:
        _state.update(status="failed", finished_at=_now(), message="Stopped before it finished. You can run it again.")
        raise
    except Exception as exc:
        _state.update(status="failed", finished_at=_now(), message=f"Stopped safely: {store.safe_error(exc)}")
    finally:
        try:
            await db.platform_settings.update_one({"name": _DOC}, {"$set": {"name": _DOC, "result": dict(_state)}}, upsert=True)
        except Exception:
            log.warning("migration result could not be saved", exc_info=True)


def start_migration(db, pause: float = 0.75) -> dict:
    """Begin the copy. Raises ValueError with a message the tab can show."""
    global _task, _state
    if analytics.storage_mode() != "postgres":
        raise ValueError("Switch to PostgreSQL first, then migrate.")
    store = analytics._analytics_store(db)
    if not isinstance(store, PostgresAnalyticsStore):
        raise ValueError("PostgreSQL is not the active store yet.")
    if _task is not None and not _task.done():
        raise ValueError("A migration is already running.")
    # The cutoff is the day of the switch: MongoDB stopped receiving writes then, and that day is added to, not overwritten.
    day = analytics.storage_status().get("switch_day") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff = date.fromisoformat(day)
    _state = {"status": "running", "started_at": _now(), "cutoff": day, "counts": {}, "message": "Copying history."}
    _task = asyncio.create_task(_run(db, store, cutoff, pause))
    return migration_state()
