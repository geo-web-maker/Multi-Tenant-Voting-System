"""Pure-function tests for roster_utils: ID shape check, configurable fields, small-group suppression."""
import pytest

from roster_utils import (
    OTHER_LABEL, UNRECORDED_LABEL, apply_field_changes, attr_columns, check_id_shapes, diff_attrs, id_shape,
    merge_voter_fields, normalize_attr_value, row_attrs, shape_warnings, suppress_small_groups,
)


# ── registration-number shape ───────────────────────────────────────────────

def test_id_shape_collapses_runs():
    assert id_shape("24/u/afd/02107/pd") == "9/A/A/9/A"
    assert id_shape("23/u/bmsx/1/pe") == "9/A/A/9/A"           # serial / programme length don't matter
    assert id_shape("24/u/msd,02527/pd") == "9/A/A,9/A"
    assert id_shape("24/u/afd/03278/pd.") != id_shape("24/u/afd/03278/pd")


def _kyu_ids(n=289):
    codes = ["baf", "bba", "bms", "afd", "msd"]
    return [f"24/u/{codes[i % 5]}/{i:05d}/{'pd' if i % 3 else 'pe'}" for i in range(n)]


BAD = ["24/u/msd,02527/pd", "24/u/afd/03278/pd.", "24/u/afd/03547/pd/", "24/u/afd/0999?/pd"]


def test_shape_check_flags_exactly_the_outliers():
    ids = _kyu_ids() + BAD
    r = check_id_shapes(ids)
    assert r["source"] == "file" and r["reference"] == "9/A/A/9/A"
    assert set(r["outliers"]) == set(BAD)
    assert r["share"] == pytest.approx(289 / 293)


def test_no_check_without_clear_majority_or_enough_rows():
    assert check_id_shapes(_kyu_ids(10) + ["x-1"]) is None                       # < 20 rows
    mixed = _kyu_ids(15) + [f"S{i}" for i in range(15)]                          # 50/50
    assert check_id_shapes(mixed) is None


def test_roster_is_the_reference_so_a_whole_wrong_file_is_caught():
    roster = _kyu_ids(60)
    file_ids = [f"S{i:04d}" for i in range(8)]                                   # small file, other format
    r = check_id_shapes(file_ids, roster)
    assert r["source"] == "roster" and r["outliers"] == file_ids
    w = shape_warnings(r, len(file_ids), {i: n + 2 for n, i in enumerate(file_ids)})
    assert len(w) == 1 and "8 of 8" in w[0] and "existing voter register" in w[0]


def test_per_row_warnings_when_few_outliers():
    r = check_id_shapes(_kyu_ids() + BAD)
    w = shape_warnings(r, 293, {i: n + 2 for n, i in enumerate(BAD)})
    assert len(w) == 4 and all("Row " in x for x in w)


# ── suppression ─────────────────────────────────────────────────────────────

def g(label, reg, voted):
    return {"label": label, "registered": reg, "voted": voted}


def test_small_groups_fold_into_other():
    res = suppress_small_groups([g("BAF", 264, 200), g("BBA", 24, 10), g("BMS", 5, 2), g("X", 3, 1), g("Y", 4, 1)], k=10)
    labels = {x["label"]: x for x in res["groups"]}
    assert set(labels) == {"BAF", "BBA", OTHER_LABEL}
    assert labels[OTHER_LABEL]["registered"] == 12 and labels[OTHER_LABEL]["voted"] == 4
    assert res["groups"][-1]["label"] == OTHER_LABEL and not res["suppressed"]


def test_other_absorbs_next_smallest_so_it_cannot_be_subtracted_out():
    res = suppress_small_groups([g("F", 100, 50), g("M", 12, 6), g("X", 2, 1)], k=10)
    assert {x["label"] for x in res["groups"]} == {"F", OTHER_LABEL}
    other = next(x for x in res["groups"] if x["label"] == OTHER_LABEL)
    assert other["registered"] == 14 and other["pct"] == 50.0


def test_tiny_or_single_bucket_is_withheld():
    assert suppress_small_groups([g("F", 4, 1), g("M", 3, 1)], k=10) == {"groups": [], "suppressed": True}
    assert suppress_small_groups([g("F", 50, 20)], k=10) == {"groups": [], "suppressed": True}
    assert suppress_small_groups([g("F", 50, 20), g("M", 3, 1)], k=10) == {"groups": [], "suppressed": True}


def test_no_published_group_is_below_k():
    for k in (5, 10, 30):
        res = suppress_small_groups([g("a", 200, 1), g("b", 31, 2), g("c", 9, 3), g("d", 6, 1), g("e", 1, 0)], k)
        assert all(x["registered"] >= k for x in res["groups"])


# ── configurable fields ─────────────────────────────────────────────────────

def test_defaults_are_standard_fields_switched_off():
    f = merge_voter_fields(None)
    assert [x["key"] for x in f] == ["gender", "programme"]
    assert not any(x["enabled"] or x["public"] for x in f) and all(x["standard"] for x in f)


def test_public_implies_enabled():
    f = merge_voter_fields([{"key": "gender", "enabled": False, "public": True}])
    assert f[0]["public"] is False


def test_add_custom_field_toggle_and_remove():
    cur = merge_voter_fields(None)
    new, removed = apply_field_changes(cur, [{"key": "Hostel", "enabled": True, "public": True},
                                             {"key": "gender", "enabled": True}], [])
    assert [x["key"] for x in new] == ["gender", "programme", "hostel"]
    h = new[2]
    assert (h["label"], h["standard"], h["enabled"], h["public"]) == ("Hostel", False, True, True)
    new2, removed = apply_field_changes(new, [{"key": "hostel", "enabled": False}], [])
    assert new2[2]["public"] is False                                            # switching off drops public
    new3, removed = apply_field_changes(new2, [], ["hostel"])
    assert removed == ["hostel"] and [x["key"] for x in new3] == ["gender", "programme"]


@pytest.mark.parametrize("upserts,remove,msg", [
    ([{"key": "9bad"}], [], "must start with a letter"),
    ([{"key": "phone"}], [], "reserved"),
    ([{"key": "student_id"}], [], "reserved"),
    ([], ["gender"], "standard field"),
    ([], ["nope"], "Unknown field"),
    ([{"key": "faculty", "label": "Gender"}], [], "same label"),
    ([{"key": "faculty", "label": "x" * 41}], [], "Label must be"),
])
def test_field_edit_validation(upserts, remove, msg):
    with pytest.raises(ValueError, match=msg):
        apply_field_changes(merge_voter_fields(None), upserts, remove)


def test_max_fields():
    cur = merge_voter_fields(None)
    with pytest.raises(ValueError, match="At most"):
        apply_field_changes(cur, [{"key": f"f{i}"} for i in range(7)], [])


@pytest.mark.parametrize("raw,expected", [
    ("baf", "BAF"), ("BAF", "BAF"), (" f ", "F"), ("female", "Female"), ("FEMALE", "Female"),
    ("Bachelor of Arts", "Bachelor of Arts"), ("", ""), (None, ""), ("x" * 100, "X" * 60 if False else ("x" * 60).title()),
])
def test_normalize_attr_value(raw, expected):
    assert normalize_attr_value(raw) == expected
    assert normalize_attr_value(normalize_attr_value(raw)) == normalize_attr_value(raw)


def test_columns_match_key_label_and_aliases_only_when_enabled():
    fields = merge_voter_fields([{"key": "gender", "enabled": True}, {"key": "programme", "enabled": False},
                                 {"key": "hostel", "label": "Hostel Block", "enabled": True}])
    cols = attr_columns(["NAME", "student_id", "SEX", "PROGRAMME", "hostel-block"], fields)
    assert cols == {"gender": "SEX", "hostel": "hostel-block"}                   # programme is off
    assert row_attrs({"SEX": " f ", "hostel-block": ""}, cols) == {"gender": "F"}  # blank = not provided


def test_diff_attrs_separates_fills_from_overwrites():
    fills, over = diff_attrs({"gender": "F", "programme": ""}, {"gender": "M", "programme": "BAF", "hostel": "A"},
                             {"gender", "programme"})
    assert fills == {"programme": "BAF"}                                          # hostel disabled -> ignored
    assert over == {"gender": {"old": "F", "new": "M"}}
    assert diff_attrs({"gender": "F"}, {"gender": "f"}, {"gender"}) == ({}, {})   # case is not a change
