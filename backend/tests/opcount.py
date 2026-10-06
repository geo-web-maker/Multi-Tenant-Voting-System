"""Counts database calls at the application level (what main.py itself asks Mongo for), so the numbers do
not include the mock's own internals. Used by tests/test_performance_budget.py."""
import collections

OPS = {"find_one", "find", "count_documents", "update_one", "update_many", "insert_one", "insert_many",
       "delete_one", "delete_many", "find_one_and_update", "find_one_and_delete", "aggregate",
       "bulk_write", "replace_one", "estimated_document_count", "distinct"}


class _Coll:
    def __init__(self, real, name, counter):
        self._real, self._name, self._c = real, name, counter

    def __getattr__(self, attr):
        v = getattr(self._real, attr)
        if attr in OPS and callable(v):
            def counted(*a, **k):
                self._c[(self._name, attr)] += 1
                return v(*a, **k)
            return counted
        return v


class CountingDB:
    def __init__(self, real):
        self._real, self.counter = real, collections.Counter()

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Coll(getattr(self._real, name), name, self.counter)

    __getitem__ = __getattr__

    def total(self):
        return sum(self.counter.values())

    def snapshot(self):
        return collections.Counter(self.counter)

    def since(self, snap):
        d = collections.Counter({k: v - snap.get(k, 0) for k, v in self.counter.items() if v - snap.get(k, 0)})
        return d


class FakeSession:
    """mongomock cannot run transactions; this runs the callback straight through."""
    async def with_transaction(self, cb):
        return await cb(None)


class FakeSessionCM:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, *a):
        return False


class FakeClient:
    async def start_session(self):
        return FakeSessionCM()
