"""The pure half of the file writes (package W4a: runtime/files_document.py, the arguments of runtime/step_files.py, the read-only seams of
runtime/ops_step_seams.py): the effect document and every refusal of its form, the requests it derives and their equality with what each writer's dry run
prints, the key, the card lines, and the narrowness of the seams a step kind is given. No service is started except the writers' own `--dry-run`, which reads
no credential and opens no connection. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_files_document.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys

import pytest

import standin_tree as st

fd = st.load("files_document")
step_files = st.load("step_files")
steps = st.load("steps")
effects = st.load("effects")
phrases = st.load("phrases")
seams = st.load("ops_step_seams")
effect_files = st.load("effect_files")
project_config = st.load("project_config")

GDRIVE = st.REPO / "providers" / "writer" / "gdrive.py"
ONEDRIVE = st.REPO / "providers" / "writer" / "onedrive.py"
COMMON = st.REPO / "providers" / "writer" / "_files_common.py"
TEXT = "# CV 2026\n\nPat Example, engineer.\n"
READ_AT = "2026-10-18T14:30:00Z"
HEAD = "Rev_0001_stand_in"
MD5 = "0123456789abcdef0123456789abcdef"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def text_content(text=TEXT, media="text/markdown", **more):
    return fd.content_of("text", text.encode("utf-8"), media, text=text, **more)


def google_base(native=False):
    base = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime": fd.DOC_MIME if native else "text/markdown", "md5": None if native else MD5,
            "head_revision": None if native else HEAD, "source_version": "3@2026-10-10T09:00:00.000Z"}
    return base


def make(operation="create", account="google", **over):
    """A document of each shape, by name."""
    folder = {"kind": "folder", "label": "default", "id": "Folder_ID_01" if account == "google" else "01FOLDER0000!101"}
    parts = {"task_id": 7, "operation": operation, "account": account, "address": "pat@example.com", "target": folder, "name": "CV 2026.md",
             "content": text_content(), "base": None, "read_at": READ_AT}
    if operation == "replace":
        parts.update(target={"kind": "file", "label": "cv", "id": "File_ID_0001" if account == "google" else "b!FakeDrive_1/01FILE000001!102"}, name="CV 2026.md",
                     base=google_base() if account == "google" else {"etag": '"{A-1},3"', "ctag": '"c:{A-1},3"', "size": 9, "modified": "2026-10-10T09:00:00Z",
                                                                      "source_version": '"c:{A-1},3"'})
    if operation == "save":
        parts.update(name="Contract.pdf", content={"kind": "held", "bytes": 28, "sha256": sha(b"%PDF-1.4 the signed contract"), "media_type": "application/pdf",
                                                    "text": None, "path": None, "attachment": 5, "gdoc": False})
    parts.update(over)
    return fd.document(**parts)


VARIANTS = {
    "google create": lambda: make(),
    "google gdoc": lambda: make(name="CV 2026", content=text_content(gdoc=True)),
    "google save": lambda: make("save"),
    "google replace binary": lambda: make("replace"),
    "google replace native": lambda: make("replace", base=google_base(native=True), content=text_content()),
    "microsoft create id": lambda: make(account="microsoft"),
    "microsoft create path": lambda: make(account="microsoft", target={"kind": "folder", "label": "docs", "id": "/Documents/openhora"}),
    "microsoft save": lambda: make("save", account="microsoft"),
    "microsoft replace": lambda: make("replace", account="microsoft"),
}


# --- the document ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_every_shape_of_document_is_in_its_form_and_derives_its_own_key_and_dry_run(name):
    doc = VARIANTS[name]()
    assert fd.check(copy.deepcopy(doc)) == doc and doc["effect"] == "files" and set(doc) == set(fd.KEYS)
    assert doc["idempotency_key"] == fd.key_of(doc) and doc["dry_run_sha256"] == fd.dry_run_sha256(doc)
    assert fd.IMPLEMENTATION[doc["account"]] == doc["implementation"]
    other = copy.deepcopy(doc)
    other["content"]["sha256"] = sha("another")
    with pytest.raises(effects.EffectError):
        fd.check(other)       # the key and the dry run derive from the content: a document with another hash is no document
    assert fd.describe(doc) and fd.summary(doc)["content_sha256"] == doc["content"]["sha256"] and "text" not in json.dumps(fd.summary(doc))


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_the_requests_the_document_derives_are_exactly_what_the_writers_dry_run_prints(name, tmp_path):
    doc = VARIANTS[name]()
    verb, flags = fd.provider_args(doc)
    script = GDRIVE if doc["implementation"] == "gdrive" else ONEDRIVE
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "MICROSOFT_", "WRITER_", "OPENHORA_"))}
    env["OPENHORA_STATE_DIR"] = str(tmp_path / "state")
    done = subprocess.run([sys.executable, str(script), verb, *flags, "--dry-run"], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed["requests"] == json.loads(json.dumps(fd.requests(doc))), "the document and the writer build the same list of requests"
    assert printed["would_sha256"] == doc["dry_run_sha256"], "so the writer's dry run hashes to the document's"
    assert not (tmp_path / "state").exists(), "a dry run makes no ledger"


def test_a_writer_that_would_send_something_else_is_a_deviation_and_nothing_is_called_with_confirmed(tmp_path):
    doc = make()
    calls = []

    def call(verb, args, implementation):
        calls.append(args[-1])
        return {"would_sha256": "0" * 64}
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": sha(effects._text(doc))}
    with pytest.raises(effects.EffectError) as deviation:
        effect_files.execute(doc, approval, call, doc["idempotency_key"], str(tmp_path), str(tmp_path))
    assert deviation.value.kind == "deviation" and calls == ["--dry-run"]


def test_the_writers_and_the_runtime_share_the_tables_of_media_types_and_the_fields_they_ask_of_the_services():
    writer = {}
    for path in (COMMON, GDRIVE):
        namespace = {}
        spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location("w4a_" + path.stem, path)
        module = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        writer[path.stem] = module
    assert writer["_files_common"].MEDIA_TYPES == fd.MEDIA_TYPES and writer["_files_common"].CONTENT_MAX == fd.FILE_MAX
    assert writer["gdrive"].FILE_FIELDS == fd.DRIVE_FILE_FIELDS and writer["gdrive"].PARENT_FIELDS == fd.DRIVE_PARENT_FIELDS
    assert writer["gdrive"].LIST_FIELDS == fd.DRIVE_LIST_FIELDS and writer["gdrive"].MARK == fd.DRIVE_MARK and writer["gdrive"].DOC_MIME == fd.DOC_MIME
    spec = __import__("importlib.util", fromlist=["util"]).spec_from_file_location("w4a_onedrive", ONEDRIVE)
    onedrive = __import__("importlib.util", fromlist=["util"]).module_from_spec(spec)
    sys.modules[spec.name] = onedrive
    spec.loader.exec_module(onedrive)
    assert onedrive.ITEM_FIELDS == fd.ONEDRIVE_ITEM_FIELDS and onedrive.FOLDER_FIELDS == fd.ONEDRIVE_FOLDER_FIELDS and onedrive.UPLOAD_PATH == fd.UPLOAD_PATH
    assert effect_files.SECRETS == {"gdrive": "GOOGLE_ACCOUNT_TOKEN", "onedrive": "MICROSOFT_ACCOUNT_TOKEN"}


# --- every refusal of the form ------------------------------------------------------------------------------------------------------------------


def broken(doc, *path, value):
    out = copy.deepcopy(doc)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


BREAKS = [
    ("effect", "send"), ("operation", "delete"), ("task", 0), ("task", True), ("account", "dropbox"), ("implementation", "onedrive"), ("address", "a\u202eb@x.example"),
    ("read_at", "2026-10-18 14:30"), ("name", "CV 2026.pdf"), ("name", "../CV.md"), ("name", " CV.md"), ("name", "x" * 130 + ".md"),
    ("target", {"kind": "file", "label": "default", "id": "Folder_ID_01"}), ("target", {"kind": "folder", "label": "Default", "id": "Folder_ID_01"}),
    ("target", {"kind": "folder", "label": "default", "id": "../Folder"}), ("target", {"kind": "folder", "label": "default", "id": "a/b"}),
    ("target", {"kind": "folder", "label": "default", "id": "Folder_ID_01", "extra": 1}), ("base", {"version": "1"}), ("idempotency_key", "files-" + "0" * 32),
    ("dry_run_sha256", "0" * 64), ("dry_run_sha256", "nope"),
]


@pytest.mark.parametrize("key, value", BREAKS)
def test_a_document_out_of_its_form_is_refused(key, value):
    with pytest.raises(effects.EffectError) as refused:
        fd.check(broken(make(), key, value=value))
    assert refused.value.kind == "usage"


CONTENT_BREAKS = [
    ("kind", "folder"), ("bytes", 0), ("bytes", fd.FILE_MAX + 1), ("sha256", "zz"), ("media_type", "application/x-msdownload"), ("gdoc", "yes"),
    ("text", None), ("text", "another text"), ("attachment", 3), ("path", "notes/x.md"), ("path", "docs/../x.md"),
]


@pytest.mark.parametrize("key, value", CONTENT_BREAKS)
def test_a_content_out_of_its_form_is_refused(key, value):
    with pytest.raises(effects.EffectError):
        fd.check(broken(make(), "content", key, value=value))


def test_the_kinds_of_content_fit_only_the_operations_that_may_hold_them():
    held = make("save")["content"]
    for operation in ("create", "replace"):
        with pytest.raises(effects.EffectError):
            doc = make(operation)
            doc["content"] = held
            fd.check(doc)
    with pytest.raises(effects.EffectError):
        fd.document(task_id=7, operation="save", account="google", address="pat@example.com", target={"kind": "folder", "label": "default", "id": "Folder_ID_01"},
                    name="Contract.pdf", content=text_content(media="text/markdown"), base=None, read_at=READ_AT)
    with pytest.raises(effects.EffectError):
        make(account="microsoft", name="CV 2026", content=text_content(gdoc=True))            # a Google Doc is made in a Google Drive
    with pytest.raises(effects.EffectError):
        make(content=fd.content_of("file", b"PK", fd.MEDIA_TYPES["docx"], path="docs/x.docx"))      # the name says .md and the file is a word file
    with pytest.raises(effects.EffectError):
        make(content=fd.content_of("file", b"%PDF", "application/pdf", path="notes/x.pdf"), name="x.pdf")      # a project file is under docs/


def test_a_text_that_holds_a_credential_a_hidden_character_or_too_many_bytes_is_not_a_document():
    for text in ("token = ghp_" + "a" * 36 + "\n", "a\u202eb\n", "a\x00b\n", "a\x1bb\n", "   \n", "x" * (fd.TEXT_MAX + 1)):
        with pytest.raises(effects.EffectError):
            make(content=text_content(text))
    assert make(content=text_content("a\n\tb\n"))["content"]["bytes"] == 5
    assert make(content=text_content("a Markdown rule\n\n---\n\n- an item -----\n"))["content"]["bytes"] > 10, "a rule of three hyphens is no frame"


def test_a_replace_needs_its_base_in_the_form_of_its_service():
    for key in ("version", "md5", "head_revision", "mime"):
        base = google_base()
        base[key] = None if key in ("md5", "head_revision") else ""
        with pytest.raises(effects.EffectError):
            make("replace", base=base)
    native = google_base(native=True)
    native["md5"] = MD5
    with pytest.raises(effects.EffectError):
        make("replace", base=native)
    with pytest.raises(effects.EffectError):
        make("replace", account="microsoft", base={"etag": "bad etag", "ctag": '"c:{A-1},3"', "size": 9, "modified": "2026-10-10T09:00:00Z", "source_version": "x"})
    with pytest.raises(effects.EffectError):
        make("replace", base=None)


def test_the_unchanged_check_names_what_moved_and_passes_a_file_as_it_was_read():
    doc = make("replace")
    meta = {"version": "3", "modified": "2026-10-10T09:00:00.000Z", "mime_type": "text/markdown", "md5": MD5, "head_revision": HEAD, "in_trash": False, "folder": False,
            "owned": True}
    assert fd.unchanged(doc, meta) == ""
    assert fd.unchanged(doc, {**meta, "version": "4", "md5": "f" * 32}) == "version, checksum"
    assert "trash" in fd.unchanged(doc, {**meta, "in_trash": True}) and "trash" in fd.unchanged(doc, {**meta, "folder": True})
    ms = make("replace", account="microsoft")
    item = {"etag": '"{A-1},3"', "ctag": '"c:{A-1},3"', "size": 9, "writable": True, "owned": True}
    assert fd.unchanged(ms, item) == "" and fd.unchanged(ms, {**item, "etag": '"{A-1},4"'}) == "eTag" and fd.unchanged(ms, {**item, "size": 10}) == "size"
    assert fd.unchanged(ms, {**item, "writable": False}) and fd.unchanged(ms, {}) != ""


def test_the_key_depends_on_the_task_the_target_the_name_the_content_and_the_base_and_on_nothing_else():
    base = make()
    assert make()["idempotency_key"] == base["idempotency_key"] and make(read_at="2027-01-01T00:00:00Z")["idempotency_key"] == base["idempotency_key"]
    assert make(task_id=8)["idempotency_key"] != base["idempotency_key"] and make(name="Other.md")["idempotency_key"] != base["idempotency_key"]
    assert make(content=text_content("another\n"))["idempotency_key"] != base["idempotency_key"]
    assert make(target={"kind": "folder", "label": "cv", "id": "Cv_Folder_0001"})["idempotency_key"] != base["idempotency_key"]
    assert make("replace")["idempotency_key"] != make("replace", base={**google_base(), "version": "4"})["idempotency_key"]


def test_the_requests_hold_every_id_percent_encoded_and_a_file_name_escaped_in_the_query():
    ms = make(account="microsoft", name="A (1).md")
    assert fd.requests(ms)[0]["path"] == "/me/drive/items/01FOLDER0000%21101" and fd.requests(ms)[1]["path"] == "/me/drive/items/01FOLDER0000%21101:/A%20%281%29.md:/content"
    path = make(account="microsoft", target={"kind": "folder", "label": "docs", "id": "/Documents/My folder"}, name="A.md")
    assert fd.requests(path)[0]["path"] == "/me/drive/root:/Documents/My%20folder" and fd.requests(path)[1]["path"] == "/me/drive/root:/Documents/My%20folder/A.md:/content"
    replace = make("replace", account="microsoft")
    assert fd.requests(replace)[0]["path"] == "/drives/b%21FakeDrive_1/items/01FILE000001%21102" and fd.requests(replace)[1]["if_match"] == '"{A-1},3"'
    assert all(step["method"] in ("GET", "POST", "PUT", "PATCH") for name in VARIANTS for step in fd.requests(VARIANTS[name]()))
    assert not any(step["method"] == "DELETE" for name in VARIANTS for step in fd.requests(VARIANTS[name]())), "no variant of any write asks for a removal"


def test_the_card_of_every_shape_is_valid_translatable_and_ends_with_the_hash_and_the_command():
    for name in sorted(VARIANTS):
        doc = VARIANTS[name]()
        lines = fd.card_lines(doc, "a" * 64)
        assert phrases.card_valid(lines), name
        assert lines[0][0].startswith("CARD_FILE_CODE_") and lines[1][0] == "CARD_ACCOUNT" and lines[-2][0] == "CARD_FILE_HASH" and lines[-1][0] == "CARD_FILE_APPROVE"
        assert fd.body(doc, "a" * 64) == phrases.card_text(lines) and "a" * 64 in fd.body(doc, "a" * 64)
        assert phrases.card_text(lines, {"language": "pt-BR"}) != phrases.card_text(lines)
        assert fd.title(doc) == phrases.en(fd.TITLE_KEY[doc["operation"]]) and len(fd.title(doc)) <= 60
    assert "CARD_FILE_TEXT" in [k for k, _ in fd.card_lines(make(), "a" * 64)] and "CARD_FILE_SAVE" in [k for k, _ in fd.card_lines(make("save"), "a" * 64)]
    binary = make(content=fd.content_of("file", b"PK", fd.MEDIA_TYPES["docx"], path="docs/x.docx"), name="x.docx")
    assert "CARD_FILE_PROJECT" in [k for k, _ in fd.card_lines(binary, "a" * 64)] and "CARD_FILE_TEXT" not in [k for k, _ in fd.card_lines(binary, "a" * 64)]


def test_a_name_a_service_gave_is_shown_cleaned_on_one_line():
    assert fd.clean_display("a\u202eb\nc\x00d") == "a?b c?d" and fd.clean_display("x" * 300) == "x" * 200 and fd.clean_display(None) == ""
    assert phrases.card_valid(fd.card_lines(make("replace", name="Report.md"), "a" * 64))
    with pytest.raises(effects.EffectError):
        make("replace", name="Report\u202e.md")      # an uncleaned name is no document


# --- the arguments of the step ---------------------------------------------------------------------------------------------------------------


def bad(args):
    with pytest.raises(steps.StepFailure) as refused:
        step_files.check(args)
    return refused.value


def test_the_arguments_of_each_operation_are_closed_and_normalised():
    assert step_files.check({"operation": "create", "account": "google", "name": "CV 2026.md", "content": "a\r\nb\rc\n"}) == {
        "operation": "create", "account": "google", "name": "CV 2026.md", "content": "a\nb\nc\n"}
    assert step_files.check({"operation": "create", "account": "microsoft", "name": "x.docx", "from": "docs/outputs/x.docx", "folder": "docs"})["folder"] == "docs"
    assert step_files.check({"operation": "replace", "account": "google", "file": "cv", "content": "new\n"}) == {"operation": "replace", "account": "google",
                                                                                                                  "file": "cv", "content": "new\n"}
    assert step_files.check({"operation": "save", "account": "google", "attachment": 4}) == {"operation": "save", "account": "google", "attachment": 4}
    assert step_files.check({"operation": "save", "account": "google", "attachment": 4, "name": "x.pdf", "folder": "cv"})["name"] == "x.pdf"
    assert step_files.check({"operation": "create", "account": "google", "name": "CV.gdoc", "content": "x\n"})["name"] == "CV.gdoc"


@pytest.mark.parametrize("args, field", [
    ({}, "operation"), ({"operation": "delete", "account": "google"}, "operation"), ({"operation": "create", "account": "box", "name": "a.md", "content": "x"}, "account"),
    ({"operation": "create", "account": "google", "content": "x"}, "name"), ({"operation": "create", "account": "google", "name": "a.md"}, "content"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "x", "from": "docs/a.md"}, "content"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "x", "file": "cv"}, "file"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "x", "attachment": 1}, "attachment"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": 5}, "content"),
    ({"operation": "create", "account": "google", "name": "a.md", "from": "notes/a.md"}, "from"), ({"operation": "create", "account": "google", "name": "a.md", "from": "docs/../a.md"}, "from"),
    ({"operation": "create", "account": "google", "name": "a.md", "from": "docs/a.comments.md"}, "from"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "x", "folder": "Elsewhere"}, "folder"),
    ({"operation": "create", "account": "microsoft", "name": "a.gdoc", "content": "x"}, "name"), ({"operation": "create", "account": "google", "name": "a.exe", "content": "x"}, "name"),
    ({"operation": "replace", "account": "google", "content": "x"}, "file"), ({"operation": "replace", "account": "google", "file": "Cv", "content": "x"}, "file"),
    ({"operation": "replace", "account": "google", "file": "cv", "content": "x", "name": "a.md"}, "name"),
    ({"operation": "replace", "account": "google", "file": "cv", "content": "x", "folder": "cv"}, "folder"),
    ({"operation": "save", "account": "google"}, "attachment"), ({"operation": "save", "account": "google", "attachment": "4"}, "attachment"),
    ({"operation": "save", "account": "google", "attachment": True}, "attachment"), ({"operation": "save", "account": "google", "attachment": 0}, "attachment"),
    ({"operation": "save", "account": "google", "attachment": 4, "content": "x"}, "content"), ({"operation": "save", "account": "google", "attachment": 4, "name": "a.exe"}, "name"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "x", "sender": "telegram:1"}, "args"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "token = ghp_" + "a" * 36}, "content"),
    ({"operation": "create", "account": "google", "name": "a.md", "content": "a\u202eb"}, "content"),
])
def test_an_argument_out_of_the_closed_rules_is_refused_naming_the_field(args, field):
    failure = bad(args)
    assert failure.code == "bad_args" and failure.field == field


# --- the seams ------------------------------------------------------------------------------------------------------------------------------


def test_limit_58_the_files_reader_a_step_kind_is_given_has_one_verb_and_it_is_a_read():
    cfg = {"accounts": {"google": {"address": "pat@example.com", "calendars": {}, "folders": {}, "mail_folders": {}, "move_removes_inbox": True},
                        "microsoft": {"address": "casey.rivera@mail.example", "calendars": {}, "folders": {}, "mail_folders": {}, "move_removes_inbox": True}}}
    reader = seams.FilesReader(cfg, str(st.REPO))
    assert {name for name in dir(reader) if not name.startswith("_")} == {"meta"} and seams.FILES_READ_VERB == "file-meta"
    seen = []
    resolver = project_config.resolver(str(st.REPO))
    original_call, original_env = resolver.call, resolver.provider_environment
    try:
        resolver.call = lambda cls, verb, args, **kw: seen.append((cls, verb, kw["implementation"], kw["env"], args)) or {"exists": False}
        resolver.provider_environment = lambda cls, env=None, passes=(): {"PATH": "x", **{p: "v" for p in passes}}
        assert reader.meta("google", ["--id", "abc"]) == {"exists": False} and reader.meta("microsoft", ["--id", "d/i"]) == {"exists": False}
    finally:
        resolver.call, resolver.provider_environment = original_call, original_env
    assert seen == [("writer:files", "file-meta", "gdrive", {"PATH": "x", "GOOGLE_ACCOUNT_TOKEN": "v"}, ["--id", "abc", "--account", "pat@example.com"]),
                    ("writer:files", "file-meta", "onedrive", {"PATH": "x", "MICROSOFT_ACCOUNT_TOKEN": "v"}, ["--id", "d/i", "--account", "casey.rivera@mail.example"])], "one verb, the implementation of the account, one secret"
    with pytest.raises(seams.StepServiceError):
        reader.meta("dropbox", [])


def test_the_services_a_step_kind_is_given_for_files_are_the_four_and_nothing_writes_through_them():
    assert {name for name in dir(seams.HeldFiles) if not name.startswith("_")} == {"meta"}
    assert {name for name in dir(seams.FileSources) if not name.startswith("_")} == {"lookup"}
    assert {name for name in dir(seams.AccountTargets) if not name.startswith("_")} == {"address", "target"}
    cfg = {"accounts": {"google": {"address": "pat@example.com", "calendars": {}, "folders": {"default": "Folder_ID_01"}, "mail_folders": {}, "move_removes_inbox": True}}}
    targets = seams.AccountTargets(cfg)
    assert targets.address("google") == "pat@example.com" and targets.target("google", "folders", "default") == "Folder_ID_01" and targets.target("google", "folders") == "Folder_ID_01"
    for call in (lambda: targets.address("microsoft"), lambda: targets.target("google", "folders", "elsewhere"), lambda: targets.target("google", "mail_folders", "inbox")):
        with pytest.raises(seams.StepServiceError):
            call()


def test_the_step_kind_of_the_files_imports_no_module_that_calls_a_provider_and_names_no_writer():
    for module in ("files_document.py", "ops_files.py", "step_files.py", "account_start.py"):
        assert "writer:" not in (st.RUNTIME / module).read_text(encoding="utf-8"), module
    import ast
    tree = ast.parse((st.RUNTIME / "step_files.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert "effect_files" not in imported and "ops_step_seams" not in imported and "effects" not in imported
