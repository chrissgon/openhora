"""Tests of the mirror of documents with the documents platform (runtime/documents.py), in run_next and in `sync`:
the local provider on a temporary folder, the stand-in tree and adapter (standin_tree.py), two stand-in skills with
their manifests (demo-asks writes docs/business/market.md, editable, with a checker that fails on a marker line;
demo-writes writes docs/business/icp.md, read_only), no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_documents_mirror.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
docs = st.load("documents")

MARKET = "docs/business/market.md"
ICP = "docs/business/icp.md"
CHECKER = '''import os, sys
path = sys.argv[sys.argv.index("--file") + 1]
log = sys.argv[sys.argv.index("--log") + 1] if "--log" in sys.argv else None
if log:
    with open(log, "a") as f:
        # where it ran, then which planted variables of the runtime's environment it saw (the checker is isolated)
        f.write(os.getcwd() + "\\n" + ",".join(sorted(k for k in os.environ if "PLANTED" in k)) + "\\n")
with open("checker-was-here", "w") as f:
    f.write("x")
with open(path, encoding="utf-8") as f:
    text = f.read()
if any(line.strip() == "BROKEN" for line in text.splitlines()):
    print("a marker line BROKEN is in the document")
    sys.exit(1)
'''


def manifest(tree, skill, documents):
    path = tree / "skills" / skill / "evals" / "runtime-manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["documents"] = documents
    path.write_text(json.dumps(data), encoding="utf-8")


def configure(built, documents):
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["documents"] = documents
    path.write_text(json.dumps(cfg), encoding="utf-8")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    folder = built["tree"] / "providers" / "documents"
    folder.mkdir(parents=True)
    shutil.copyfile(st.REPO / "providers" / "documents" / "local.py", folder / "local.py")
    (built["tree"] / "skills" / "demo-asks" / "scripts" / "check_doc.py").write_text(CHECKER, encoding="utf-8")
    log = tmp_path / "check-log.txt"
    manifest(built["tree"], "demo-asks", [{"path": MARKET, "checks": [["check_doc.py", "--file", "{path}", "--log", str(log)]],
                                           "platform": "editable", "bound_to_approval": False}])
    pages = tmp_path / "pages"
    pages.mkdir()
    configure(built, {"provider": "local", "dir": str(pages)})
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setenv("WB_PLANTED_SECRET", "planted")  # in the runtime's environment, never in the checker's
    calls = []
    real = docs.call

    def counted(cfg, root, verb, args, timeout=docs.TIMEOUT):
        calls.append(verb)
        return real(cfg, root, verb, args, timeout)

    monkeypatch.setattr(docs, "call", counted)
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return {**built, "pages": pages, "calls": calls, "log": log, "real_call": real}


def project_of(tree) -> str:
    return str(tree["project"])


def page(tree, rel=MARKET):
    return tree["pages"] / rel


def project_file(tree, rel=MARKET):
    return tree["project"] / rel


def record(tree, rel=MARKET):
    ctx = ops_core.context(project_of(tree))
    return ctx["store"].document_get(ctx["conn"], rel)


def delivered(tree) -> dict:
    """The demo request: the market task asks, is answered, and writes docs/business/market.md. Returns the
    run_next result of the run that wrote it."""
    project = project_of(tree)
    ops.request(project, "Find the first market.", flow="demo")
    asked = ops.run_next(project)
    assert asked["ending"] == "question"
    ops.answer(project, asked["pending_id"], "Clinics in Portugal.")
    out = ops.run_next(project)
    assert out["ending"] == "done" and project_file(tree).is_file()
    return out


def edit_page(tree, old, new, rel=MARKET):
    text = page(tree, rel).read_text(encoding="utf-8")
    assert old in text, (old, text)
    page(tree, rel).write_text(text.replace(old, new, 1), encoding="utf-8")


def task_state(tree, key) -> str:
    return next(t["state"] for t in ops.status(project_of(tree))["requests"][0]["tasks"] if t["key"] == key)


def test_a_document_a_run_returned_is_written_to_the_platform_once(tree):
    out = delivered(tree)
    assert out["documents"]["pushed"] == [MARKET] and out["documents"]["failed"] == []
    assert page(tree).read_bytes() == project_file(tree).read_bytes()
    assert tree["calls"].count("write") == 1
    assert record(tree)["status"] == "mirrored" and record(tree)["remote_id"] == MARKET
    again = ops.sync(project_of(tree))["documents"]
    assert again["pushed"] == [] and tree["calls"].count("write") == 1


def test_a_run_that_changed_nothing_writes_nothing(tree):
    project = project_of(tree)
    ops.request(project, "Find the first market.", flow="demo")
    asked = ops.run_next(project)
    assert asked["ending"] == "question" and asked["documents"]["pushed"] == []
    assert "write" not in tree["calls"] and list(tree["pages"].iterdir()) == []
    assert ops.status(project)["documents"] == []


def test_a_page_that_did_not_change_is_never_read(tree):
    delivered(tree)
    tree["calls"].clear()
    out = ops.sync(project_of(tree))["documents"]
    assert tree["calls"] == ["stat", "comments"]  # the page's own comments are listed, the page is not read
    assert out["imported"] == [] and out["pushed"] == [] and out["comments"] == 0


def test_a_comment_added_on_an_unchanged_page_is_saved_by_the_next_pull(tree):
    # WP-3.15: on the live service a comment does not move the page's version (N3), and the local provider's version
    # covers the document only, so the page is not read; its comments are listed at every pull all the same.
    delivered(tree)
    project = project_of(tree)
    version = record(tree)["remote_version"]
    (tree["pages"] / (MARKET + ".comments.md")).write_text("- Name the city.\n", encoding="utf-8")
    tree["calls"].clear()
    out = ops.sync(project)["documents"]
    assert tree["calls"] == ["stat", "comments"] and out["comments"] == 1 and out["imported"] == []
    assert record(tree)["remote_version"] == version
    ctx = ops_core.context(project)
    assert [c["text"] for c in ctx["store"].comments_list(ctx["conn"], document_path=MARKET)] == ["Name the city."]
    assert ops.sync(project)["documents"]["comments"] == 0  # saved once
    tree["calls"].clear()  # the pull run_next makes before a claim lists them too
    (tree["pages"] / (MARKET + ".comments.md")).write_text("- Name the city.\n- And the year.\n", encoding="utf-8")
    assert ops.run_next(project)["documents"]["comments"] == 1 and tree["calls"][:2] == ["stat", "comments"]


def test_a_persons_edit_replaces_the_whole_project_document_and_the_next_task_reads_it(tree):
    review = delivered(tree)
    edited = "# Market analysis\n\nDental clinics in Lisbon first.\n\n- Owner: demo-asks\n- Status: draft\n"
    page(tree).write_text(edited, encoding="utf-8")
    ops.release(project_of(tree), review["pending_id"])
    out = ops.run_next(project_of(tree))
    assert out["skill"] == "demo-writes" and out["documents"]["imported"] == [MARKET]
    assert project_file(tree).read_text(encoding="utf-8") == edited
    seen = (Path(out["run_dir"]) / "cwd" / MARKET).read_text(encoding="utf-8")
    assert "Dental clinics in Lisbon first." in seen


def test_an_imported_edit_is_named_once_to_the_next_run_of_a_task_that_reads_it(tree):
    review = delivered(tree)
    project = project_of(tree)
    line = ops.EDITED_LINE.format(path=MARKET)
    assert line == f"The person edited {MARKET} on the platform since the last run; its content is theirs."
    prompt = lambda out: (Path(out["run_dir"]) / "prompt.md").read_text(encoding="utf-8")
    assert line not in prompt(review)  # the run that wrote the document itself
    edit_page(tree, "- Status: draft", "- Status: draft\n\nStart with dental clinics.")
    assert ops.sync(project)["documents"]["imported"] == [MARKET]
    # A task whose skill does not list the document among its inputs is not told, though the document is in its copy.
    ops.request(project, "Find a second market.", flow="demo")
    other = ops.run_next(project)
    assert other["skill"] == "demo-asks" and (Path(other["run_dir"]) / "cwd" / MARKET).is_file()
    assert line not in prompt(other)
    # The next run of a task that reads it is told, in one line, before the answers.
    ops.release(project, review["pending_id"])
    reads = ops.run_next(project)
    assert reads["skill"] == "demo-writes" and prompt(reads).count(line) == 1
    placed = ops.task_prompt("Find the market.", "choose.", [{"body": "Which?", "answer": "This."}], edited=[MARKET])
    assert placed.index(line) < placed.index("In an earlier run of this task")  # next to the answers
    # Not twice: the import came before this task's last run.
    ops.answer(project, reads["pending_id"], "Name the clinics' size too.")
    again = ops.run_next(project)
    assert again["skill"] == "demo-writes" and "the user's answer" in prompt(again) and line not in prompt(again)
    # Only code writes it: a run's own text never makes the line, and a document changed after the import is no
    # longer the person's text.
    assert docs.imported_since(ops_core.context(project)["cfg"], None) == [MARKET]
    project_file(tree).write_text("# Market analysis\n\nRewritten.\n", encoding="utf-8")
    assert docs.imported_since(ops_core.context(project)["cfg"], None) == []


def test_an_imported_edit_is_not_written_back(tree):
    delivered(tree)
    edit_page(tree, "- Status: draft", "- Status: draft\n\nStart with dental clinics.")
    tree["calls"].clear()
    out = ops.sync(project_of(tree))["documents"]
    assert out["imported"] == [MARKET] and out["pushed"] == [] and "write" not in tree["calls"]
    got = record(tree)
    assert got["written_sha256"] == got["read_sha256"] == docs._sha(project_file(tree).read_bytes())
    tree["calls"].clear()
    assert ops.sync(project_of(tree))["documents"]["pushed"] == [] and tree["calls"] == ["stat", "comments"]


def test_an_edit_that_breaks_the_skills_checker_is_not_taken_and_the_person_gets_the_reason(tree):
    delivered(tree)
    before = project_file(tree).read_bytes()
    edit_page(tree, "- Status: draft", "- Status: draft\nBROKEN")
    out = ops.sync(project_of(tree))["documents"]
    assert [r["path"] for r in out["rejected"]] == [MARKET] and "marker line BROKEN" in out["rejected"][0]["note"]
    assert out["imported"] == [] and project_file(tree).read_bytes() == before
    shown = ops.status(project_of(tree))["documents"]
    assert shown[0]["path"] == MARKET and shown[0]["status"] == "rejected" and "BROKEN" in shown[0]["note"]
    edit_page(tree, "BROKEN", "Fixed on the page.")
    fixed = ops.sync(project_of(tree))["documents"]
    assert fixed["imported"] == [MARKET] and record(tree)["status"] == "mirrored"


def test_a_task_that_reads_a_rejected_document_does_not_start(tree):
    review = delivered(tree)
    project = project_of(tree)
    ops.release(project, review["pending_id"])
    edit_page(tree, "- Status: draft", "- Status: draft\nBROKEN")
    calls = len(st.calls(tree["adapter"]))
    out = ops.run_next(project)
    assert out["ran"] is None and out["reason"] == "a document was edited on the platform and was not taken"
    assert [d["path"] for d in out["documents"]] == [MARKET] and "BROKEN" in out["documents"][0]["note"]
    assert task_state(tree, "profile") == "ready" and len(st.calls(tree["adapter"])) == calls
    settled = ops.sync(project, take="project", path=MARKET)["documents"]
    assert settled["pushed"] == [MARKET] and page(tree).read_bytes() == project_file(tree).read_bytes()
    assert list((tree["data"] / "documents" / "not-taken" / "docs" / "business").iterdir())
    assert ops.run_next(project)["skill"] == "demo-writes"


def test_open_comments_are_saved_before_the_page_is_replaced(tree):
    review = delivered(tree)
    project = project_of(tree)
    (tree["pages"] / (MARKET + ".comments.md")).write_text("- Name the city.\n", encoding="utf-8")
    project_file(tree).write_text("# Market analysis\n\nA new draft.\n", encoding="utf-8")
    ctx = ops_core.context(project)
    tree["calls"].clear()
    out = docs.push(ctx, [MARKET])
    assert out["pushed"] == [MARKET] and out["comments"] == 1
    assert tree["calls"].index("read") < tree["calls"].index("write")
    saved = ctx["store"].comments_list(ctx["conn"], document_path=MARKET)
    assert [c["text"] for c in saved] == ["Name the city."]
    answered = ops.answer(project, review["pending_id"], "Narrow it.", with_comments=True)
    assert answered["comments"] == [saved[0]["id"]]
    assert ops.pending(project, review["pending_id"])["answer"].endswith(
        "Comments left on the platform:\n- unknown: Name the city.")


def test_a_document_both_sides_changed_is_overwritten_on_neither_side_until_the_person_takes_one(tree):
    delivered(tree)
    project = project_of(tree)
    edit_page(tree, "- Status: draft", "- Status: draft\n\nEdited on the page.")
    project_file(tree).write_text("# Market analysis\n\nEdited in the project.\n", encoding="utf-8")
    on_page, in_project = page(tree).read_bytes(), project_file(tree).read_bytes()
    for _ in range(2):
        out = ops.sync(project)["documents"]
        assert out["conflicts"] == [MARKET] and out["imported"] == [] and out["pushed"] == []
        assert page(tree).read_bytes() == on_page and project_file(tree).read_bytes() == in_project
        assert (record(tree)["status"], record(tree)["note"]) == ("rejected", "both changed")
    taken = ops.sync(project, take="page", path=MARKET)["documents"]
    assert taken["imported"] == [MARKET] and project_file(tree).read_bytes() == on_page
    assert record(tree)["status"] == "mirrored"
    with pytest.raises(ops.OpsError):
        ops.sync(project, take="page", path=MARKET)  # nothing is left to settle


def profiled(tree) -> str:
    """The demo request up to the read_only document: demo-writes writes docs/business/icp.md and pushes it."""
    review = delivered(tree)
    project = project_of(tree)
    ops.release(project, review["pending_id"])
    profile = ops.run_next(project)
    assert profile["documents"]["pushed"] == [ICP] and record(tree, ICP)["status"] == "read_only"
    return project


def notice_lines(tree, rel=ICP) -> list:
    return [line for line in page(tree, rel).read_text(encoding="utf-8").splitlines() if line.startswith("> [notice] ")]


def test_a_read_only_page_edited_after_the_last_write_is_not_overwritten_and_is_rejected(tree):
    # WP-3.21 (replaces test_an_edit_of_a_read_only_type_is_kept_aside_and_the_page_is_written_again): the edit is
    # still kept aside and never imported, and the page is no longer written over.
    project = profiled(tree)
    written = project_file(tree, ICP).read_bytes()
    edit_page(tree, "- Status: hypothesis", "- Status: confirmed", rel=ICP)
    on_page = page(tree, ICP).read_bytes()
    out = ops.sync(project)["documents"]
    assert out["rejected"] == [{"path": ICP, "note": docs.READ_ONLY_CHANGED}]
    assert out["pushed"] == [] and out["imported"] == [] and out["not_taken"] == []
    assert project_file(tree, ICP).read_bytes() == written and page(tree, ICP).read_bytes() == on_page
    kept = list((tree["data"] / "documents" / "not-taken" / "docs" / "business").glob("icp.md.*.md"))
    assert len(kept) == 1 and "- Status: confirmed" in kept[0].read_text(encoding="utf-8")
    assert (record(tree, ICP)["status"], record(tree, ICP)["note"]) == ("rejected", docs.READ_ONLY_CHANGED)
    shown = next(d for d in ops.status(project)["documents"] if d["path"] == ICP)
    assert shown["status"] == "rejected" and "read-only on the platform" in shown["note"]
    # The file changes in the project too: still not written over the page, by a sync or by a direct push.
    project_file(tree, ICP).write_text("# ICP\n\nA new profile from the project.\n", encoding="utf-8")
    tree["calls"].clear()
    assert ops.sync(project)["documents"]["pushed"] == [] and "write" not in tree["calls"]
    assert docs.push(ops_core.context(project), [ICP])["pushed"] == [] and page(tree, ICP).read_bytes() == on_page
    # A push that meets the edit itself (no pull before it) refuses as well.
    other = profiled_again(tree, project)
    assert other["rejected"] == [{"path": ICP, "note": docs.READ_ONLY_CHANGED}] and other["pushed"] == []


def profiled_again(tree, project) -> dict:
    """Take the project's side, edit the page again, change the file, and push without a pull first."""
    ops.sync(project, take="project", path=ICP)
    edit_page(tree, "A new profile from the project.", "Edited on the page again.", rel=ICP)
    project_file(tree, ICP).write_text("# ICP\n\nAnother profile.\n", encoding="utf-8")
    on_page = page(tree, ICP).read_bytes()
    out = docs.push(ops_core.context(project), [ICP])
    assert page(tree, ICP).read_bytes() == on_page
    return out


def test_take_page_keeps_a_read_only_page_and_the_file_is_not_mirrored_until_it_changes_again(tree):
    project = profiled(tree)
    written = project_file(tree, ICP).read_bytes()
    edit_page(tree, "- Status: hypothesis", "- Status: confirmed", rel=ICP)
    on_page = page(tree, ICP).read_bytes()
    assert ops.sync(project)["documents"]["rejected"]
    taken = ops.sync(project, take="page", path=ICP)["documents"]
    assert taken["not_taken"] == [ICP] and taken["imported"] == [] and taken["pushed"] == []
    assert project_file(tree, ICP).read_bytes() == written and page(tree, ICP).read_bytes() == on_page
    assert (record(tree, ICP)["status"], record(tree, ICP)["note"]) == ("read_only", docs.KEPT_AS_IS)
    for _ in range(2):  # nothing is written while the file is unchanged
        tree["calls"].clear()
        out = ops.sync(project)["documents"]
        assert out["pushed"] == [] and out["rejected"] == [] and "write" not in tree["calls"]
        assert page(tree, ICP).read_bytes() == on_page
    project_file(tree, ICP).write_text("# ICP\n\nThe profile, rewritten in the project.\n", encoding="utf-8")
    out = ops.sync(project)["documents"]
    assert out["pushed"] == [ICP] and "rewritten in the project" in page(tree, ICP).read_text(encoding="utf-8")
    assert (record(tree, ICP)["status"], record(tree, ICP)["note"]) == ("read_only", None)
    with pytest.raises(ops.OpsError):
        ops.sync(project, take="page", path=ICP)  # nothing is left to settle


def test_take_project_writes_the_file_over_a_read_only_page(tree):
    project = profiled(tree)
    written = project_file(tree, ICP).read_bytes()
    edit_page(tree, "- Status: hypothesis", "- Status: confirmed", rel=ICP)
    assert ops.sync(project)["documents"]["rejected"]
    taken = ops.sync(project, take="project", path=ICP)["documents"]
    assert taken["pushed"] == [ICP] and taken["not_taken"] == [ICP]
    got = ops_core.context(project)
    read = docs.call(got["cfg"], got["root"], "read", ["--id", ICP])
    assert read["markdown"].encode("utf-8") == written and read["notice"] == docs.NOTICE
    assert (record(tree, ICP)["status"], record(tree, ICP)["note"]) == ("read_only", None)
    kept = list((tree["data"] / "documents" / "not-taken" / "docs" / "business").glob("icp.md.*.md"))
    assert any("- Status: confirmed" in k.read_text(encoding="utf-8") for k in kept)
    assert ops.sync(project)["documents"]["rejected"] == []


def test_a_read_only_page_carries_the_notice_once_and_an_editable_page_never(tree):
    project = profiled(tree)
    assert notice_lines(tree) == ["> [notice] " + docs.NOTICE]
    assert page(tree, ICP).read_text(encoding="utf-8").startswith("> [notice] ")
    assert notice_lines(tree, MARKET) == []
    # Never counted as a change of the page, never imported: syncs read nothing new and write nothing.
    for _ in range(2):
        out = ops.sync(project)["documents"]
        assert out["imported"] == [] and out["rejected"] == [] and out["pushed"] == [] and out["notices"] == []
    assert "[notice]" not in project_file(tree, ICP).read_text(encoding="utf-8")
    # A page that has none (made before WP-3.21, or a person removed it) gets it once, with nothing else touched.
    text = page(tree, ICP).read_text(encoding="utf-8")
    body = text.split("\n", 2)[2]
    page(tree, ICP).write_text(body, encoding="utf-8")
    first = ops.sync(project)["documents"]  # the pull sees the page without it: same text, not a change
    assert first["rejected"] == [] and first["imported"] == []
    assert first["notices"] == [ICP] and notice_lines(tree) == ["> [notice] " + docs.NOTICE]
    assert page(tree, ICP).read_text(encoding="utf-8") == text
    tree["calls"].clear()
    again = ops.sync(project)["documents"]  # the version the notice moved is read once and recorded
    assert again["notices"] == [] and again["rejected"] == [] and "write" not in tree["calls"]
    assert "notice" not in tree["calls"]
    tree["calls"].clear()
    assert ops.sync(project)["documents"]["notices"] == [] and tree["calls"].count("read") == 0
    # A new write of the file keeps exactly one notice, first.
    project_file(tree, ICP).write_text("# ICP\n\nA second profile.\n", encoding="utf-8")
    assert ops.sync(project)["documents"]["pushed"] == [ICP]
    assert notice_lines(tree) == ["> [notice] " + docs.NOTICE] and notice_lines(tree, MARKET) == []
    assert page(tree, ICP).read_text(encoding="utf-8").startswith("> [notice] ")


def test_an_unchanged_read_only_page_is_written_as_before(tree):
    project = profiled(tree)
    project_file(tree, ICP).write_text("# ICP\n\nA profile written by a later run.\n", encoding="utf-8")
    tree["calls"].clear()
    out = ops.sync(project)["documents"]
    assert out["pushed"] == [ICP] and out["rejected"] == [] and out["not_taken"] == []
    assert tree["calls"].count("write") == 1
    assert page(tree, ICP).read_text(encoding="utf-8") == (
        "> [notice] " + docs.NOTICE + "\n\n" + project_file(tree, ICP).read_text(encoding="utf-8"))
    got = record(tree, ICP)
    assert got["status"] == "read_only" and got["written_sha256"] == docs._sha(project_file(tree, ICP).read_bytes())
    tree["calls"].clear()
    assert ops.sync(project)["documents"]["pushed"] == [] and "write" not in tree["calls"]


def test_a_document_no_manifest_lists_is_never_sent(tree):
    delivered(tree)
    (tree["project"] / "docs" / "business" / "notes.md").write_text("# Notes\n", encoding="utf-8")
    out = ops.sync(project_of(tree))["documents"]
    assert out["pushed"] == []
    assert sorted(p.name for p in (tree["pages"] / "docs" / "business").iterdir()) == ["market.md"]
    root = str(tree["tree"])
    for rel in ("docs/business/notes.md", "docs/workbench/state.md", "docs/business/market.lint.json"):
        assert docs.entry_for(root, rel) is None
    manifest(tree["tree"], "demo-asks", [{"path": MARKET, "checks": [], "platform": "editable", "bound_to_approval": True}])
    assert docs.entry_for(root, MARKET) is None


def test_a_platform_that_cannot_be_read_stops_the_run_before_it_starts(tree):
    review = delivered(tree)
    project = project_of(tree)
    ops.release(project, review["pending_id"])
    tree["pages"].rename(tree["pages"].with_name("pages-gone"))
    calls = len(st.calls(tree["adapter"]))
    out = ops.run_next(project)
    assert out["ran"] is None and out["reason"] == "the documents platform could not be read"
    assert task_state(tree, "profile") == "ready" and len(st.calls(tree["adapter"])) == calls
    tree["pages"].with_name("pages-gone").rename(tree["pages"])
    assert ops.run_next(project)["skill"] == "demo-writes"


def test_a_failed_write_fails_no_task_and_is_tried_again_at_the_next_sync(tree, monkeypatch):
    failed = []

    def once(cfg, root, verb, args, timeout=docs.TIMEOUT):
        tree["calls"].append(verb)
        if verb == "write" and not failed:
            failed.append(verb)
            raise docs.DocumentsError("failed", "the platform is down")
        return tree["real_call"](cfg, root, verb, args, timeout)

    monkeypatch.setattr(docs, "call", once)
    out = delivered(tree)
    assert out["task_state"] == "waiting" and out["pending_id"] is not None
    assert [f["path"] for f in out["documents"]["failed"]] == [MARKET] and out["documents"]["pushed"] == []
    assert record(tree) is None and not page(tree).exists()
    assert ops.sync(project_of(tree))["documents"]["pushed"] == [MARKET]
    assert page(tree).read_bytes() == project_file(tree).read_bytes()


def test_the_checker_runs_on_a_scratch_copy_and_never_on_the_project(tree):
    delivered(tree)
    edit_page(tree, "- Status: draft", "- Status: draft\n\nChecked on a copy.")
    assert ops.sync(project_of(tree))["documents"]["imported"] == [MARKET]
    written = tree["log"].read_text().split("\n")[:-1]
    ran_in, saw = written[0::2], written[1::2]
    assert len(ran_in) == 1
    assert saw == [""], "the checker saw a variable of the runtime's environment"
    assert ran_in[0] != str(tree["project"]) and not ran_in[0].startswith(str(tree["project"]))
    assert not Path(ran_in[0]).exists()  # the scratch folder is removed
    assert not list(tree["project"].rglob("checker-was-here"))
