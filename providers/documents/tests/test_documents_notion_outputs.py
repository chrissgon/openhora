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
        ["Candles", None, 8, "2026-11-02T09:30:00+02:00", "craft", False, None],
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
        {"Stall": "Candles", "Notes": "", "Fee": 8, "Opens": "2026-11-02T09:30:00.000+02:00", "Kind": "craft", "Paid": False, "Site": None},
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
    ({"columns": COLUMNS, "rows": [["T", "x" * 2001, None, None, None, False, None]]}, "2000 UTF-16 code units"),
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


# --- review round: dates as instants, a scope that finds rows again, claims across keys, the trash, the units, the ledger -----------------


def test_a_row_with_a_date_time_whose_answer_was_lost_is_found_although_the_service_writes_the_moment_in_its_own_form(out):
    rows = [["Bread", None, None, "2026-11-02T09:30:00Z", None, False, None], ["Tea", None, None, "2026-11-03T10:00:00+02:00", None, False, None]]
    out.fake.fail_at("create_page", 1, 500, carried_out=True)
    assert out.create_table(table=out.table(rows=rows))[0] == 1
    source = out.source()
    assert out.fake.cells(out.fake.rows_of(source)[0])["Opens"] == "2026-11-02T09:30:00.000+00:00", "the stand-in writes it back as the service does"
    code, made, said = out.create_table(table=out.table(rows=rows))
    assert code == 0, said
    assert made["rows_created"] == 1 and len(out.fake.rows_of(source)) == 2


def test_a_date_time_with_no_zone_is_refused_before_any_call(out):
    rows = [["Bread", None, None, "2026-11-02T09:30:00", None, False, None]]
    before = len(out.fake.requests)
    code, _, said = out.create_table(table=out.table(rows=rows))
    assert code == 2 and "Z or an offset" in said and len(out.fake.requests) == before


def test_the_dates_compare_as_dates_and_as_moments():
    same = [("2026-11-02T09:30:00Z", "2026-11-02T09:30:00.000+00:00"), ("2026-11-02T11:30:00+02:00", "2026-11-02T09:30:00.000+00:00"),
            ("2026-11-02", "2026-11-02")]
    for a, b in same:
        assert nt.instant(a) == nt.instant(b), (a, b)
    assert nt.instant("2026-11-02T09:30:00Z") != nt.instant("2026-11-02T09:30:00+01:00")
    assert nt.instant("2026-11-02") != nt.instant("2026-11-02T00:00:00Z")
    assert nt.instant("2026-11-02T09:30:00") is None and nt.instant("soon") is None
    page = {"properties": {"D": {"type": "date", "date": {"start": "2026-11-02T09:30:00.000+00:00"}}, "T": {"type": "title", "title": []}}}
    assert nt.row_matches(page, [{"name": "D", "type": "date"}], ["2026-11-02T10:30:00+01:00"])
    assert not nt.row_matches(page, [{"name": "D", "type": "date"}], [None])


def test_rows_an_earlier_attempt_of_the_same_scope_wrote_are_found_again_under_another_key_and_not_written_twice(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    scope = ["--scope", "task-7"]
    out.fake.fail_at("create_page", 3, 500)           # rows 1 and 2 are written, the third fails and is of unknown outcome
    code, _, _ = out.run("rows-append", "--id", source, "--table-file", out.table(), "--idempotency-key", "k1", "--confirmed", *scope)
    assert code == 1 and len(out.fake.rows_of(source)) == 1 + 2
    code, state, said = out.run("rows-state", "--id", source, "--table-file", out.table(), "--scope", "task-7")
    assert code == 0 and state["rows_done"] == 2 and state["rows_pending"] == 1, said
    code, state, _ = out.run("rows-state", "--id", source, "--table-file", out.table(), "--scope", "task-8")
    assert state["rows_done"] == 0, "another scope finds nothing"
    code, done, said = out.run("rows-append", "--id", source, "--table-file", out.table(), "--idempotency-key", "k2", "--confirmed", *scope)
    assert code == 0, said
    assert done["rows_replayed"] == 2 and done["rows_created"] == 1, "two found, the third looked for in the table, not there, written"
    assert sorted(c["Stall"] for c in cells(out, source)) == ["Bread", "Bread", "Candles", "Tea"], "the seeded row, then the three once each"
    code, again, _ = out.run("rows-append", "--id", source, "--table-file", out.table(), "--idempotency-key", "k3", "--dry-run", *scope)
    assert again["would"]["rows_done"] == 3, "a later key of the same scope finds all three, now under k2"


def test_no_scope_means_no_reconciliation_across_keys(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    assert out.append(source, key="k1", table=out.table(rows=ROWS[:2]))[0] == 0
    code, done, _ = out.append(source, key="k2", table=out.table(rows=ROWS[:2]))
    assert done["rows_created"] == 2 and len(out.fake.rows_of(source)) == 1 + 2 + 2


def test_a_row_of_unknown_outcome_never_adopts_a_row_that_another_key_made(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    twin = out.table(rows=[["Bread", "Fresh at six", 12.5, "2026-11-01", "food", True, "https://bread.example/shop"]])
    assert out.append(source, key="ka", table=twin)[0] == 0                   # another key made the same row
    out.fake.fail_at("create_page", 1, 500)                                   # this key's attempt did not land
    assert out.append(source, key="kb", table=twin)[0] == 1
    code, done, said = out.append(source, key="kb", table=twin)
    assert code == 0 and done["rows_created"] == 1, said
    assert len([r for r in cells(out, source) if r["Stall"] == "Bread"]) == 3, "the seeded row, key ka's and key kb's: kb did not take ka's"


def test_a_page_the_person_put_in_the_trash_is_made_again_and_not_called_replayed(out):
    md = out.file("page.md", "Hello.\n")
    args = ("page-create", "--parent", out.parent, "--title", "Dead soon", "--markdown-file", md, "--idempotency-key", "p1", "--confirmed")
    first = out.run(*args)[1]
    out.fake.person_trashes(first["id"])
    code, again, said = out.run(*args)
    assert code == 0 and again["created"] is True and again["id"] != first["id"], said


def test_a_database_the_person_put_in_the_trash_is_made_again(out):
    first = out.create_table()[1]
    out.fake.databases[first["id"]]["in_trash"] = True
    code, again, said = out.create_table()
    assert code == 0 and again["created"] is True and again["id"] != first["id"] and again["rows_created"] == 3, said


def test_a_cell_is_counted_in_utf16_code_units(out):
    fits = [["x", "\U0001F600" * 1000, None, None, None, False, None]]
    over = [["x", "\U0001F600" * 1001, None, None, None, False, None]]
    assert out.create_table(mode="--dry-run", table=out.table(rows=fits))[0] == 0
    code, _, said = out.create_table(mode="--dry-run", table=out.table(rows=over))
    assert code == 2 and "2000 UTF-16 code units" in said


def test_stat_and_table_read_name_what_they_describe_and_table_read_lists_the_select_options(out):
    made = out.create_table()[1]
    read = out.read(made["data_source_id"])[1]
    assert read["name"] == "Market stalls" and read["select_options"] == {"Kind": ["food", "craft"]}
    code, seen, _ = out.run("stat", "--id", out.parent)
    assert code == 0 and seen["title"] == "Workbench" and seen["archived"] is False


def test_done_entries_of_the_outputs_older_than_ninety_days_are_dropped_when_the_ledger_is_next_saved(out):
    md = out.file("page.md", "Hello.\n")
    out.run("page-create", "--parent", out.parent, "--title", "Old", "--markdown-file", md, "--idempotency-key", "old", "--confirmed")
    ledger = out.harness.ledger
    data = json.loads(ledger.read_text(encoding="utf-8"))
    old = [k for k in data["entries"] if k.endswith("/old")]
    assert old and data["entries"][old[0]]["kind"] == "output"
    data["entries"][old[0]]["recorded_at"] = "2020-01-01T00:00:00Z"
    ledger.write_text(json.dumps(data), encoding="utf-8")
    out.run("page-create", "--parent", out.parent, "--title", "New", "--markdown-file", md, "--idempotency-key", "new", "--confirmed")
    kept = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    assert not any(k.endswith("/old") for k in kept) and any(k.endswith("/new") for k in kept)


# --- review round 2: a ledger the table must bear out, the lock of a key, the age of a key ----------------------------------------------------


def test_rows_state_counts_only_rows_the_table_still_lists_and_the_dry_run_says_it_reads_the_ledger_alone(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    scope = ["--scope", "task-9"]
    assert out.run("rows-append", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--idempotency-key", "k1", "--confirmed", *scope)[0] == 0
    gone = next(r for r in out.fake.rows_of(source) if out.fake.cells(r)["Stall"] == "Candles")
    out.fake.person_trashes(gone["id"])
    code, state, said = out.run("rows-state", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--scope", "task-9",
                                "--idempotency-key", "k1")
    assert code == 0 and state["verified"] is True and state["rows_done"] == 1 and state["rows_new"] == 1, said
    code, dry, _ = out.run("rows-append", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--idempotency-key", "k1", "--dry-run",
                           *scope)
    assert dry["would"]["rows_done"] == 2 and dry["would"]["verified"] is False


def test_a_row_the_person_trashed_is_written_again_and_one_still_there_is_not(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    assert out.append(source, key="k1", table=out.table(rows=ROWS[1:]))[0] == 0
    gone = next(r for r in out.fake.rows_of(source) if out.fake.cells(r)["Stall"] == "Candles")
    out.fake.person_trashes(gone["id"])
    code, done, said = out.append(source, key="k1", table=out.table(rows=ROWS[1:]))
    assert code == 0 and done["rows_created"] == 1 and done["rows_replayed"] == 1, said
    assert sorted(c["Stall"] for c in cells(out, source)) == ["Bread", "Candles", "Tea"]


def test_a_table_longer_than_the_listing_reads_is_refused_and_not_guessed_at(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    for _ in range(2001):
        out.fake.create_page({"type": "data_source_id", "data_source_id": source}, {})
    code, _, said = out.append(source, key="k1", table=out.table(rows=ROWS[1:]))
    assert code == 1 and "will not guess" in said and len(out.fake.rows_of(source)) == 2002 and out.creates() == 1, "only the seed row was written through the provider"
    code, _, said = out.run("rows-state", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--scope", "task-1")
    assert code == 1 and "will not guess" in said


def test_a_key_that_still_has_a_row_of_unknown_outcome_loses_none_of_its_done_rows_to_the_pruning(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    out.fake.fail_at("create_page", 2, 500)                    # row 1 done, row 2 of unknown outcome
    assert out.append(source, key="k1", table=out.table(rows=ROWS[1:]))[0] == 1
    ledger = out.harness.ledger
    data = json.loads(ledger.read_text(encoding="utf-8"))
    done = [k for k, e in data["entries"].items() if k.startswith(f"{source}/k1/") and e["status"] == "done"]
    assert done
    for k in done:
        data["entries"][k]["recorded_at"] = "2020-01-01T00:00:00Z"
    ledger.write_text(json.dumps(data), encoding="utf-8")
    md = out.file("page.md", "Hello.\n")
    out.run("page-create", "--parent", out.parent, "--title", "Other", "--markdown-file", md, "--idempotency-key", "other", "--confirmed")
    kept = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    assert all(k in kept for k in done), "the key has a pending row, so none of its done rows was dropped"
    code, finished, said = out.append(source, key="k1", table=out.table(rows=ROWS[1:]))
    assert code == 0 and finished["rows_replayed"] == 1 and len(cells(out, source)) == 3, said


def test_two_runs_of_the_same_key_do_not_write_together(out):
    import fcntl
    md = out.file("page.md", "Hello.\n")
    ledger = out.harness.ledger
    ledger.parent.mkdir(parents=True, exist_ok=True)
    digest = __import__("hashlib").sha256(f"key/{out.parent}/held".encode("utf-8")).hexdigest()[:24]
    lock = ledger.parent / f"{ledger.name}.{digest}.key.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        before = len(out.fake.requests)
        code, _, said = out.run("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "held",
                                "--confirmed")
        assert code == 1 and "another run of this provider is writing this key" in said and len(out.fake.requests) == before
        assert out.run("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "held",
                       "--dry-run")[0] == 0, "a dry run takes no lock"
    finally:
        os.close(fd)
    code, made, said = out.run("page-create", "--parent", out.parent, "--title", "T", "--markdown-file", md, "--idempotency-key", "held",
                               "--confirmed")
    assert code == 0 and made["created"] is True, said
    assert not list(ledger.parent.glob("*.key.lock")), "the lock file goes with the lock"


def test_a_date_time_at_the_edge_of_the_calendar_names_no_moment_and_matches_nothing():
    for text in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"):
        assert nt.instant(text) is None
    page = {"properties": {"D": {"type": "date", "date": {"start": "0001-01-01T00:00:00.000+01:00"}}}}
    assert nt.row_matches(page, [{"name": "D", "type": "date"}], ["0001-01-01T00:00:00+01:00"]) is False
    assert nt.instant("0001-01-01T00:00:00Z") is not None and nt.instant("9999-12-31T23:59:59Z") is not None


# --- review round 3: the lock of a scope, the pruning of a key made of a database and its rows -----------------------------------------------


def held_lock(out, identity):
    """Take the exclusive lock the provider takes for an identity, as an orphaned provider would hold it; returns the descriptor."""
    import fcntl
    ledger = out.harness.ledger
    ledger.parent.mkdir(parents=True, exist_ok=True)
    digest = __import__("hashlib").sha256(identity.encode("utf-8")).hexdigest()[:24]
    fd = os.open(ledger.parent / f"{ledger.name}.{digest}.key.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def test_the_lock_is_of_the_scope_so_a_new_key_of_the_same_task_waits_for_an_orphan_still_writing_under_the_old_one(out):
    source = out.create_table(key="k0", table=out.table(rows=ROWS[:1]))[1]["data_source_id"]
    fd = held_lock(out, "scope/task-7")
    try:
        before = len(out.fake.requests)
        code, _, said = out.run("rows-append", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--idempotency-key", "k2",
                                "--scope", "task-7", "--confirmed")
        assert code == 1 and "another run of this provider is writing this key now" in said and len(out.fake.requests) == before
        code, done, said = out.run("rows-append", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--idempotency-key", "k3",
                                   "--scope", "task-8", "--confirmed")
        assert code == 0, f"another task is not held back: {said}"
    finally:
        os.close(fd)
    code, done, said = out.run("rows-append", "--id", source, "--table-file", out.table(rows=ROWS[1:]), "--idempotency-key", "k2",
                               "--scope", "task-7", "--confirmed")
    assert code == 0, said


def test_a_database_with_a_pending_entry_keeps_the_done_rows_of_its_key_from_the_pruning(out):
    ledger = out.harness.ledger
    ledger.parent.mkdir(parents=True, exist_ok=True)
    old = "2020-01-01T00:00:00Z"
    source, parent = "a" * 32, out.parent
    ledger.write_text(json.dumps({"version": 1, "entries": {
        f"{parent}/kz": {"status": "pending", "kind": "output", "started_at": old},
        f"{source}/kz/row-0001": {"status": "done", "kind": "output", "id": "b" * 32, "recorded_at": old, "row_sha": "c" * 64},
        f"{source}/ky/row-0001": {"status": "done", "kind": "output", "id": "d" * 32, "recorded_at": old, "row_sha": "e" * 64}}}),
        encoding="utf-8")
    md = out.file("page.md", "Hello.\n")
    out.run("page-create", "--parent", out.parent, "--title", "Other", "--markdown-file", md, "--idempotency-key", "other", "--confirmed")
    kept = json.loads(ledger.read_text(encoding="utf-8"))["entries"]
    assert f"{source}/kz/row-0001" in kept, "a pending database of that key: its rows stay"
    assert f"{source}/ky/row-0001" not in kept, "a key with nothing pending is pruned"
