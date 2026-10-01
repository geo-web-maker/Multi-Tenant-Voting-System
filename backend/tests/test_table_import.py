"""Multi-format voter import + column mapping: tabular_import unit tests and the /inspect + /preview endpoints.
Reuses the `env` fixture (mongomock, org 't1', tokens e.it / e.sa) from test_flows."""
import io
import json

import pytest
from openpyxl import Workbook

import main  # noqa: F401
import tabular_import as ti
from tests.test_flows import env  # noqa: F401  (fixture)



def sid(n):
    return f"24/u/baf/{n:05d}/pd"


def xlsx_bytes(sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FIELDS = [{"key": "gender", "label": "Gender", "standard": True, "enabled": True, "public": False},
          {"key": "programme", "label": "Programme", "standard": True, "enabled": False, "public": False}]


# ── reading ─────────────────────────────────────────────────────────────────

def test_csv_semicolon_and_cp1252():
    raw = "Reg No;Names;Tel\n24/u/1;Zoë Nakato;0772123456\n".encode("cp1252")
    t = ti.read_table(raw, "roster.csv")
    assert t.rows[0] == ["Reg No", "Names", "Tel"] and t.rows[1][1] == "Zoë Nakato"


def test_tsv_and_xlsx_read_the_same():
    tsv = ti.read_table(b"student_id\tfull_name\n1\tA B\n", "x.tsv")
    xl = ti.read_table(xlsx_bytes({"S": [["student_id", "full_name"], [1, "A B"]]}), "x.xlsx")
    assert tsv.rows[1] == ["1", "A B"] and xl.rows[1] == ["1", "A B"]      # numbers arrive as clean text


def test_excel_numeric_phone_has_no_trailing_point_zero():
    t = ti.read_table(xlsx_bytes({"S": [["Phone"], [772123456.0]]}), "x.xlsx")
    assert t.rows[1] == ["772123456"]


def test_sheet_choice_and_listing():
    data = xlsx_bytes({"Cover": [["hello"]], "Voters": [["Reg No", "Name"], ["a", "b"]]})
    t = ti.read_table(data, "x.xlsx")
    assert t.sheets == ["Cover", "Voters"] and t.sheet == "Cover"
    assert ti.read_table(data, "x.xlsx", "Voters").rows[0] == ["Reg No", "Name"]
    assert ti.read_table(data, "x.xlsx", "nope").sheet == "Cover"          # unknown sheet falls back


def test_bad_inputs_have_clear_errors():
    for content, name, frag in [(b"", "a.csv", "empty"), (b"not a zip", "a.xlsx", "valid .xlsx"),
                                (b"x", "a.xls", "Save As")]:
        with pytest.raises(ti.TableError, match=frag):
            ti.read_table(content, name)


# ── guessing ────────────────────────────────────────────────────────────────

def test_header_row_skips_title_rows():
    rows = [["Kyambogo Guild Roll 2026"], [], ["No.", "Reg No", "Student Name", "Contact"], ["1", "a", "b", "c"]]
    assert ti.guess_header_row(rows, FIELDS) == 3


def test_suggest_mapping_variants():
    m = ti.suggest_mapping(["S/N", "Registration Number", "Surname", "Other Names", "Phone 1", "Phone 2", "Sex"], FIELDS)
    assert m == {"student_id": [1], "full_name": [2, 3], "phone": [4, 5], "gender": [6]}
    # a disabled field is never suggested, and bare "ID" only wins when nothing better exists
    assert "programme" not in ti.suggest_mapping(["Reg No", "Name", "Programme"], FIELDS)
    assert ti.suggest_mapping(["ID", "Reg No", "Name"], FIELDS)["student_id"] == [1]


def test_validate_mapping_rules():
    ok = ti.validate_mapping({"student_id": ["0"], "full_name": [1, "2"], "phone": "3"}, {"gender"})
    assert ok == {"student_id": [0], "full_name": [1, 2], "phone": [3]}
    for bad, frag in [({"student_id": [0]}, "Full name"),
                      ({"student_id": [0], "full_name": [0]}, "can't feed both"),
                      ({"student_id": [0, 1], "full_name": [2]}, "one column"),
                      ({"student_id": [0], "full_name": [1], "hostel": [2]}, "not a field"),
                      ({"student_id": [0], "full_name": [999]}, "outside"),
                      ({"student_id": ["a"], "full_name": [1]}, "not valid"),
                      ([], "not valid")]:
        with pytest.raises(ti.TableError, match=frag):
            ti.validate_mapping(bad, {"gender"})


# ── endpoints ───────────────────────────────────────────────────────────────

async def inspect(e, content, name="v.xlsx", **form):
    return await e.client.post("/admin/import-voters/inspect", headers=e.it, files={"file": (name, content)}, data=form)


async def preview(e, content, name="v.xlsx", **form):
    return await e.client.post("/admin/import-voters/preview", headers=e.it, files={"file": (name, content)}, data=form)


MESSY = xlsx_bytes({"Roll": [
    ["Kyambogo Guild Roll"], [],
    ["No.", "Student Reg", "First", "Surname", "Tel 1", "Tel 2"],
    [1, sid(1), "Ayebale", "Elizabeth", 772123456, "0701234567, 0752000111"],
    [2, sid(2), "Zoe", "Nakato", "0782000222", None],
]})


async def test_inspect_then_mapped_preview(env):
    r = await inspect(env, MESSY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["header_row"] == 3 and body["sheet"] == "Roll" and body["data_rows"] == 2
    assert [t["key"] for t in body["targets"]] == ["student_id", "full_name", "phone"]
    assert body["raw_preview"][2]["cells"][:2] == ["No.", "Student Reg"]

    # The admin corrects the guess: Student Reg -> id, First + Surname -> name, both tel columns -> phone.
    mapping = {"student_id": [1], "full_name": [2, 3], "phone": [4, 5]}
    p = await preview(env, MESSY, mapping=json.dumps(mapping), sheet="Roll", header_row="3")
    assert p.status_code == 200, p.text
    j = p.json()
    assert j["summary"]["new"] == 2 and j["summary"]["file_rows"] == 2
    first = next(n for n in j["new"] if n["full_name"].lower().startswith("ayebale"))
    assert first["full_name"].lower() == "ayebale elizabeth" and len(first["phones"]) == 3   # 772123456 + two in one cell


async def test_preview_without_mapping_still_guesses(env):
    clean = xlsx_bytes({"S": [["Reg No", "Student Name", "Phone"], [sid(1), "Ayebale Elizabeth", "0772123456"]]})
    p = await preview(env, clean)
    assert p.status_code == 200 and p.json()["summary"]["new"] == 1
    # "Student Reg" is not a header the guesser knows: without a mapping it refuses instead of guessing wrong.
    assert (await preview(env, MESSY)).status_code == 400


async def test_wrong_header_row_and_bad_mapping_are_400(env):
    assert (await inspect(env, MESSY, header_row="99")).status_code == 400
    bad = json.dumps({"student_id": [0]})
    assert (await preview(env, MESSY, mapping=bad, header_row="3")).status_code == 400
    assert (await preview(env, MESSY, mapping="{nope", header_row="3")).status_code == 400
    empty = json.dumps({"student_id": [1], "full_name": [10]})       # a name column with nothing in it
    assert (await preview(env, MESSY, mapping=empty, header_row="3")).status_code == 400


async def test_inspect_needs_it_admin_or_superadmin(env):
    r = await env.client.post("/admin/import-voters/inspect", headers=env.com1, files={"file": ("v.csv", b"a,b\n1,2\n")})
    assert r.status_code == 403
    assert (await env.client.post("/admin/import-voters/inspect", files={"file": ("v.csv", b"a,b\n1,2\n")})).status_code in (401, 403)


async def test_inspect_blocked_when_roster_frozen(env):
    await env.freeze()
    r = await inspect(env, MESSY)
    assert r.status_code == 409
