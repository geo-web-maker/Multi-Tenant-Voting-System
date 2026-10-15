"""Pure-logic tests for the Bulk SMS tab (counting, variables, pricing validation, audience query, estimate).
The same counting vectors are in frontend/src/smsCalc.test.js: keep them in step."""
import pytest

import sms_bulk as sb


def norm_phone(raw):
    import re
    c = re.sub(r"\D", "", raw or "")
    if c.startswith("0"):
        c = "256" + c[1:]
    if not 10 <= len(c) <= 15:
        raise ValueError("bad phone")
    return c


def norm_sid(s):
    return str(s).strip().lower()


# ── counting ─────────────────────────────────────────────────────────────────
def test_empty():
    assert sb.count_parts("") == {"chars": 0, "encoding": "GSM-7", "parts": 0, "remaining": 160}


def test_exactly_single_limit_and_one_over():
    assert sb.count_parts("a" * 160)["parts"] == 1
    over = sb.count_parts("a" * 161)
    assert over["parts"] == 2 and over["remaining"] == 2 * 153 - 161


def test_two_full_parts():
    assert sb.count_parts("a" * 306)["parts"] == 2
    assert sb.count_parts("a" * 307)["parts"] == 3


def test_extended_char_counts_twice():
    assert sb.count_parts("€")["chars"] == 2
    assert sb.count_parts("a" * 159 + "€")["parts"] == 2     # 161 units


def test_emoji_flips_encoding():
    c = sb.count_parts("hi 😀")
    assert c["encoding"] == "UCS-2" and c["chars"] == 5 and c["parts"] == 1
    assert sb.count_parts("a" * 70 + "😀")["parts"] == 2


def test_curly_quote_flips_encoding():
    assert sb.count_parts("it\u2019s")["encoding"] == "UCS-2"


def test_custom_limits():
    lim = {"single_limit": 10, "multi_limit": 5}
    assert sb.count_parts("a" * 10, lim)["parts"] == 1
    assert sb.count_parts("a" * 11, lim)["parts"] == 3


# ── variables ────────────────────────────────────────────────────────────────
def test_render_known_missing_unknown_and_braces():
    v = sb.voter_values({"full_name": "Jane  Okello", "student_id": "21/U/1", "attrs": {"hostel": "Hall A"}}, ["hostel", "programme"])
    assert v["first_name"] == "Jane" and v["name"] == "Jane Okello" and v["reg_no"] == "21/U/1"
    assert sb.render("Hi {first_name} {hostel}{programme} {x} {", v) == "Hi Jane Hall A {x} {"


def test_unknown_tokens():
    assert sb.unknown_tokens("{name} {foo} {foo} {bar}", sb.variable_names(["hostel"])) == ["foo", "bar"]


def test_variable_names_no_duplicates():
    assert sb.variable_names(["name", "hostel"]).count("name") == 1


# ── pricing validation ───────────────────────────────────────────────────────
def test_pricing_valid_merge():
    out = sb.validate_pricing({"egosms": {"cost_per_part_ugx": 35}})
    assert out["egosms"]["cost_per_part_ugx"] == 35 and out["egosms"]["single_limit"] == 160
    assert out["mambosms"]["cost_per_part_ugx"] is None


@pytest.mark.parametrize("bad", [
    {"egosms": {"cost_per_part_ugx": -1}},
    {"egosms": {"multi_limit": 200}},                       # > single_limit
    {"egosms": {"unicode_multi_limit": 80}},                # > unicode_single_limit
    {"egosms": {"single_limit": 0}},
    {"egosms": {"single_limit": 1001}},
    {"egosms": {"single_limit": 160.5}},
    {"egosms": {"nonsense": 1}},
    {"twilio": {"cost_per_part_ugx": 1}},
])
def test_pricing_rejects(bad):
    with pytest.raises(ValueError):
        sb.validate_pricing(bad)


def test_pricing_unset_stays_none():
    assert sb.pricing_for({}, "egosms")["cost_per_part_ugx"] is None


# ── audience query ───────────────────────────────────────────────────────────
def test_query_only_enabled_keys():
    with pytest.raises(ValueError):
        sb.build_voter_query({"attrs": {"$where": ["1"]}}, ["hostel"], norm_sid)
    with pytest.raises(ValueError):
        sb.build_voter_query({"attrs": {"gender": ["F"]}}, ["hostel"], norm_sid)


def test_query_and_between_fields_or_within():
    q = sb.build_voter_query({"voted": "not_voted", "attrs": {"hostel": ["A", "B"]}, "reg_numbers": "21/U/1, 21/U/2"}, ["hostel"], norm_sid)
    assert q["has_voted"] == {"$ne": True}
    assert {"attrs.hostel": {"$in": ["A", "B"]}} in q["$and"]
    assert {"student_id": {"$in": ["21/u/1", "21/u/2"]}} in q["$and"]


def test_query_bad_voted():
    with pytest.raises(ValueError):
        sb.build_voter_query({"voted": "maybe"}, [], norm_sid)


# ── phones + estimate ────────────────────────────────────────────────────────
def test_first_phone_splits_slash_and_skips_bad():
    assert sb.first_phone({"phone_numbers": ["junk/0772000001"]}, norm_phone) == "256772000001"
    assert sb.first_phone({"phone_numbers": []}, norm_phone) is None


def test_estimate_total_is_sum_of_parts_times_cost():
    voters = [
        {"full_name": "Al", "student_id": "a", "phone_numbers": ["0772000001"]},
        {"full_name": "B" * 200, "student_id": "b", "phone_numbers": ["0772000002"]},
        {"full_name": "NoPhone", "student_id": "c", "phone_numbers": []},
    ]
    est = sb.estimate(voters, "Hi {name}", [], sb.DEFAULT_LIMITS, 30, norm_phone)
    assert est["recipients"] == 2 and est["no_phone"] == 1
    assert est["by_parts"] == {"1": 1, "2": 1} and est["total_parts"] == 3
    assert est["total_cost"] == 90 and est["min_len"] < est["max_len"]


def test_estimate_unset_price_has_no_total():
    est = sb.estimate([{"full_name": "Al", "student_id": "a", "phone_numbers": ["0772000001"]}], "Hi", [], sb.DEFAULT_LIMITS, None, norm_phone)
    assert est["total_cost"] is None and est["total_parts"] == 1


def test_estimate_reports_missing_only_for_used_vars():
    voters = [{"full_name": "Al", "student_id": "a", "phone_numbers": ["0772000001"], "attrs": {}}]
    est = sb.estimate(voters, "Hi {programme}", ["programme", "hostel"], sb.DEFAULT_LIMITS, 1, norm_phone)
    assert est["missing"] == {"programme": 1}
