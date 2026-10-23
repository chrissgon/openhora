#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of sending an e-mail from the project's outbox (package EMAIL-SEND): the text a step task prepared is sent, to exactly
the recipients the person approved, once.

It is registered under the side-effect word `send` (runtime/effects.py KINDS; contracts/environment.md) and is the STEP path of an effect,
like the write-back (runtime/effect_write.py): a step task of the kind `send-email` (runtime/step_send_email.py) writes this module's
document (runtime/send_document.py) and opens an `effect` decision whose hash is the document's; nothing in the engine or in the kind
sends. The send happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else,
with the approval the person gave. What a kind module of this path exposes, besides the names of runtime/effect_write.py (the document,
`check`, `title`, `body`, `describe`, `summary`, `execute`):

    PROVIDER_CLASS, GATE, POLICY, STEP   sender:email; False and False (no skill's gate names `send`, and no standing approval covers it:
                                         every e-mail is approved by the hash of its exact content); True
    NOTHING_DONE                         "nothing was sent": how a refusal of the approval starts
    FORGETS_KEYS                         False: the provider's ledger keeps a key; the age of a decision is no reason to refuse it
    preflight(cfg, doc, root)            the project's outbox is configured, names the document's sender and resolves to the document's
                                         provider ((exit code, sentence) or None)
    caller(cfg, root)                    the `call(verb, args)` that reaches the provider (providers/mailer/smtp.py) with the outbox
                                         password in its environment and nothing else of the secrets
    idempotency_key(doc, default)        the document's own key: one e-mail is sent once, however many decisions reach it
    is_long(doc)                         whether the decision takes the decision's lock (every send does: an answer is refused while it runs, a cancel keeps the decision open)
    on_cards(doc)                        whether the whole e-mail can be on a messaging card (False with an attachment: the card cannot
                                         carry the file the hash covers); read by the policy layer when it grants approval from a messaging app
    APPROVAL_GROUP                       the policy group that would let a messaging app approve this kind (`approve-effect-send`,
                                         decision POL-1); until it is granted an e-mail is approved in the terminal or on the page only
                                         (operations.EFFECT_CHANNELS)

Execution (`execute`). It refuses unless `approval` is the person's approval of exactly this document (scope action, status
pending-execution, payload_sha256 the hash of the document's canonical text) and `key` is the document's own. Each attachment is read from
the project again, with no link anywhere on the way, and copied to a private folder (0700; the files O_EXCL, 0600); a file whose sha256 is
not the one the task read is `stale`: nothing is sent, and the task starts over from the step that reads. The subject and the body are
written to private files. The provider is asked for a dry run first, and what it prints must hash to the document's `dry_run_sha256` (a
provider that would render another message than the one previewed is a `deviation`); then `send --confirmed` is called with the document's
key and Message-ID. The recipients are the document's, passed as the flags the provider builds the envelope from; no address of the text is
ever one. Results: `sent`; `replayed` (the key was done already, or the provider found the message in the Sent folder after an earlier
attempt lost its answer: nothing was sent again); `unknown` (the provider's exit code 4, or a call that timed out: the e-mail may or may not
have been sent; the effect stays open, and approving it again meets the provider's ledger); or a refusal with nothing sent (the provider's
exit 1 guarantees it).

From the person's own account (package W2, SPEC-SECRETARY-WRITES 3.2). A document with an `account` (runtime/send_document.py) is sent by the mailer of that account
(`gmail` for google, `outlook` for microsoft: implementations of the same class, named explicitly, never "auto"), with the account token (`GOOGLE_ACCOUNT_TOKEN`,
`MICROSOFT_ACCOUNT_TOKEN`) as the one secret in the mailer's environment; the dry run is started without it. Every rule above holds for it as it does for the outbox:
the approval of the exact hash, all or none of the recipients, the whole card, no attachment approvable on a messaging card, at most once per key, `unknown` on the
mailer's exit code 4. What differs: `preflight` finds the account in the project's `accounts` with the address of the document (limit L55), the From of the document
is the account's address (the mailer checks it again against the token), and the sentence that says how to settle an unknown outcome names the account's sent mail.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402
import mail_address  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import send_document  # noqa: E402
from send_document import WORD, document, check, title, describe, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

PROVIDER_CLASS = "sender:email"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a send: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the provider's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-send"      # decision POL-1: the group a project's policy grants to let a messaging app approve a send
APPROVAL_GROUP_OWN = "approve-effect-send-own"      # an e-mail from the person's own account has a grant of its own: the outbox's does not cover it (decision of 2026-10-19)
NOTHING_DONE = "nothing was sent"      # the words ops_step_effects.py starts a refusal with
PASSWORD = "MAILER_SMTP_PASSWORD"
SECRET_OF = {"google": "GOOGLE_ACCOUNT_TOKEN", "microsoft": "MICROSOFT_ACCOUNT_TOKEN"}      # the one secret the mailer of an own-account e-mail is given
UNKNOWN_EXIT = 4          # the provider's exit code for "the e-mail may or may not have been sent"
CALL_TIMEOUT = 300        # seconds: 18 MB of attachments over a slow line
UNKNOWN_NEXT = ("the outcome is unknown: look in the outbox account's Sent folder. The effect stays open. Approving it again with the same hash "
                "looks there first: found, it is recorded as sent; not found, nothing is sent and it stays unknown until you settle the key with "
                "the provider's `resolve` (providers/mailer/README.md): --sent if it was delivered, --not-sent if it was not, after which "
                "approving again sends it. Some hosts do not file mail sent over SMTP in the Sent folder, and then 'not found' says nothing: "
                "check with a recipient or the host's log first, because --not-sent can lead to a second copy")
UNKNOWN_NEXT_ACCOUNT = ("the outcome is unknown: look in the sent mail of your account. The effect stays open. Approving it again with the same hash looks there first "
                        "(by the message's own Message-ID): found, it is recorded as sent; not found, nothing is sent and it stays unknown until you settle the key with the "
                        "mailer's `resolve` (providers/mailer/README.md): --sent if it was delivered, --not-sent if it was not, after which approving again sends it. A "
                        "service may give a sent message another Message-ID than the one it was asked to carry, and then 'not found' says nothing: look in the sent mail "
                        "first, because --not-sent can lead to a second copy")
STALE_NOTE = ("Nothing was sent by this attempt: an attachment is not the file the task read (it was edited or replaced). The task starts "
              "over from the step that reads the files; start it again to be asked about the e-mail as it is now.")


class StaleError(effects.EffectError):
    """An attachment is not the file the task read."""

    def __init__(self, reason: str):
        super().__init__("stale", reason)
        self.answer = STALE_NOTE


class UnknownError(effects.EffectError):
    """The outcome of the send is not known."""

    def __init__(self, reason: str, account: bool = False):
        super().__init__("unknown", reason)
        self.next = UNKNOWN_NEXT_ACCOUNT if account else UNKNOWN_NEXT


def approval_word(doc) -> str:
    """The word the policy is asked about for this document: `send` for the outbox's e-mail, `send-own` for one from the person's own account (the group
    `approve-effect-send-own`; a sender granted `approve-effect-send` does not gain it)."""
    return "send-own" if send_document.is_own(doc) else "send"


def is_long(doc) -> bool:
    """Whether the send is made without the project's write lock, under the lock of the decision: every send is. It opens connections, takes
    seconds to minutes (20 recipients, a slow line, 18 MB), and an answer of the decision must be refused while it runs ("being written"), and a
    cancel of its request must leave the decision open (ops_cancel): the e-mail would otherwise be delivered after the decision was closed, and
    its record refused."""
    return isinstance(doc, dict)


def on_cards(doc) -> bool:
    """Whether the whole e-mail can be on a messaging card: the text is, the files are not, and the hash covers them."""
    return not (isinstance(doc, dict) and doc.get("attachments"))


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (runtime/send_document.py key_of), not the pending decision's."""
    return doc["idempotency_key"]


def provider_setting(cfg: dict):
    """The implementation the project's outbox names, or None for "auto" (the resolver chooses)."""
    chosen = (cfg.get("outbox") or {}).get("provider", "auto")
    return None if chosen == "auto" else chosen


def resolved_provider(cfg: dict, root: str):
    """The name of the implementation of the class sender:email that this project and this machine resolve to, or a sentence that says why
    none does."""
    resolve = project_config.resolver(root)
    try:
        return resolve.resolve(PROVIDER_CLASS, root=root, implementation=provider_setting(cfg))["implementation"], None
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return None, str(e)


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this send now, else None: the outbox is configured, names the sender
    the document has, and resolves to the provider the document was prepared for. Nothing is sent when it answers."""
    if send_document.is_own(doc):
        return preflight_own(cfg, doc, root)
    outbox = cfg.get("outbox")
    if not outbox:
        return 3, "the project has no outbox configured (the key outbox of docs/workbench/runtime.json): nothing was sent"
    if mail_address.address_key(outbox["from"]) != mail_address.address_key(doc.get("from") or ""):
        return 1, "nothing was sent: the project's outbox sender is not the one the e-mail was prepared for"
    name, why = resolved_provider(cfg, root)
    if name is None:
        return 3, f"nothing was sent: the e-mail provider does not resolve: {why}"
    if name in project_config.OWN_ACCOUNT_MAILERS:
        return 3, "nothing was sent: the project's outbox resolves to a mailer of an own account; the outbox is an SMTP account"
    if name != doc.get("provider"):
        return 1, "nothing was sent: the project's e-mail provider is not the one the effect was prepared for"
    return None


def preflight_own(cfg: dict, doc: dict, root: str):
    """The preflight of an e-mail from the person's own account: the account is one the project's `accounts` lists, with the address the document has (limit L55: the
    token could send as its owner and nothing else, and the project says which account the platform may send from), the document names the mailer of that
    account, and that mailer is shipped and serves the class. Nothing is sent when it answers."""
    entry = project_config.account_entry(cfg, doc.get("account"))
    if entry is None:
        return 3, phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(doc.get("account"), 20)) + " Nothing was sent."
    if mail_address.address_key(entry["address"]) != mail_address.address_key(doc.get("from") or ""):
        return 1, "nothing was sent: the account's address is not the one the e-mail was prepared for"
    if doc.get("provider") != send_document.ACCOUNTS.get(doc["account"]):
        return 1, "nothing was sent: the mailer of the document is not the mailer of its account"
    resolve = project_config.resolver(root)
    try:
        resolve.resolve(PROVIDER_CLASS, root=root, implementation=doc["provider"])
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return 3, f"nothing was sent: the e-mail provider does not resolve: {e}"
    return None


def caller(cfg: dict, root: str):
    """The `call(verb, args)` that reaches the provider the project's outbox resolves to. The provider starts with the minimum environment
    and the outbox password if it is in the environment: no other secret of this process reaches it. A call that timed out, or whose
    provider exited with UNKNOWN_EXIT, is `unknown`; any other refusal is a failure with nothing sent."""
    resolve = project_config.resolver(root)
    implementation = provider_setting(cfg)

    def call(verb, args, account=None):
        # An own-account e-mail goes to the mailer of its account, with that account's token as the one secret: a dry run is started without it (it reads no
        # credential and opens no connection). The outbox keeps its password.
        named, passes = (send_document.ACCOUNTS[account], () if "--dry-run" in args else (SECRET_OF[account],)) if account else (implementation, (PASSWORD,))
        try:
            return resolve.call(PROVIDER_CLASS, verb, args, root=root, implementation=named, timeout=CALL_TIMEOUT,
                                env=resolve.provider_environment(PROVIDER_CLASS, None, passes))
        except resolve.ProviderCallError as e:
            if e.kind == "timeout" or e.exit_code == UNKNOWN_EXIT:
                raise UnknownError(f"{verb}: {e.reason}", account=bool(account)) from None
            raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None
    return call


def _private_file(folder: str, name: str, data: bytes) -> str:
    path = os.path.join(folder, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def read_project_file(project: str, rel: str, limit: int) -> bytes:
    """The bytes of a regular file of the project, opened component by component from a descriptor of the project's folder with O_NOFOLLOW
    (a link anywhere on the way is refused), at most `limit` bytes. OSError, ValueError when it is not there, is a link or is a folder."""
    parts = rel.split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise ValueError("a path of the project")
    opened = []
    try:
        fd = os.open(os.path.realpath(project), os.O_RDONLY | os.O_DIRECTORY)
        opened.append(fd)
        for part in parts[:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            opened.append(fd)
        last = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        opened.append(last)
        if os.fstat(last).st_mode & 0o170000 != 0o100000:
            raise ValueError("not a regular file")
        with os.fdopen(os.dup(last), "rb") as f:
            data = f.read(limit + 1)
    finally:
        for descriptor in opened:
            os.close(descriptor)
    if len(data) > limit:
        raise ValueError("too large")
    return data


def _copy_attachments(doc: dict, folder: str, project) -> list:
    """The private copy of each attachment, by the path of the copy. StaleError when a file is not there or is not the one the task read."""
    paths = []
    for index, item in enumerate(doc["attachments"]):
        try:
            data = read_project_file(project, item["path"], item["bytes"]) if project else None
        except (OSError, ValueError):
            data = None
        if data is None or sha(data) != item["sha256"] or len(data) != item["bytes"]:
            raise StaleError(f"the attachment {item['name']} is not the file the task read")
        paths.append(_private_file(folder, f"attachment-{index}", data))
    return paths


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The send, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope
    action, status pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and
    unless `key` is the document's own. Then the document is checked again, the attachments are copied from the project to a private folder
    and compared with the hashes the task recorded (StaleError), the provider's dry run must hash to the document's dry_run_sha256
    (EffectError deviation), and `send --confirmed` is called with the document's key and Message-ID. `call(verb, args)` is the seam: the
    provider's one JSON object, or EffectError (UnknownError when the outcome is not known). `project` is the project's folder. Returns
    send_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is sent")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this e-mail derives: nothing is sent")
    folder = tempfile.mkdtemp(prefix="openhora-send-", dir=work_dir)
    try:
        attached = _copy_attachments(doc, folder, project)
        args = send_document.provider_args(doc, _private_file(folder, "subject.txt", doc["subject"].encode("utf-8")),
                                           _private_file(folder, "body.txt", doc["body"].encode("utf-8")), attached)
        own = send_document.is_own(doc)
        ask = (lambda verb, a: call(verb, a, account=doc["account"])) if own else call      # the seam keeps its two arguments for the outbox
        shown = ask("send", args + ["--dry-run"])
        if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
            raise effects.EffectError("deviation", "the provider would send something other than the e-mail that was previewed: nothing is sent")
        done = ask("send", args + ["--confirmed"])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(done, dict) or done.get("sent") is not True or done.get("message_id") != doc["message_id"]:
        raise UnknownError("the provider's answer is not a sent e-mail with this Message-ID: the e-mail may or may not have been sent", account=send_document.is_own(doc))
    return send_document.facts(doc, "replayed" if done.get("replayed") else "sent", done.get("service_message_id"))


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
