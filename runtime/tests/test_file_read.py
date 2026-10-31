"""Read a file by its name from the folders the project lists for the person's accounts (slice S8, runtime/ops_file_read.py), through `ops.say` on a messaging line.

A stand-in model answers each line with a text the test wrote by hand (the interpreter decides the operation and the name, never reads a file), and stand-in providers
(`ops_file_read.provider_call`, the seam of `sources.drive_call` and `sources_onedrive.onedrive_call`) keep two small fictional drives in memory: a listing per configured
folder and the bytes of each file. Every expectation is a literal of this file: the line, the model's text, the reply, the calls the providers saw. No network, no model,
no secret store; every name, folder and text is invented.

  the two lines of the maintainer's first use (pt-BR): the text of the file shown, from the folders the accounts list and from no other
  several matches: a numbered list; none: one sentence naming the configured folders; a sender without the group `read-files`: the refusal and no provider call
  a text over 3,500 characters: cut on a word with the count of what is left; a kind of file the converter takes: converted, not registered
  what is kept: the conversation holds a neutral word, the store and the project's files hold no byte of the file, no source is made, the staging folder is gone
  the catalog and the enabling entry: the operation is served, the interpreter stays on with the entry that names the served catalog and is off with a wrong hash

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_read.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL_PT  # noqa: E402

import hashlib
import json
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
from test_ask import accept
from test_ops_natural import KEY, OWNER, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_file_read = st.load("ops_file_read")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
interpreter = st.load("interpreter")
interpreter_enable = st.load("interpreter_enable")
interpreter_route = st.load("interpreter_route")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
sources = st.load("sources")
service = st.load("service")

REPO = Path(__file__).resolve().parents[2]
ZONE = "America/Sao_Paulo"
READER = "55119000000021"        # holds read-files
PLAIN = "55119000000022"         # holds interpret and talk, not read-files
READER_KEY, PLAIN_KEY = f"telegram:{READER}", f"telegram:{PLAIN}"
# D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: these tests are about the file read itself, which runs at once for a sender who holds `confirm-reads-off` (accepted with --widen by `accept`).
FILE_PROFILES = dict(PROFILES, reader=["read", "talk", "interpret", "read-files", "confirm-reads-off"], plain=["read", "talk", "interpret", "confirm-reads-off"])
FILE_SENDERS = {"telegram": [{"id": READER, "policy": "reader"}, {"id": PLAIN, "policy": "plain"}]}
ACCOUNTS = {"google": {"address": "ana@mail.example", "folders": {"default": "GDRIVEFOLDER0001", "contratos": "GDRIVEFOLDER0002"}},
            "microsoft": {"address": "ana@outlook.example", "folders": {"default": "/Documentos"}}}
WANTED = "Copy of the-first-sin-activities"
SECRET_MARK = "ZEBRA-CLAUSE-7-UNIQUE-MARK"
ACTIVITIES = f"Atividades da semana\n\nSegunda: ensaio do coral.\nQuarta: visita as familias. {SECRET_MARK}\n"
LINE_1 = f"Me traga o conteudo do arquivo {WANTED}"
LINE_2 = f'Leia o arquivo do meu onedrive com o nome "{WANTED}"'
PT = {"language": "pt-BR"}
HEAD = f"{WANTED} (OneDrive, pasta Documentos):\n\n"      # literal: kept only because test_file_send.py imports it (its asserts are T8-5's); this file asserts FR_HEAD through `shown`
NONE_FOLDERS = "Arquivos (Google Drive), Contratos 2026 (Google Drive), Documentos (OneDrive)"      # the names the configuration gives its folders, as the sentence lists them
REFUSAL = "error: /file-read is not enabled for this channel; the project's configuration (channels.messaging) turns it on"


def item(ident, name, kind="file", supported=True):
    return {"id": ident, "name": name, "kind": kind, "path": "/", "size": 10, "modified": "2026-10-20T10:00:00Z", "supported": supported, "reason": ""}


class Drives:
    """Two fictional drives: {(service, folder id or path): [items]} and {(service, item id): bytes}. Records every call a provider received."""

    def __init__(self):
        self.folders = {("google", "GDRIVEFOLDER0001"): [item("gfile0000000001", "Planilha de custos.xlsx"), item("gsub000000000001", WANTED, kind="folder")],
                        ("google", "GDRIVEFOLDER0002"): [item("gfile0000000002", "Contrato de locacao.docx")],
                        ("microsoft", "/Documentos"): [item("drv1/it!1", WANTED), item("drv1/it!2", "Lista de presenca.txt")],
                        ("google", "OUTSIDEFOLDER0001"): [item("gfile0000000009", WANTED)],
                        ("microsoft", "/Particular"): [item("drv1/it!9", WANTED)]}
        self.files = {("microsoft", "drv1/it!1"): ACTIVITIES.encode("utf-8"), ("microsoft", "drv1/it!2"): b"Ana\nBeto\n",
                      ("google", "gfile0000000001"): b"x", ("google", "gfile0000000002"): b"%PDF-1.7 fake body for the converter",
                      ("google", "gfile0000000009"): b"the file outside the folders",
                      ("microsoft", "drv1/it!9"): b"the private folder"}
        self.names = {("google", "GDRIVEFOLDER0001"): "Arquivos", ("google", "GDRIVEFOLDER0002"): "Contratos 2026"}      # the real names `stat` gives the configured Google folders
        self.calls = []
        self.markdown = set()      # (service, id) read as a Google Doc exported to Markdown

    def __call__(self, cls, verb, args, **kw):
        service = "google" if kw.get("implementation") == "gdrive" else "microsoft"
        self.calls.append((service, verb, tuple(args)))
        value = lambda flag: args[args.index(flag) + 1]  # noqa: E731
        if verb == "stat":
            name = self.names.get((service, value("--id")))
            if name is None:
                raise RuntimeError("Drive said: no such folder")
            return {"id": value("--id"), "name": name, "mime_type": "application/vnd.google-apps.folder", "supported": False}
        if verb == "children":
            folder = value("--id") if "--id" in args else value("--path") if "--path" in args else value("--folder-id")
            return {"items": list(self.folders.get((service, folder), [])), "count": len(self.folders.get((service, folder), [])), "truncated": False}
        ident = value("--id")
        data = self.files[(service, ident)]
        Path(value("--out-dir"), "content").write_bytes(data)
        return {"id": ident, "name": "x", "version": "v1", "content": "markdown" if (service, ident) in self.markdown else "file", "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "file": "content"}

    def listed(self):
        return sorted({(s, a[1]) for s, v, a in self.calls if v == "children"})

    def reads(self):
        return [(s, a[a.index("--id") + 1]) for s, v, a in self.calls if v == "read"]


def op(name, slots=None):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}}, ensure_ascii=False)


@pytest.fixture
def drives(world, monkeypatch):
    """The world with the two accounts configured, the senders accepted, the zone named, the stand-in providers and the stand-in model (`ANSWER["text"]`)."""
    accept(world["path"], policies=FILE_PROFILES, messaging={"senders": FILE_SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    made = Drives()
    answer = {"text": op("file-read", {"file": WANTED})}
    monkeypatch.setattr(ops_file_read, "provider_call", made)
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: {"ok": True, "text": answer["text"], "finish": "stop", "usage": {}, "latency_ms": 5})
    world.update(drives=made, answer=answer)
    return world


def phone(world, line, key=READER_KEY):
    return ops.say(world["path"], line, channel="messaging", sender=key)["reply"]


def shown(reply, text, name=WANTED, folder="Documentos", account="OneDrive"):
    """`reply` is the head of the file (FR_HEAD), a blank line and exactly `text`."""
    head, blank, body = reply.partition("\n\n")
    assert blank == "\n\n" and "\n" not in head, reply
    pk.assert_said(head, "FR_HEAD", PT, name=name, folder=folder, account=account)
    assert body == text, body


def one_line(reply, key, **fields):
    """`reply` is exactly the one sentence of `key` in Portuguese (one line, nothing else is said)."""
    assert "\n" not in reply, reply
    pk.assert_said(reply, key, PT, **fields)


def stored(world) -> list:
    ctx = ops_core.context(world["path"])
    return ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)


# --- the two lines of the first use ------------------------------------------------------------------------------------------------------------


def test_the_first_line_with_no_service_shows_the_text_of_the_file_found_in_the_configured_folders(drives):
    shown(phone(drives, LINE_1), ACTIVITIES.strip())
    assert sorted(drives["drives"].listed()) == [("google", "GDRIVEFOLDER0001"), ("google", "GDRIVEFOLDER0002"), ("google", "gsub000000000001"), ("microsoft", "/Documentos")]      # S17: the subfolder is walked too
    assert drives["drives"].reads() == [("microsoft", "drv1/it!1")]


def test_the_second_line_that_names_onedrive_searches_that_account_only(drives):
    drives["answer"]["text"] = op("file-read", {"file": WANTED, "service": "onedrive"})
    shown(phone(drives, LINE_2), ACTIVITIES.strip())
    assert drives["drives"].listed() == [("microsoft", "/Documentos")]
    assert [c for c in drives["drives"].calls if c[0] == "google"] == []


def test_a_file_outside_the_configured_folders_and_a_folder_of_that_name_are_never_found(drives):
    drives["drives"].folders[("microsoft", "/Documentos")] = [item("drv1/it!2", "Lista de presenca.txt")]
    reply = phone(drives, LINE_1)
    one_line(reply, "FR_NONE_SUB", folders=NONE_FOLDERS)
    assert drives["drives"].reads() == []
    assert ("google", "OUTSIDEFOLDER0001") not in drives["drives"].listed() and ("microsoft", "/Particular") not in drives["drives"].listed()
    for piece in ("OUTSIDE", "Particular", "GDRIVEFOLDER", "/Documentos", "the file outside"):
        assert piece not in reply, "folders are named as the configuration names them, never by an id or a path"


def test_vacuity_a_search_that_also_listed_an_unconfigured_folder_would_be_seen(drives, monkeypatch):
    """The planted fault: the search lists a folder the configuration does not list. The oracle of the test above then fails, so it can fail."""
    drives["drives"].folders[("microsoft", "/Documentos")] = []
    real = ops_file_read._search

    def wrong(cfg, wanted, account=None, said=None):
        cfg = dict(cfg, accounts={**cfg["accounts"], "google": {**cfg["accounts"]["google"], "folders": {"default": "OUTSIDEFOLDER0001"}}})
        return real(cfg, wanted, account, said)
    monkeypatch.setattr(ops_file_read, "_search", wrong)
    assert not pk.said(phone(drives, LINE_1), "FR_NONE_SUB", PT)
    assert ("google", "OUTSIDEFOLDER0001") in drives["drives"].listed()


def test_several_files_with_the_name_are_listed_as_a_numbered_list_and_nothing_is_read(drives):
    drives["drives"].folders[("google", "GDRIVEFOLDER0002")].append(item("gfile0000000003", WANTED))
    pick, first, second = phone(drives, LINE_1).split("\n")
    pk.assert_said(pick, "FR_SEVERAL_PICK", PT, count=2)
    pk.assert_said(first, "FR_ITEM", PT, n=1, name=WANTED, folder="Contratos 2026", account="Google Drive")
    pk.assert_said(second, "FR_ITEM", PT, n=2, name=WANTED, folder="Documentos", account="OneDrive")
    assert drives["drives"].reads() == []


def test_no_file_with_the_name_gets_one_sentence_naming_the_folders_by_their_configured_names(drives):
    drives["answer"]["text"] = op("file-read", {"file": "Relatorio inexistente"})
    one_line(phone(drives, "Mostre o arquivo Relatorio inexistente"), "FR_NONE_SUB", folders=NONE_FOLDERS)


def test_the_name_may_be_typed_without_case_accents_or_the_extension(drives):
    drives["answer"]["text"] = op("file-read", {"file": "LISTA DE PRESENÇA"})  # validate: allow english-only -- the Portuguese sentence or name under test
    shown(phone(drives, "mostre o arquivo LISTA DE PRESENÇA"), "Ana\nBeto", name="Lista de presenca.txt")  # validate: allow english-only -- the name under test


@pytest.mark.parametrize("wanted, found, same", [
    ("Lista de presenca", "Lista de presenca.txt", True), ("lista de presença.txt", "Lista de presenca.txt", True), ("Lista de presenca.docx", "Lista de presenca.txt", False),  # validate: allow english-only -- the Portuguese sentence or name under test
    ("Lista", "Lista de presenca.txt", False), ("notes.txt", "Notes", True), ("notes", "notes-old", False), ("", "x", False)])
def test_the_names_are_compared_whole_with_the_extension_optional(wanted, found, same):
    assert ops_file_read._same_name(wanted, found) is same


# --- the policy ------------------------------------------------------------------------------------------------------------------------------


def test_a_sender_without_the_group_read_files_gets_the_refusal_and_no_provider_is_called(drives):
    assert phone(drives, LINE_1, PLAIN_KEY) == PLAIN_REFUSAL_PT
    assert drives["drives"].calls == []


def test_the_group_read_files_is_in_no_default_and_the_widening_says_what_it_means(drives):
    assert "read-files" not in operations.DEFAULT_POLICY["messaging"]
    assert operations.GROUPS["read-files"] == {"operations": ("file-read",), "kind": None}
    assert policy_widening.means("messaging", "read-files") == (
        "shows the text of the files in your configured Drive and OneDrive folders in the chat, found by their names; a messaging app's servers see it as they see any message, and no model reads it")
    before = ops.config(drives["path"])
    assert [w for w in before["widening"] if w["group"] == "read-files"] == []
    accept_text = json.loads((Path(drives["path"]) / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
    accept_text["policies"]["plain"] = FILE_PROFILES["plain"] + ["read-files"]
    (Path(drives["path"]) / "docs" / "workbench" / "runtime.json").write_text(json.dumps(accept_text), encoding="utf-8")
    mine = [w for w in ops.config(drives["path"])["widening"] if w["group"] == "read-files"]
    assert len(mine) == 1 and mine[0]["place"] == PLAIN_KEY and mine[0]["means"] == policy_widening.means("messaging", "read-files")


def test_the_page_and_the_terminal_read_by_the_typed_operation_and_a_messaging_sender_needs_the_group(drives):
    out = ops.file_read(drives["path"], WANTED, account="microsoft", channel="page")
    assert out == {"status": "text", "name": WANTED, "folder": "Documentos", "account": "microsoft", "text": ACTIVITIES.strip(), "remaining": 0}
    with pytest.raises(ops_core.OpsError) as refused:
        ops.file_read(drives["path"], WANTED, channel="messaging", sender=PLAIN_KEY)
    assert str(refused.value) == REFUSAL[len("error: "):]


# --- the text -------------------------------------------------------------------------------------------------------------------------------


def test_the_page_reaches_the_operation_by_one_post_route_that_takes_the_name_in_the_body():
    routes = [r for r in service.ROUTES if r["op"] == "file-read"]
    assert len(routes) == 1 and routes[0]["method"] == "POST" and routes[0]["pattern"] == "/projects/{p}/files/read" and routes[0]["take"] == ("file", "account")
    assert operations.by_name("file-read")["channels"] == ("terminal", "page", "messaging") and "mcp" not in operations.by_name("file-read")["channels"]


def test_a_text_over_the_cap_is_cut_on_a_word_and_says_how_many_characters_remain(drives):
    long = " ".join(["palavra"] * 600)      # 600 words of 7 letters and 599 spaces: 4,799 characters
    drives["drives"].files[("microsoft", "drv1/it!1")] = long.encode("utf-8")
    reply = phone(drives, LINE_1)
    head, _, rest = reply.partition("\n\n")
    body, _, more = rest.rpartition("\n\n")
    pk.assert_said(head, "FR_HEAD", PT, name=WANTED, folder="Documentos", account="OneDrive")
    pk.assert_said(more, "FR_MORE", PT, remaining=1304)
    assert len(body) == 3495 and body == " ".join(["palavra"] * 437)
    assert len(long) - len(body) == 1304


def test_a_google_doc_exported_as_markdown_is_shown_without_its_pictures(drives):
    drives["drives"].folders[("microsoft", "/Documentos")] = []
    drives["drives"].folders[("google", "GDRIVEFOLDER0002")] = [item("gdoc0000000001", WANTED)]
    drives["drives"].files[("google", "gdoc0000000001")] = b"# Atividades\n\n![logo](data:image/png;base64,AAAA)\n\nSegunda: ensaio.\n"
    drives["drives"].markdown.add(("google", "gdoc0000000001"))
    reply = phone(drives, LINE_1)
    head, _, rest = reply.partition("\n\n")
    pk.assert_said(head, "FR_HEAD", PT, name=WANTED, folder="Contratos 2026", account="Google Drive")
    assert rest.startswith("# Atividades\n\n")
    assert "base64" not in reply and reply.endswith("Segunda: ensaio.")


def test_a_pdf_goes_through_the_converter_of_a_source_and_a_text_file_does_not(drives, monkeypatch):
    converted = []

    def converter(input_path, subtype, out_dir):
        converted.append(subtype)
        Path(out_dir, "converted.md").write_text("Contrato de locacao\n\nClausula 3: o prazo e de doze meses.\n", encoding="utf-8")
        return {"converter": "stand-in"}
    monkeypatch.setattr(ops_file_read, "converter", converter)
    drives["answer"]["text"] = op("file-read", {"file": "Contrato de locacao"})
    shown(phone(drives, "mostre o arquivo Contrato de locacao"), "Contrato de locacao\n\nClausula 3: o prazo e de doze meses.", name="Contrato de locacao.docx", folder="Contratos 2026", account="Google Drive")
    assert converted == ["pdf"]
    drives["answer"]["text"] = op("file-read", {"file": "Lista de presenca"})
    phone(drives, "mostre o arquivo Lista de presenca")
    assert converted == ["pdf"], "a text file is shown as it is: the container is not started for it"


def test_a_text_that_looks_like_a_credential_is_withheld_and_never_shown(drives):
    drives["drives"].files[("microsoft", "drv1/it!1")] = (b"notes\n-----BEGIN PRIV" + b"ATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIV" + b"ATE KEY-----\n")
    reply = phone(drives, LINE_1)
    one_line(reply, "FR_WITHHELD", name=WANTED, account="OneDrive")
    assert "MIIEvQ" not in reply


def test_a_provider_that_fails_is_a_fixed_sentence_with_none_of_its_words(drives, monkeypatch):
    def failing(cls, verb, args, **kw):
        raise RuntimeError("Graph said: token abc-SECRET-123 for ana@outlook.example refused")
    monkeypatch.setattr(ops_file_read, "provider_call", failing)
    reply = phone(drives, LINE_1)
    one_line(reply, "FR_UNAVAILABLE")
    assert "SECRET" not in reply and "ana@" not in reply


def test_a_project_with_no_folders_says_so(drives):
    accept(drives["path"], accounts={"google": {"address": "ana@mail.example"}})
    one_line(phone(drives, LINE_1), "FR_NO_FOLDERS")


def test_a_service_word_no_table_reads_as_one_service_or_a_name_that_is_not_in_the_line_asks_again(drives):
    drives["answer"]["text"] = op("file-read", {"file": WANTED, "service": "dropbox"})
    one_line(phone(drives, f"Leia o arquivo {WANTED} do meu dropbox"), "IX_ASK_AGAIN")
    drives["answer"]["text"] = op("file-read", {"file": "Outro nome"})
    one_line(phone(drives, "Leia o arquivo " + WANTED), "IX_ASK_AGAIN")
    assert drives["drives"].calls == []


# --- what is kept ---------------------------------------------------------------------------------------------------------------------------


def test_nothing_of_the_file_is_kept_the_conversation_holds_a_neutral_word_and_no_source_is_made(drives, caplog, capsys):
    reply = phone(drives, LINE_1)
    assert SECRET_MARK in reply
    rows = stored(drives)
    # literal: the neutral words are the stored text itself, what the conversation keeps instead of the file's words
    assert [r["text"] for r in rows if r["role"] == "assistant"][-1] == "(mostrado onde foi pedido)"
    assert [r["text"] for r in rows if r["role"] == "user"][-1] == "(uma mensagem)"
    everything = json.dumps(rows, ensure_ascii=False)
    for piece in (SECRET_MARK, WANTED, "ensaio do coral", "Atividades"):
        assert piece not in everything
    assert ops.sources_catalog(drives["path"])["sources"] == []
    seen = capsys.readouterr()
    assert SECRET_MARK not in seen.out + seen.err + caplog.text
    holders = [Path(drives["path"]), Path(ops_core.context(drives["path"])["cfg"]["data_dir"])]
    for root in holders:
        for found in root.rglob("*"):
            if found.is_file() and ".git" not in found.parts:
                assert SECRET_MARK.encode() not in found.read_bytes(), str(found.relative_to(root))
    staging = Path(ops_core.context(drives["path"])["cfg"]["data_dir"]) / "sources-staging"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_a_typed_command_line_on_a_phone_is_not_a_command_of_the_conversation_and_reaches_no_provider(drives):
    """`file-read` is not a verb of the conversation's shell (its row lists no `chat`): the line gets the help, and the file's words are asked in words."""
    reply = ops.say(drives["path"], f'/file-read "{WANTED}" --account microsoft', channel="messaging", sender=READER_KEY)["reply"]
    assert reply.startswith("Commands, one per line") and SECRET_MARK not in reply
    assert drives["drives"].calls == []


def test_vacuity_a_reply_stored_as_it_was_written_would_be_seen_by_the_scan(drives, monkeypatch):
    """The planted fault: the reply keeps no neutral word. The oracle that scans the conversation for the file's words then fails, so it can fail."""
    real = ops_file_read.reply

    def keeps(project, ctx, args, said, channel, sender, extras):
        out = real(project, ctx, args, said, channel, sender, extras)
        extras["stored"] = out
        return out
    monkeypatch.setattr(ops_file_read, "reply", keeps)
    phone(drives, LINE_1)
    assert SECRET_MARK in json.dumps(stored(drives), ensure_ascii=False)


# --- the catalog and the enabling entry ------------------------------------------------------------------------------------------------------


def test_the_served_catalog_has_the_operation_as_a_read_with_a_span_and_a_word():
    rows = [row for row in interpreter.SERVED["ops"] if row["op"] == "file-read"]
    assert len(rows) == 1 and rows[0]["class"] == "R" and rows[0]["slots"] == {"file": "span", "service": "word"}
    assert "refused" in interpreter.SERVED and all(r["op"] != "file-read" for r in interpreter.SERVED["refused"])


def test_the_interpreter_stays_on_with_the_newest_entry_and_is_off_when_its_catalog_hash_is_wrong(tmp_path):
    data = json.loads((REPO / "runtime" / "interpreter_enable.json").read_text(encoding="utf-8"))
    before = PINNED_HASHES["interpreter_catalog_before_s8"]      # the catalog before this slice: an earlier entry still names it
    served = PINNED_HASHES["interpreter_catalog_mail_ask"]      # MAIL-SUMMARY-FLIP: the catalog of version 3
    assert any(e["catalog_sha256"] == before for e in data["entries"][:-1])
    assert any(e["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_s8"] for e in data["entries"][:-1]), "an earlier entry (R2-A) names the catalog before B″-lite"
    newest = data["entries"][-1]
    assert interpreter.SERVED_SHA256 == served and newest["catalog_sha256"] == served
    assert {k: newest[k] for k in interpreter_enable.HASH_KEYS} == interpreter_enable.checkout_hashes(newest["route"])
    for language in ("pt-BR", "en", "es", "fr", "de", "it"):
        assert interpreter_enable.active(language) is not None
    wrong = json.loads(json.dumps(data))
    wrong["entries"][-1]["catalog_sha256"] = before
    broken = tmp_path / "interpreter_enable.json"
    broken.write_text(json.dumps(wrong), encoding="utf-8")
    assert interpreter_enable.active("pt-BR", path=str(broken)) is None
    assert interpreter_enable.active("pt-BR", path=str(REPO / "runtime" / "interpreter_enable.json")) is not None
