"""D1a (guide 5.3): `usable_ms` - time until the voter login form was interactive. Validate, store as a histogram, aggregate."""
from datetime import datetime, timezone

import analytics as a
from tests.test_analytics import ingest, docs_from_deltas, body, clean_state  # noqa: F401  (autouse fixture + helpers)


def perf(**kw):
    return {"t": "perf", "page": "voter_identity", "load_ms": 1500, "first_api_ms": 700, "net": "4g", **kw}


def summary():
    return a.build_summary(docs_from_deltas(), 1, datetime.now(timezone.utc))


def test_validate_clamps_usable_ms():
    _, _, _, ev = a.validate_events(body([
        perf(usable_ms=999999), perf(usable_ms=-5), perf(usable_ms="abc"), perf(), perf(usable_ms=1200.7),
    ]))
    assert [e["usable_ms"] for e in ev] == [60000, 0, 0, 0, 1200]


def test_usable_ms_is_stored_as_a_histogram_next_to_load():
    ingest([perf(usable_ms=1200)])
    f = next(v for k, v in a._deltas.items() if k[2] == "perf")
    assert f["n"] == 1 and f[f"us.{a._hist_index(1200, a.USABLE_EDGES)}"] == 1 and f[f"l.{a._hist_index(1500, a.LOAD_EDGES)}"] == 1


def test_missing_or_zero_usable_adds_no_histogram_sample_but_still_counts_the_session():
    ingest([perf(), perf(usable_ms=0)])
    f = next(v for k, v in a._deltas.items() if k[2] == "perf")
    assert f["n"] == 2 and not any(key.startswith("us.") for key in f)


def test_summary_reports_usable_percentiles_per_page_and_per_network():
    ingest([perf(usable_ms=600), perf(usable_ms=900), perf(usable_ms=1800), perf(usable_ms=6000, net="3g")])
    s = summary()
    row = s["perf"][0]
    assert row["sessions"] == 4 and row["usable_p50"] is not None and row["usable_p95"] >= row["usable_p50"] > 0
    nets = {r["net"]: r for r in s["network_perf"]}
    assert nets["3g"]["usable_p50"] is not None and nets["3g"]["usable_p50"] > nets["4g"]["usable_p50"]


def test_usable_percentiles_are_none_without_samples_and_existing_fields_unchanged():
    ingest([perf()])
    row = summary()["perf"][0]
    assert row["usable_p50"] is None and row["usable_p95"] is None
    assert row["load_p50"] is not None and row["first_api_p50"] is not None and row["cold_pct"] == 0


def test_old_clients_without_usable_ms_still_ingest():
    ingest([{"t": "perf", "page": "results", "load_ms": 800, "first_api_ms": 300, "net": "4g"}])
    assert summary()["cold_starts"]["sessions"] == 1
