"""Storage adapters for privacy-safe aggregate analytics.

Mongo remains the default and rollback target. The Postgres adapter uses a small
asyncpg pool and never imports asyncpg until Postgres storage is selected.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlsplit

from perf_sinks import scrub

log = logging.getLogger("analytics.store")

COUNTER_COLUMNS = ("org_id", "day", "kind", "k1", "k2", "device", "seg", "field", "n")
HEAT_COLUMNS = ("org_id", "page", "device", "seg", "kind", "gx", "gy", "n")
COUNTER_PK = "org_id, day, kind, k1, k2, device, seg, field"
HEAT_PK = "org_id, page, device, seg, kind, gx, gy"

COUNTER_DDL = (
    "CREATE TABLE IF NOT EXISTS analytics_counter ("
    "org_id text NOT NULL, day text NOT NULL, kind text NOT NULL, "
    "k1 text NOT NULL, k2 text NOT NULL, device text NOT NULL, seg text NOT NULL, "
    "field text NOT NULL, n bigint NOT NULL, PRIMARY KEY (org_id, day, kind, k1, k2, device, seg, field))"
)
HEAT_DDL = (
    "CREATE TABLE IF NOT EXISTS analytics_heat ("
    "org_id text NOT NULL, page text NOT NULL, device text NOT NULL, seg text NOT NULL, "
    "kind text NOT NULL, gx integer NOT NULL, gy integer NOT NULL, n bigint NOT NULL, "
    "PRIMARY KEY (org_id, page, device, seg, kind, gx, gy))"
)
IMPORT_DDL = (
    "CREATE TABLE IF NOT EXISTS analytics_history_imports ("
    "source_collection text NOT NULL, source_id text NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(), "
    "PRIMARY KEY (source_collection, source_id))"
)
INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS analytics_heat_lookup_idx ON analytics_heat (org_id, page, kind)",
)
VERIFY_SCHEMA_SQL = (
    "SELECT 1 FROM analytics_counter LIMIT 0",
    "SELECT 1 FROM analytics_heat LIMIT 0",
    "SELECT 1 FROM analytics_history_imports LIMIT 0",
)
COUNTER_ADD = (
    "INSERT INTO analytics_counter (org_id, day, kind, k1, k2, device, seg, field, n) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
    "ON CONFLICT (org_id, day, kind, k1, k2, device, seg, field) "
    "DO UPDATE SET n = analytics_counter.n + EXCLUDED.n"
)
COUNTER_MAX = (
    "INSERT INTO analytics_counter (org_id, day, kind, k1, k2, device, seg, field, n) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
    "ON CONFLICT (org_id, day, kind, k1, k2, device, seg, field) "
    "DO UPDATE SET n = GREATEST(analytics_counter.n, EXCLUDED.n)"
)
COUNTER_COPY = (
    "INSERT INTO analytics_counter (org_id, day, kind, k1, k2, device, seg, field, n) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT DO NOTHING"
)
HEAT_ADD = (
    "INSERT INTO analytics_heat (org_id, page, device, seg, kind, gx, gy, n) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) "
    "ON CONFLICT (org_id, page, device, seg, kind, gx, gy) "
    "DO UPDATE SET n = analytics_heat.n + EXCLUDED.n"
)
IMPORT_MARK = (
    "INSERT INTO analytics_history_imports (source_collection, source_id) VALUES ($1,$2) "
    "ON CONFLICT (source_collection, source_id) DO NOTHING RETURNING source_id"
)
RETENTION_DELETE = "DELETE FROM analytics_counter WHERE day < $1"


def _path_value(doc: dict, field: str, value: int) -> None:
    parts = field.split(".")
    cur = doc
    for part in parts[:-1]:
        child = cur.get(part)
        if not isinstance(child, dict):
            child = {}
            cur[part] = child
        cur = child
    cur[parts[-1]] = int(value)


def _flatten_numeric_fields(doc: dict, *, excluded: set[str]) -> list[tuple[str, int]]:
    """Flatten dotted/nested numeric counter fields while excluding metadata."""
    rows: list[tuple[str, int]] = []
    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for subkey, child in value.items():
                walk(f"{prefix}.{subkey}" if prefix else str(subkey), child)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            rows.append((prefix, int(value)))
    for key, value in doc.items():
        if key not in excluded:
            walk(str(key), value)
    return rows


def flatten_counter_deltas(deltas: dict) -> list[tuple]:
    rows = []
    for (org, day, kind, k1, k2, device, seg), fields in deltas.items():
        for field, n in fields.items():
            rows.append((str(org), str(day), str(kind), str(k1), str(k2), str(device), str(seg),
                         str(field), int(n)))
    return rows


def flatten_heat_deltas(heat: dict) -> list[tuple]:
    return [(str(org), str(page), str(device), str(seg), str(kind), int(gx), int(gy), int(n))
            for (org, page, device, seg, kind, gx, gy), n in heat.items()]


def flatten_counter_document(doc: dict) -> list[tuple]:
    required = ("org_id", "day", "kind", "k1", "k2", "device", "seg")
    if any(doc.get(k) is None for k in required):
        raise ValueError("analytics counter document is missing a key field")
    fields = _flatten_numeric_fields(doc, excluded={*required, "_id", "day_dt"})
    return [(str(doc["org_id"]), str(doc["day"]), str(doc["kind"]), str(doc["k1"]), str(doc["k2"]),
             str(doc["device"]), str(doc["seg"]), field, n) for field, n in fields]


def flatten_heat_document(doc: dict) -> tuple:
    required = ("org_id", "page", "device", "seg", "kind", "gx", "gy", "n")
    if any(k not in doc for k in required):
        raise ValueError("analytics heat document is missing a key field")
    return (str(doc["org_id"]), str(doc["page"]), str(doc["device"]), str(doc["seg"]),
            str(doc["kind"]), int(doc["gx"]), int(doc["gy"]), int(doc["n"]))


def counter_documents_from_rows(rows: Iterable[Any]) -> list[dict]:
    """Rebuild Mongo-shaped documents so build_summary remains unchanged."""
    docs: dict[tuple, dict] = {}
    for row in rows:
        if hasattr(row, "keys"):
            get = row.__getitem__
        else:
            raise TypeError("counter row must be mapping-like")
        key_names = ("org_id", "day", "kind", "k1", "k2", "device", "seg")
        key = tuple(get(k) for k in key_names)
        doc = docs.get(key)
        if doc is None:
            doc = dict(zip(key_names, key))
            docs[key] = doc
        _path_value(doc, get("field"), get("n"))
    return list(docs.values())


class MongoAnalyticsStore:
    name = "mongo"

    def __init__(self, db, build_ops: Callable):
        self.db = db
        self._build_ops = build_ops

    async def ensure_schema(self, create: bool = True) -> None:
        if not create:
            return
        await self.db.analytics_counters.create_index(
            [("org_id", 1), ("day", 1), ("kind", 1), ("k1", 1), ("k2", 1), ("device", 1), ("seg", 1)], unique=True)
        await self.db.analytics_counters.create_index("day_dt", expireAfterSeconds=400 * 86400)
        await self.db.analytics_heat.create_index(
            [("org_id", 1), ("page", 1), ("device", 1), ("seg", 1), ("kind", 1), ("gx", 1), ("gy", 1)], unique=True)

    async def warm_keys(self) -> list[dict]:
        cur = self.db.analytics_counters.aggregate([
            {"$match": {"kind": {"$in": ["pv", "click", "err", "api", "chan"]}}},
            {"$group": {"_id": {"o": "$org_id", "k": "$kind", "a": "$k1", "b": "$k2"}}},
            {"$limit": 20000},
        ])
        out = []
        async for row in cur:
            key = row.get("_id") or {}
            out.append({"org_id": key.get("o"), "kind": key.get("k"), "k1": key.get("a"), "k2": key.get("b")})
        return out

    async def write(self, deltas: dict, heat: dict) -> None:
        ops, hops = self._build_ops(deltas, heat)
        if ops:
            await self.db.analytics_counters.bulk_write(ops, ordered=False)
        if hops:
            await self.db.analytics_heat.bulk_write(hops, ordered=False)

    async def fetch_counters(self, orgs, days: int, seg: str, device: str, now: datetime) -> list[dict]:
        query: dict[str, Any] = {
            "org_id": {"$in": orgs} if isinstance(orgs, list) else orgs,
            "day": {"$gte": (now - timedelta(days=days)).strftime("%Y-%m-%d")},
        }
        if seg != "all":
            query["seg"] = {"$in": [seg, "all"]}
        if device != "all":
            query["device"] = {"$in": [device, "all"]}
        return [row async for row in self.db.analytics_counters.find(query)]

    async def fetch_heat(self, org_id: str, page: str, device: str, kind: str, seg: str) -> list[dict]:
        query: dict[str, Any] = {"org_id": org_id, "page": page, "kind": kind}
        if device != "all":
            query["device"] = device
        if seg != "all":
            query["seg"] = seg
        return [row async for row in self.db.analytics_heat.find(query).limit(5000)]

    async def first_day(self, org_id: str) -> str | None:
        async for row in self.db.analytics_counters.find(
                {"org_id": org_id}, {"day": 1, "_id": 0}).sort("day", 1).limit(1):
            return row.get("day")
        return None

    async def purge(self, org_id: str) -> None:
        await self.db.analytics_counters.delete_many({"org_id": org_id})
        await self.db.analytics_heat.delete_many({"org_id": org_id})

    async def close(self) -> None:
        return None

    def safe_error(self, exc: BaseException) -> str:
        return str(exc)[:250]


class PostgresAnalyticsStore:
    """Neon/Postgres store. It verifies a pre-provisioned schema using CRUD-only credentials."""
    name = "postgres"

    def __init__(self, url: str, pooled: bool = False, pool_factory=None):
        self._url = (url or "").strip()
        self._pooled = bool(pooled)
        self._pool_factory = pool_factory
        self._pool = None
        self._ready = False
        self._last_retention_day: str | None = None
        self.last_pool_kwargs = None

    async def _get_pool(self):
        if self._pool is None:
            if not self._url:
                raise RuntimeError("ANALYTICS_POSTGRES_URL is required when ANALYTICS_STORE=postgres")
            kw = {"min_size": 1, "max_size": 2, "command_timeout": 5, "timeout": 5}
            # TLS is mandatory. Neon normally supplies sslmode=require in its URL;
            # force it in the driver when the URL omits an explicit secure sslmode.
            query = parse_qs(urlsplit(self._url).query)
            sslmode = (query.get("sslmode") or [""])[0].lower()
            if sslmode and sslmode not in {"require", "verify-ca", "verify-full"}:
                raise RuntimeError("ANALYTICS_POSTGRES_URL must require TLS (sslmode=require or stronger)")
            if not sslmode:
                kw["ssl"] = "require"
            if self._pooled:
                kw["statement_cache_size"] = 0
            self.last_pool_kwargs = kw
            if self._pool_factory is not None:
                self._pool = await asyncio.wait_for(self._pool_factory(self._url, **kw), timeout=5)
            else:
                import asyncpg  # lazy import by design
                self._pool = await asyncio.wait_for(asyncpg.create_pool(self._url, **kw), timeout=5)
        return self._pool

    async def _verify_schema(self, con) -> None:
        if self._ready:
            return
        for sql in VERIFY_SCHEMA_SQL:
            await con.execute(sql)
        self._ready = True

    async def ensure_schema(self, create: bool = False) -> None:
        """Verify schema by default; create=True is only for a privileged one-off bootstrap."""
        if self._ready:
            return
        pool = await self._get_pool()
        async with pool.acquire() as con:
            if create:
                for sql in (COUNTER_DDL, HEAT_DDL, IMPORT_DDL, *INDEX_DDL):
                    await con.execute(sql)
                self._ready = True
            else:
                await self._verify_schema(con)

    async def warm_keys(self) -> list[dict]:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            rows = await con.fetch(
                "SELECT DISTINCT org_id, kind, k1, k2 FROM analytics_counter "
                "WHERE kind = ANY($1::text[]) LIMIT 20000", ["pv", "click", "err", "api", "chan"])
        return [dict(row) for row in rows]

    async def write(self, deltas: dict, heat: dict) -> None:
        counter_rows = flatten_counter_deltas(deltas)
        heat_rows = flatten_heat_deltas(heat)
        # A quiet day still needs its daily retention pass, but do not keep waking Neon
        # on every scheduled empty flush after today's cleanup has completed.
        today_date = datetime.now(timezone.utc).date()
        today = today_date.isoformat()
        retention_due = self._last_retention_day != today
        if not counter_rows and not heat_rows and not retention_due:
            return
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            async with con.transaction():
                additive = [r for r in counter_rows if r[2] != "conc"]
                maxima = [r for r in counter_rows if r[2] == "conc"]
                if additive:
                    await con.executemany(COUNTER_ADD, additive)
                if maxima:
                    await con.executemany(COUNTER_MAX, maxima)
                if heat_rows:
                    await con.executemany(HEAT_ADD, heat_rows)
                # Retention runs even on the first empty daily flush, then at most once per UTC day.
                if retention_due:
                    cutoff = (today_date - timedelta(days=400)).isoformat()
                    await con.execute(RETENTION_DELETE, cutoff)
                    retention_day_to_mark = today
                else:
                    retention_day_to_mark = None
            if retention_day_to_mark is not None:
                self._last_retention_day = retention_day_to_mark

    async def fetch_counters(self, orgs, days: int, seg: str, device: str, now: datetime) -> list[dict]:
        org_ids = orgs if isinstance(orgs, list) else [orgs]
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            rows = await con.fetch(
                "SELECT org_id, day, kind, k1, k2, device, seg, field, n FROM analytics_counter "
                "WHERE org_id = ANY($1::text[]) AND day >= $2 "
                "AND ($3::text = 'all' OR seg = $3 OR seg = 'all') "
                "AND ($4::text = 'all' OR device = $4 OR device = 'all')",
                [str(x) for x in org_ids], cutoff, seg, device)
        return counter_documents_from_rows(rows)

    async def fetch_heat(self, org_id: str, page: str, device: str, kind: str, seg: str) -> list[dict]:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            rows = await con.fetch(
                "SELECT gx, gy, n FROM analytics_heat WHERE org_id = $1 AND page = $2 AND kind = $3 "
                "AND ($4::text = 'all' OR device = $4) AND ($5::text = 'all' OR seg = $5) LIMIT 5000",
                org_id, page, kind, device, seg)
        return [dict(row) for row in rows]

    async def first_day(self, org_id: str) -> str | None:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            return await con.fetchval("SELECT MIN(day) FROM analytics_counter WHERE org_id = $1", org_id)

    async def purge(self, org_id: str) -> None:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            async with con.transaction():
                await con.execute("DELETE FROM analytics_counter WHERE org_id = $1", org_id)
                await con.execute("DELETE FROM analytics_heat WHERE org_id = $1", org_id)

    async def copy_history_batch(self, counter_docs: list[dict], heat_docs: list[dict]) -> dict[str, int]:
        """Idempotently copy one batch; heat is cumulative and must be additive exactly once."""
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        added_counters = added_heat = skipped = 0
        async with pool.acquire() as con:
            await self._verify_schema(con)
            async with con.transaction():
                for doc in counter_docs:
                    source_id = str(doc.get("_id", ""))
                    if not source_id:
                        raise ValueError("counter history document has no _id")
                    inserted = await con.fetchval(IMPORT_MARK, "analytics_counters", source_id)
                    if not inserted:
                        skipped += 1
                        continue
                    rows = flatten_counter_document(doc)
                    if rows:
                        # The ledger above guarantees each Mongo document is applied once, so adding is safe even on the
                        # cutover day, where live Postgres rows already exist for the same keys. "conc" keeps max.
                        additive = [r for r in rows if r[2] != "conc"]
                        maxima = [r for r in rows if r[2] == "conc"]
                        if additive:
                            await con.executemany(COUNTER_ADD, additive)
                        if maxima:
                            await con.executemany(COUNTER_MAX, maxima)
                        added_counters += len(rows)
                for doc in heat_docs:
                    source_id = str(doc.get("_id", ""))
                    if not source_id:
                        raise ValueError("heat history document has no _id")
                    inserted = await con.fetchval(IMPORT_MARK, "analytics_heat", source_id)
                    if not inserted:
                        skipped += 1
                        continue
                    await con.execute(HEAT_ADD, *flatten_heat_document(doc))
                    added_heat += 1
        return {"counter_rows": added_counters, "heat_rows": added_heat, "skipped_documents": skipped}

    async def counter_totals(self, cutoff: str, start_day: str) -> list[dict]:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            rows = await con.fetch(
                "SELECT org_id, kind, field, SUM(n)::bigint AS total FROM analytics_counter "
                "WHERE day >= $1 AND day < $2 GROUP BY org_id, kind, field ORDER BY org_id, kind, field",
                start_day, cutoff)
        return [dict(r) for r in rows]

    async def heat_totals(self) -> dict[str, int]:
        pool = await asyncio.wait_for(self._get_pool(), timeout=5)
        async with pool.acquire() as con:
            await self._verify_schema(con)
            rows = await con.fetch("SELECT org_id, SUM(n)::bigint AS total FROM analytics_heat GROUP BY org_id")
        return {str(r["org_id"]): int(r["total"]) for r in rows}

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            close = getattr(pool, "close", None)
            if close is not None:
                await asyncio.wait_for(close(), timeout=5)
        self._ready = False

    def safe_error(self, exc: BaseException) -> str:
        return scrub(str(exc), secrets=(self._url,))


def make_postgres_store_from_env(pool_factory=None) -> PostgresAnalyticsStore:
    pooled = os.getenv("ANALYTICS_POSTGRES_POOLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    return PostgresAnalyticsStore(os.getenv("ANALYTICS_POSTGRES_URL", ""), pooled=pooled, pool_factory=pool_factory)
