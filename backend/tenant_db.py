"""Tenant-scoped database access (fail-closed by construction).

Instead of remembering to write ``db.voters.find_one(org_query(request, {...}))`` at ~300 call sites,
a route obtains a scoped handle once::

    tdb = scoped_db(request)                      # raises 400 if the request has no tenant
    voter = await tdb.voters.find_one({"student_id": sid})
    await tdb.voters.update_one({"_id": voter["_id"]}, {"$set": {...}})
    await tdb.audit_log.insert_one({...})         # org_id stamped automatically

What a ``TenantCollection`` guarantees for every operation:

* reads / counts / updates / deletes have ``org_id == <this tenant>`` AND-ed into the filter;
* inserts are stamped with the tenant, and a document that already carries a *different* org_id is refused;
* an explicit ``org_id`` in a caller's filter that names another tenant is refused (never silently overridden);
* updates / replacements cannot move a document to another tenant (``$set: {org_id: ...}`` is refused);
* aggregation pipelines get a leading ``$match`` on the tenant, and stages that can reach other
  documents (``$lookup``, ``$unionWith``, ``$graphLookup``, ``$out``, ``$merge``) are refused;
* an empty / missing tenant raises ``HTTPException(400)`` when the handle is created, so there is no
  unscoped fallback to forget about.

Cross-tenant work (superadmin dashboards, backups, migrations) is still possible, but only through the
loudly named ``cross_tenant()`` below, so it is always a deliberate, greppable choice.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from fastapi import HTTPException

# Collections whose documents belong to exactly one tenant and carry an ``org_id`` field.
# (Global / infrastructure collections - organizations, revoked_tokens, ip_rate_limits, ip_send_stats,
# login_attempts, admin_otps, otp_* throttles keyed by their own scheme - are intentionally not listed.)
TENANT_COLLECTIONS = frozenset({
    "voters",
    "applications",
    "settings",
    "panel_members",
    "candidates",
    "contact_changes",
    "student_changes",
    "otps",
    "vote_events",
    "student_edit_audit",
    "roster_ledger",
    "audit_log",
    "positions",
    "candidate_tokens",
    "exception_grants",
    "certificates",
    "voter_import_previews",
    "nomination_uploads",
    "demo_inbox",
})

_FORBIDDEN_STAGES = frozenset({"$lookup", "$unionWith", "$graphLookup", "$out", "$merge"})


def require_tenant(org_id) -> str:
    """Return ``str(org_id)`` or refuse. A missing tenant is a 400, never an unscoped query."""
    if not org_id:
        raise HTTPException(400, "X-Org-Slug header is required.")
    return str(org_id)


class TenantScopeError(RuntimeError):
    """A caller tried to read or write outside its own tenant (programming error, not user error)."""


class TenantCollection:
    """Wraps one Motor collection; every operation is confined to ``org_id``."""

    __slots__ = ("_coll", "_org_id", "name")

    def __init__(self, coll, org_id: str, name: str):
        self._coll = coll
        self._org_id = org_id
        self.name = name

    # ---- helpers ------------------------------------------------------------------------------
    def _scope(self, flt: Mapping[str, Any] | None) -> dict:
        q = dict(flt) if flt else {}
        if "org_id" in q and q["org_id"] != self._org_id:
            raise TenantScopeError(
                f"{self.name}: filter names org_id={q['org_id']!r} but this handle is scoped to {self._org_id!r}")
        q["org_id"] = self._org_id
        return q

    def _stamp(self, doc: Mapping[str, Any]) -> dict:
        d = dict(doc)
        if "org_id" in d and d["org_id"] != self._org_id:
            raise TenantScopeError(
                f"{self.name}: document carries org_id={d['org_id']!r} but this handle is scoped to {self._org_id!r}")
        d["org_id"] = self._org_id
        return d

    def _check_update(self, update: Any) -> Any:
        if isinstance(update, Mapping):
            for op, body in update.items():
                if isinstance(body, Mapping) and "org_id" in body:
                    if op == "$setOnInsert" and body["org_id"] == self._org_id:
                        continue
                    if op == "$set" and body["org_id"] == self._org_id:
                        continue
                    raise TenantScopeError(f"{self.name}: update may not change org_id ({op})")
        else:  # aggregation-pipeline style update
            for stage in update:
                for body in stage.values():
                    if isinstance(body, Mapping) and "org_id" in body:
                        raise TenantScopeError(f"{self.name}: pipeline update may not touch org_id")
        return update

    def _scope_pipeline(self, pipeline: Iterable[Mapping[str, Any]]) -> list:
        stages = list(pipeline)
        for st in stages:
            bad = _FORBIDDEN_STAGES.intersection(st.keys())
            if bad:
                raise TenantScopeError(f"{self.name}: aggregation stage {sorted(bad)[0]} is not allowed on a tenant handle")
        return [{"$match": {"org_id": self._org_id}}, *stages]

    # ---- reads --------------------------------------------------------------------------------
    def find(self, flt=None, *args, **kwargs):
        return self._coll.find(self._scope(flt), *args, **kwargs)

    async def find_one(self, flt=None, *args, **kwargs):
        return await self._coll.find_one(self._scope(flt), *args, **kwargs)

    async def count_documents(self, flt=None, *args, **kwargs):
        return await self._coll.count_documents(self._scope(flt), *args, **kwargs)

    async def distinct(self, key, flt=None, *args, **kwargs):
        return await self._coll.distinct(key, self._scope(flt), *args, **kwargs)

    def aggregate(self, pipeline, *args, **kwargs):
        return self._coll.aggregate(self._scope_pipeline(pipeline), *args, **kwargs)

    # ---- writes -------------------------------------------------------------------------------
    async def insert_one(self, doc, *args, **kwargs):
        return await self._coll.insert_one(self._stamp(doc), *args, **kwargs)

    async def insert_many(self, docs, *args, **kwargs):
        return await self._coll.insert_many([self._stamp(d) for d in docs], *args, **kwargs)

    async def update_one(self, flt, update, *args, **kwargs):
        return await self._coll.update_one(self._scope(flt), self._check_update(update), *args, **kwargs)

    async def update_many(self, flt, update, *args, **kwargs):
        return await self._coll.update_many(self._scope(flt), self._check_update(update), *args, **kwargs)

    async def replace_one(self, flt, replacement, *args, **kwargs):
        return await self._coll.replace_one(self._scope(flt), self._stamp(replacement), *args, **kwargs)

    async def delete_one(self, flt, *args, **kwargs):
        return await self._coll.delete_one(self._scope(flt), *args, **kwargs)

    async def delete_many(self, flt, *args, **kwargs):
        # An empty filter is fine here: it means "everything in THIS tenant", which _scope() enforces.
        return await self._coll.delete_many(self._scope(flt), *args, **kwargs)

    async def find_one_and_update(self, flt, update, *args, **kwargs):
        return await self._coll.find_one_and_update(self._scope(flt), self._check_update(update), *args, **kwargs)

    async def find_one_and_delete(self, flt, *args, **kwargs):
        return await self._coll.find_one_and_delete(self._scope(flt), *args, **kwargs)

    async def find_one_and_replace(self, flt, replacement, *args, **kwargs):
        return await self._coll.find_one_and_replace(self._scope(flt), self._stamp(replacement), *args, **kwargs)

    async def bulk_write(self, requests, *args, **kwargs):
        """Accepts pymongo Insert/Update/Replace/Delete ops and rewrites each so it is tenant-confined."""
        import copy
        from pymongo import DeleteMany, DeleteOne, InsertOne, ReplaceOne, UpdateMany, UpdateOne
        safe = []
        for op in requests:
            op = copy.copy(op)          # keep every option the caller set (upsert, hint, collation, ...)
            if isinstance(op, InsertOne):
                op._doc = self._stamp(op._doc)
            elif isinstance(op, (UpdateOne, UpdateMany)):
                op._filter = self._scope(op._filter)
                op._doc = self._check_update(op._doc)
            elif isinstance(op, ReplaceOne):
                op._filter = self._scope(op._filter)
                op._doc = self._stamp(op._doc)
            elif isinstance(op, (DeleteOne, DeleteMany)):
                op._filter = self._scope(op._filter)
            else:
                raise TenantScopeError(f"{self.name}: unsupported bulk operation {type(op).__name__}")
            safe.append(op)
        return await self._coll.bulk_write(safe, *args, **kwargs)

    def __getattr__(self, attr):
        # Anything not listed above (create_index, drop, rename, watch, ...) is NOT exposed on a tenant
        # handle: index management and DDL belong on the raw db at startup, not in request code.
        raise AttributeError(
            f"TenantCollection({self.name!r}) does not expose {attr!r}; "
            f"use the raw db for index/DDL work, or add a tenant-safe wrapper for it in tenant_db.py")


class ScopedDB:
    """``tdb.<collection>`` -> TenantCollection for tenant-owned collections; anything else is refused."""

    __slots__ = ("_db", "org_id")

    def __init__(self, db, org_id: str):
        self._db = db
        self.org_id = org_id

    def __getattr__(self, name: str) -> TenantCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in TENANT_COLLECTIONS:
            raise AttributeError(
                f"{name!r} is not a tenant-owned collection; use the raw db for global collections "
                f"(or add {name!r} to TENANT_COLLECTIONS if its documents carry org_id)")
        return TenantCollection(self._db[name], self.org_id, name)


def scoped_db_for(db, org_id) -> ScopedDB:
    """Scoped handle for code that has an org_id but no request (background jobs, helpers)."""
    return ScopedDB(db, require_tenant(org_id))


def scoped_db(db, request) -> ScopedDB:
    """Scoped handle for the tenant resolved by the org-context middleware. 400 if there is none."""
    return ScopedDB(db, require_tenant(getattr(request.state, "org_id", None)))


def cross_tenant(db):
    """Raw database handle for the few deliberate cross-tenant operations (superadmin overviews, backups,
    migrations). Using this name is the audit trail: grep for it to list every place that can see all clients."""
    return db
