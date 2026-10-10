"""Where performance history is written.

Every sink implements write / read / status. The live tab never calls these;
only the flusher does, and a failure stays inside the retry queue (P1).
asyncpg is imported inside PostgresSink, and only when that sink is actually used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_SECRET_RE = re.compile(r"://[^\s/@:]+:[^@\s]+@")


def scrub(text, secrets=()) -> str:
    if not text:
        return ""
    out = str(text)
    for secret in secrets:
        if secret:
            out = out.replace(str(secret), "[redacted]")
    out = _SECRET_RE.sub("://[redacted]@", out)
    out = re.sub(r"(postgres(?:ql)?://)[^\s]+", r"\1[redacted]", out, flags=re.I)
    out = re.sub(r"(mongodb(?:\+srv)?://)[^\s]+", r"\1[redacted]", out, flags=re.I)
    return out[:300]


def gap_fill(batches, start_epoch: int, end_epoch: int, step: int = 60, limit: int = 1440) -> list[dict]:
    """One entry per minute. A minute nobody recorded is null, never zero."""
    by_t = {}
    for batch in batches or []:
        rows = batch.get("rows") if isinstance(batch, dict) else None
        if rows is None and isinstance(batch, dict) and "t" in batch:
            rows = [batch]
        for row in rows or []:
            if isinstance(row, dict) and row.get("t") is not None:
                by_t[int(row["t"])] = row
    start, end = int(start_epoch), int(end_epoch)
    if end < start:
        start, end = end, start
    if (end - start) // step + 1 > limit:
        start = end - (limit - 1) * step
    out = []
    t = start
    while t <= end:
        row = by_t.get(t)
        if row is None:
            out.append({"t": t, "ops": None})
        else:
            out.append(dict(row))
        t += step
    return out


class Sink:
    name = "base"

    async def write(self, batch: dict) -> None:
        raise NotImplementedError

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        return []

    def detail(self) -> str:
        return ""


class NullSink(Sink):
    name = "none"

    def __init__(self, detail: str = ""):
        self._detail = detail

    async def write(self, batch: dict) -> None:
        return None

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        return []

    def detail(self) -> str:
        return self._detail


class MongoSink(Sink):
    """History on the main cluster, collection perf_minutes (excluded from ops/s)."""
    name = "mongo"

    def __init__(self, get_db=None, coll=None):
        self._get_db = get_db
        self._coll_override = coll
        self.indexed = False

    def coll(self):
        if self._coll_override is not None:
            return self._coll_override
        from tenant_db import cross_tenant
        return cross_tenant(self._get_db()).perf_minutes

    async def ensure_index(self, days: int) -> None:
        await self.coll().create_index("minute_dt", expireAfterSeconds=int(days) * 86400)
        self.indexed = True

    async def write(self, batch: dict) -> None:
        await self.coll().replace_one({"_id": batch["_id"]}, batch, upsert=True)

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        cursor = self.coll().find({"_id": {"$gte": int(start_epoch) - 3600, "$lte": int(end_epoch)}}).sort("_id", 1)
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(length=500)
        out = []
        async for doc in cursor:
            out.append(doc)
        return out


class SeparateMongoSink(Sink):
    """A different cluster. Its client has no command listener, so it costs the main cluster nothing."""
    name = "mongo_separate"

    def __init__(self, url: str, dbname: str, client_factory=None):
        self._url = url
        self._dbname = dbname or "ballotbox_perf"
        factory = client_factory
        if factory is None:
            import motor.motor_asyncio
            factory = motor.motor_asyncio.AsyncIOMotorClient
        # No event_listeners: this traffic must not be counted as main-cluster operations.
        self._client = factory(url, maxPoolSize=2, serverSelectionTimeoutMS=3000)
        self._coll = self._client[self._dbname]["perf_batches"]

    async def write(self, batch: dict) -> None:
        await asyncio.wait_for(self._coll.replace_one({"_id": batch["_id"]}, batch, upsert=True), timeout=5)

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        cursor = self._coll.find({"_id": {"$gte": int(start_epoch) - 3600, "$lte": int(end_epoch)}}).sort("_id", 1)
        if hasattr(cursor, "to_list"):
            return await cursor.to_list(length=500)
        out = []
        async for doc in cursor:
            out.append(doc)
        return out


class PostgresSink(Sink):
    """Recommended sink. asyncpg is imported only if no pool factory is injected and a pool is needed."""
    name = "postgres"
    DDL = (
        "CREATE TABLE IF NOT EXISTS perf_batches ("
        "minute_epoch bigint PRIMARY KEY, "
        "minute_dt timestamptz NOT NULL, "
        "rows jsonb NOT NULL)"
    )
    INDEX = "CREATE INDEX IF NOT EXISTS perf_batches_dt ON perf_batches (minute_dt)"
    UPSERT = (
        "INSERT INTO perf_batches (minute_epoch, minute_dt, rows) VALUES ($1, $2, $3::jsonb) "
        "ON CONFLICT (minute_epoch) DO UPDATE SET minute_dt = EXCLUDED.minute_dt, rows = EXCLUDED.rows"
    )
    DELETE = "DELETE FROM perf_batches WHERE minute_dt < now() - make_interval(days => $1)"

    def __init__(self, url: str, pooled: bool = False, retention_days: int = 14, pool_factory=None):
        self._url = url
        self._pooled = pooled
        self._days = int(retention_days)
        self._pool = None
        self._ready = False
        self._pool_factory = pool_factory
        self.last_pool_kwargs = None

    async def _get_pool(self):
        if self._pool is None:
            kw = {"min_size": 1, "max_size": 2, "command_timeout": 5, "timeout": 5}
            if self._pooled:
                kw["statement_cache_size"] = 0
            self.last_pool_kwargs = kw
            if self._pool_factory is not None:
                self._pool = await self._pool_factory(self._url, **kw)
            else:
                import asyncpg  # lazy: only this sink needs it (rule P5)
                self._pool = await asyncpg.create_pool(self._url, **kw)
        return self._pool

    async def write(self, batch: dict) -> None:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            if not self._ready:
                await con.execute(self.DDL)
                await con.execute(self.INDEX)
                self._ready = True
            when = datetime.fromtimestamp(int(batch["_id"]), tz=timezone.utc)
            await con.execute(self.UPSERT, int(batch["_id"]), when, json.dumps(batch.get("rows") or []))
            try:
                await con.execute(self.DELETE, self._days)
            except Exception:
                _swallow_once("pg_retention")

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            recs = await con.fetch(
                "SELECT minute_epoch, rows FROM perf_batches "
                "WHERE minute_epoch BETWEEN $1 AND $2 ORDER BY minute_epoch",
                int(start_epoch) - 3600, int(end_epoch),
            )
        out = []
        for rec in recs:
            raw = rec["rows"]
            rows = json.loads(raw) if isinstance(raw, str) else raw
            out.append({"_id": rec["minute_epoch"], "rows": rows})
        return out

    def detail(self) -> str:
        return ""


class B2Sink(Sink):
    """Objects under perf/YYYY/MM/DD/HHMM.json. The app cannot expire them (see H12)."""
    name = "b2"

    def __init__(self, client, bucket: str):
        self._client = client
        self._bucket = bucket

    def _key(self, epoch: int) -> str:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        return dt.strftime("perf/%Y/%m/%d/%H%M.json")

    async def write(self, batch: dict) -> None:
        if self._client is None or not self._bucket:
            raise RuntimeError("B2 client is not configured")
        key = self._key(batch["_id"])
        body = json.dumps({"_id": batch["_id"], "rows": batch.get("rows") or []}).encode()

        def _put():
            self._client.put_object(Bucket=self._bucket, Key=key, Body=body, ContentType="application/json")

        await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, _put), timeout=5)

    async def read(self, start_epoch: int, end_epoch: int) -> list[dict]:
        if self._client is None or not self._bucket:
            return []
        # History on this sink is one day per request; the route also clamps the window.
        def _list():
            return self._client.list_objects_v2(Bucket=self._bucket, Prefix="perf/")

        found = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, _list), timeout=5)
        keys = []
        for item in (found or {}).get("Contents") or []:
            key = item.get("Key") or ""
            if key.endswith(".json"):
                keys.append(key)
        out = []
        for key in sorted(keys):
            def _get(k=key):
                obj = self._client.get_object(Bucket=self._bucket, Key=k)
                return obj["Body"].read()

            raw = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, _get), timeout=5)
            doc = json.loads(raw)
            if start_epoch - 3600 <= int(doc.get("_id", 0)) <= end_epoch:
                out.append(doc)
        return out


class SinkManager:
    """Retry queue in front of one sink. A full queue drops the oldest batch."""

    def __init__(self, sink: Sink, limit: int = 12):
        self.sink = sink
        self.limit = limit
        self.queue: deque = deque()
        self.dropped = 0
        self.ok = True
        self.last_success = None
        self.last_error = ""
        self._secrets = []

    def add_secret(self, value: str | None) -> None:
        """Register a connection string. The string and its password (and user) are scrubbed from any text."""
        if not value:
            return
        self._secrets.append(value)
        try:
            from urllib.parse import unquote, urlsplit
            parts = urlsplit(value)
            for piece in (parts.password, parts.username):
                if piece and len(piece) >= 3:
                    self._secrets.append(piece)
                    self._secrets.append(unquote(piece))
        except Exception:
            pass

    def enqueue(self, batch: dict) -> None:
        self.queue.append(batch)
        while len(self.queue) > self.limit:
            self.queue.popleft()
            self.dropped += 1

    def mark_ok(self) -> None:
        self.ok = True
        self.last_success = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.last_error = ""

    def mark_err(self, exc: BaseException) -> None:
        self.ok = False
        self.last_error = scrub(f"{type(exc).__name__}: {exc}", self._secrets)

    def status(self) -> dict:
        return {
            "type": self.sink.name,
            "ok": self.ok and not self.last_error,
            "last_success": self.last_success,
            "queued": len(self.queue),
            "dropped": self.dropped,
            "last_error": self.last_error,
            "detail": scrub(self.sink.detail(), self._secrets),
        }

    async def drain(self) -> None:
        pending = list(self.queue)
        self.queue.clear()
        for batch in pending:
            try:
                await asyncio.wait_for(self.sink.write(batch), timeout=5)
                self.mark_ok()
            except Exception as exc:
                self.mark_err(exc)
                self.enqueue(batch)
                break


def build_sink(get_db, b2_client=None, pool_factory=None, mongo_client_factory=None) -> Sink:
    kind = (os.getenv("PERF_SINK") or "mongo").strip().lower()
    days = int(os.getenv("PERF_RETENTION_DAYS") or "14")
    if kind in ("none", "off"):
        return NullSink("History is off (PERF_SINK=none).")
    if kind == "postgres":
        url = os.getenv("PERF_POSTGRES_URL") or ""
        if not url.strip():
            return NullSink("PERF_SINK=postgres but PERF_POSTGRES_URL is unset; using none.")
        pooled = (os.getenv("PERF_POSTGRES_POOLED") or "").strip().lower() in ("1", "true", "yes", "on")
        return PostgresSink(url.strip(), pooled=pooled, retention_days=days, pool_factory=pool_factory)
    if kind == "mongo_separate":
        url = os.getenv("PERF_MONGO_URL") or ""
        if not url.strip():
            return NullSink("PERF_SINK=mongo_separate but PERF_MONGO_URL is unset; using none.")
        dbname = os.getenv("PERF_MONGO_DB") or "ballotbox_perf"
        return SeparateMongoSink(url.strip(), dbname, client_factory=mongo_client_factory)
    if kind == "b2":
        bucket = os.getenv("B2_BUCKET_NAME") or ""
        return B2Sink(b2_client, bucket)
    return MongoSink(get_db)


_swallowed: dict[str, float] = {}


def _swallow_once(where: str) -> None:
    import time
    now = time.monotonic()
    if now - _swallowed.get(where, 0.0) < 60:
        return
    _swallowed[where] = now
    log.warning("perf sink %s failed", where, exc_info=True)
