#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind registered under the side-effect word `publish` (runtime/effects.py KINDS): a facade over the two things the word does (package
PUBLISH-EFFECT). Before this package the word had one module, runtime/effect_reply.py, the reply to a comment under a standing approval. A registry
has one module for a word, so this module is the registry's row and holds both:

  the policy path (unchanged)   the names of runtime/effect_reply.py, re-exported as they are: POLICY, PROVIDER_CLASS, policy_platform,
                                policy_effect, policy_argv, resolve_targets, policy_judgement (and the constants a test reads). The document
                                is the one a handler hands to ops.execute_under_policy; `GATE` is False, so no skill's confirmation gate opens
                                an effect of this kind (a skill that publishes still opens a review, as before). effect_reply.py is not edited.
  the step path (new)           a post prepared by a step task of the kind `publish-post` (runtime/step_publish_post.py), approved by the hash of
                                its exact content, published now and once. The names of runtime/effect_send.py: the document (runtime/
                                publish_document.py: `document`, `check`, `title`, `body`, `summary`), `describe`, `execute`, and
                                PROVIDER_CLASS, GATE, POLICY, STEP, NOTHING_DONE, FORGETS_KEYS, `preflight`, `caller`, `idempotency_key`,
                                `is_long`, `on_cards`, APPROVAL_GROUP.

`describe` answers for both documents: a step document has the key `operation` ("post"), a reply's has not. `POLICY` is True for the word and
`STEP` is True; runtime/ops.py's list of the words a standing approval's bounds may name (`_bounds_words`) drops a word only when it is a STEP kind
and not a POLICY one (effects.step_only_words), so the reply's bounds keep naming `publish`. What a standing approval covers is the reply to a
comment on a post the project published, and no bound can name a post: the step path's approval is the hash of the exact text, each time.

Execution (`execute`, the step path's only place a post is published; reached from runtime/ops_step_effects.py `approve` and nowhere else). It
refuses unless `approval` is the person's approval of exactly this document (scope action, status pending-execution, payload_sha256 the hash of the
document's canonical text) and `key` is the document's own. Then the post is built again by the publishing skill's own script
(runtime/publish_payload.py) in a private folder, and the document must still be that post: the key, the slot, the text, the first comment and the
image (its source file opened with no link on the way and its hash) are compared, and another is `stale` (nothing is published, the decision is
answered and the task starts over from `prepare`). The files the script wrote are the files the publisher is given. The provider's dry run is made
again and, without the ledger's lines and the private folder's path, must equal the one in the document (else `deviation`; where a published key's
dry run names the post it holds, the document's placeholder stands for it), and print the document's ledger; the person's ledger variable and the
scheduled jobs pinned to this key are read too (else `deviation`); then `publish
--confirmed` is called with the document's key. Results: `published`; `replayed` (the ledger held this key with this content already, from the
publishing skill's job or from an earlier approval: nothing was published again); `unknown` (a timeout, or a failure after which the ledger
holds the key `pending`, or cannot be read: the post may or may not be out; the effect stays open, approving it again meets the ledger, and the
person settles a pending key with the provider's `resolve`); `published, but the call failed` (also `unknown`: the ledger holds the key as
published; if the first comment failed, approving again replays the post and retries only the comment); or a refusal with nothing published (the
ledger holds nothing under the key afterwards).

The key is the publishing skill's: the content file's name without `.md`. The ledger is the provider's, in the data folder both paths see
(runtime/publish_payload.py PASSES), so a post published by either path is not published again by the other.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effect_reply  # noqa: E402
import effects  # noqa: E402
import project_config  # noqa: E402
import publish_document  # noqa: E402
import publish_payload  # noqa: E402
from publish_document import WORD, document, check, title, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

# --- the policy path: the reply to a comment under a standing approval, exactly as effect_reply.py states it --------------------------------------
PROVIDER_CLASS = effect_reply.PROVIDER_CLASS      # publisher:<platform>
GATE = False      # no skill's confirmation gate names this word: the gate path never opens an effect of this kind
POLICY = True
VERB = effect_reply.VERB
TARGET_CLASS = effect_reply.TARGET_CLASS
policy_platform = effect_reply.policy_platform
policy_effect = effect_reply.policy_effect
policy_argv = effect_reply.policy_argv
resolve_targets = effect_reply.resolve_targets
policy_judgement = effect_reply.policy_judgement

# --- the step path: a post, approved by the hash of its exact content -------------------------------------------------------------------------
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the provider's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-publish"      # decision POL-1: the group a project's policy grants to let a messaging app approve a post
NOTHING_DONE = "nothing was published"      # the words ops_step_effects.py starts a refusal with
CALL_TIMEOUT = 420        # seconds: an image upload, the post, and the first comment's retries
CHECK_TIMEOUT = 90
UNKNOWN_NEXT = ("the outcome is unknown: look at the profile for the post. The effect stays open. Approving it again with the same hash asks the "
                "provider's ledger first: a key it holds as published is not published again. A key it holds as pending stays blocked, for this "
                "path and for the publishing skill's job, until you settle it with the provider's `resolve` verb (providers/publisher/README.md): "
                "give it the post's id if the post is there, or --not-published if it is not, after which approving again publishes it")
PARTIAL_NEXT = ("the provider's ledger holds this key as published, so neither this approval nor the publishing skill's job makes a second post. "
                "Read the reason: if it says the first comment failed, the post is out, and approving again with the same hash retries only the "
                "comment; if it says the key holds other content, the post under this key is another one and nothing was published by this attempt "
                "(reject this decision)")
STALE_NOTE = ("Nothing was published by this attempt: the post file, its first comment or its image is not what the task read (it was edited, "
              "replaced or can no longer be built). The task starts over from the step that reads; start it again to be asked about the post as it "
              "is now.")


class StaleError(effects.EffectError):
    """The post is not what the task read."""

    def __init__(self, reason: str):
        super().__init__("stale", reason)
        self.answer = STALE_NOTE


class UnknownError(effects.EffectError):
    """The outcome of the publication is not known."""
    next = UNKNOWN_NEXT

    def __init__(self, reason: str):
        super().__init__("unknown", reason)


class PartialError(UnknownError):
    """The ledger holds the key as published after a failed call: the post is out and its first comment failed, or the key holds another post."""
    next = PARTIAL_NEXT


def describe(doc: dict) -> str:
    """What is approved or done, in one line: for a step document (it has `operation`) the post, for the policy's document the reply."""
    if isinstance(doc, dict) and doc.get("operation") == publish_document.OPERATION:
        return publish_document.describe(doc)
    return effect_reply.describe(doc)


def is_long(doc) -> bool:
    """Whether the publication is made without the project's write lock, under the lock of the decision: every one is. It takes a request to the
    platform, an upload when there is an image and the first comment's retries, and a cancel or an answer of the decision must be refused while it
    runs: the post would otherwise go out after the decision was closed, and its record would be refused."""
    return isinstance(doc, dict)


def on_cards(doc) -> bool:
    """Whether the whole post can be on a messaging card: the text is, the image is not, and the hash covers it."""
    return not (isinstance(doc, dict) and doc.get("image"))


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (the content file's name, the publishing skill's key), not the pending decision's."""
    return doc["idempotency_key"]


def _resolve(root: str):
    return project_config.resolver(root)


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this publication now, else None: the class publisher:<platform> resolves to the
    provider the document was prepared for, and that provider's check says it is ready with a token not past its expiry. Nothing is published when
    it answers."""
    platform = doc.get("platform")
    try:
        cls = publish_payload.publisher_class(platform)
    except effects.EffectError as e:
        return 1, f"nothing was published: {e.reason}"
    resolve = _resolve(root)
    try:
        name = resolve.resolve(cls, root=root)["implementation"]
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return 3, f"nothing was published: the publisher does not resolve: {e}"
    if name != doc.get("provider"):
        return 1, "nothing was published: the project's publisher is not the one the post was prepared for"
    try:
        ready = resolve.call(cls, None, ["--check", "--platform", platform], root=root, timeout=CHECK_TIMEOUT,
                             env=publish_payload.environment(resolve, platform))
    except resolve.ProviderCallError as e:
        return (3 if e.kind == "not-configured" else 1), f"nothing was published: the publisher's check failed: {e.reason}"
    why = publish_payload.token_problem(ready)
    if why:
        return 3, f"nothing was published: {why}: renew it (the provider's auth.py, run by you), then approve again"
    return None


def _platform_in(args) -> str:
    found = args.index("--platform") if "--platform" in args else -1
    if found < 0 or found + 1 >= len(args):
        raise effects.EffectError("usage", "the publisher is called with --platform")
    return args[found + 1]


class Call:
    """The `call(verb, args)` that reaches the publisher the platform in `args` resolves to, and, beside it, `build`, which runs the publishing
    skill's script for a document. The provider starts with the minimum environment and the data folder's variable: no secret of this process
    reaches it (it reads its token from the secret store). A call that timed out while publishing is `unknown`; any other failure is one with a
    reason, and `execute` reads the ledger to know what it left."""

    def __init__(self, cfg: dict, root: str):
        self.cfg, self.root = cfg, root

    def __call__(self, verb, args):
        platform = _platform_in(args)
        resolve = _resolve(self.root)
        try:
            return resolve.call(publish_payload.publisher_class(platform), verb, args, root=self.root, timeout=CALL_TIMEOUT,
                                env=publish_payload.environment(resolve, platform))
        except resolve.ProviderCallError as e:
            if e.kind == "timeout" and "--confirmed" in args:
                raise UnknownError(f"{verb}: {e.reason}") from None
            raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None

    def build(self, doc: dict, project: str, work_dir=None):
        return publish_payload.build(self.root, project, doc["content"], doc["platform"], work_dir)

    def ledger_problem(self, doc: dict, args: list):
        """Why the ledger of the document may not be the one that decides whether this key was published (publish_payload.ledger_problem), or None."""
        return publish_payload.ledger_problem(_resolve(self.root), self.root, doc["platform"], doc["idempotency_key"], args, doc["ledger"])


def caller(cfg: dict, root: str):
    """The `call` that reaches the provider (see Call)."""
    return Call(cfg, root)


def _same_as_document(built, doc: dict) -> None:
    """StaleError unless the post just built is the document's: the key, the slot, the text, the first comment, the image."""
    image, theirs = doc["image"], built.image
    same_image = (image is None and theirs is None) or (image is not None and theirs is not None and
                                                         all(image[k] == theirs[k] for k in ("source", "name", "bytes", "sha256")))
    if built.key != doc["idempotency_key"] or built.at != doc["slot"] or built.text != doc["text"] or built.comment != doc["comment"] or not same_image:
        raise StaleError("the post is not the one the task read")


def _recorded(call, args):
    """What the ledger holds under the key now, by a dry run of the same call: "published", "pending", None (nothing) or "unreported"."""
    try:
        shown = call("publish", args + ["--dry-run"])
    except effects.EffectError:
        return "unreported"
    return shown.get("existing_status", "unreported") if isinstance(shown, dict) else "unreported"


def _after_failure(call, args, failure: effects.EffectError) -> effects.EffectError:
    """The error to raise after a failed `publish --confirmed`. A refusal before anything was sent (a usage error, a token that is not set up)
    stands as it is. Any other failure may have left the key in the ledger: published (the post is out; its first comment failed), pending (the
    outcome is unknown), or nothing (the key was released, so nothing was published); a ledger that says nothing about it is read as unknown."""
    if failure.kind in ("usage", "not-configured"):
        return failure
    state = _recorded(call, args)
    if state is None:
        return failure
    return PartialError(failure.reason) if state == "published" else UnknownError(failure.reason)


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The publication, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope action,
    status pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and unless `key` is the
    document's own. Then the document is checked again, the post is built again with the publishing skill's script (`call.build`) and must still be
    the document's (StaleError), the provider's dry run must equal the document's (EffectError deviation), and `publish --confirmed` is called with the
    document's key. `call(verb, args)` is the seam: the provider's one JSON object, or EffectError (UnknownError when the outcome is not known).
    `project` is the project's folder. Returns publish_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is published")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this post derives from its file: nothing is published")
    builder = getattr(call, "build", None)
    if builder is None or not project:
        raise effects.EffectError("not-configured", "the post cannot be built again without the project and the publishing skill's script: nothing is published")
    try:
        built = builder(doc, project, work_dir)
    except publish_payload.PayloadError as e:
        raise StaleError(f"the post can no longer be built as the task read it ({e.reason})") from None
    try:
        _same_as_document(built, doc)
        paths = built.paths
        args = publish_document.provider_args(doc["platform"], doc["idempotency_key"], paths["text"], paths["comment"], paths["image"])
        shown = call("publish", args + ["--dry-run"])
        if not publish_document.same_dry_run(doc["dry_run"], publish_document.stable_dry_run(shown, (built.folder,))):
            raise effects.EffectError("deviation", "the provider would publish something other than the post that was previewed: nothing is published")
        if doc["ledger"] is not None and shown.get("ledger") != doc["ledger"]:
            raise effects.EffectError("deviation", "the publisher's ledger is not the one the post was prepared with: nothing is published")
        why = getattr(call, "ledger_problem", lambda doc, args: None)(doc, args)
        if why:
            raise effects.EffectError("deviation", f"{why}: nothing is published")
        try:
            done = call("publish", args + ["--confirmed"])
        except UnknownError:
            raise
        except effects.EffectError as failure:
            raise _after_failure(call, args, failure) from None
    finally:
        built.cleanup()
    url = done.get("post_url") if isinstance(done, dict) else None
    if not isinstance(url, str) or not url or len(url) > 500:
        raise UnknownError("the provider's answer is not a published post: the post may or may not be out")
    first = done.get("first_comment")
    comment = "none" if doc["comment"] is None else ("replayed" if isinstance(first, dict) and first.get("replayed") else
                                                      "posted" if isinstance(first, dict) else "not_reported")
    return publish_document.facts(doc, {"replayed": done.get("replayed") is True, "post_url": url, "first_comment": comment})


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
