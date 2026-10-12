"""Shared test doubles for the backup/mirror/restore tests (no network, no real cluster)."""
import gzip, hashlib, io, json
from bson import json_util
import backup


class _Admin:
    async def command(self, *a, **k):
        return {"ok": 1}


class FakeClient:
    """Stands in for a Motor client: distinct node set, ping, db lookup."""
    def __init__(self, mongo_db_client, nodes):
        self._c, self.nodes, self.admin = mongo_db_client, set(nodes), _Admin()

    def __getitem__(self, name):
        return self._c[name]

    def close(self):
        pass


class FakeDb:
    """Wraps a mongomock-motor db, exposing `.client` with a node set like a real Motor db."""
    def __init__(self, db, nodes):
        self._db, self.name, self.client = db, db.name, FakeClient(db.client, nodes)

    def __getattr__(self, n):
        return getattr(self._db, n)

    def __getitem__(self, n):
        return self._db[n]


class FakeS3:
    """Minimal boto3 double: get_object + paginator over an in-memory key->bytes dict."""
    def __init__(self):
        self.objects = {}

    def put(self, key, data):
        self.objects[key] = data

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {}

    def get_paginator(self, _):
        outer = self

        class P:
            def paginate(self, Bucket, Prefix, Delimiter):
                seen = sorted({Prefix + k[len(Prefix):].split("/")[0] + "/"
                               for k in outer.objects if k.startswith(Prefix) and "/" in k[len(Prefix):]})
                return [{"CommonPrefixes": [{"Prefix": p} for p in seen]}]
        return P()


def put_backup(s3, prefix, tenant, org_id, collections, kind="full", lock_class="routine", tamper=None):
    """Write a backup in the same layout backup.py uses. `tamper` in {'checksum','count'} corrupts it."""
    entries = {}
    for name, docs in collections.items():
        raw = b"".join(backup._dump_line(d) for d in docs)
        gz = gzip.compress(raw)
        entry = {"file": f"{name}.jsonl.gz", "sha256_gz": hashlib.sha256(gz).hexdigest(),
                 "sha256_uncompressed": hashlib.sha256(raw).hexdigest(), "count": len(docs)}
        if tamper == "count":
            entry["count"] += 1
        if tamper == "checksum":
            entry["sha256_gz"] = "0" * 64
        entries[name] = entry
        s3.put(f"{prefix}/{entry['file']}", gz)
    s3.put(f"{prefix}/manifest.json", json.dumps({
        "tenant": tenant, "org_id": org_id, "kind": kind, "lock_class": lock_class,
        "created_at": "2026-10-12T00:00:00+00:00", "collections": entries}).encode())


CFG = {"bucket": "b"}
