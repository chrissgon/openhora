"""Tests of the effect kind `publish` (CONS-2a): a reply to a comment on one of the project's own posts, executed by
ops.execute_under_policy under the engagement policy's standing approval. The kind module answers what the operation
asks of a kind (the platform, the effect checked, the verb, one line), resolves the target class from the publisher's
ledger, and runs the engagement gate and the credential scan on the exact text; the bounds of the policy are derived
by code from its block at approval. Offline: the stand-in tree of runtime/tests/standin_tree.py, a stand-in publisher
that records its calls and lists a ledger, the real engagement gate and sensitive-topics lock copied into the tree.
No network, no post. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_effect_reply.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import standin_tree as st

autonomy = st.load("autonomy")
effects = st.load("effects")
effect_reply = st.load("effect_reply")
isolated = st.load("isolated")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")

POLICY = "engagement-policy"
POLICY_FILE = "docs/marketing/engagement-policy.md"
POST = "urn:li:share:7400000000000000001"
COMMENT = "urn:li:comment:(urn:li:share:7400000000000000001,7400000000000000002)"
TEXT = "Thanks, Ana. Glad it helped.\n"
BLOCK = {"auto_reply_categories": ["thanks_or_praise"], "languages": ["EN"], "max_replies_per_day": 3,
         "max_auto_replies_per_person_per_post": 1, "reply_rules": {"max_sentences": 3, "max_emojis": 0,
                                                                   "max_hashtags": 0, "allow_links": False, "banned": []},
         "never_in_replies": []}
POLICY_TEXT = "# Engagement policy\n\n```engagement-policy\n" + json.dumps(BLOCK, indent=1) + "\n```\n"
PROFILE = ("# Profile\n\n```sensitive-topics\n{\"action\": \"never_reply_escalate_to_user\", \"topics\": "
           "{\"salary\": {\"keywords\": [\"salary\"], \"exclude\": []}}}\n```\n")

PUBLISHER = r'''# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
PLATFORMS = ("linkedin",)
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps(argv) + "\n")
if argv[0] == "posts":
    if os.path.exists(os.path.join(here, "ledger-fails")):
        print("the idempotency ledger is not valid JSON", file=sys.stderr)
        sys.exit(1)
    ledger = os.path.join(here, "ledger.json")
    urns = json.load(open(ledger)) if os.path.exists(ledger) else []
    posts = [{"idempotency_key": "post-%d" % n, "post_url": "https://www.linkedin.com/feed/update/%s/" % urn,
              "published_at": "2026-10-01T09:00:00+00:00"} for n, urn in enumerate(urns)]
    print(json.dumps({"platform": "linkedin", "since": argv[argv.index("--since") + 1], "ledger": ledger,
                      "posts": posts, "undated": []}))
elif argv[0] == "comment":
    if "--text-file" in argv:
        with open(os.path.join(here, "texts.jsonl"), "a") as f:
            f.write(json.dumps({"path": argv[argv.index("--text-file") + 1], "dry": "--dry-run" in argv,
                                "text": open(argv[argv.index("--text-file") + 1]).read()}) + "\n")
    print(json.dumps({"comment_urn": "urn:li:comment:(urn:li:share:1,2)", "replayed": False,
                      "dry_run": "--dry-run" in argv}))
'''


def ahead(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def reply_key(comment_id: str) -> str:
    return "reply-" + hashlib.sha256(comment_id.encode("utf-8")).hexdigest()[:32]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    root = built["tree"]
    monkeypatch.setattr(ops_core, "ROOT", str(root))
    for rel in ("scripts/validate.py", "skills/mkt-engage/scripts/policy_gate.py",
                "skills/mkt-engage/scripts/sensitive_topics.py", "shared/references/platforms/linkedin.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, root / rel)
    (root / "providers" / "publisher").mkdir(parents=True, exist_ok=True)
    (root / "providers" / "publisher" / "standin.py").write_text(PUBLISHER, encoding="utf-8")
    ledger(built, [POST])
    project = built["project"]
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    data["area_agents"] = {"planning": {"pack": "planning"},
                           "marketing": {"pack": "brand", "mode": "autonomous-with-policy"}}
    config.write_text(json.dumps(data))
    (project / "docs" / "marketing").mkdir(parents=True)
    (project / "docs" / "brand").mkdir(parents=True)
    (project / POLICY_FILE).write_text(POLICY_TEXT)
    (project / "docs" / "brand" / "profile.md").write_text(PROFILE)
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    return built


def ledger(tree, urns) -> None:
    (tree["tree"] / "providers" / "publisher" / "ledger.json").write_text(json.dumps(urns))


def project_of(tree) -> str:
    return str(tree["project"])


def approve(tree, days: int = 30) -> dict:
    digest = hashlib.sha256((tree["project"] / POLICY_FILE).read_bytes()).hexdigest()
    return ops.approve_policy(project_of(tree), POLICY_FILE, "marketing", digest, ahead(days))


def publisher_calls(tree) -> list:
    path = tree["tree"] / "providers" / "publisher" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def texts(tree) -> list:
    """What the stand-in publisher read from the --text-file it was given, per comment call."""
    path = tree["tree"] / "providers" / "publisher" / "texts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def sent(tree) -> list:
    """The confirmed calls of the stand-in publisher: what went out."""
    return [c for c in publisher_calls(tree) if c[0] == "comment" and "--confirmed" in c]


def run_folder(tree, name="1"):
    """The run folder the handler writes in: runs/<n> of the project's data folder."""
    folder = tree["data"] / "runs" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def document(tree, name="effect.json", text=TEXT, comment=None, decision=None, folder_name="1", **changes) -> str:
    """An effect document as the social handler writes it, with its files beside it; returns the effect file."""
    folder = run_folder(tree, folder_name)
    comment = comment or {"comment_urn": COMMENT, "post_urn": POST, "parent_comment_urn": COMMENT, "commenter": "Ana Lima",
                          "text": "Great post, thanks!", "received_at": "2026-10-09T10:00:00Z"}
    (folder / "comment.json").write_text(json.dumps(comment))
    (folder / "sources.json").write_text("[]")
    (folder / "decision.json").write_text(json.dumps(decision or {"category": "thanks_or_praise", "language": "EN"}))
    (folder / "reply.txt").write_text(text)
    doc = {"policy": POLICY, "kind": "publish", "target": POST,
           "files": [str(folder / n) for n in ("comment.json", "sources.json", "decision.json", "reply.txt")],
           "items": 1, "idempotency_key": reply_key(COMMENT),
           "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
           "args": ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", COMMENT,
                    "--text-file", str(folder / "reply.txt")]}
    doc.update(changes)
    doc = {k: v for k, v in doc.items() if v is not None}
    path = folder / name
    path.write_text(json.dumps(doc))
    return str(path)


def execute(tree, **kw) -> dict:
    replay_log = kw.pop("replay_log", None)
    path = document(tree, **kw)
    if replay_log is not None:
        return ops.execute_under_policy(project_of(tree), POLICY, path, replay_log=replay_log)
    return ops.execute_under_policy(project_of(tree), POLICY, path)


def actions(tree) -> list:
    import sqlite3
    with sqlite3.connect(str(tree["db"])) as db:
        return db.execute("SELECT kind, target, payload_sha256, idempotency_key FROM actions").fetchall()


# --- the kind module: what the operation asks of a kind -----------------------------------------------------------


def plain_document(**changes) -> dict:
    files = ["/run/1/comment.json", "/run/1/sources.json", "/run/1/decision.json", "/run/1/reply.txt"]
    doc = {"policy": POLICY, "kind": "publish", "target": POST, "files": files, "items": 1,
           "idempotency_key": reply_key(COMMENT), "payload_sha256": "ab" * 32,
           "args": ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", COMMENT,
                    "--text-file", "/run/1/reply.txt"]}
    doc.update(changes)
    return doc


def test_the_kind_is_registered_under_publish_and_runs_only_under_a_policy():
    assert effects.KINDS["publish"] == "effect_reply"
    assert effects.module_for("publish") is effect_reply
    assert effect_reply.POLICY is True and effect_reply.GATE is False
    assert effect_reply.PROVIDER_CLASS == "publisher:<platform>"
    assert "publish" in effects.policy_kinds()
    for name in ("policy_platform", "policy_effect", "policy_argv", "describe", "resolve_targets", "policy_judgement"):
        assert callable(getattr(effect_reply, name)), name


def test_the_kind_reads_the_platform_the_effect_and_the_verb_from_the_document():
    doc = plain_document()
    assert effect_reply.policy_platform(doc) == "linkedin"
    assert effect_reply.policy_effect(doc) == {"kind": "publish", "target": POST, "files": [], "items": 1}
    assert effect_reply.policy_argv(doc) == ["comment", *doc["args"]]
    assert effect_reply.describe(doc) == f"reply to a comment on post {POST}"
    assert effect_reply.TARGET_CLASS == "comment-on-published-post"


@pytest.mark.parametrize("changes", [
    {"args": ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", COMMENT]},               # no text file
    {"args": ["--platform", "linkedin", "--post-id", POST, "--text-file", "/run/1/reply.txt"]},            # no parent
    {"args": ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", COMMENT, "--text-file",
              "/run/1/reply.txt", "--ledger", "/elsewhere.json"]},                                      # a flag outside the set
    {"args": ["--platform", "linkedin", "--platform", "other", "--post-id", POST, "--parent-comment-id", COMMENT,
              "--text-file", "/run/1/reply.txt"]},                                                       # a flag twice
    {"args": ["--platform", "--post-id", POST, "--parent-comment-id", COMMENT, "--text-file", "/run/1/reply.txt"]},
    {"target": "urn:li:share:7400000000000000009"},                                                      # not the post id
    {"items": 2},                                                                                        # a reply is one
    {"files": ["/run/1/comment.json", "/run/1/sources.json", "/run/1/reply.txt"]},                       # no decision file
    {"files": ["/run/1/comment.json", "/run/1/sources.json", "/run/1/decision.json", "/run/2/reply.txt"]},
    {"files": ["comment.json", "sources.json", "decision.json", "reply.txt"]},                           # not absolute
])
def test_a_document_that_is_not_a_reply_is_refused_by_the_kind_with_a_usage_error(changes):
    for call in (effect_reply.policy_platform, effect_reply.policy_effect, effect_reply.policy_argv):
        with pytest.raises(effects.EffectError) as refused:
            call(plain_document(**changes))
        assert refused.value.kind == "usage"


# --- the target class: resolved from the publisher's ledger ---------------------------------------------------


def ledger_answer(*urns, undated=()):
    return {"platform": "linkedin", "since": "x", "ledger": "/ledger.json", "undated": list(undated),
            "posts": [{"idempotency_key": f"k{n}", "post_url": f"https://www.linkedin.com/feed/update/{urn}/",
                       "published_at": "2026-10-01T09:00:00+00:00"} for n, urn in enumerate(urns)]}


def cfg_of(tree=None):
    return {"workbench": str(st.REPO)}


def test_the_ledger_is_read_through_the_readonly_verb_and_the_post_ids_come_back_as_the_class():
    seen = []

    def resolve_call(cls, verb, args):
        seen.append((cls, verb, args))
        return ledger_answer(POST, "urn:li:ugcPost:7400000000000000003")

    out = effect_reply.resolve_targets(cfg_of(), plain_document(), resolve_call)
    assert out == {"comment-on-published-post": {POST, "urn:li:ugcPost:7400000000000000003"}}
    assert seen == [("publisher:linkedin", "posts", ["--platform", "linkedin", "--since", "1970-01-01T00:00:00+00:00"])]


def test_an_entry_that_is_not_a_post_url_of_the_platform_is_left_out_and_an_empty_ledger_is_an_empty_set():
    answer = ledger_answer(POST)
    answer["posts"].append({"idempotency_key": "x", "post_url": "https://elsewhere.example/feed/update/urn:li:share:1/"})
    answer["posts"].append({"idempotency_key": "y", "post_url": "https://www.linkedin.com/feed/update/not-a-urn/"})
    answer["posts"].append({"idempotency_key": "z"})
    assert effect_reply.resolve_targets(cfg_of(), plain_document(), lambda *a: answer) == \
        {"comment-on-published-post": {POST}}
    assert effect_reply.resolve_targets(cfg_of(), plain_document(), lambda *a: ledger_answer(undated=["old"])) == \
        {"comment-on-published-post": set()}


def test_a_ledger_that_cannot_be_read_or_makes_no_sense_is_an_error_the_operation_turns_into_not_covered():
    def failing(cls, verb, args):
        raise effects.EffectError("provider", "posts: the idempotency ledger is not valid JSON")

    with pytest.raises(effects.EffectError) as refused:
        effect_reply.resolve_targets(cfg_of(), plain_document(), failing)
    assert "ledger could not be read" in refused.value.reason and "not valid JSON" in refused.value.reason
    for answer in ({"posts": "all"}, {"posts": [1]}, {}):
        with pytest.raises(effects.EffectError):
            effect_reply.resolve_targets(cfg_of(), plain_document(), lambda *a, _=answer: _)
    with pytest.raises(effects.EffectError):  # the platform's data file is not there
        effect_reply.resolve_targets({"workbench": "/nowhere"}, plain_document(), lambda *a: ledger_answer(POST))


# --- the judgement and the credential scan, on the exact text -------------------------------------------------


def fake_gate(answer=None, code=0, stderr=""):
    calls = []

    def run_script(script, args, *, cwd, timeout, stdin=None):
        calls.append({"script": script, "args": list(args), "cwd": cwd})
        return subprocess.CompletedProcess([script], code, json.dumps(answer) if answer is not None else "", stderr)

    run_script.calls = calls
    return run_script


def on_disk(tmp_path, text=TEXT, name="run", **changes):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "comment.json").write_text("{}")
    (folder / "sources.json").write_text("[]")
    (folder / "decision.json").write_text(json.dumps({"category": "thanks_or_praise", "language": "EN"}))
    (folder / "reply.txt").write_text(text)
    args = ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", COMMENT, "--text-file",
            str(folder / "reply.txt")]
    fields = {"files": [str(folder / n) for n in ("comment.json", "sources.json", "decision.json", "reply.txt")],
              "args": args, "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), **changes}
    return plain_document(**fields)


def judge(tmp_path, doc, run, root=None, **more):
    """policy_judgement with a private folder of its own, kept as judge.last; (ok, why, copies). The root is a checkout
    that holds the platform's data file (the parent comment is checked against it)."""
    judge.last = Path(tempfile.mkdtemp(prefix="private-", dir=tmp_path))
    return effect_reply.policy_judgement(root or str(st.REPO), "/project", doc, run, POLICY_FILE, str(judge.last), **more)


def test_the_judgement_runs_the_gate_isolated_on_the_private_copy_of_the_text(tmp_path):
    doc = on_disk(tmp_path)
    run = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    ok, why, copies = judge(tmp_path, doc, run, now="2026-10-09T10:00:00-03:00")
    private = str(judge.last / "reply.txt")
    assert (ok, why, copies) == (True, "", {"--text-file": private})
    assert Path(private).read_bytes() == TEXT.encode() and oct(Path(private).stat().st_mode & 0o777) == "0o600"
    (call,) = run.calls
    assert call["script"] == isolated.skill_script(str(st.REPO), "mkt-engage", "policy_gate.py") and call["cwd"] == "/project"
    args = call["args"]
    assert args[0] == "decide"
    named = {args[i]: args[i + 1] for i in range(1, len(args), 2)}
    folder = str(tmp_path / "run")
    assert named == {"--policy": POLICY_FILE, "--state": "docs/workbench/state.md",
                     "--log": "docs/marketing/engagement-log.jsonl", "--comment-file": f"{folder}/comment.json",
                     "--category": "thanks_or_praise", "--language": "EN", "--profile": "docs/brand/profile.md",
                     "--reply-file": private, "--sources-file": f"{folder}/sources.json",
                     "--skills-dir": f"{st.REPO}/skills", "--now": "2026-10-09T10:00:00-03:00"}  # the gate reads the copy


def test_a_gate_that_says_inbox_gives_its_reasons_as_the_why_and_a_gate_that_did_not_run_is_not_an_auto(tmp_path):
    doc = on_disk(tmp_path)
    ok, why, copies = judge(tmp_path, doc, fake_gate({"decision": "inbox", "reasons": [
        "comment touches sensitive topics ['salary']", "daily limit reached (3/3)"], "idempotency_key": reply_key(COMMENT)}))
    assert ok is False and copies == {} and "sensitive topics" in why and "daily limit reached (3/3)" in why
    ok, why, _ = judge(tmp_path, doc, fake_gate({"decision": "auto", "reasons": [], "idempotency_key": "reply-other"}))
    assert ok is False and "reply-other" in why and reply_key(COMMENT) in why  # the key is the document's, or nothing goes
    for run in (fake_gate(None, code=2, stderr="error: engagement-policy needs max_replies_per_day (int)"),
                fake_gate(None, code=0), fake_gate({"decision": "maybe"}), fake_gate([1])):
        ok, why, copies = judge(tmp_path, doc, run)
        assert ok is False and why and copies == {}


def test_the_text_is_the_one_the_document_hashed_and_holds_no_credential_before_the_gate_is_asked(tmp_path):
    never = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    changed = on_disk(tmp_path, payload_sha256="cd" * 32)
    ok, why, _ = judge(tmp_path, changed, never)
    assert ok is False and "hash" in why and never.calls == []
    token = "ghp" + "_" + "Z9" * 18  # built at run time: no credential-shaped literal in the repository
    leaked = on_disk(tmp_path, text=f"Thanks, Ana. The token is {token}.\n", name="leaked")
    ok, why, _ = judge(tmp_path, leaked, never)
    assert ok is False and "looks like a credential (GitHub token)" in why and token not in why and never.calls == []
    assert not list(judge.last.iterdir())  # nothing was copied of a text that was refused


def test_an_input_that_is_missing_or_a_link_is_refused_before_anything_runs(tmp_path):
    doc = on_disk(tmp_path)
    never = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    (tmp_path / "run" / "sources.json").unlink()
    ok, why, _ = judge(tmp_path, doc, never)
    assert ok is False and "sources.json" in why and never.calls == []
    (tmp_path / "elsewhere.json").write_text("[]")
    (tmp_path / "run" / "sources.json").symlink_to(tmp_path / "elsewhere.json")
    ok, why, _ = judge(tmp_path, doc, never)
    assert ok is False and "sources.json" in why and never.calls == []


SHORT = "urn:li:comment:(share:7400000000000000001,7400000000000000002)"


@pytest.mark.parametrize("parent, accepted", [
    (COMMENT, True),                                                                # a comment on the post
    ("urn:li:comment:(urn:li:share:7400000000000000009,7400000000000000002)", False),   # on another post
    ("urn:li:comment:(urn:li:activity:7400000000000000001,7400000000000000002)", False),  # the same number, another type
    ("urn:li:comment:(urn:li:share:7400000000000000001,abc)", False),               # not a comment id
    ("urn:li:share:7400000000000000001", False),                                    # a post, not a comment
    ("https://elsewhere.example/comment/1", False),                                 # an address
    (SHORT, True),                                                                  # the short form names the same post
])
def test_the_parent_comment_must_be_a_comment_on_the_post_of_the_request(tmp_path, parent, accepted):
    args = ["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", parent, "--text-file", str(tmp_path / "run" / "reply.txt")]
    doc = on_disk(tmp_path, args=args)
    run = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    ok, why, _ = judge(tmp_path, doc, run)
    assert ok is accepted and (bool(run.calls) is accepted) and (accepted or "parent comment" in why)


def test_the_short_form_of_a_comment_id_is_a_comment_on_the_post_it_names(tmp_path):
    post = "urn:li:activity:111"
    args = ["--platform", "linkedin", "--post-id", post, "--parent-comment-id", "urn:li:comment:(activity:111,5)",
            "--text-file", str(tmp_path / "run" / "reply.txt")]
    run = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    assert judge(tmp_path, on_disk(tmp_path, args=args, target=post), run)[0] is True
    args = ["--platform", "linkedin", "--post-id", post, "--parent-comment-id", "urn:li:comment:(activity:222,5)",
            "--text-file", str(tmp_path / "other2" / "reply.txt")]
    ok, why, _ = judge(tmp_path, on_disk(tmp_path, args=args, target=post, name="other2"), run)
    assert ok is False and "not a comment on the post" in why


def test_a_folder_that_is_not_a_run_folder_of_the_data_folder_is_refused_but_not_in_a_replay(tmp_path):
    data = tmp_path / "data"
    (data / "runs" / "7").mkdir(parents=True)
    run = fake_gate({"decision": "auto", "reasons": [], "idempotency_key": reply_key(COMMENT)})
    doc = on_disk(tmp_path)
    ok, why, _ = judge(tmp_path, doc, run, data_dir=str(data))
    assert ok is False and "runs/<n>" in why and run.calls == []
    assert judge(tmp_path, doc, run, data_dir=str(data), log="/copy/of/the/log")[0] is True  # a replay executes nothing
    inside = on_disk(data / "runs", name="7x")  # a folder of runs/ that is not a number
    assert judge(tmp_path, inside, fake_gate({}), data_dir=str(data))[0] is False
    (data / "runs" / "7").rmdir()
    good = on_disk(data / "runs", name="7")
    assert judge(tmp_path, good, run, data_dir=str(data))[0] is True


# --- the operation: the bounds derived from the policy, the class resolved, the judgement, the call ---------------


def test_an_engagement_policy_is_approved_with_bounds_derived_from_its_block(tree):
    shown = ops.approve_policy(project_of(tree), POLICY_FILE, "marketing")
    assert shown["policy"] == POLICY
    assert shown["bounds"] == {"policy": POLICY, "agent": "marketing", "effects": ["publish"],
                               "targets": ["comment-on-published-post"], "files": [], "max_per_day": 3,
                               "max_items_per_run": 1, "file": POLICY_FILE}
    row = approve(tree)
    assert row["bounds"] == shown["bounds"] and ops.standing(project_of(tree), POLICY)["covered"] is True
    assert ops.standing(project_of(tree), POLICY)["approval"]["bounds"]["max_per_day"] == 3


def test_a_changed_block_is_a_changed_file_the_approval_no_longer_covers_and_the_next_approval_derives_again(tree):
    approve(tree)
    path = tree["project"] / POLICY_FILE
    path.write_text(POLICY_TEXT.replace('"max_replies_per_day": 3', '"max_replies_per_day": 9'))
    assert ops.standing(project_of(tree), POLICY)["covered"] is False
    assert execute(tree)["executed"] is False and sent(tree) == []
    again = approve(tree)
    assert again["bounds"]["max_per_day"] == 9 and ops.standing(project_of(tree), POLICY)["covered"] is True


def test_a_block_without_a_daily_cap_is_refused_at_approval_and_a_policy_without_a_block_keeps_three_keys(tree):
    path = tree["project"] / POLICY_FILE
    path.write_text(POLICY_TEXT.replace('"max_replies_per_day": 3,', ""))
    with pytest.raises(ops.OpsError) as refused:
        ops.approve_policy(project_of(tree), POLICY_FILE, "marketing")
    assert refused.value.code == 2 and "max_replies_per_day" in str(refused.value)
    path.write_text("# A policy kept as prose\n")
    shown = ops.approve_policy(project_of(tree), POLICY_FILE, "marketing")
    assert shown["bounds"] == {"policy": POLICY, "agent": "marketing", "file": POLICY_FILE}


def test_a_reply_to_a_comment_on_a_post_the_ledger_records_is_sent_once_by_the_operation(tree):
    approved = approve(tree)
    out = execute(tree)
    assert out["executed"] is True and out["approval_id"] == approved["id"] and out["action"]["created"] is True
    calls = publisher_calls(tree)
    assert [c[0] for c in calls] == ["posts", "comment", "comment"]
    assert calls[0][calls[0].index("--since") + 1] == "1970-01-01T00:00:00+00:00"
    dry, real = calls[1], calls[2]
    assert dry[-1] == "--dry-run" and real[-1] == "--confirmed" and dry[:-1] == real[:-1]
    flags = {real[i]: real[i + 1] for i in range(1, len(real) - 1, 2)}
    assert flags["--platform"] == "linkedin" and flags["--post-id"] == POST and flags["--parent-comment-id"] == COMMENT
    assert flags["--idempotency-key"] == reply_key(COMMENT) and "--allow" not in real
    assert flags["--text-file"].endswith("reply.txt")
    assert actions(tree) == [(POLICY, POST, hashlib.sha256(TEXT.encode()).hexdigest(), reply_key(COMMENT))]
    assert ops.standing(project_of(tree), POLICY)["executed_today"] == 1


def test_a_post_the_ledger_does_not_record_is_not_covered_whatever_the_notification_said(tree):
    approve(tree)
    ledger(tree, ["urn:li:share:7400000000000000099"])
    out = execute(tree)
    assert out["executed"] is False and "comment-on-published-post" in out["why"] and sent(tree) == []
    assert [c[0] for c in publisher_calls(tree)] == ["posts"] and actions(tree) == []
    ledger(tree, [])
    out = execute(tree)
    assert out["executed"] is False and sent(tree) == []


def test_a_ledger_that_cannot_be_read_covers_nothing_and_runs_nothing(tree):
    approve(tree)
    (tree["tree"] / "providers" / "publisher" / "ledger-fails").write_text("")
    out = execute(tree)
    assert out["executed"] is False and "ledger could not be read" in out["why"]
    assert [c[0] for c in publisher_calls(tree)] == ["posts"] and actions(tree) == []


def test_the_gate_sending_the_reply_to_the_inbox_runs_nothing_and_the_reasons_are_the_why(tree):
    approve(tree)
    out = execute(tree, comment={"comment_urn": COMMENT, "post_urn": POST, "parent_comment_urn": COMMENT,
                                 "commenter": "Ana Lima", "text": "Nice! What is your salary?",
                                 "received_at": "2026-10-09T10:00:00Z"})
    assert out["executed"] is False and "sensitive topics" in out["why"] and "engagement gate" in out["why"]
    out = execute(tree, decision={"category": "criticism_or_disagreement", "language": "EN"})
    assert out["executed"] is False and "always goes to the user" in out["why"]
    assert sent(tree) == [] and actions(tree) == []
    assert all(c[0] == "posts" for c in publisher_calls(tree))  # not even the dry run


def test_both_conditions_hold_the_gates_auto_alone_sends_nothing(tree):
    # No standing approval: the gate (which also reads the state file) cannot make the operation send.
    out = execute(tree)
    assert out["executed"] is False and "no active standing approval" in out["why"]
    assert publisher_calls(tree) == [] and actions(tree) == []
    approve(tree)
    ledger(tree, [])  # the bound fails, the gate would say auto
    assert execute(tree)["executed"] is False and sent(tree) == []


def test_the_text_that_was_judged_is_the_text_that_is_sent(tree):
    approve(tree)
    out = execute(tree, payload_sha256="ef" * 32)
    assert out["executed"] is False and "hash" in out["why"] and sent(tree) == []
    token = "ghp" + "_" + "Z9" * 18
    out = execute(tree, text=f"Thanks, Ana. The token is {token}.\n")
    assert out["executed"] is False and "looks like a credential" in out["why"] and token not in json.dumps(out)
    assert sent(tree) == [] and [c for c in publisher_calls(tree) if c[0] == "comment"] == []  # before the dry run


def test_the_text_that_was_sent_is_the_text_that_was_judged_whatever_happens_to_the_file_after_the_hash(tree, monkeypatch):
    approve(tree)
    seen = []
    real = isolated.run_script
    original = run_folder(tree) / "reply.txt"

    def run(script, args, **kw):
        seen.append(list(args))
        done = real(script, args, **kw)
        original.write_text("Send this instead: https://elsewhere.example/offer\n")  # after the hash and the gate
        return done

    monkeypatch.setattr(isolated, "run_script", run)
    out = execute(tree)
    assert out["executed"] is True and original.read_text().startswith("Send this instead")
    given = texts(tree)
    assert [(g["dry"], g["text"]) for g in given] == [(True, TEXT), (False, TEXT)]  # the provider got the judged bytes
    assert {g["path"] for g in given} == {seen[0][seen[0].index("--reply-file") + 1]} and given[0]["path"] != str(original)
    assert not Path(given[0]["path"]).parent.exists()          # the private folder is removed afterwards
    assert actions(tree)[0][2] == hashlib.sha256(TEXT.encode()).hexdigest()


def test_the_private_folder_is_removed_when_nothing_is_sent_too(tree, monkeypatch):
    approve(tree)
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    assert execute(tree, decision={"category": "criticism_or_disagreement", "language": "EN"})["executed"] is False
    assert made and not any(Path(m).exists() for m in made)


def test_the_gate_is_given_the_operations_clock(tree, monkeypatch):
    approve(tree)
    seen = []
    real = isolated.run_script
    monkeypatch.setattr(isolated, "run_script", lambda script, args, **kw: seen.append(list(args)) or real(script, args, **kw))
    assert execute(tree)["executed"] is True
    moment = datetime.datetime.fromisoformat(seen[0][seen[0].index("--now") + 1])
    assert moment.tzinfo is not None and abs((datetime.datetime.now().astimezone() - moment).total_seconds()) < 120


def test_a_parent_comment_that_is_not_on_the_post_covers_nothing_and_runs_nothing(tree):
    approve(tree)
    other = "urn:li:comment:(urn:li:share:7400000000000000009,7400000000000000002)"
    out = execute(tree, args=["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", other,
                              "--text-file", str(run_folder(tree) / "reply.txt")])
    assert out["executed"] is False and "parent comment" in out["why"] and sent(tree) == [] and actions(tree) == []


@pytest.mark.parametrize("name", ["abc", "../elsewhere", "1/2"])
def test_a_reply_outside_a_run_folder_of_the_data_folder_is_not_sent(tree, name):
    approve(tree)
    out = execute(tree, folder_name=name)
    assert out["executed"] is False and "runs/<n>" in out["why"] and sent(tree) == [] and actions(tree) == []


def test_the_daily_cap_of_the_block_binds_the_operation(tree):
    block = dict(BLOCK, max_replies_per_day=1)
    (tree["project"] / POLICY_FILE).write_text("```engagement-policy\n" + json.dumps(block) + "\n```\n")
    approve(tree)
    assert execute(tree)["executed"] is True
    comment = {"comment_urn": "urn:li:comment:(urn:li:share:7400000000000000001,7400000000000000008)", "post_urn": POST,
               "parent_comment_urn": "urn:li:comment:(urn:li:share:7400000000000000001,7400000000000000008)",
               "commenter": "Bruno", "text": "Thanks!", "received_at": "2026-10-09T10:05:00Z"}
    out = execute(tree, comment=comment, idempotency_key=reply_key(comment["comment_urn"]),
                  args=["--platform", "linkedin", "--post-id", POST, "--parent-comment-id", comment["comment_urn"],
                        "--text-file", str(run_folder(tree) / "reply.txt")])
    assert out["executed"] is False and "per day" in out["why"] and len(sent(tree)) == 1


def test_the_gate_is_run_through_the_isolated_runner_from_the_project_folder(tree, monkeypatch):
    approve(tree)
    seen = []
    real = isolated.run_script
    monkeypatch.setattr(isolated, "run_script", lambda script, args, **kw: seen.append((script, kw["cwd"])) or real(script, args, **kw))
    assert execute(tree)["executed"] is True
    assert seen == [(isolated.skill_script(str(tree["tree"]), "mkt-engage", "policy_gate.py"),
                     ops.project_config.load(project_of(tree))["project"])]


def test_a_replay_runs_every_check_and_nothing_else_and_judges_against_the_log_it_is_given(tree, tmp_path):
    approve(tree)
    log = tmp_path / "log.jsonl"
    log.write_text("")
    out = execute(tree, replay_log=str(log))
    assert out == {"executed": False, "policy": POLICY, "checked": True, "would_execute": True, "why": ""}
    assert [c[0] for c in publisher_calls(tree)] == ["posts"]          # the ledger read, no dry run, no call
    assert actions(tree) == [] and ops.standing(project_of(tree), POLICY)["executed_today"] == 0
    log.write_text(json.dumps({"action": "auto_replied", "comment_urn": COMMENT, "idempotency_key": reply_key(COMMENT),
                               "logged_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}) + "\n")
    out = execute(tree, replay_log=str(log))
    assert out["executed"] is False and out["would_execute"] is False and "already answered" in out["why"]
    ledger(tree, [])
    out = execute(tree, replay_log=str(tmp_path / "missing.jsonl"))
    assert out["executed"] is False and out["checked"] is True and out["would_execute"] is False
    assert sent(tree) == [] and actions(tree) == []
    assert not (tree["project"] / "docs" / "marketing" / "engagement-log.jsonl").exists()  # nothing written to the project


def test_the_shell_passes_the_replay_log_and_still_answers_with_one_json_object(tree, capsys):
    approve(tree)
    log = tree["project"].parent / "log.jsonl"
    log.write_text("")
    path = document(tree)
    argv = ["execute-under-policy", "--project", project_of(tree), "--policy", POLICY, "--effect-file", path,
            "--replay-log", str(log)]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["would_execute"] is True and sent(tree) == []


def test_a_class_bound_with_a_kind_that_cannot_resolve_it_covers_nothing(tree, monkeypatch):
    import sys
    import types
    kind = types.ModuleType("standin_resolveless_kind")
    kind.POLICY, kind.PROVIDER_CLASS = True, "publisher:<platform>"
    kind.policy_platform = lambda doc: "linkedin"
    kind.policy_effect = lambda doc: {"kind": "send", "target": POST, "files": [], "items": 1}
    kind.policy_argv = lambda doc: ["comment", *doc["args"]]
    kind.describe = lambda doc: "a stand-in"
    monkeypatch.setitem(sys.modules, "standin_resolveless_kind", kind)
    monkeypatch.setitem(effects.KINDS, "send", "standin_resolveless_kind")
    bounds = {"policy": "other-replies", "agent": "marketing", "effects": ["send"],
              "targets": ["comment-on-published-post"], "files": ["docs/x.md"], "max_per_day": 5, "max_items_per_run": 1}
    (tree["project"] / "docs" / "workbench" / "policies").mkdir()
    (tree["project"] / "docs" / "workbench" / "policies" / "other-replies.json").write_text(json.dumps(bounds))
    digest = hashlib.sha256((tree["project"] / "docs" / "workbench" / "policies" / "other-replies.json").read_bytes()).hexdigest()
    ops.approve_policy(project_of(tree), "docs/workbench/policies/other-replies.json", "marketing", digest, ahead(30))
    path = document(tree, kind="send", policy="other-replies")
    out = ops.execute_under_policy(project_of(tree), "other-replies", path)
    assert out["executed"] is False and "comment-on-published-post" in out["why"] and publisher_calls(tree) == []
