"""Tests of the outputs to the documents platform as external effects (package NOTION-OUT): a new page, a new table, rows added to a table
(runtime/step_output.py, runtime/output_document.py, runtime/table_data.py, runtime/effect_write.py, runtime/ops_step_effects.py). The
platform is the Notion provider against its stand-in service (providers/documents/tests/fake_notion.py): no workspace is ever called.
The cases of the package's "Done when": a page made from an approved document; a table made with inferred columns and filled from a CSV
and from an XLSX; rows added after a schema check; a changed cell, column, type, parent, title or operation is another hash and the
earlier approval covers nothing of it; a lost answer and a failure after some rows re-run without a duplicate row; a table changed
since it was read stops and asks; an approval from messaging, the tool server or a conversation is refused; the caps refuse with a
closed reason. Fictional names throughout.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_outputs.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import zipfile
from datetime import date
from pathlib import Path

import pytest

import standin_tree as st
from test_documents_mirror import Platform

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
docs = st.load("documents")
effects = st.load("effects")
effect_write = st.load("effect_write")
ops_step_effects = st.load("ops_step_effects")
output_document = st.load("output_document")
table_data = st.load("table_data")
step_output = st.load("step_output")
steps = st.load("steps")

STORE = "0123456789ab"
PAGE_MD = "# Weekly report\n\nSales were up in week 44.\n\n- stalls: forty\n- music: yes\n"
PAGE_PATH = "docs/outputs/weekly-report.md"
CSV = ("Stall,Notes,Fee,Opens,Paid,Site,Zip\n"
       "Bread,Fresh at six,12.5,2026-11-01,true,https://bread.example/shop,01234\n"
       "Candles,,8,2026-11-02T09:30:00+02:00,false,,02345\n"
       "Tea,\"Loose leaf, green\",,,true,https://tea.example,\n")
CSV_PATH = "docs/outputs/stalls.csv"
XLSX_PATH = "docs/outputs/stalls.xlsx"
TITLE = "Market stalls, week 44"
MORE = "Stall,Notes,Fee,Opens,Paid,Site,Zip\nHoney,Local,9,2026-11-03,false,,03456\nJam,,6.5,2026-11-04,true,https://jam.example,\n"
MORE_PATH = "docs/outputs/more-stalls.csv"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def make_xlsx(rows, date1904=False, second_sheet=True) -> bytes:
    """A small workbook: shared strings for text, numbers as numbers, ("date", "YYYY-MM-DD") with a date format, True/False as booleans,
    None as no cell. A second sheet is there to show that only the first is read."""
    strings, body = [], []
    base = date(1904, 1, 1) if date1904 else date(1899, 12, 30)
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if value is None:
                continue
            if isinstance(value, bool):
                cells.append(f'<c r="{ref}" t="b"><v>{int(value)}</v></c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif isinstance(value, tuple):
                serial = (date.fromisoformat(value[1]) - base).days
                cells.append(f'<c r="{ref}" s="1"><v>{serial}</v></c>')
            else:
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    pr = ' date1904="1"' if date1904 else ""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    parts = {
        "xl/workbook.xml": f'<workbook xmlns="{ns}" xmlns:r="{rel}"><workbookPr{pr}/><sheets>'
                           f'<sheet name="Stalls" sheetId="1" r:id="rId1"/><sheet name="Other" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                      f'<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                      f'<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>',
        "xl/sharedStrings.xml": f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
        "xl/styles.xml": f'<styleSheet xmlns="{ns}"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>',
    }
    if second_sheet:
        parts["xl/worksheets/sheet2.xml"] = f'<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="A1"><v>99</v></c></row></sheetData></worksheet>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return out.getvalue()


XLSX_ROWS = [["Stall", "Notes", "Fee", "Opens", "Paid", "Site", "Zip"],
             ["Bread", "Fresh at six", 12.5, ("date", "2026-11-01"), True, "https://bread.example/shop", "01234"],
             ["Candles", None, 8, ("date", "2026-11-02"), False, None, "02345"],
             ["Tea", "Loose leaf, green", None, None, True, "https://tea.example"]]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    folder = built["tree"] / "providers" / "documents"
    folder.mkdir(parents=True)
    for name in ("notion.py", "notion_blocks.py", "notion_tables.py"):
        shutil.copyfile(st.REPO / "providers" / "documents" / name, folder / name)
    platform = Platform(tmp_path)
    config = json.loads(platform.config.read_text(encoding="utf-8"))
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["documents"] = config
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    calls, lost = [], set()

    def call(cfg, root, verb, args, timeout=docs.TIMEOUT):
        calls.append((verb, [a for a in args if a not in ("--confirmed", "--dry-run")], "--confirmed" in args, "--dry-run" in args))
        done = platform.mirror_call(cfg, root, verb, args, timeout)
        if verb in lost and "--confirmed" in args:       # the provider did the work and its answer is lost
            lost.discard(verb)
            raise docs.DocumentsError("failed", "the provider ran over 900 s")
        return done

    monkeypatch.setattr(docs, "call", call)
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    out = built["project"] / "docs" / "outputs"
    out.mkdir(parents=True)
    (out / "weekly-report.md").write_text(PAGE_MD, encoding="utf-8")
    (out / "stalls.csv").write_text(CSV, encoding="utf-8")
    (out / "more-stalls.csv").write_text(MORE, encoding="utf-8")
    (out / "stalls.xlsx").write_bytes(make_xlsx(XLSX_ROWS))
    parent = platform.fake.create_root()
    return {**built, "path": project, "platform": platform, "fake": platform.fake, "calls": calls, "lost": lost, "parent": parent,
            "tmp": tmp_path, "root": Path(project)}


def writes(world):
    """The calls that write to the platform: a confirmed page-create, table-create or rows-append."""
    return [c for c in world["calls"] if c[0] in ("page-create", "table-create", "rows-append") and c[2]]


def add(world, kind, **args):
    ctx = ops_core.context(world["path"])
    made = steps.add_task(ctx["store"], ctx["conn"], kind, args, key=kind, title="Output", text="Make it.")
    return made["task"]


def page_task(world, **extra):
    return add(world, "output-page", **{"parent": world["parent"], "title": "Weekly report", "content": PAGE_PATH, **extra})


def table_task(world, **extra):
    args = {"parent": world["parent"], "title": TITLE, "rows": CSV_PATH, **extra}
    return add(world, "output-table", **{k: v for k, v in args.items() if v is not None})


def run_task(world, task):
    ctx = ops_core.context(world["path"])
    if ctx["store"].task_get(ctx["conn"], task)["state"] == "failed":
        ctx["store"].task_retry(ctx["conn"], task)
    return ops_steps.run_step(world["path"], task)


def pending_of(world, task):
    ctx = ops_core.context(world["path"])
    rows = [p for p in ctx["store"].pending_list(ctx["conn"], "open", task)]
    assert len(rows) == 1, rows
    return rows[0]


def task_state(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["state"]


def opened(world, task):
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting", out
    return pending_of(world, task)


def approve(world, item, channel="terminal"):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)


def effect_doc(world, task, cycle=0):
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, cycle)) / "effect.json"
    return path, json.loads(path.read_text(encoding="ascii"))


def made_table(world):
    """The data source the last create_table approval made, and its rows as plain values."""
    fake = world["fake"]
    source = [b for b in fake.bases if fake.bases[b].get("database_id")][-1]
    return source, [fake.cells(r) for r in fake.rows_of(source)]


def existing_table(world, rows=()):
    """A table a person made, with the columns of the CSV (so that rows can be added to it), and some rows."""
    fake = world["fake"]
    props = {"Stall": {"type": "title", "title": {}}, "Notes": {"type": "rich_text", "rich_text": {}},
             "Fee": {"type": "number", "number": {"format": "number"}}, "Opens": {"type": "date", "date": {}},
             "Paid": {"type": "checkbox", "checkbox": {}}, "Site": {"type": "url", "url": {}},
             "Zip": {"type": "rich_text", "rich_text": {}}}
    database = fake.create_database({"parent": {"type": "page_id", "page_id": world["parent"]}, "title": [], "initial_data_source": {"properties": props}})
    source = database["data_sources"][0]["id"]
    for name in rows:
        page = fake.create_page({"type": "data_source_id", "data_source_id": source}, {})
        fake.person_sets(page["id"], "Stall", name)
    return source


# --- a page ---------------------------------------------------------------------------------------------------------------------------


def test_a_page_is_previewed_with_its_parent_title_and_content_whole_and_nothing_is_written(world):
    item = opened(world, page_task(world))
    assert item["kind"] == "effect" and len(item["payload_sha256"]) == 64 and writes(world) == []
    body = item["body"]
    for needle in (world["parent"], "Weekly report", PAGE_PATH, PAGE_MD.rstrip("\n"), item["payload_sha256"], "--sha256", "makes a new page"):
        assert needle in body, needle
    assert item["payload"]["step"] == {"kind": "output-page", "step": "approval"} and item["title"] == "Create page: Weekly report"
    assert item["payload"]["effect"]["operation"] == "create_page" and "Weekly" not in json.dumps(item["payload"]), "the state keeps closed facts"


def test_a_page_is_made_under_the_parent_after_the_approval_and_the_effect_is_recorded(world):
    task = page_task(world)
    item = opened(world, task)
    path, doc = effect_doc(world, task)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["payload_sha256"]
    assert doc["operation"] == "create_page" and doc["target"] == {"id": world["parent"], "path": PAGE_PATH} and doc["title"] == "Weekly report"
    assert doc["idempotency_key"].startswith("o-") and doc["notes"] == [] and oct(path.stat().st_mode & 0o777) == "0o600"
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["written"] is True and done["result"]["operation"] == "create_page"
    assert done["result"]["replayed"] is False and done["result"]["content_sha256"] == sha(PAGE_MD)
    fake = world["fake"]
    page = fake.pages[done["result"]["id"]]
    assert page["parent"] == {"type": "page_id", "page_id": world["parent"]} and page["properties"]["title"]["title"][0]["plain_text"] == "Weekly report"
    assert world["platform"].text(done["result"]["id"]) == world["platform"].blocks.round_trip(PAGE_MD)
    ctx = ops_core.context(world["path"])
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    assert row["status"] == "executed" and row["payload_sha256"] == item["payload_sha256"]
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    assert len(writes(world)) == 1


def test_a_page_whose_answer_was_lost_is_found_and_recorded_as_replayed_without_a_second_page(world):
    task = page_task(world)
    item = opened(world, task)
    world["lost"].add("page-create")
    with pytest.raises(ops_core.OpsError) as lost:
        approve(world, item)
    assert "outcome is unknown" in str(lost.value) and "stays open" in str(lost.value) and task_state(world, task) == "waiting"
    under = lambda: [p for p in world["fake"].pages.values() if p["parent"].get("page_id") == world["parent"]]
    assert len(under()) == 1
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and len(under()) == 1


def test_a_parent_that_is_gone_stops_the_preview_and_the_write(world):
    task = page_task(world, parent="f" * 32)
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "provider_failed" and writes(world) == []
    task = page_task(world)
    item = opened(world, task)
    world["fake"].pages[world["parent"]]["in_trash"] = True
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "nothing" in str(refused.value).lower() and writes(world) == [] and task_state(world, task) == "waiting"


# --- the hash covers the operation, the parent, the title and every cell -------------------------------------------------------------------


def doc_of(operation="create_table", **change):
    columns = [{"name": "Stall", "type": "title"}, {"name": "Fee", "type": "number"}, {"name": "Paid", "type": "checkbox"}]
    base = None if operation != "append_rows" else {"schema_sha256": "a" * 64, "row_count": 2, "version": None, "rows_done": 0}
    fields = dict(store=STORE, operation=operation, task_id=1, provider="notion", target_id="a" * 32, path="docs/outputs/stalls.csv",
                  title="Stalls" if operation != "append_rows" else None,
                  content={"columns": columns, "rows": [["Bread", 12.5, True], ["Tea", None, False]]}, base=base,
                  notes=["given: the title", "inferred: every filled cell is a plain number", "inferred: every cell is true or false"])
    fields.update(change)
    return output_document.document(**fields)


def digest(doc):
    return sha(effects._text(doc))


def test_a_changed_parent_title_column_type_cell_or_operation_is_another_hash_and_the_old_approval_covers_nothing(world):
    original = doc_of()
    columns = original["content"]["columns"]
    changes = {
        "parent": doc_of(target_id="b" * 32),
        "title": doc_of(title="Stalls, week 45"),
        "a cell": doc_of(content={"columns": columns, "rows": [["Bread", 12.5, True], ["Tea", 3, False]]}),
        "a cell, one character": doc_of(content={"columns": columns, "rows": [["Bread", 12.5, True], ["Tee", None, False]]}),
        "a column name": doc_of(content={"columns": [dict(columns[0], name="Name")] + columns[1:], "rows": original["content"]["rows"]}),
        "a column type": doc_of(content={"columns": columns[:1] + [dict(columns[1], type="rich_text")] + columns[2:],
                                         "rows": [["Bread", "12.5", True], ["Tea", None, False]]}),
        "a row removed": doc_of(content={"columns": columns, "rows": original["content"]["rows"][:1]}),
        "the task": doc_of(task_id=2),
        "the source file": doc_of(path="docs/outputs/other.csv"),
        "a note": doc_of(notes=["given: the title", "inferred: every filled cell is a plain number", "given"]),
    }
    seen = {digest(original)}
    for what, other in changes.items():
        assert digest(other) not in seen, what
        seen.add(digest(other))
        approval = {"scope": "action", "status": "pending-execution", "payload_sha256": digest(original)}
        with pytest.raises(effects.EffectError) as refused:
            effect_write.execute(other, approval, lambda verb, args: pytest.fail("the platform was called"), "k")
        assert refused.value.kind == "deviation" and "no approval of this exact content" in refused.value.reason, what
    rows = doc_of("append_rows")
    assert digest(rows) not in seen and rows["idempotency_key"] != original["idempotency_key"]
    assert digest(doc_of("append_rows", base={"schema_sha256": "a" * 64, "row_count": 3, "version": None, "rows_done": 0})) != digest(rows), "the base is covered"
    assert digest(doc_of("append_rows", base={"schema_sha256": "c" * 64, "row_count": 2, "version": None, "rows_done": 0})) != digest(rows)
    assert doc_of()["idempotency_key"] == original["idempotency_key"], "the same document carries the same key"


def test_the_effect_file_edited_after_the_preview_is_not_the_approved_one_and_nothing_is_written(world):
    task = table_task(world)
    item = opened(world, task)
    path, doc = effect_doc(world, task)
    doc["content"]["rows"][0][0] = "Bread and butter"
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="ascii")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "not the one approved" in str(refused.value) and writes(world) == [] and task_state(world, task) == "waiting"


def test_a_document_out_of_its_form_is_refused_by_its_own_check():
    base = doc_of()
    for broken in (dict(base, operation="update_page"), dict(base, extra=1), dict(base, title=None), dict(base, idempotency_key="o-x"),
                   dict(base, notes=["only one"]), dict(base, base={"schema_sha256": "a" * 64, "row_count": 1, "version": None}),
                   dict(base, bytes=1), dict(base, target={"id": "short", "path": "docs/a.csv"}),
                   dict(base, target={"id": "a" * 32, "path": "docs/a.md"})):
        with pytest.raises(effects.EffectError):
            output_document.check(broken)
    with pytest.raises(effects.EffectError):
        doc_of(content={"columns": [{"name": "A", "type": "title"}], "rows": []})
    with pytest.raises(effects.EffectError):
        doc_of("append_rows", base=None)


# --- the approval: only from the terminal or the page, only of the hash -------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["page", "table", "rows"])
def test_limit_31_an_output_is_not_approved_from_messaging_the_tool_server_or_a_conversation(world, kind):
    if kind == "page":
        task = page_task(world)
    elif kind == "table":
        task = table_task(world)
    else:
        task = add(world, "output-table", table=existing_table(world, ["Pie"]), rows=MORE_PATH)
    item = opened(world, task)
    for channel in ("messaging", "mcp", "conversation", None):
        with pytest.raises(ops_core.OpsError) as refused:
            ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
        assert "approved in the terminal" in str(refused.value)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(refused.value)
    with pytest.raises(ops_core.OpsError):
        ops.approve(world["path"], item["id"], sha256=None, channel="terminal")
    with pytest.raises(ops_core.OpsError):
        ops.answer(world["path"], item["id"], "approve")
    assert writes(world) == [] and task_state(world, task) == "waiting"


def test_limit_31_an_output_without_the_approval_of_its_exact_content_is_refused_by_structure(world):
    doc = doc_of()
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": digest(doc)},
                     {"scope": "action", "status": "revoked", "payload_sha256": digest(doc)},
                     {"scope": "action", "status": "executed", "payload_sha256": digest(doc)},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64}):
        for operation in ("create_table", "create_page", "append_rows"):
            other = doc_of(operation) if operation != "create_page" else output_document.document(
                store=STORE, operation="create_page", task_id=1, provider="notion", target_id="a" * 32, path="docs/a.md", title="T", content="Text\n")
            with pytest.raises(effects.EffectError):
                effect_write.execute(other, approval, lambda verb, args: pytest.fail("the platform was called"), "k")


def test_a_standing_approval_cannot_name_the_write_effect_for_an_output_either():
    assert "write" not in effects.policy_kinds() and effect_write.POLICY is False and effect_write.STEP is True


# --- a table made from a CSV file and from a workbook ----------------------------------------------------------------------------------


EXPECTED_COLUMNS = [("Stall", "title"), ("Notes", "rich_text"), ("Fee", "number"), ("Opens", "date"), ("Paid", "checkbox"), ("Site", "url"),
                    ("Zip", "rich_text")]
EXPECTED_ROWS = [
    {"Stall": "Bread", "Notes": "Fresh at six", "Fee": 12.5, "Opens": "2026-11-01", "Paid": True, "Site": "https://bread.example/shop", "Zip": "01234"},
    {"Stall": "Candles", "Notes": "", "Fee": 8, "Opens": "2026-11-02T09:30:00.000+02:00", "Paid": False, "Site": None, "Zip": "02345"},
    {"Stall": "Tea", "Notes": "Loose leaf, green", "Fee": None, "Opens": None, "Paid": True, "Site": "https://tea.example", "Zip": ""}]


def test_a_table_is_previewed_with_its_columns_types_and_how_each_was_settled_the_row_count_and_the_first_rows(world):
    item = opened(world, table_task(world))
    body = item["body"]
    assert writes(world) == [] and "creates" not in body and "create a new table" in body.replace("Code makes a new table", "create a new table")
    for needle in (world["parent"], TITLE, CSV_PATH, "3 in all", "| Fee | number | inferred: every filled cell is a plain number |",
                   "| Stall | title | inferred: the first column is the title |", "| Zip | rich_text | text: no other type fits |",
                   "| Paid | checkbox |", "| Bread | Fresh at six | 12.5 | 2026-11-01 | true |", item["payload_sha256"]):
        assert needle in body, needle
    assert item["payload"]["effect"]["rows"] == 3 and item["payload"]["effect"]["columns"] == 7 and TITLE not in json.dumps(item["payload"])


def test_a_table_is_made_with_inferred_columns_and_filled_from_a_csv_file_after_the_approval(world):
    task = table_task(world)
    item = opened(world, task)
    path, doc = effect_doc(world, task)
    assert [(c["name"], c["type"]) for c in doc["content"]["columns"]] == EXPECTED_COLUMNS
    assert doc["operation"] == "create_table" and doc["base"] == {"schema_sha256": None, "row_count": None, "version": None, "rows_done": None}
    done = approve(world, item, "page")
    assert done["task_state"] == "done" and done["result"]["rows"] == 3 and done["result"]["rows_created"] == 3 and done["result"]["replayed"] is False
    source, rows = made_table(world)
    assert source == done["result"]["data_source_id"] and rows == EXPECTED_ROWS
    schema = {n: p["type"] for n, p in world["fake"].bases[source]["properties"].items()}
    assert schema == dict(EXPECTED_COLUMNS)
    assert len(writes(world)) == 1 and writes(world)[0][0] == "table-create"


def test_a_table_is_made_from_the_first_sheet_of_a_workbook_with_the_same_rule(world):
    task = table_task(world, rows=XLSX_PATH)
    item = opened(world, task)
    path, doc = effect_doc(world, task)
    assert [(c["name"], c["type"]) for c in doc["content"]["columns"]] == EXPECTED_COLUMNS[:6] + [("Zip", "rich_text")]
    done = approve(world, item)
    source, rows = made_table(world)
    assert [r["Stall"] for r in rows] == ["Bread", "Candles", "Tea"] and rows[0]["Fee"] == 12.5 and rows[0]["Opens"] == "2026-11-01"
    assert rows[1]["Opens"] == "2026-11-02" and rows[2]["Paid"] is True and rows[0]["Zip"] == "01234"
    assert done["result"]["rows_created"] == 3


def test_columns_given_in_the_arguments_win_over_the_rule_and_the_preview_says_so(world):
    task = table_task(world, columns={"Zip": "number", "Notes": "select", "Stall": "title"})
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "cell_not_type", "01234 is not a number"
    (world["root"] / CSV_PATH).write_text(CSV.replace("01234", "1234").replace("02345", "2345").replace("Fresh at six", "food")
                                          .replace("Loose leaf, green", "drink"), encoding="utf-8")
    task = table_task(world, columns={"Zip": "number", "Notes": "select", "Stall": "title"})
    item = opened(world, task)
    _, doc = effect_doc(world, task)
    types = {c["name"]: c["type"] for c in doc["content"]["columns"]}
    assert types["Zip"] == "number" and types["Notes"] == "select" and "| Zip | number | given |" in item["body"]
    approve(world, item)
    source, rows = made_table(world)
    assert world["fake"].bases[source]["properties"]["Notes"]["type"] == "select" and rows[0]["Zip"] == 1234 and rows[0]["Notes"] == "food"


def test_a_checkbox_column_with_a_gap_is_text_unless_it_is_named_and_then_the_gap_is_unchecked_and_said(world):
    (world["root"] / CSV_PATH).write_text("Stall,Open\nBread,true\nTea,\n", encoding="utf-8")
    item = opened(world, table_task(world))
    assert "| Open | rich_text | text, ambiguous: true and false with empty cells (name the type to make a checkbox) |" in item["body"]
    task = table_task(world, columns={"Open": "checkbox"})
    item = opened(world, task)
    assert "| Open | checkbox | given; an empty cell is unchecked |" in item["body"]
    _, doc = effect_doc(world, task)
    assert doc["content"]["rows"] == [["Bread", True], ["Tea", False]]


def test_a_long_table_shows_its_first_rows_and_the_last_three_and_says_the_hash_covers_all(world):
    rows = "".join(f"Stall {n},{n}\n" for n in range(1, 61))
    (world["root"] / CSV_PATH).write_text("Stall,Fee\n" + rows, encoding="utf-8")
    item = opened(world, table_task(world))
    body = item["body"]
    assert "60 in all; the first 20, then the last 3" in body and "| Stall 20 | 20 |" in body and "| Stall 21 | 21 |" not in body
    assert "| Stall 60 | 60 |" in body and "| ... |" in body and len(body.encode("utf-8")) < 20000
    assert item["payload"]["effect"]["rows"] == 60


# --- rows added to an existing table -------------------------------------------------------------------------------------------------------


def test_rows_are_added_to_an_existing_table_after_the_schema_check_and_the_columns_that_must_match_are_shown(world):
    source = existing_table(world, ["Pie", "Soup"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    _, doc = effect_doc(world, task)
    assert doc["operation"] == "append_rows" and doc["title"] is None and doc["target"]["id"] == source
    assert doc["base"]["row_count"] == 2 and len(doc["base"]["schema_sha256"]) == 64
    assert [n for n in doc["notes"]] == ["the table's"] * 7
    body = item["body"]
    assert "Code adds these rows to a table of your platform" in body and "When it was read the table had 2 rows" in body
    assert "| Fee | number | the table's |" in body and "The columns of the rows must be columns of the table" in body
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["rows_created"] == 2 and done["result"]["operation"] == "append_rows"
    rows = [world["fake"].cells(r) for r in world["fake"].rows_of(source)]
    assert [r["Stall"] for r in rows] == ["Pie", "Soup", "Honey", "Jam"] and rows[3]["Fee"] == 6.5 and rows[2]["Paid"] is False


def test_rows_whose_columns_are_not_the_tables_are_refused_when_the_task_reads_with_a_closed_reason(world):
    source = existing_table(world)
    (world["root"] / MORE_PATH).write_text("Stall,Colour\nHoney,gold\n", encoding="utf-8")
    out = run_task(world, add(world, "output-table", table=source, rows=MORE_PATH))
    assert out["ok"] is False and out["code"] == "column_not_in_table"
    (world["root"] / MORE_PATH).write_text("Fee,Notes\n9,x\n", encoding="utf-8")
    assert run_task(world, add(world, "output-table", table=source, rows=MORE_PATH))["code"] == "title_missing"
    (world["root"] / MORE_PATH).write_text("Stall,Fee\nHoney,nine\n", encoding="utf-8")
    assert run_task(world, add(world, "output-table", table=source, rows=MORE_PATH))["code"] == "cell_not_type"
    assert run_task(world, add(world, "output-table", table=source, rows=MORE_PATH, columns={"Fee": "rich_text"}))["code"] == "column_type_differs"
    assert writes(world) == []


# --- a table changed since it was read ------------------------------------------------------------------------------------------------------------


def stopped_by(world, item, task):
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "not the one the task read" in str(stopped.value) and "starts over" in str(stopped.value)
    assert writes(world) == [] and task_state(world, task) == "ready"
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["resolution"] == "answered"
    return str(stopped.value)


def test_a_schema_changed_since_it_was_read_stops_the_write_and_asks_again_about_the_table_as_it_is(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    world["fake"].person_adds_property(source, "Extra")
    assert "columns changed" in stopped_by(world, item, task)
    new = opened(world, task)
    assert new["id"] != item["id"] and new["payload_sha256"] != item["payload_sha256"] and new["payload"]["cycle"] == 1
    assert approve(world, new)["task_state"] == "done"
    assert len(world["fake"].rows_of(source)) == 3
    with pytest.raises(ops_core.OpsError):
        approve(world, item)


@pytest.mark.parametrize("change", ["edit", "add", "remove"])
def test_rows_changed_since_the_table_was_read_stop_the_write_and_ask_again(world, change):
    source = existing_table(world, ["Pie", "Soup"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    fake = world["fake"]
    rows = fake.rows_of(source)
    if change == "edit":
        fake.person_sets(rows[0]["id"], "Notes", "Edited by a person")
    elif change == "add":
        fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", "Cake")
    else:
        fake.person_trashes(rows[1]["id"])
    assert "rows changed" in stopped_by(world, item, task)
    assert len(fake.rows_of(source)) == (3 if change == "add" else 1 if change == "remove" else 2)


def test_a_page_parent_edited_meanwhile_does_not_stop_a_new_page_but_a_gone_parent_does(world):
    task = page_task(world)
    item = opened(world, task)
    world["fake"].person_replaces_body(world["parent"], world["platform"].blocks.to_blocks("A person edited the parent.\n"))
    assert approve(world, item)["task_state"] == "done"


# --- a lost answer and a failure after some rows ---------------------------------------------------------------------------------------------------


def test_a_table_whose_answer_was_lost_is_recorded_as_replayed_and_has_each_row_once(world):
    task = table_task(world)
    item = opened(world, task)
    world["lost"].add("table-create")
    with pytest.raises(ops_core.OpsError) as lost:
        approve(world, item)
    assert "outcome is unknown" in str(lost.value) and task_state(world, task) == "waiting"
    source, rows = made_table(world)
    assert len(rows) == 3
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and done["result"]["rows_created"] == 0
    assert done["result"]["rows_replayed"] == 3 and made_table(world)[1] == EXPECTED_ROWS
    assert len([d for d in world["fake"].databases.values() if d["parent"].get("page_id") == world["parent"]]) == 1


def test_a_failure_after_some_rows_leaves_the_decision_open_and_the_next_approval_writes_only_the_missing_rows(world):
    task = table_task(world)
    item = opened(world, task)
    world["fake"].fail_at("create_page", 3, 500)           # the third row's call fails, as a 5xx does
    with pytest.raises(ops_core.OpsError) as unknown:
        approve(world, item)
    assert "outcome is unknown" in str(unknown.value) and "row 3" in str(unknown.value) and task_state(world, task) == "waiting"
    source, rows = made_table(world)
    assert [r["Stall"] for r in rows] == ["Bread", "Candles"]
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["rows_created"] == 1 and done["result"]["rows_replayed"] == 2
    assert done["result"]["replayed"] is False
    assert made_table(world)[1] == EXPECTED_ROWS, "three rows, none twice"
    assert len([c for c in writes(world) if c[0] == "table-create"]) == 2


def test_rows_added_whose_answer_was_lost_are_not_added_twice_on_the_next_approval(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    world["lost"].add("rows-append")
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    assert len(world["fake"].rows_of(source)) == 3
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and done["result"]["rows_replayed"] == 2
    assert [r["Stall"] for r in (world["fake"].cells(p) for p in world["fake"].rows_of(source))] == ["Pie", "Honey", "Jam"]
    assert len([c for c in world["calls"] if c[0] == "rows-append" and c[2]]) == 1, "the second approval found every row done and called nothing"


def test_rows_added_after_a_failure_midway_complete_even_though_the_row_count_has_moved(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    world["fake"].fail_at("create_page", 2, 500)
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    assert len(world["fake"].rows_of(source)) == 2          # Pie and Honey
    done = approve(world, item)                              # the table has changed by this document's own rows: not stale
    assert done["task_state"] == "done" and done["result"]["rows_created"] == 1 and len(world["fake"].rows_of(source)) == 3


def test_a_table_that_changes_by_another_hand_after_a_failure_still_gets_only_its_missing_rows_when_the_columns_are_unchanged(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    world["fake"].fail_at("create_page", 2, 500)
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    world["fake"].person_adds_property(source, "Extra")      # a column added meanwhile is another table
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "columns changed" in str(stopped.value) and len(world["fake"].rows_of(source)) == 2


@pytest.mark.parametrize("change, rows_after", [("trash", 1), ("two added", 4)])
def test_rows_removed_or_added_by_a_person_after_a_failure_midway_stop_the_next_approval(world, change, rows_after):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    fake = world["fake"]
    fake.fail_at("create_page", 2, 500)               # Honey is written, Jam's outcome is unknown
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    if change == "trash":
        fake.person_trashes(fake.rows_of(source)[0]["id"])
    else:
        for name in ("Cake", "Bun"):
            fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", name)
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "rows changed" in str(stopped.value) and len(fake.rows_of(source)) == rows_after


# --- the caps, the file and the arguments ----------------------------------------------------------------------------------------------------------------


def refused_with(world, text, code, **extra):
    (world["root"] / CSV_PATH).write_text(text, encoding="utf-8")
    out = run_task(world, table_task(world, **extra))
    assert out["ok"] is False and out["code"] == code, out
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open") == [] and writes(world) == []
    return out


def test_the_row_and_column_caps_refuse_with_a_closed_reason(world):
    refused_with(world, "Stall,Fee\n" + "".join(f"s{n},{n}\n" for n in range(501)), "too_many_rows")
    refused_with(world, ",".join(f"c{n}" for n in range(31)) + "\n" + ",".join("x" for _ in range(31)) + "\n", "too_many_columns")
    refused_with(world, "Stall,Fee\n" + "x" * 2001 + ",1\n", "cell_too_long")
    refused_with(world, "Stall,Fee\n", "table_empty")
    refused_with(world, "", "table_empty")
    refused_with(world, "Stall,Stall\na,b\n", "columns_bad")
    refused_with(world, "Stall,\na,b\n", "columns_bad")
    refused_with(world, "Stall,Fee\na\n", "table_ragged")
    refused_with(world, "Stall,Fee\na,1,extra\n", "table_ragged")
    refused_with(world, "Stall,Fee\n,1\n", "title_empty")


def test_exactly_500_rows_and_30_columns_are_taken(world):
    (world["root"] / CSV_PATH).write_text("Stall,Fee\n" + "".join(f"s{n},{n}\n" for n in range(500)), encoding="utf-8")
    item = opened(world, table_task(world))
    assert item["payload"]["effect"]["rows"] == 500
    (world["root"] / CSV_PATH).write_text(",".join(f"c{n}" for n in range(30)) + "\n" + ",".join("x" for _ in range(30)) + "\n", encoding="utf-8")
    assert opened(world, table_task(world))["payload"]["effect"]["columns"] == 30


def test_a_cell_that_does_not_fit_a_given_type_a_second_title_and_an_unknown_column_stop_the_step(world):
    refused_with(world, CSV, "title_count", columns={"Stall": "title", "Notes": "title"})
    refused_with(world, CSV, "column_unknown", columns={"Missing": "number"})
    refused_with(world, CSV, "cell_not_type", columns={"Notes": "number"})
    refused_with(world, "Stall,Kind\na,x\nb,y,z\n", "table_ragged")
    refused_with(world, "Stall,Kind\na,\"x,y\"\n", "cell_not_type", columns={"Kind": "select"})
    refused_with(world, "Stall,Kind\n" + "".join(f"a{n},opt{n}\n" for n in range(101)), "too_many_options", columns={"Kind": "select"})


def test_a_credential_in_a_cell_or_in_a_page_opens_no_effect(world):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    (world["root"] / CSV_PATH).write_text(f"Stall,Notes\nBread,{key}\n", encoding="utf-8")
    out = run_task(world, table_task(world))
    assert out["code"] == "content_refused" and key not in json.dumps(out)
    (world["root"] / PAGE_PATH).write_text(f"The key: {key}\n", encoding="utf-8")
    out = run_task(world, page_task(world))
    assert out["code"] == "content_refused" and key not in json.dumps(out) and writes(world) == []


def test_a_missing_file_a_link_a_binary_and_a_workbook_that_is_not_one_stop_the_step_with_a_closed_reason(world):
    root = world["root"]
    (root / CSV_PATH).unlink()
    assert run_task(world, table_task(world))["code"] == "rows_missing"
    (root / "docs" / "real.csv").write_text("Stall\na\n", encoding="utf-8")
    (root / CSV_PATH).symlink_to(root / "docs" / "real.csv")
    assert run_task(world, table_task(world))["code"] == "path_unsafe"
    (root / CSV_PATH).unlink()
    (root / CSV_PATH).write_bytes(b"\xff\xfe\x00 not text")
    assert run_task(world, table_task(world))["code"] == "table_not_text"
    (root / XLSX_PATH).write_bytes(b"this is not a workbook")
    assert run_task(world, table_task(world, rows=XLSX_PATH))["code"] == "xlsx_unreadable"
    (root / CSV_PATH).write_text("Stall\n" + "x" * (table_data.CSV_MAX + 1), encoding="utf-8")
    assert run_task(world, table_task(world))["code"] == "rows_too_large"
    (root / PAGE_PATH).write_text("x" * (effect_write.CONTENT_MAX + 1), encoding="utf-8")
    assert run_task(world, page_task(world))["code"] == "content_too_large"
    assert writes(world) == []


def test_the_arguments_are_checked_when_the_task_is_planned():
    good_page = {"parent": "a" * 32, "title": "T", "content": "docs/a.md"}
    good_new = {"parent": "a" * 32, "title": "T", "rows": "docs/a.csv"}
    good_add = {"table": "b" * 32, "rows": "docs/a.xlsx"}
    for kind, args in (("output-page", good_page), ("output-table", good_new), ("output-table", good_add),
                       ("output-table", dict(good_new, columns={"A": "number"}))):
        ok = steps.plan_task(kind, args, key="k", title="t", text="x")
        assert ok["footprint"] == [] and ok["step"] == kind
    bad = [("output-page", dict(good_page, extra=1)), ("output-page", {**good_page, "content": "docs/a.txt"}),
           ("output-page", {**good_page, "content": "other/a.md"}), ("output-page", {**good_page, "parent": "short"}),
           ("output-page", {**good_page, "parent": "https://www.notion.so/Plan-" + "a" * 32}), ("output-page", {**good_page, "title": ""}),
           ("output-page", {**good_page, "title": "a\nb"}), ("output-page", {**good_page, "title": "x" * 201}),
           ("output-page", {k: v for k, v in good_page.items() if k != "title"}),
           ("output-table", {**good_new, "table": "b" * 32}), ("output-table", {"rows": "docs/a.csv"}),
           ("output-table", {**good_add, "title": "T"}), ("output-table", {k: v for k, v in good_new.items() if k != "title"}),
           ("output-table", {**good_new, "rows": "docs/a.md"}), ("output-table", {**good_new, "rows": "docs/../a.csv"}),
           ("output-table", {**good_new, "columns": {"A": "money"}}), ("output-table", {**good_new, "columns": {}}),
           ("output-table", {**good_new, "columns": "A"}), ("output-table", {**good_new, "extra": 1}), ("output-table", {"parent": "a" * 32})]
    for kind, args in bad:
        with pytest.raises(steps.StepFailure) as refused:
            steps.plan_task(kind, args, key="k", title="t", text="x")
        assert refused.value.code == "bad_args", (kind, args)


def test_a_configuration_without_a_documents_platform_or_with_expired_bounds_opens_no_effect(world):
    task = table_task(world)
    path = world["root"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(raw, documents=dict(raw["documents"], expires="2020-01-01"))), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert run_task(world, task)["code"] == "bounds_expired"
    path.write_text(json.dumps({k: v for k, v in raw.items() if k != "documents"}), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert run_task(world, task)["code"] == "not_configured" and writes(world) == []


def test_bounds_that_expire_between_the_preview_and_the_approval_stop_the_write(world):
    item = opened(world, table_task(world))
    path = world["root"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(raw, documents=dict(raw["documents"], expires="2020-01-01"))), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "expired" in str(refused.value) and writes(world) == []


def test_a_provider_that_cannot_make_tables_fails_with_nothing_written_and_the_effect_stays_open(world, monkeypatch):
    task = table_task(world)
    item = opened(world, task)
    real = docs.call

    def no_tables(cfg, root, verb, args, timeout=docs.TIMEOUT):
        if verb in ("table-create", "page-create", "rows-append"):
            raise docs.DocumentsError("failed", f"unknown argument {verb!r}; see --help")
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", no_tables)
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "outcome is unknown" in str(refused.value) or "stays open" in str(refused.value)
    assert task_state(world, task) == "waiting" and made_tables(world) == 0


def made_tables(world):
    return len(world["fake"].databases)


def test_the_long_verbs_get_their_own_time_limit_and_the_short_ones_the_usual(world, monkeypatch):
    seen = {}
    real = docs.call

    def spy(cfg, root, verb, args, timeout=docs.TIMEOUT):
        seen.setdefault(verb, set()).add(timeout)
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", spy)
    approve(world, opened(world, table_task(world)))
    assert seen["table-create"] == {ops_step_effects.OUTPUT_TIMEOUT} and seen["stat"] == {docs.TIMEOUT}
    assert ops_step_effects.OUTPUT_TIMEOUT >= 500 * 0.35 * 2 and set(ops_step_effects.OUTPUT_VERBS) == {"page-create", "table-create", "rows-append", "table-read", "rows-state"}


# --- the effect kind and the module split --------------------------------------------------------------------------------------------------------------


def test_the_effect_word_stays_write_and_the_kinds_are_registered_without_an_effectful_step(world):
    assert effects.KINDS["write"] == "effect_write" and output_document.WORD == "write"
    for name in ("output-page", "output-table"):
        kind = steps.REGISTRY[name] if name in steps.REGISTRY else steps.kind_of(name)
        assert kind.effectful == () and kind.unattended is False and kind.order == ("prepare", "approval") and kind.footprint({}) == ()
        assert kind.gates["approval"].word == "write" and kind.gates["approval"].redo == "prepare"
    assert set(output_document.OPERATIONS) | {"update_page"} == {"create_page", "create_table", "append_rows", "update_page"}


def test_the_effect_module_dispatches_each_document_to_its_own_pure_half():
    page = output_document.document(store=STORE, operation="create_page", task_id=1, provider="notion", target_id="a" * 32, path="docs/a.md", title="T",
                                    content="Text\n")
    table = doc_of()
    update = effect_write.document(task_id=1, provider="notion", target_id="a" * 32, path="docs/a.md", content="Text\n",
                                   base_text_sha256="b" * 64, base_version=None)
    assert update["operation"] == "update_page"
    for doc in (page, table, update):
        assert effect_write.check(doc) is doc and effect_write.describe(doc) and effect_write.summary(doc)["target"] == doc["target"]["id"]
        assert effect_write.title(doc) and effect_write.body(doc, "d" * 64).count("d" * 64) >= 2
    assert effect_write.summary(table)["rows"] == 2 and "rows" not in effect_write.summary(page)
    with pytest.raises(effects.EffectError):
        effect_write.check(dict(update, operation="delete_page"))


def test_the_provider_side_caps_and_this_side_caps_are_the_same_numbers():
    spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location("notion_tables_for_runtime", st.REPO / "providers" / "documents" / "notion_tables.py")
    nt = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
    spec.loader.exec_module(nt)
    for name in ("ROWS_MAX", "COLUMNS_MAX", "CELL_MAX", "NAME_MAX", "SELECT_MAX", "OPTIONS_MAX", "TYPES"):
        assert getattr(table_data, name) == getattr(nt, name), name
    for text in ("2026-02-29", "2024-02-29", "2026-13-01", "2026-11-01T24:00", "2026-11-01T09:30:00Z", "2026-11-01T09:30+02:00", "01/11/2026",
                 "2026-11-01T09:30+25:00", "2026-1-1", "0000-01-01"):
        assert table_data.valid_date(text) == nt.valid_date(text), text
    for kind, value in (("number", 1.5), ("number", True), ("title", " "), ("checkbox", None), ("url", "ftp://x.example"), ("select", "a,b")):
        try:
            nt.check_value(kind, value, "x")
            theirs = True
        except nt.TableError:
            theirs = False
        try:
            table_data.check_table({"columns": [{"name": "T", "type": "title"}, {"name": "V", "type": kind}] if kind != "title" else
                                    [{"name": "V", "type": "title"}], "rows": [["t", value] if kind != "title" else [value]]})
            ours = True
        except table_data.TableError:
            ours = False
        assert ours == theirs, (kind, value)


# --- the inference rule and the readers -----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("cells, kind", [
    (["1", "2.5", "-3", "0", "0.5"], "number"), (["1", None, "3"], "number"), (["007", "8"], "rich_text"), (["1,200", "5"], "rich_text"),
    (["1e3", "5"], "rich_text"), (["50%", "5"], "rich_text"), (["1234567890123456", "1"], "rich_text"), (["123456789012345", "1"], "number"),
    (["true", "false", "TRUE"], "checkbox"), (["true", None], "rich_text"), (["yes", "no"], "rich_text"),
    (["2026-11-01", "2026-11-02T09:30+02:00", "2026-11-03T10:00:00.5Z"], "date"), (["2026-11-01T09:30:00"], "rich_text"),
    (["2026-11-01", "2026-11-02T09:30"], "rich_text"), (["2026-02-30"], "rich_text"), (["2026-11-01", "soon"], "rich_text"),
    (["https://a.example", None, "http://b.example/x?y=1"], "url"), (["https://a.example", "b.example"], "rich_text"),
    ([None, None], "rich_text"), (["a", "b"], "rich_text"), (["+31 6 12345678"], "rich_text"), (["1", "x"], "rich_text"),
])
def test_the_inference_rule_by_cases(cells, kind):
    assert table_data.infer(cells)[0] == kind


def test_an_ambiguous_column_is_text_and_the_note_names_why():
    assert table_data.infer(["1", "x"])[1] == "text, ambiguous: some cells look like number and some do not"
    assert table_data.infer(["a", "b"])[1] == "text: no other type fits"
    assert table_data.infer([None])[1] == "text: the column has no value"


def test_select_is_never_inferred_and_the_first_column_is_the_title_unless_one_is_named():
    table = table_data.build(["A", "B", "C"], [["x", "red", "1"], ["y", "red", "2"]])
    assert [c["type"] for c in table["columns"]] == ["title", "rich_text", "number"]
    table = table_data.build(["A", "B", "C"], [["x", "red", "1"], ["y", "red", "2"]], {"C": "title", "B": "select"})
    assert [c["type"] for c in table["columns"]] == ["rich_text", "select", "title"] and table["rows"][0] == ["x", "red", "1"]


def test_a_csv_reader_takes_a_bom_quotes_blank_lines_and_trims_the_space_around_a_cell():
    header, rows = table_data.parse_csv(b"\xef\xbb\xbfName, Note \r\n\r\n\"A, B\", \"x\ny\"\r\nC,\r\n")
    assert header == ["Name", "Note"] and rows == [["A, B", "x\ny"], ["C", None]]


def test_a_workbook_reader_takes_the_first_sheet_shared_strings_booleans_dates_and_cells_a_row_does_not_store():
    header, rows, extras = table_data.parse_xlsx(make_xlsx(XLSX_ROWS))
    assert extras == {"sheet": "Stalls", "hidden": [], "no_value": {}}
    assert header == XLSX_ROWS[0] and rows[0] == ["Bread", "Fresh at six", "12.5", "2026-11-01", "true", "https://bread.example/shop", "01234"]
    assert rows[1] == ["Candles", None, "8", "2026-11-02", "false", None, "02345"]
    assert rows[2] == ["Tea", "Loose leaf, green", None, None, "true", "https://tea.example", None], "the cell a row does not store is empty"
    other = make_xlsx([["A", "B"], ["x", ("date", "2026-11-01")]], date1904=True)
    assert table_data.parse_xlsx(other)[1] == [["x", "2026-11-01"]]


def zipped(parts: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return out.getvalue()


def test_a_workbook_with_an_entity_a_bomb_a_missing_part_or_an_error_cell_is_refused():
    good = {"xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="a" sheetId="1"/></sheets></workbook>',
            "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                                        '<row r="1"><c r="A1" t="inlineStr"><is><t>H</t></is></c></row>'
                                        '<row r="2"><c r="A2" t="inlineStr"><is><t>x</t></is></c></row></sheetData></worksheet>'}
    assert table_data.parse_xlsx(zipped(good))[:2] == (["H"], [["x"]])
    entity = dict(good, **{"xl/worksheets/sheet1.xml": '<!DOCTYPE x [<!ENTITY a "aaaa">]>' + good["xl/worksheets/sheet1.xml"]})
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped(entity))
    assert refused.value.code == "xlsx_unsafe"
    bomb = dict(good, **{"xl/worksheets/sheet1.xml": "<worksheet>" + "<!--" + "a" * 5_000_000 + "-->" + "</worksheet>"})
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped(bomb))
    assert refused.value.code == "xlsx_unsafe"
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped({"xl/other.xml": "<a/>"}))
    assert refused.value.code == "xlsx_unreadable"
    broken = dict(good, **{"xl/worksheets/sheet1.xml": good["xl/worksheets/sheet1.xml"].replace('t="inlineStr"><is><t>x</t></is>', 't="e"><v>#REF!</v>')})
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped(broken))
    assert refused.value.code == "xlsx_unreadable"
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(b"PK" + b"\x00" * 100)
    assert refused.value.code == "xlsx_unreadable"
    many = dict(good, **{"xl/worksheets/sheet1.xml": '<worksheet><sheetData>' + "".join(
        f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>v{n}</t></is></c></row>' for n in range(1, 503)) + "</sheetData></worksheet>"})
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped(many))
    assert refused.value.code == "too_many_rows"


def test_a_workbook_made_by_a_spreadsheet_library_is_read_the_same():
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Stall", "Fee", "Opens", "Paid", "Note"])
    sheet.append(["Bread", 12.5, date(2026, 11, 1), True, "=1+1"])
    sheet.append(["Tea", None, None, False, None])
    book.create_sheet("Other").append(["x"])
    out = io.BytesIO()
    book.save(out)
    header, rows, _ = table_data.parse_xlsx(out.getvalue())
    assert header == ["Stall", "Fee", "Opens", "Paid", "Note"]
    assert rows[0][:4] == ["Bread", "12.5", "2026-11-01", "true"] and rows[1][0] == "Tea" and rows[1][1] is None


def test_the_cell_a_workbook_holds_as_a_formula_text_is_text_for_the_platform_and_never_evaluated():
    table = table_data.build(["Stall", "Note"], [["Bread", "=HYPERLINK(\"http://evil.example\")"], ["Tea", "+1"]])
    assert table["rows"][0][1].startswith("=") and table["columns"][1]["type"] == "rich_text"
    assert table["rows"][1][1] == "+1" and table["columns"][1]["type"] == "rich_text"


def test_the_oversized_table_as_the_approval_holds_it_is_refused():
    big = [[f"s{n}", "y" * 2000, "z" * 2000] for n in range(500)]
    with pytest.raises(table_data.TableError) as refused:
        table_data.build(["Stall", "Note", "More"], big)
    assert refused.value.code == "table_too_large"


def test_the_state_of_a_task_that_waits_holds_the_decision_and_the_effect_file_is_in_a_private_folder(world):
    task = table_task(world)
    item = opened(world, task)
    path, _ = effect_doc(world, task)
    for folder in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert oct(folder.stat().st_mode & 0o777) == "0o700", folder
    assert item["payload_sha256"] == sha(path.read_bytes())


# --- review round: the rows an earlier approval wrote, a bomb, a long write, and what the preview says -----------------------------------------


def select_table(world, options=("food",), rows=()):
    """A table a person made, named Pantry, with a title column and a select column that has some options."""
    fake = world["fake"]
    props = {"Stall": {"type": "title", "title": {}},
             "Kind": {"type": "select", "select": {"options": [{"name": o} for o in options]}}}
    database = fake.create_database({"parent": {"type": "page_id", "page_id": world["parent"]},
                                     "title": [{"type": "text", "text": {"content": "Pantry"}}], "initial_data_source": {"properties": props}})
    return database["data_sources"][0]["id"]


def test_rows_written_by_an_earlier_approval_are_not_sent_again_when_the_task_starts_over_after_the_table_changed(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    first = opened(world, task)
    fake = world["fake"]
    fake.fail_at("create_page", 2, 400)                 # Honey is written; Jam is refused (nothing of it exists)
    with pytest.raises(ops_core.OpsError):
        approve(world, first)
    assert [r["Stall"] for r in (fake.cells(p) for p in fake.rows_of(source))] == ["Pie", "Honey"]
    fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", "Cake")   # a colleague
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, first)
    text = str(stopped.value)
    assert "1 row(s)" in text and "stay there" in text and "Nothing was written by this attempt" not in text, text
    ctx = ops_core.context(world["path"])
    assert "already wrote 1 row(s)" in ctx["store"].pending_get(ctx["conn"], first["id"])["answer"]
    assert task_state(world, task) == "ready"
    second = opened(world, task)
    _, doc = effect_doc(world, task, 1)
    assert doc["cycle"] == 1 and doc["base"]["rows_done"] == 1 and doc["base"]["row_count"] == 3
    assert second["payload_sha256"] != first["payload_sha256"] and "1 of these 2 rows are ALREADY in the table" in second["body"]
    done = approve(world, second)
    assert done["task_state"] == "done" and done["result"]["rows_created"] == 1 and done["result"]["rows_replayed"] == 1
    assert sorted(r["Stall"] for r in (fake.cells(p) for p in fake.rows_of(source))) == ["Cake", "Honey", "Jam", "Pie"], "each once"


def test_when_every_row_is_already_there_the_new_preview_says_so_and_approving_only_records_it(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    first = opened(world, task)
    fake = world["fake"]
    world["lost"].add("rows-append")                     # both rows are written; the answer is lost
    with pytest.raises(ops_core.OpsError):
        approve(world, first)
    fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", "Cake")
    done = approve(world, first)                         # every row is there: nothing to compare, nothing to write
    assert done["result"]["replayed"] is True and done["result"]["rows_replayed"] == 2 and len(fake.rows_of(source)) == 4


def test_a_long_write_does_not_hold_the_projects_write_lock_and_a_second_approval_of_the_decision_is_refused(world, monkeypatch):
    import threading
    import time
    item = opened(world, table_task(world))
    real = docs.call
    started, release = threading.Event(), threading.Event()

    def slow(cfg, root, verb, args, timeout=docs.TIMEOUT):
        if verb == "table-create" and "--confirmed" in args:
            started.set()
            assert release.wait(60)
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", slow)
    monkeypatch.setattr(ops_core, "ROUTE_LOCK_WAIT", 0.3)
    result, failure = {}, []

    def approving():
        try:
            result["done"] = approve(world, item)
        except Exception as e:      # reported by the assertion below
            failure.append(e)
    writer = threading.Thread(target=approving)
    writer.start()
    try:
        assert started.wait(60)
        cfg = ops_core.context(world["path"])["cfg"]
        began = time.monotonic()
        with ops_core._write_lock(cfg, wait=1):       # another writer of the project (a sync, the return of a run) is not made to wait
            pass
        assert time.monotonic() - began < 1
        with pytest.raises(ops_core.OpsError) as busy:
            approve(world, item)
        assert "already executing" in str(busy.value) or "being written" in str(busy.value)
    finally:
        release.set()
        writer.join(60)
    assert not failure, failure
    assert result["done"]["task_state"] == "done" and made_table(world)[1] == EXPECTED_ROWS


def test_a_write_back_still_holds_the_write_lock_for_its_short_write(world):
    assert effect_write.is_long(doc_of()) is True
    update = effect_write.document(task_id=1, provider="notion", target_id="a" * 32, path="docs/a.md", content="Text\n",
                                   base_text_sha256="b" * 64, base_version=None)
    assert effect_write.is_long(update) is False


def sheet_xml(rows_xml: str) -> str:
    return f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{rows_xml}</sheetData></worksheet>'


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
BOOK = f'<workbook xmlns="{MAIN}"><sheets><sheet name="a" sheetId="1"/></sheets></workbook>'


def small_book(rows_xml: str, book=BOOK, extra=None) -> bytes:
    parts = {"xl/workbook.xml": book, "xl/worksheets/sheet1.xml": sheet_xml(rows_xml)}
    parts.update(extra or {})
    return zipped(parts)


def inline(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def test_a_cell_far_to_the_right_is_refused_before_any_list_is_built_and_an_empty_one_is_ignored():
    head = f'<row r="1">{inline("A1", "H")}</row>'
    for ref in ("ZZZZZ2", "XFD2", "AE2", "ZZZ2"):
        with pytest.raises(table_data.TableError) as refused:
            table_data.parse_xlsx(small_book(head + f'<row r="2">{inline(ref, "far")}</row>'))
        assert refused.value.code in ("too_many_columns", "xlsx_unreadable"), ref
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(small_book(head + f'<row r="2">{inline("AE2", "far")}</row>'))
    assert refused.value.code == "too_many_columns"
    empty = '<row r="2">' + inline("A2", "x") + '<c r="ZZZ2" s="1"/><c r="ZZZZZ2"/></row>'      # styled and empty: no value, no column
    assert table_data.parse_xlsx(small_book(head + empty))[:2] == (["H"], [["x"]])
    thirty = '<row r="2">' + "".join(inline(f"{chr(65 + n)}2", "v") for n in range(26)) + inline("AA2", "v") + inline("AB2", "v") \
        + inline("AC2", "v") + inline("AD2", "v") + "</row>"
    names = '<row r="1">' + "".join(inline(f"{chr(65 + n)}1", f"c{n}") for n in range(26)) + "".join(
        inline(f"A{c}1", f"c{26 + i}") for i, c in enumerate("ABCD")) + "</row>"
    assert len(table_data.parse_xlsx(small_book(names + thirty))[0]) == 30


def test_a_workbook_in_another_encoding_cannot_hide_an_entity_a_nul_byte_is_refused():
    sheet = ('<!DOCTYPE x [<!ENTITY a "aaaa">]>' + sheet_xml(f'<row r="1">{inline("A1", "H")}</row>')).encode("utf-16")
    book = zipped({"xl/workbook.xml": BOOK})
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(book)) as z, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        w.writestr("xl/workbook.xml", z.read("xl/workbook.xml"))
        w.writestr("xl/worksheets/sheet1.xml", sheet)
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(out.getvalue())
    assert refused.value.code == "xlsx_unsafe"


@pytest.mark.parametrize("fault", [RuntimeError("encrypted"), NotImplementedError("compression type 99"), zipfile.BadZipFile("bad"),
                                   __import__("zlib").error("bad data"), EOFError("short")])
def test_a_damaged_encrypted_or_unsupported_part_is_a_closed_code(fault, monkeypatch):
    good = small_book(f'<row r="1">{inline("A1", "H")}</row><row r="2">{inline("A2", "x")}</row>')

    def broken(self, *args, **kwargs):
        raise fault
    monkeypatch.setattr(zipfile.ZipFile, "open", broken)
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(good)
    assert refused.value.code == "xlsx_unreadable"


def test_a_corrupted_part_is_a_closed_code():
    good = bytearray(small_book(f'<row r="1">{inline("A1", "H")}</row><row r="2">{inline("A2", "x")}</row>'))
    marker = good.index(b"sheet1.xml") + 40
    for n in range(marker, marker + 30):
        good[n] ^= 0xFF
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(bytes(good))
    assert refused.value.code in ("xlsx_unreadable", "xlsx_unsafe")


def test_a_negative_shared_string_index_and_one_past_the_end_are_refused():
    for index in ("-1", "5"):
        sheet = f'<row r="1"><c r="A1" t="s"><v>{index}</v></c></row>'
        book = small_book(sheet, extra={"xl/sharedStrings.xml": f'<sst xmlns="{MAIN}"><si><t>H</t></si></sst>'})
        with pytest.raises(table_data.TableError) as refused:
            table_data.parse_xlsx(book)
        assert refused.value.code == "xlsx_unreadable", index


def test_the_first_visible_sheet_is_read_and_the_remarks_name_it_and_the_formulas_with_no_stored_value():
    book = (f'<workbook xmlns="{MAIN}"><sheets><sheet name="Secret" sheetId="1" state="hidden"/><sheet name="Stalls" sheetId="2"/></sheets>'
            "</workbook>")
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
    rows = f'<row r="1">{inline("A1", "Stall")}{inline("B1", "Fee")}</row><row r="2">{inline("A2", "Bread")}<c r="B2"><f>1+1</f></c></row>'
    parts = {"xl/workbook.xml": book, "xl/_rels/workbook.xml.rels": rels, "xl/worksheets/sheet1.xml": sheet_xml(rows)}
    header, data, extras = table_data.parse_xlsx(zipped(parts))
    assert header == ["Stall", "Fee"] and data == [["Bread", None]]
    assert extras == {"sheet": "Stalls", "hidden": ["Secret"], "no_value": {1: 1}}
    table = table_data.build(header, data, extras=extras)
    assert any("read from the sheet 'Stalls'" in r and "1 hidden sheet(s)" in r for r in table["remarks"])
    assert any("1 cell(s) of the column 'Fee' hold a formula with no stored value" in r for r in table["remarks"])
    only_hidden = book.replace('<sheet name="Stalls" sheetId="2"/>', "")
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(zipped({**parts, "xl/workbook.xml": only_hidden}))
    assert refused.value.code == "xlsx_unreadable"


def test_the_remarks_reach_the_preview_and_the_hash(world):
    (world["root"] / XLSX_PATH).write_bytes(make_xlsx(XLSX_ROWS))
    task = table_task(world, rows=XLSX_PATH)
    item = opened(world, task)
    _, doc = effect_doc(world, task)
    assert doc["remarks"] and "read from the sheet 'Stalls'" in doc["remarks"][0] and "Read before approving:" in item["body"]
    assert "- read from the sheet 'Stalls'" in item["body"]


def test_new_select_options_the_platform_will_add_to_the_persons_table_are_said_in_the_preview(world):
    source = select_table(world)
    (world["root"] / MORE_PATH).write_text("Stall,Kind\nHoney,food\nJam,sweet\nTea,drink\n", encoding="utf-8")
    item = opened(world, add(world, "output-table", table=source, rows=MORE_PATH))
    assert "the column 'Kind' gets 2 NEW option(s) in the table: drink, sweet" in item["body"]
    (world["root"] / MORE_PATH).write_text("Stall,Kind\nHoney,food\n", encoding="utf-8")
    assert "NEW option" not in opened(world, add(world, "output-table", table=source, rows=MORE_PATH))["body"]


def test_the_preview_shows_the_names_the_platform_gave_next_to_the_ids(world):
    page = opened(world, page_task(world))
    assert f"Parent: the page {world['parent']} named 'Workbench'" in page["body"]
    source = select_table(world)
    (world["root"] / MORE_PATH).write_text("Stall,Kind\nHoney,food\n", encoding="utf-8")
    item = opened(world, add(world, "output-table", table=source, rows=MORE_PATH))
    assert f"Table: the data source {source} named 'Pantry'" in item["body"]


def test_a_date_time_with_no_zone_makes_a_text_column_that_says_why_and_a_named_date_column_stops(world):
    (world["root"] / CSV_PATH).write_text("Stall,When\nBread,2026-11-01T09:30:00\nTea,2026-11-02T10:00:00\n", encoding="utf-8")
    item = opened(world, table_task(world))
    assert "| When | rich_text | text, ambiguous: a date-time with no Z or offset is not sent as a date" in item["body"]
    out = run_task(world, table_task(world, columns={"When": "date"}))
    assert out["code"] == "cell_not_type" and "Z or an offset" in out.get("next", "")
    (world["root"] / CSV_PATH).write_text("Stall,When\nBread,2026-11-01T09:30:00+02:00\nTea,2026-11-02T10:00:00Z\n", encoding="utf-8")
    ok = opened(world, table_task(world))
    assert "| When | date | inferred: every filled cell is an ISO date |" in ok["body"]


def test_a_cell_is_counted_in_utf16_code_units_by_the_step(world):
    emoji = "\U0001F600"
    (world["root"] / CSV_PATH).write_text(f"Stall,Note\nBread,{emoji * 1000}\n", encoding="utf-8")
    refused_with(world, f"Stall,Note\nBread,{emoji * 1001}\n", "cell_too_long")
    (world["root"] / CSV_PATH).write_text(f"Stall,Note\nBread,{emoji * 1000}\n", encoding="utf-8")
    assert opened(world, table_task(world))["payload"]["effect"]["rows"] == 1


def test_the_cycle_is_in_the_document_and_the_key_of_a_task_that_started_over_is_another(world):
    a = doc_of()
    b = output_document.document(store=STORE, operation="create_table", task_id=1, provider="notion", target_id="a" * 32, path="docs/outputs/stalls.csv",
                                 title="Stalls", content=a["content"], notes=a["notes"], cycle=1)
    assert a["cycle"] == 0 and b["cycle"] == 1 and a["idempotency_key"] != b["idempotency_key"] and digest(a) != digest(b)
    named = output_document.document(store=STORE, operation="create_table", task_id=1, provider="notion", target_id="a" * 32, path="docs/outputs/stalls.csv",
                                     title="Stalls", content=a["content"], notes=a["notes"], target_name="Reports\n  2026")
    assert named["target_name"] == "Reports 2026" and digest(named) != digest(a)
    with pytest.raises(effects.EffectError):
        output_document.check(dict(named, target_name="two\nlines"))


# --- review round 2: reject during a write, a ledger the table does not bear out, two projects, the ledger's age -----------------------------


def locks_of(world):
    return os.listdir(ops_core._locks_dir(ops_core.context(world["path"])["cfg"]))


def during_a_table_write(world, monkeypatch, item, while_held):
    """Run the approval of `item` in a thread that is paused inside the provider's table-create, call `while_held()` meanwhile, and let
    it finish; returns what the approval returned."""
    import threading
    real = docs.call
    started, release = threading.Event(), threading.Event()

    def slow(cfg, root, verb, args, timeout=docs.TIMEOUT):
        if verb == "table-create" and "--confirmed" in args:
            started.set()
            assert release.wait(60)
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", slow)
    result, failure = {}, []

    def approving():
        try:
            result["done"] = approve(world, item)
        except Exception as e:      # reported by the assertion below
            failure.append(e)
    writer = threading.Thread(target=approving)
    writer.start()
    try:
        assert started.wait(60)
        while_held()
    finally:
        release.set()
        writer.join(60)
    assert not failure, failure
    return result["done"]


def test_a_decision_cannot_be_rejected_or_answered_while_its_write_runs_and_the_write_is_recorded(world, monkeypatch):
    task = table_task(world)
    item = opened(world, task)

    def meanwhile():
        with pytest.raises(ops_core.OpsError) as rejected:
            ops.reject(world["path"], item["id"], "not now")
        assert "being written; wait for the write to finish" in str(rejected.value)
        with pytest.raises(ops_core.OpsError) as answered:
            ops.answer(world["path"], item["id"], "use another title")
        assert "being written; wait for the write to finish" in str(answered.value)
        ctx = ops_core.context(world["path"])
        assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "open", "neither of them cancelled it"
        assert f"output-{item['id']}.lock" in locks_of(world)
    done = during_a_table_write(world, monkeypatch, item, meanwhile)
    assert done["task_state"] == "done" and made_table(world)[1] == EXPECTED_ROWS
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["resolution"] == "approved", "recorded, not cancelled"
    assert ctx["store"].approval_get(ctx["conn"], done["approval_id"])["status"] == "executed"
    assert f"output-{item['id']}.lock" not in locks_of(world), "the lock file is removed with the lock"
    assert f"sha256:{item['payload_sha256']}" in (world["root"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")


def test_a_decision_nobody_is_writing_is_rejected_at_once_and_leaves_no_lock_file(world):
    task = table_task(world)
    item = opened(world, task)
    ops.reject(world["path"], item["id"], "not now")
    assert task_state(world, task) == "cancelled" and writes(world) == [] and f"output-{item['id']}.lock" not in locks_of(world)


def test_the_ledger_is_not_trusted_over_the_table_a_row_a_person_trashed_is_a_row_to_write(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    item = opened(world, task)
    fake = world["fake"]
    fake.fail_at("create_page", 2, 500)               # Honey is written; Jam's outcome is unknown
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    honey = next(r for r in fake.rows_of(source) if fake.cells(r)["Stall"] == "Honey")
    fake.person_trashes(honey["id"])
    done = approve(world, item)                       # not stale: no row of this document is in the table now, one may have landed
    assert done["task_state"] == "done"
    assert sorted(fake.cells(r)["Stall"] for r in fake.rows_of(source)) == ["Honey", "Jam", "Pie"]
    assert done["result"]["rows_created"] == 2 and done["result"]["rows_replayed"] == 0


def test_the_preview_and_the_stale_answer_count_only_rows_the_table_still_lists(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    first = opened(world, task)
    fake = world["fake"]
    fake.fail_at("create_page", 2, 400)               # Honey is written; Jam is refused
    with pytest.raises(ops_core.OpsError):
        approve(world, first)
    fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", "Cake")
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, first)
    assert "already wrote 1 row(s)" in str(stopped.value)
    honey = next(r for r in fake.rows_of(source) if fake.cells(r)["Stall"] == "Honey")
    fake.person_trashes(honey["id"])                  # the person removes the row the earlier attempt wrote
    second = opened(world, task)
    _, doc = effect_doc(world, task, 1)
    assert doc["base"]["rows_done"] == 0 and "ALREADY" not in second["body"], "the ledger says Honey; the table does not"
    done = approve(world, second)
    assert done["result"]["rows_created"] == 2 and sorted(fake.cells(r)["Stall"] for r in fake.rows_of(source)) == ["Cake", "Honey", "Jam", "Pie"]


def test_fewer_of_the_tasks_rows_than_the_task_counted_is_stale_and_sends_nothing(world):
    source = existing_table(world, ["Pie"])
    task = add(world, "output-table", table=source, rows=MORE_PATH)
    first = opened(world, task)
    fake = world["fake"]
    fake.fail_at("create_page", 2, 400)
    with pytest.raises(ops_core.OpsError):
        approve(world, first)
    fake.person_sets(fake.create_page({"type": "data_source_id", "data_source_id": source}, {})["id"], "Stall", "Cake")
    with pytest.raises(ops_core.OpsError):
        approve(world, first)
    second = opened(world, task)
    _, doc = effect_doc(world, task, 1)
    assert doc["base"]["rows_done"] == 1 and "1 of these 2 rows are ALREADY in the table" in second["body"]
    assert "the platform's own listing of the table" in second["body"]
    honey = next(r for r in fake.rows_of(source) if fake.cells(r)["Stall"] == "Honey")
    fake.person_trashes(honey["id"])                  # after the preview: the row the preview counted is gone
    before = len(writes(world))
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, second)
    assert "fewer of this task's rows" in str(stopped.value) and len(writes(world)) == before, "nothing was sent"
    assert task_state(world, task) == "ready"


def test_a_table_longer_than_the_listing_reads_is_refused_and_not_guessed_at(world):
    source = existing_table(world, ["Pie"])
    fake = world["fake"]
    for n in range(2000):
        fake.create_page({"type": "data_source_id", "data_source_id": source}, {})
    out = run_task(world, add(world, "output-table", table=source, rows=MORE_PATH))
    assert out["ok"] is False and out["code"] == "provider_failed" and writes(world) == []


def test_the_scope_and_the_key_carry_the_projects_store_so_two_projects_never_share_rows(world):
    a, b = output_document.store_id("/projects/a/store.sqlite"), output_document.store_id("/projects/b/store.sqlite")
    assert a != b and output_document.scope_of(a, 1) != output_document.scope_of(b, 1) and len(output_document.scope_of(a, 1)) <= 80
    one = doc_of()
    other = output_document.document(store=b, operation="create_table", task_id=1, provider="notion", target_id="a" * 32,
                                     path="docs/outputs/stalls.csv", title="Stalls", content=one["content"], notes=one["notes"])
    assert one["idempotency_key"] != other["idempotency_key"] and digest(one) != digest(other), "the same task number in another project"
    item = opened(world, table_task(world))
    task_id = item["task_id"]
    _, doc = effect_doc(world, task_id)
    cfg = ops_core.context(world["path"])["cfg"]
    assert doc["store"] == output_document.store_id(cfg["store_db"]) and doc["store"] != STORE
    approve(world, item)
    ledger = json.loads(Path(world["platform"].env["INTEGRATION_DOCUMENTS_NOTION_LEDGER"]).read_text(encoding="utf-8"))["entries"]
    assert {e.get("scope") for k, e in ledger.items() if "/row-" in k} == {output_document.scope_of(doc["store"], task_id)}


def test_a_decision_older_than_the_ledger_remembers_is_refused_for_an_output_only(world, monkeypatch):
    item = opened(world, table_task(world))
    ctx = ops_core.context(world["path"])
    assert ops_step_effects.decision_age_days(ctx["store"].pending_get(ctx["conn"], item["id"])) == 0
    assert ops_step_effects.decision_age_days({"created_at": "2020-01-01T00:00:00Z"}) > 365
    assert ops_step_effects.decision_age_days({"created_at": "never"}) is None
    monkeypatch.setattr(ops_step_effects, "decision_age_days", lambda item: 91)
    with pytest.raises(ops_core.OpsError) as old:
        approve(world, item)
    assert "91 days old" in str(old.value) and "could write twice" in str(old.value) and writes(world) == []
    monkeypatch.setattr(ops_step_effects, "decision_age_days", lambda item: 89)
    assert approve(world, item)["task_state"] == "done"


def test_the_retention_of_the_runtime_and_of_the_provider_are_the_same_number():
    spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location(
        "notion_for_retention", st.REPO / "providers" / "documents" / "notion.py")
    text = (st.REPO / "providers" / "documents" / "notion.py").read_text(encoding="utf-8")
    assert f"RETENTION_DAYS = {ops_step_effects.OUTPUT_RETENTION_DAYS} " in text and spec is not None


def test_a_cell_with_a_value_and_no_reference_is_refused():
    sheet = f'<row r="1">{inline("A1", "H")}</row><row r="2"><c t="inlineStr"><is><t>x</t></is></c></row>'
    with pytest.raises(table_data.TableError) as refused:
        table_data.parse_xlsx(small_book(sheet))
    assert refused.value.code == "xlsx_unreadable"


# --- review round 3: cancelling the request during a write, and the record of a write that landed -----------------------------------------------


def request_of(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["parent_id"]


def cancel_by(world, how, request, monkeypatch):
    """Cancel the request by one of the four ways the runtime has; returns what the way returned (None when it returns nothing)."""
    ctx = ops_core.context(world["path"])
    if how == "ops":
        return ops.cancel(world["path"], request)
    if how == "board":
        board = st.load("board")
        assert board._take_state(ctx, ctx["store"].task_get(ctx["conn"], request), "cancelled") is None
        return None
    if how == "routine":
        monkeypatch.setattr(ctx["store"], "routine_fires_list", lambda conn, routine, limit: [{"status": "asked", "request_id": request}])
        st.load("ops_routines")._close_stops(ctx, 1)
        return None
    say = st.load("ops_say")
    fake_ops = type("Ops", (), {"request": staticmethod(lambda project, text, **kw: {"request": request}),
                                "route": staticmethod(lambda project, request_id, channel=None: {"kind": "direct", "next": None, "run_id": None})})
    monkeypatch.setattr(say, "_ops", lambda: fake_ops)
    monkeypatch.setattr(say, "_planning_may_start", lambda ctx: (True, ""))
    monkeypatch.setattr(say, "state_reply", lambda project, nxt: "a direct reply")
    say._say_route(world["path"], ctx, "what is the plan?", 10**9, "terminal")
    return None


@pytest.mark.parametrize("how", ["ops", "board", "say", "routine"])
def test_cancelling_the_request_during_a_write_leaves_the_running_write_open_to_record_its_outcome(world, monkeypatch, how):
    task = table_task(world)
    item = opened(world, task)
    request = request_of(world, task)
    other = add(world, "output-page", parent=world["parent"], title="Other", content=PAGE_PATH)
    ctx = ops_core.context(world["path"])
    ctx["conn"].execute("UPDATE tasks SET parent_id = ? WHERE id = ?", (request, other))     # a second task of the same request
    ctx["conn"].commit()
    seen = {}

    def meanwhile():
        seen["out"] = cancel_by(world, how, request, monkeypatch)
        c = ops_core.context(world["path"])
        assert c["store"].pending_get(c["conn"], item["id"])["status"] == "open", "the decision of the running write stays open"
        assert c["store"].task_get(c["conn"], task)["state"] == "waiting", "and so does its task"
        assert c["store"].task_get(c["conn"], request)["state"] == "cancelled", "the request is cancelled"
        assert c["store"].task_get(c["conn"], other)["state"] == "cancelled", "everything else too"
    done = during_a_table_write(world, monkeypatch, item, meanwhile)
    c = ops_core.context(world["path"])
    assert done["task_state"] == "done" and made_table(world)[1] == EXPECTED_ROWS
    assert c["store"].pending_get(c["conn"], item["id"])["resolution"] == "approved", "the running write recorded its outcome"
    assert c["store"].approval_get(c["conn"], done["approval_id"])["status"] == "executed"
    assert c["store"].task_get(c["conn"], request)["state"] == "cancelled", "and the request ends cancelled"
    assert f"sha256:{item['payload_sha256']}" in (world["root"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"output-{item['id']}.lock" not in locks_of(world)
    if how == "ops":
        assert seen["out"]["kept"] == [item["id"]] and seen["out"]["writing"][0]["pending"] == item["id"]
        assert seen["out"]["said"] == f"the write of {world['parent']} is running and will be recorded; everything else is cancelled"
        assert item["id"] not in seen["out"]["pending"] and task not in seen["out"]["cancelled"]


def test_cancelling_a_request_nobody_is_writing_cancels_everything_as_before_and_leaves_no_lock_file(world):
    task = table_task(world)
    item = opened(world, task)
    out = ops.cancel(world["path"], request_of(world, task))
    assert item["id"] in out["pending"] and "kept" not in out and "writing" not in out and "said" not in out
    assert task_state(world, task) == "cancelled" and f"output-{item['id']}.lock" not in locks_of(world) and writes(world) == []
    with pytest.raises(ops_core.OpsError):
        approve(world, item)


def test_every_way_of_cancelling_a_request_goes_through_the_one_function_that_leaves_a_running_write_open():
    import re
    calls = {}
    for path in sorted((st.REPO / "runtime").glob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.request_cancel[,(]", line) and "ops_cancel.request_cancel" not in line and path.name != "ops_cancel.py":
                calls.setdefault(path.name, []).append(line.strip())
    assert not calls, f"a way to cancel a request that does not go through ops_cancel.request_cancel: {calls}"
    for name in ("ops.py", "board.py", "ops_say.py", "ops_routines.py"):
        assert "ops_cancel.request_cancel" in (st.REPO / "runtime" / name).read_text(encoding="utf-8"), name


def test_the_record_of_a_write_that_landed_waits_for_the_project_files_as_long_as_it_takes(world, monkeypatch):
    import threading
    import time
    item = opened(world, table_task(world))
    monkeypatch.setattr(ops_core, "WRITE_LOCK_WAIT", 0.3)      # the usual wait a writer gives the project's files
    cfg = ops_core.context(world["path"])["cfg"]
    real = docs.call
    started, release = threading.Event(), threading.Event()

    def slow(cfg_, root, verb, args, timeout=docs.TIMEOUT):
        if verb == "table-create" and "--confirmed" in args:
            started.set()
            assert release.wait(60)
        return real(cfg_, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", slow)
    result, failure = {}, []

    def approving():
        try:
            result["done"] = approve(world, item)
        except Exception as e:
            failure.append(e)
    writer = threading.Thread(target=approving)
    writer.start()
    try:
        assert started.wait(60)
        with ops_core._write_lock(cfg):          # another writer holds the project's files when the write ends...
            release.set()
            time.sleep(1.0)                      # ...for longer than the usual wait
    finally:
        release.set()
        writer.join(60)
    assert not failure, failure
    assert result["done"]["task_state"] == "done" and made_table(world)[1] == EXPECTED_ROWS, "the record waited and was made"
