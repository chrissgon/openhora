"""Tests of the outputs of a task on Notion (providers/documents/notion.py: page-create, table-read, table-create, rows-append, and the
pure half notion_tables.py), against the stand-in service (fake_notion.py). Offline: no network, no real credential, no workspace.

What is held: a page under a parent the call names; a table made with its columns and filled; rows added to an existing table after
its schema is checked; the idempotency of the operation and of each row (a lost answer, a failure after some rows, a second run);
the retry of a 429; the caps; the token that writes is NOTION_TOKEN and never the sources one. Fictional names throughout.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_notion_outputs.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import documents_harness  # noqa: E402

SCRIPT = HERE.parent / "notion.py"
_spec = importlib.util.spec_from_file_location("notion_tables_for_the_tests", HERE.parent / "notion_tables.py")
nt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nt)

COLUMNS = [{"name": "Stall", "type": "title"}, {"name": "Notes", "type": "rich_text"}, {"name": "Fee", "type": "number"},
           {"name": "Opens", "type": "date"}, {"name": "Kind", "type": "select"}, {"name": "Paid", "type": "checkbox"},
           {"name": "Site", "type": "url"}]
ROWS = [["Bread", "Fresh at six", 12.5, "2026-11-01", "food", True, "https://bread.example/shop"],
        ["Candles", None, 8, "2026-11-02T09:30:00", "craft", False, None],
        ["Tea", "Loose leaf", None, None, "food", False, "https://tea.example"]]


class Outputs:
    def __init__(self, tmp_path: Path):
        self.harness = documents_harness.NotionDocuments()
        cfg = self.harness.config(tmp_path)
        self.fake = self.harness.fake
        self.config = tmp_path / "documents.json"
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        self.tmp = tmp_path
        self.parent = self.fake.create_root()      # another parent than the configured one
        self.n = 0
        self.start = len(self.fake.requests)       # the stand-in is shared by the tests of a process: count from here
        self.had = (set(self.fake.databases), set(self.fake.bases))

    def run(self, *argv, env=None):
        done = subprocess.run([sys.executable, str(SCRIPT), *argv, "--config-file", str(self.config)], capture_output=True, text=True,
                              timeout=120, env={**os.environ, **self.harness.env(), **(env or {})})
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout + done.stderr

    def file(self, name, text):
        self.n += 1
        path = self.tmp / f"{self.n}-{name}"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def table(self, columns=COLUMNS, rows=ROWS):
        return self.file("table.json", json.dumps({"columns": columns, "rows": rows}))

    def create_table(self, key="k1", mode="--confirmed", title="Market stalls", table=None, parent=None, env=None):
        return self.run("table-create", "--parent", parent or self.parent, "--title", title, "--table-file", table or self.table(),
                        "--idempotency-key", key, mode, env=env)

    def append(self, source, key="k2", mode="--confirmed", table=None, schema=None, env=None):
        extra = ["--schema-sha256", schema] if schema else []
        return self.run("rows-append", "--id", source, "--table-file", table or self.table(), "--idempotency-key", key, mode, *extra, env=env)

    def read(self, source):
        return self.run("table-read", "--id", source)

    def sent(self):
        return self.fake.requests[self.start:]

    def count(self, name):
        method, pattern = next((m, p) for n, m, p in documents_harness.NotionDocuments.fake_notion.ROUTES if n == name)
        return sum(1 for m, path, _ in self.sent() if m == method and re.fullmatch(pattern, path))

    def creates(self):
        return self.count("create_page")

    def databases(self):
        return [d for d in self.fake.databases if d not in self.had[0]]

    def source(self):
        return [b for b in self.fake.bases if b not in self.had[1]][-1]


@pytest.fixture
def out(tmp_path):
    return Outputs(tmp_path)


def cells(out, source):
    return [out.fake.cells(r) for r in out.fake.rows_of(source)]


# --- a page ------------------------------------------------------------------------------------------------------------------------


def test_a_page_is_made_under_the_parent_the_call_names_with_the_markdown_as_its_body(out):
    md = out.file("page.md", "# Weekly report\n\nSales were up.\n\n- stalls: forty\n")
    code, made, said = out.run("page-create", "--parent", out.parent, "--title", "Report, week 44", "--markdown-file", md,
                               "--idempotency-key", "p1", "--confirmed")
    assert code == 0, said
    assert made["created"] is True and made["replayed"] is False and re.fullmatch(r"[0-9a-f-]{36}", made["id"])
    page = out.fake.pages[made["id"]]
    assert page["parent"] == {"type": "page_id", "page_id": out.parent}, "under the parent named, not the configured one"
    assert page["properties"]["title"]["title"][0]["plain_text"] == "Report, week 44"
    code, read, _ = out.run("read", "--id", made["id"])
    assert read["markdown"] == out.harness.expected("# Weekly report\n\nSales were up.\n\n- stalls: forty\n")


def test_a_page_under_the_same_key_is_not_made_twice(out):
    md = out.file("page.md", "Hello.\n")
    args = ("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "p1", "--confirmed")
    first = out.run(*args)[1]
    again = out.run(*args)[1]
    assert again["id"] == first["id"] and again["replayed"] is True and again["created"] is False
    assert out.creates() == 1 and len([p for p in out.fake.pages.values() if p["parent"].get("page_id") == out.parent]) == 1


def test_a_page_dry_run_reads_no_credential_and_makes_no_call(out):
    md = out.file("page.md", "Hello.\n")
    before = len(out.fake.requests)
    code, said, text = out.run("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "p1",
                               "--dry-run", env={"NOTION_TOKEN": ""})
    assert code == 0 and said["dry_run"] is True and said["would"]["state"] == "new" and len(out.fake.requests) == before, text


def test_a_page_whose_creation_answer_was_lost_is_found_among_the_parents_children_and_finished_once(out):
    md = out.file("page.md", "# Notes\n\nSecond line.\n")
    args = ("page-create", "--parent", out.parent, "--title", "Lost answer", "--markdown-file", md, "--idempotency-key", "p1", "--confirmed")
    out.fake.fail_next("create_page", 500, carried_out=True)       # the page is made and the answer is a 500
    code, _, said = out.run(*args)
    assert code == 1 and "500" in said
    code, made, said = out.run(*args)
    assert code == 0, said
    mine = [p for p in out.fake.pages.values() if p["parent"].get("page_id") == out.parent]
    assert len(mine) == 1 and made["id"] == mine[0]["id"] and out.creates() == 1, "found, not made again"
    assert out.run("read", "--id", made["id"])[1]["markdown"] == out.harness.expected("# Notes\n\nSecond line.\n")


def test_a_page_whose_creation_cannot_be_found_stays_pending_until_the_person_resolves_it(out):
    md = out.file("page.md", "Hello.\n")
    args = ("page-create", "--parent", out.parent, "--title", "Never made", "--markdown-file", md, "--idempotency-key", "p1", "--confirmed")
    out.fake.fail_next("create_page", 500)                         # not carried out
    assert out.run(*args)[0] == 1
    code, _, said = out.run(*args)
    assert code == 1 and "pending creation" in said and "--parent" in said and out.creates() == 1
    code, _, said = out.run("resolve", "--parent", out.parent, "--idempotency-key", "p1", "--not-created", "--confirmed")
    assert code == 0, said
    code, made, said = out.run(*args)
    assert code == 0 and made["created"] is True and out.creates() == 2, said


def test_a_page_whose_body_failed_halfway_is_finished_on_the_same_page(out):
    md = out.file("page.md", "# One\n\nTwo.\n")
    args = ("page-create", "--parent", out.parent, "--title", "Half", "--markdown-file", md, "--idempotency-key", "p1", "--confirmed")
    out.fake.fail_next("append_children", 500)
    assert out.run(*args)[0] == 1
    code, made, said = out.run(*args)
    assert code == 0, said
    assert out.creates() == 1 and out.run("read", "--id", made["id"])[1]["markdown"] == out.harness.expected("# One\n\nTwo.\n")


def test_a_parent_the_integration_was_not_given_is_exit_3_and_releases_the_key(out):
    md = out.file("page.md", "Hello.\n")
    code, _, said = out.run("page-create", "--parent", "f" * 32, "--title", "T", "--markdown-file", md, "--idempotency-key", "p1",
                            "--confirmed")
    assert code == 3 and "does not exist or the integration was not given it" in said
    assert out.run("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "p1",
                   "--dry-run")[1]["would"]["state"] == "new"


# --- a table made and filled ---------------------------------------------------------------------------------------------------


def test_a_table_is_made_under_the_parent_with_its_columns_and_filled_with_the_rows(out):
    code, made, said = out.create_table()
    assert code == 0, said
    assert made["created"] is True and made["rows"] == 3 and made["rows_created"] == 3 and made["rows_replayed"] == 0
    assert made["id"] in out.fake.databases and made["data_source_id"] in out.fake.bases and made["id"] != made["data_source_id"]
    database = out.fake.databases[made["id"]]
    assert database["parent"] == {"type": "page_id", "page_id": out.parent} and database["title"][0]["plain_text"] == "Market stalls"
    schema = {n: p["type"] for n, p in out.fake.bases[made["data_source_id"]]["properties"].items()}
    assert schema == {c["name"]: c["type"] for c in COLUMNS}
    assert [o["name"] for o in out.fake.bases[made["data_source_id"]]["properties"]["Kind"]["select"]["options"]] == ["food", "craft"]
    assert cells(out, made["data_source_id"]) == [
        {"Stall": "Bread", "Notes": "Fresh at six", "Fee": 12.5, "Opens": "2026-11-01", "Kind": "food", "Paid": True,
         "Site": "https://bread.example/shop"},
        {"Stall": "Candles", "Notes": "", "Fee": 8, "Opens": "2026-11-02T09:30:00", "Kind": "craft", "Paid": False, "Site": None},
        {"Stall": "Tea", "Notes": "Loose leaf", "Fee": None, "Opens": None, "Kind": "food", "Paid": False, "Site": "https://tea.example"}]
    assert out.count("create_database") == 1 and out.creates() == 3


def test_a_table_under_the_same_key_is_not_made_or_filled_twice(out):
    first = out.create_table()[1]
    again = out.create_table()[1]
    assert again["id"] == first["id"] and again["created"] is False and again["rows_created"] == 0 and again["rows_replayed"] == 3
    assert out.count("create_database") == 1 and out.creates() == 3 and len(out.fake.rows_of(first["data_source_id"])) == 3


def test_a_failure_after_some_rows_is_finished_without_a_duplicate(out):
    out.fake.fail_at("create_page", 3, 500)                 # the third row is not made (the database's creation is not a page)
    code, _, said = out.create_table()
    assert code == 1 and "row 3" in said and "unknown" in said
    source = out.source()
    assert len(out.fake.rows_of(source)) == 2
    code, made, said = out.create_table()
    assert code == 0, said
    assert made["rows_created"] == 1 and made["rows_replayed"] == 2 and made["created"] is False
    assert [c["Stall"] for c in cells(out, made["data_source_id"])] == ["Bread", "Candles", "Tea"]
    assert out.count("create_database") == 1


def test_a_row_whose_answer_was_lost_is_found_in_the_table_and_not_written_again(out):
    out.fake.fail_at("create_page", 2, 500, carried_out=True)       # the second row is made and the answer is lost
    assert out.create_table()[0] == 1
    source = out.source()
    assert len(out.fake.rows_of(source)) == 2
    code, made, said = out.create_table()
    assert code == 0, said
    assert made["rows_created"] == 1 and made["rows_replayed"] == 2
    assert [c["Stall"] for c in cells(out, source)] == ["Bread", "Candles", "Tea"], "three rows, none twice"


def test_two_rows_with_the_same_values_are_two_rows_even_when_one_answer_was_lost(out):
    twin = [["Tea", "Loose leaf", None, None, "food", False, None]] * 2
    out.fake.fail_at("create_page", 2, 500, carried_out=True)
    assert out.create_table(table=out.table(rows=twin))[0] == 1
    code, made, said = out.create_table(table=out.table(rows=twin))
    assert code == 0, said
    assert len(out.fake.rows_of(made["data_source_id"])) == 2


def test_a_database_whose_creation_answer_was_lost_is_found_and_filled_once(out):
    out.fake.fail_next("create_database", 500, carried_out=True)
    code, _, said = out.create_table()
    assert code == 1 and "500" in said
    code, made, said = out.create_table()
    assert code == 0, said
    assert len(out.databases()) == 1 and made["id"] in out.fake.databases and made["rows_created"] == 3
    assert out.count("create_database") == 1


def test_a_429_is_retried_and_the_row_is_made_once(out):
    out.fake.fail_next("create_page", 429)
    code, made, said = out.create_table()
    assert code == 0, said
    assert made["rows_created"] == 3 and out.creates() == 4, "one call was refused and made again"
    assert len(out.fake.rows_of(made["data_source_id"])) == 3


def test_a_table_dry_run_makes_no_call_and_reads_no_credential(out):
    before = len(out.fake.requests)
    code, said, text = out.create_table(mode="--dry-run", env={"NOTION_TOKEN": ""})
    assert code == 0 and said["would"]["state"] == "new" and said["would"]["rows"] == 3 and len(out.fake.requests) == before, text


def test_a_database_made_on_the_edge_of_a_refusal_is_exit_3_and_releases_the_key(out):
    code, _, said = out.create_table(parent="f" * 32)
    assert code == 3 and "does not exist or the integration was not given it" in said
    assert out.create_table(mode="--dry-run", parent="f" * 32)[1]["would"]["state"] == "new"


# --- rows into a table ---------------------------------------------------------------------------------------------------------


def seeded(out):
    made = out.create_table()[1]
    return made["data_source_id"], out.read(made["data_source_id"])[1]


def test_table_read_prints_the_columns_their_hash_the_row_count_and_the_newest_edit(out):
    source, read = seeded(out)
    assert read["row_count"] == 3 and read["title"] == "Stall" and len(read["schema_sha256"]) == 64
    assert read["schema"] == sorted(({"name": c["name"], "type": c["type"]} for c in COLUMNS), key=lambda c: c["name"])
    assert read["last_edited"] == max(r["last_edited_time"] for r in out.fake.rows_of(source))
    row = out.fake.rows_of(source)[0]
    out.fake.person_sets(row["id"], "Notes", "Edited by a person")
    assert out.read(source)[1]["last_edited"] != read["last_edited"]
    assert out.read(source)[1]["schema_sha256"] == read["schema_sha256"], "an edited cell is not a changed schema"


def test_rows_are_added_to_an_existing_table_after_its_schema_is_checked(out):
    source, read = seeded(out)
    more = out.table(rows=[["Honey", "Local", 9, "2026-11-03", "food", True, None]])
    code, done, said = out.append(source, table=more, schema=read["schema_sha256"])
    assert code == 0, said
    assert done["rows_created"] == 1 and done["rows_replayed"] == 0 and len(out.fake.rows_of(source)) == 4
    assert out.append(source, table=more, schema=read["schema_sha256"])[1]["rows_created"] == 0
    assert len(out.fake.rows_of(source)) == 4, "the same key adds nothing twice"


def test_a_changed_schema_stops_the_append_and_writes_nothing(out):
    source, read = seeded(out)
    out.fake.person_adds_property(source, "Extra")
    code, _, said = out.append(source, schema=read["schema_sha256"])
    assert code == 1 and "not the ones the task read" in said and len(out.fake.rows_of(source)) == 3
    assert out.count("create_page") == 3


def test_rows_that_do_not_fit_the_table_are_refused_before_any_write(out):
    source, read = seeded(out)
    wrong_type = [dict(c, type="rich_text") if c["name"] == "Fee" else c for c in COLUMNS]
    code, _, said = out.append(source, table=out.table(columns=wrong_type, rows=[[r[0], r[1], "x", r[3], r[4], r[5], r[6]] for r in ROWS]))
    assert code == 1 and "'Fee' is number in the table and rich_text in the rows" in said
    unknown = COLUMNS + [{"name": "Missing", "type": "rich_text"}]
    code, _, said = out.append(source, table=out.table(columns=unknown, rows=[r + [None] for r in ROWS]))
    assert code == 1 and "no column named 'Missing'" in said
    no_title = [c for c in COLUMNS if c["name"] != "Stall"]
    code, _, said = out.append(source, table=out.table(columns=no_title, rows=[r[1:] for r in ROWS]))
    assert code == 2 or "title" in said     # a table file without a title column is refused whole
    assert len(out.fake.rows_of(source)) == 3 and out.creates() == 3


def test_a_table_the_integration_was_not_given_is_exit_3(out):
    code, _, said = out.append("f" * 32)
    assert code == 3 and "does not exist or the integration was not given it" in said


# --- the caps and the token ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table, why", [
    ({"columns": COLUMNS, "rows": [ROWS[0]] * 501}, "at most 500 rows"),
    ({"columns": [{"name": f"c{i}", "type": "title" if i == 0 else "rich_text"} for i in range(31)], "rows": []}, "from 1 to 30 columns"),
    ({"columns": COLUMNS, "rows": [["T", "x" * 2001, None, None, None, False, None]]}, "at most 2000 characters"),
    ({"columns": COLUMNS + [{"name": "Other", "type": "title"}], "rows": []}, "exactly one title"),
    ({"columns": COLUMNS + [{"name": "Stall", "type": "rich_text"}], "rows": []}, "same name"),
    ({"columns": COLUMNS, "rows": [["T", None, "12", None, None, False, None]]}, "a number is"),
    ({"columns": COLUMNS, "rows": [["T", None, None, "01/11/2026", None, False, None]]}, "a date is"),
    ({"columns": COLUMNS, "rows": [["T", None, None, None, "a,b", False, None]]}, "no comma"),
    ({"columns": COLUMNS, "rows": [["T", None, None, None, None, "yes", None]]}, "true or false"),
    ({"columns": COLUMNS, "rows": [["", None, None, None, None, False, None]]}, "non-empty text"),
    ({"columns": COLUMNS, "rows": [["T", None, None, None, None, False, "ftp://x.example"]]}, "starts with http"),
    ({"columns": COLUMNS, "rows": [["T"]]}, "one value for each"),
    ({"columns": COLUMNS, "rows": [], "extra": 1}, "exactly columns and rows"),
])
def test_a_table_over_a_cap_or_out_of_its_form_is_refused_with_exit_2_before_any_call(out, table, why):
    before = len(out.fake.requests)
    code, _, said = out.create_table(table=out.file("t.json", json.dumps(table)))
    assert code == 2 and why in said and len(out.fake.requests) == before


def test_more_than_100_select_options_is_refused():
    rows = [[f"r{i}", f"option-{i}"] for i in range(101)]
    with pytest.raises(nt.TableError, match="100 different select options"):
        nt.check({"columns": [{"name": "A", "type": "title"}, {"name": "B", "type": "select"}], "rows": rows})


def test_the_token_that_writes_is_notion_token_and_the_sources_token_is_never_used(out):
    other = out.fake.token
    code, _, said = out.create_table(env={"NOTION_TOKEN": "", "NOTION_SOURCES_TOKEN": other})
    assert code == 3 and "NOTION_TOKEN" in said and not out.sent(), said
    assert "NOTION_SOURCES_TOKEN" not in SCRIPT.read_text(encoding="utf-8").split("def cmd_table_read")[1].split("VERBS = ")[0]
    assert out.fake.token not in out.create_table()[2]


def test_the_caps_of_the_provider_and_of_the_runtime_are_the_same_numbers():
    sys.path.insert(0, str(HERE.parents[2] / "runtime"))
    spec = importlib.util.spec_from_file_location("table_data_for_the_caps", HERE.parents[2] / "runtime" / "table_data.py")
    td = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(td)
    for name in ("ROWS_MAX", "COLUMNS_MAX", "CELL_MAX", "NAME_MAX", "SELECT_MAX", "OPTIONS_MAX", "TYPES"):
        assert getattr(td, name) == getattr(nt, name), name
    assert td.TABLE_BYTES_MAX == nt.BYTES_MAX


def test_the_requests_use_the_one_api_version_and_the_endpoints_of_the_table(out):
    out.create_table()
    paths = {(m, re.sub(r"[0-9a-f-]{32,36}", "{id}", p)) for m, p, _ in out.fake.requests}
    assert {("POST", "/v1/databases"), ("GET", "/v1/data_sources/{id}"), ("POST", "/v1/pages")} <= paths
