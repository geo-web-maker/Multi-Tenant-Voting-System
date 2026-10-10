"""Static guard: request-path code must reach tenant-owned collections through the scoped handle.

Every direct ``db.<tenant_collection>.<op>(...)`` / ``db["<tenant_collection>"]`` in the modules below is a
violation unless it is

  * index/DDL work at startup (create_index / create_indexes / drop_index), or
  * wrapped in ``cross_tenant(db)`` (the greppable, deliberate "can see all clients" door), or
  * listed in ALLOWED with a written reason.

ALLOWED is a ratchet: a new unscoped access fails this test, and so does an entry that no longer exists
(delete it), so the list can only shrink. To fix a failure, use ``tdb(request)`` / ``tdb_for(org_id)``.
"""
import ast
import os
from collections import Counter

from tenant_db import TENANT_COLLECTIONS

BACKEND = os.path.dirname(os.path.dirname(__file__))
MODULES = ["main.py", "analytics.py", "backup_routes.py", "backup.py", "regno_audit.py", "roster_utils.py",
           "tabular_import.py", "otp_limits.py", "alerts.py", "name_utils.py", "auth.py"]
INDEX_METHODS = {"create_index", "create_indexes", "ensure_index", "drop_index"}
DB_NAMES = {"db", "_db"}

# (module, enclosing function, collection, method) -> why this raw access is acceptable
_BACKUP = ("backup.py is the operator's cross-tenant tool (snapshots every client, one org at a time, "
           "with an explicit org_id filter). It also still enumerates the ownerless 'legacy' tenant for the "
           "legacy-data check, so it cannot use a tenant handle yet.")
_REGNO = ("Shared with the operator CLI check_reg_numbers.py, whose default is 'all organisations'. The HTTP "
          "route calls it with require_org(request.state.org_id), so it is always one tenant there.")
ALLOWED = {
    ("backup.py", "_election_flags", "settings", "find_one"): _BACKUP,
    ("backup.py", "_measure", "<dynamic>", "find"): _BACKUP,
    ("backup.py", "_results_release_hint", "settings", "find_one"): _BACKUP,
    ("backup.py", "backup_tenant", "<dynamic>", "find_one"): _BACKUP,
    ("backup.py", "export_collection", "<dynamic>", "find"): _BACKUP,
    ("backup.py", "list_tenants", "settings", "find_one"): _BACKUP,
    ("backup.py", "list_tenants", "voters", "find_one"): _BACKUP,
    ("regno_audit.py", "audit_reg_numbers", "<dynamic>", "bulk_write"): _REGNO,
    ("regno_audit.py", "audit_reg_numbers", "<dynamic>", "find"): _REGNO,
    ("regno_audit.py", "audit_reg_numbers", "voters", "bulk_write"): _REGNO,
    ("regno_audit.py", "audit_reg_numbers", "voters", "find"): _REGNO,
}


def _violations(module):
    tree = ast.parse(open(os.path.join(BACKEND, module), encoding="utf-8").read())
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p

    def enclosing(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return n.name
        return "<module>"

    found = []
    for n in ast.walk(tree):
        coll = None
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in DB_NAMES \
                and n.attr in TENANT_COLLECTIONS:
            coll = n.attr
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in DB_NAMES:
            sl = n.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                if sl.value in TENANT_COLLECTIONS:
                    coll = sl.value
            else:
                coll = "<dynamic>"          # db[name]: cannot be proven tenant-free
        if coll is None:
            continue
        parent = parents.get(n)
        method = parent.attr if isinstance(parent, ast.Attribute) else "<bare-reference>"
        if method in INDEX_METHODS:
            continue
        found.append((module, enclosing(n), coll, method))
    return found


def test_no_unscoped_access_to_tenant_collections():
    seen = Counter()
    for module in MODULES:
        if os.path.exists(os.path.join(BACKEND, module)):
            seen.update(_violations(module))
    unexpected = sorted(k for k in seen if k not in ALLOWED)
    assert not unexpected, (
        "Tenant collection accessed without a tenant scope. Use tdb(request) / tdb_for(org_id) "
        "(or cross_tenant(db) if it is deliberately cross-tenant):\n  "
        + "\n  ".join(map(str, unexpected)))
    stale = sorted(k for k in ALLOWED if k not in seen)
    assert not stale, "Remove these entries from ALLOWED, they no longer exist:\n  " + "\n  ".join(map(str, stale))


def test_lint_actually_detects_a_raw_access(tmp_path, monkeypatch):
    """Guard the guard: a raw db.voters.find_one in a fresh module must be reported."""
    import tests.test_tenant_scoping_lint as me
    (tmp_path / "evil.py").write_text(
        "async def route(request):\n    return await db.voters.find_one({'student_id': 'x'})\n"
        "async def dyn(name):\n    return await db[name].count_documents({})\n"
        "async def ok(request):\n    return await tdb(request).voters.find_one({})\n"
        "async def ok2():\n    return await cross_tenant(db).voters.find_one({})\n"
        "async def idx():\n    await db.voters.create_index('x')\n")
    monkeypatch.setattr(me, "BACKEND", str(tmp_path))
    assert sorted(me._violations("evil.py")) == [
        ("evil.py", "dyn", "<dynamic>", "count_documents"),
        ("evil.py", "route", "voters", "find_one"),
    ]


def test_collections_with_org_id_are_all_listed():
    """If the app stamps org_id on a collection it must be in TENANT_COLLECTIONS so it can be scoped & linted."""
    import re
    src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
    stamped = set(re.findall(r"tdb(?:_for)?\([^)]*\)\.([a-z_]+)\.", src))
    assert stamped <= TENANT_COLLECTIONS
