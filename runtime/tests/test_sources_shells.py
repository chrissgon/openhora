"""The shells of the ingest operations (P4): which channel may call which of the five rows, the group `sources` that a project's
policy turns on, the terminal's verbs, the page's routes (the upload follows the existing file route and hands the operation a
path the service made) and the MCP tool. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sources_shells.py
"""
from __future__ import annotations

import base64
import json
import os

import pytest

import standin_tree as st
from sources_fixture import standin_convert, with_sources

ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
cli = st.load("cli")
service = st.load("service")
mcp = st.load("mcp")
sources = st.load("sources")

WRITES = ("source-add", "source-import", "source-refresh", "source-describe")


def test_the_writes_are_for_the_terminal_and_the_page_and_the_catalog_read_is_also_for_the_mcp_mode_and_the_messaging_channel():
    for name in WRITES:
        row = operations.by_name(name)
        assert row["channels"] == ("terminal", "page") and row["model"] is False and "job" not in row, name
    row = operations.by_name("sources")
    assert row["channels"] == ("terminal", "page", "mcp", "messaging") and row["args"] == ()
    assert [r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"]].count("sources") == 1
    assert not [r["name"] for r in operations.OPERATIONS if r["name"] in WRITES and ("mcp" in r["channels"] or "messaging" in r["channels"])]
    assert operations.GROUPS["sources"]["operations"] == WRITES + ("sources",) and operations.GROUPS["sources"]["kind"] is None


def test_a_project_turns_the_catalog_on_for_a_channel_with_the_group_sources_and_no_channel_but_the_terminal_and_the_page_can_write():
    assert operations.permitted("sources", "messaging", None) is False, "the default policy of messaging is read, talk, answer"
    assert operations.permitted("sources", "messaging", {"messaging": ["read", "sources"]}) is True
    assert operations.permitted("sources", "page", {"page": ["read"]}) is False and operations.permitted("sources", "page", {"page": ["read", "sources"]}) is True
    assert operations.permitted("sources", "page", None) is True and operations.permitted("sources", "terminal", {"terminal": []}) is True
    for name in WRITES:
        assert operations.permitted(name, "messaging", {"messaging": ["sources"]}) is False, "the ceiling: messaging reads only"
        assert operations.permitted(name, "mcp", {"mcp": ["read", "sources"]}) is False
        assert operations.permitted(name, "page", {"page": ["read"]}) is False and operations.permitted(name, "page", {"page": ["read", "sources"]}) is True
    assert operations.refusal("source-import", "page", {"page": ["read"]}) == operations.not_enabled("source-import", "page")
    assert "sources" in operations.permissions("page", None) and "source-import" in operations.permissions("page", {"page": ["read", "sources"]})
    assert "source-import" not in operations.permissions("page", {"page": ["read"]})


def test_the_terminal_has_a_verb_for_each_and_reads_their_flags():
    parser = cli.build_parser()
    got = parser.parse_args(["source-add", "--project", "/p", "--source", "survey", "--type", "notion", "--origin", "https://www.notion.so/x", "--description", "d"])
    assert (got.command, got.f_source, got.f_type, got.f_origin, got.f_description) == ("source-add", "survey", "notion", "https://www.notion.so/x", "d")
    got = parser.parse_args(["source-import", "--project", "/p", "--source", "survey", "--file", "/tmp/a.csv"])
    assert got.f_file == "/tmp/a.csv" and got.f_url is None
    got = parser.parse_args(["source-refresh", "--project", "/p", "--source", "survey"])
    assert got.f_file is None
    with pytest.raises(cli.Usage):
        parser.parse_args(["source-add", "--project", "/p", "--source", "x", "--type", "drive", "--origin", "x"])
    for verb in WRITES + ("sources",):
        assert verb in operations.terminal_verbs() and verb in cli.__doc__
    assert operations.command_line("source-import", "/p", checkout=None, source_id="survey", file="/tmp/a b.csv") == \
        "python3 runtime/cli.py source-import --project /p --source survey --file '/tmp/a b.csv'"


def test_the_pages_routes_bind_the_source_id_from_the_path_and_the_upload_hands_the_operation_a_file_the_service_made(tmp_path):
    found = {(r["method"], r["pattern"]): r for r in service.ROUTES if r["op"] in WRITES + ("sources",)}
    assert set(found) == {("GET", "/projects/{p}/sources"), ("POST", "/projects/{p}/sources"), ("POST", "/projects/{p}/sources/{name}/files"),
                          ("POST", "/projects/{p}/sources/{name}/import"), ("POST", "/projects/{p}/sources/{name}/refresh"),
                          ("POST", "/projects/{p}/sources/{name}/refresh/files"), ("POST", "/projects/{p}/sources/{name}/description")}
    project = "0123456789ab"
    route, params = service.match("POST", f"{service.PREFIX}/projects/{project}/sources/survey/files")
    assert route["upload"] is True and route["op"] == "source-import" and params["name"] == "survey" and route["limit"] == service.FILE_LIMIT
    assert service.match("POST", f"{service.PREFIX}/projects/{project}/sources/Bad%20Id/files") is None
    row = operations.by_name("source-import")
    assert service.arguments(row, route, params, {}, False) == {"source_id": "survey"}
    route, params = service.match("POST", f"{service.PREFIX}/projects/{project}/sources/survey/import")
    assert service.arguments(row, route, params, {"url": "https://www.notion.so/x", "description": "d"}, False) == {
        "source_id": "survey", "url": "https://www.notion.so/x", "description": "d"}
    with pytest.raises(service.Usage):
        service.arguments(row, route, params, {"file": "/etc/passwd"}, False)   # a request never supplies the path
    route, params = service.match("POST", f"{service.PREFIX}/projects/{project}/sources")
    assert service.arguments(operations.by_name("source-add"), route, params,
                             {"source_id": "survey", "source_type": "file", "origin": "survey.csv"}, False) == {
        "source_id": "survey", "source_type": "file", "origin": "survey.csv"}
    with pytest.raises(service.Usage):
        service.arguments(operations.by_name("source-add"), route, params, {"source_id": "survey"}, False)


def test_a_file_uploaded_on_the_page_is_imported_through_the_same_operation_and_the_upload_folder_is_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True)
    config = with_sources({"workbench": str(st.REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite")}, tmp_path)
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps(config), encoding="utf-8")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    seen = {}
    real = ops.source_import

    def spy(project_path, source_id, file=None, **kwargs):
        seen["file"] = file
        seen["existed"] = os.path.isfile(file)
        return real(project_path, source_id, file=file, **kwargs)
    monkeypatch.setattr(ops, "source_import", spy)
    svc = service.Service(ops, [{"id": "0123456789ab", "name": "p", "path": path, "data_dir": config["data_dir"]}], "t" * 40, 8765)
    row = operations.by_name("source-import")
    route, params = service.match("POST", f"{service.PREFIX}/projects/0123456789ab/sources/survey/files")
    body = {"name": "survey.csv", "content_base64": base64.b64encode(b"name,price\napple,1\npear,2\n").decode()}
    status, headers, data = service._upload(svc, svc.by_id["0123456789ab"], row, route, params, body)
    answer = json.loads(data)
    assert status == 200 and answer["imported"] and answer["version"] == 1 and seen["existed"] and seen["file"].endswith("/survey.csv")
    assert not os.path.exists(os.path.dirname(seen["file"])), "the uploaded file's folder is removed whatever the operation answered"
    assert os.path.isfile(os.path.join(config["sources_dir"], "survey", "1", "converted.csv"))


def test_the_mcp_mode_offers_the_catalog_and_no_write():
    names = [r["name"] for r in operations.OPERATIONS if "mcp" in r["channels"]]
    assert "sources" in names and not set(WRITES) & set(names)
