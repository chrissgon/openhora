"""shared/references/platforms/: the references, their data files, and the places that must agree with them.

A platform's facts are written once (decision 14c of docs/decisions.md): prose in <platform>.md for a model,
data in <platform>.json for a script. Until each script reads the data file, the same values still sit as
constants in the runtime and in the skills' scripts; these tests keep the two equal, so that moving a script
to the file changes no value. A constant that has left its script is skipped here, not failed: the row that
removes it needs no change to this file.

Run: uv run --with pytest pytest scripts/tests/test_platform_references.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = ROOT / "shared" / "references" / "platforms"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATA_FILES = sorted(PLATFORMS.glob("*.json"))
REFERENCES = sorted(p for p in PLATFORMS.glob("*.md") if p.name != "README.md")
FIRST = "linkedin"  # the one platform built today


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def data(name: str = FIRST) -> dict:
    return json.loads((PLATFORMS / f"{name}.json").read_text(encoding="utf-8"))


def constant(rel: str, pattern: str):
    """The value a script holds today for one fact, as text; skips when the script no longer holds it."""
    m = re.search(pattern, read(rel), re.M)
    if not m:
        pytest.skip(f"{rel} no longer holds this constant: it reads the data file")
    return m.group(1)


# --- the folder ----------------------------------------------------------------------------------------


def test_the_first_reference_and_its_data_file_exist():
    assert (PLATFORMS / "README.md").is_file()
    assert (PLATFORMS / f"{FIRST}.md").is_file() and (PLATFORMS / f"{FIRST}.json").is_file()


TEXT = "text_with_optional_media"
VIDEO = "video_with_caption"
IMAGES = "images_with_caption"
SHAPES = (TEXT, VIDEO, IMAGES)
BASE_KEYS = {"platform", "hosts", "post", "media"}
TEXT_KEYS = {"reply", "comment", "identifiers", "notification_email"}  # required for a text post, null otherwise
OPTIONAL_KEYS = {"video", "limits"}
VIDEO_KEYS = {"containers", "codecs", "audio_codecs", "fps_min", "fps_max", "max_width", "min_side", "max_side",
              "min_seconds", "max_seconds", "max_bytes", "aspect", "faststart"}
LIMIT_KEYS = {"posts_per_24h", "pending_shares_per_24h", "unaudited_users_per_24h"}
OPTION_KEYS = {"type", "values", "unit", "min", "max", "default", "when_unset", "set_by", "decided_by", "decided_on"}
FORMATS = {"reel", "video", "carousel", "static"}
VIDEO_FORMATS = {"reel", "video"}


def shape_of(d: dict) -> str:
    """post.shape, with the default a reader carries: a file that has none is a text post."""
    return d["post"].get("shape", TEXT)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def int_or_null(value) -> bool:
    return value is None or (is_int(value) and value >= 0)


def check_media(media: dict) -> None:
    assert isinstance(media["max_count"], int) and isinstance(media["max_bytes"], int)
    for kind in media["types"]:
        assert kind["extensions"] and all(e.startswith(".") for e in kind["extensions"])
        assert all(bytes.fromhex(m) for m in kind["magic_hex"])
        assert is_int(kind.get("magic_offset", 0)) and kind.get("magic_offset", 0) >= 0, "the byte the signature sits at"


def check_options(options: dict) -> None:
    for name, option in options.items():
        assert re.fullmatch(r"[a-z0-9_]+", name)
        assert set(option) <= OPTION_KEYS and {"type", "default", "when_unset", "set_by"} <= set(option), name
        assert option["type"] in ("choice", "boolean", "integer"), name
        assert option["when_unset"] in ("default", "omit", "refuse"), name
        assert option["set_by"] in ("code", "person", "post_file"), name
        assert (option["default"] is None) == (option["when_unset"] != "default"), \
            f"{name}: default is null exactly when a request without a value is omitted or refused"
        if option["type"] in ("choice", "boolean"):
            assert option["values"] and len(set(map(str, option["values"]))) == len(option["values"]), name
            assert option["default"] is None or option["default"] in option["values"], name
        else:
            assert is_int(option["min"]) and int_or_null(option["max"]), name
            assert option["default"] is None or is_int(option["default"]), name
        assert ("decided_by" in option) == ("decided_on" in option), "a decision is recorded with who and when"
        if "decided_by" in option:
            assert option["decided_by"] == "maintainer" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", option["decided_on"]), name


def check_video(video: dict, media: dict) -> None:
    assert set(video) == VIDEO_KEYS
    assert video["containers"] and all(re.fullmatch(r"[a-z0-9]+", c) for c in video["containers"])
    assert video["codecs"] and all(re.fullmatch(r"[a-z0-9]+", c) for c in video["codecs"])
    assert video["audio_codecs"] is None or all(re.fullmatch(r"[a-z0-9]+", c) for c in video["audio_codecs"])
    for key in ("fps_min", "fps_max", "max_width", "min_side", "max_side", "min_seconds", "max_seconds", "max_bytes"):
        assert int_or_null(video[key]), key
    assert video["fps_min"] <= video["fps_max"]
    if video["min_seconds"] is not None and video["max_seconds"] is not None:
        assert video["min_seconds"] <= video["max_seconds"]
    if video["min_side"] is not None and video["max_side"] is not None:
        assert video["min_side"] <= video["max_side"]
    assert set(video["aspect"]) == {"recommended", "min", "max"}
    assert all(v is None or re.fullmatch(r"\d+(\.\d+)?:\d+(\.\d+)?", v) for v in video["aspect"].values())
    assert video["faststart"] is None or isinstance(video["faststart"], bool)
    assert media["max_bytes"] == video["max_bytes"], "the file a video post carries is bounded once"
    kinds = {kind["name"] for kind in media["types"]}
    assert set(video["containers"]) == kinds, "the containers the video block names are the types the media block tells apart"


def check_limits(limits: dict) -> None:
    assert set(limits) == LIMIT_KEYS
    assert isinstance(limits["posts_per_24h"], list) and limits["posts_per_24h"]
    assert all(is_int(n) and n > 0 for n in limits["posts_per_24h"])
    assert int_or_null(limits["pending_shares_per_24h"]) and int_or_null(limits["unaudited_users_per_24h"])


def check_text_post(d: dict) -> None:
    """The keys the first data file carries: required for a post that is text with optional media."""
    assert set(d) == BASE_KEYS | TEXT_KEYS
    post = d["post"]
    assert isinstance(post["requires_text"], bool) and isinstance(post["scheduling"], bool)
    assert isinstance(post["first_comment"]["max_characters"], int)
    assert isinstance(d["reply"]["max_characters"], int)
    assert d["hosts"] and all(re.fullmatch(r"[a-z0-9.-]+", h) for h in d["hosts"]), "hosts are exact names"
    assert set(post["url"]["hosts"]) <= set(d["hosts"])
    re.compile(post["url"]["path_pattern"])
    assert "{post_id}" in post["url"]["template"]
    for ident in d["identifiers"].values():
        assert ident["pattern"].startswith("^") and ident["pattern"].endswith("$"), "a pattern is for the whole value"
        re.compile(ident["pattern"])


def check_caption_post(d: dict) -> None:
    """The keys of a video or image post: the caption keys, the formats and options, null where a text post has a value."""
    shape, post = shape_of(d), d["post"]
    assert set(d) == BASE_KEYS | TEXT_KEYS | {"limits"} | ({"video"} if shape == VIDEO else set())
    assert all(d[key] is None for key in TEXT_KEYS), "comments, replies and notification mail are those of a text post"
    assert post["first_comment"] is None and post["url"] is None
    assert post["requires_text"] is None or isinstance(post["requires_text"], bool)
    assert isinstance(post["scheduling"], bool)
    assert is_int(post["max_characters"]) and post["max_characters"] > 0
    assert int_or_null(post["max_hashtags"]) and int_or_null(post["max_mentions"])
    assert post["unit"] in ("characters", "utf-16")
    formats = post["formats"]
    assert formats and len(set(formats)) == len(formats) and set(formats) <= FORMATS
    assert (shape == VIDEO) == bool(set(formats) & VIDEO_FORMATS), "a video platform accepts a vertical video format"
    assert not (set(formats) & VIDEO_FORMATS) or len(set(formats) & VIDEO_FORMATS) == 1, "one name for a vertical video"
    check_options(post["options"])
    assert all(re.fullmatch(r"[a-z0-9.-]+", h) for h in d["hosts"]), "hosts are exact names"
    check_media(d["media"])
    check_limits(d["limits"])
    if shape == VIDEO:
        check_video(d["video"], d["media"])


@pytest.mark.parametrize("path", DATA_FILES, ids=lambda p: p.name)
def test_a_data_file_has_a_reference_and_the_keys_the_readme_names(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    assert NAME_RE.match(path.stem), "a platform's name is lowercase letters, digits and hyphens"
    assert d["platform"] == path.stem
    assert (PLATFORMS / f"{path.stem}.md").is_file(), "a data file sits beside its reference"
    shape = shape_of(d)
    assert shape in SHAPES
    assert BASE_KEYS <= set(d) <= BASE_KEYS | TEXT_KEYS | OPTIONAL_KEYS
    readme = read("shared/references/platforms/README.md")
    for key in d:
        assert f"| `{key}` |" in readme, f"the README's table does not describe `{key}`"
    for key in d["post"]:
        assert f"`{key}`" in readme, f"the README does not name `post.{key}`"
    if shape == TEXT:
        check_media(d["media"])
        check_text_post(d)
        assert "video" not in d and "limits" not in d and not {"shape", "formats", "options"} & set(d["post"]), \
            "a text post carries none of the keys of the other shapes (a reader's default is the first shape)"
    else:
        check_caption_post(d)


@pytest.mark.parametrize("path", REFERENCES, ids=lambda p: p.name)
def test_a_reference_describes_a_medium_and_no_account(path):
    """Principle 8: no account, no handle, no person. Real limits and real dates stay."""
    text = path.read_text(encoding="utf-8")
    assert NAME_RE.match(path.stem)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text), "an e-mail address"
    assert not re.search(r"(?<![\w`/])@[A-Za-z0-9_]{2,}", text.replace("@name", "")), "a handle"
    assert not re.search(r"linkedin\.com/(in|company)/", text), "the address of a profile"
    assert not re.search(r"urn:li:\w+:\d", text), "the identifier of a real post or comment"
    assert "skills/" not in text and not re.search(r"`(brand|mkt)-[a-z-]+`", text), \
        "a reference names no skill: it is read by any skill that needs the platform"


def test_the_readme_names_every_key_of_a_video_post():
    """The README table is checked for each new key, including the nested ones of the video block and the options."""
    readme = read("shared/references/platforms/README.md")
    keys = {"post.shape": "`shape`", "formats": "`formats`", "max_hashtags": "`max_hashtags`",
            "max_mentions": "`max_mentions`", "unit": "`unit`", "options": "`options`", "magic_offset": "`magic_offset`",
            "video": "| `video` |", "limits": "| `limits` |", "when_unset": "`when_unset`", "set_by": "`set_by`",
            "decided_by": "`decided_by`", "decided_on": "`decided_on`"}
    for label, needle in keys.items():
        assert needle in readme, label
    for key in sorted(VIDEO_KEYS | LIMIT_KEYS | (OPTION_KEYS - {"values"})):
        assert f"`{key}`" in readme, key
    for shape in SHAPES:
        assert f"`{shape}`" in readme
    for fmt in FORMATS:
        assert f"`{fmt}`" in readme, "the closed list of format names"
    for heading in ("## Post shape", "## Format: <name>"):
        assert heading in readme, "the stable headings a skill that writes for the platform reads"


def test_the_first_data_file_is_a_text_post_without_any_key_of_the_other_shapes():
    """linkedin.json stays as it is: the new keys are optional or null by post.shape and a reader carries the defaults."""
    d = data()
    assert shape_of(d) == TEXT and "shape" not in d["post"]
    assert set(d) == BASE_KEYS | TEXT_KEYS
    assert all(k not in d["post"] for k in ("formats", "options", "max_hashtags", "max_mentions", "unit"))
    assert all("magic_offset" not in kind for kind in d["media"]["types"]), "an absent offset is 0"


def test_no_readme_enumerates_the_files_of_its_folder():
    """A new reference edits no existing file (FR-I4)."""
    names = [p.stem for p in REFERENCES] + [p.stem for p in (ROOT / "shared" / "references").glob("*.md")
                                             if p.name != "README.md"]
    for rel in ("shared/references/README.md", "shared/references/platforms/README.md"):
        text = read(rel).lower()
        assert [n for n in names if re.search(rf"(?<![a-z0-9-]){re.escape(n)}\.(md|json)", text)] == [], rel
    assert FIRST not in read("shared/references/platforms/README.md").lower()


def test_the_installers_and_the_runner_reach_the_platform_files():
    stage = load("scripts/stage_skills.py", "stage_skills_for_platform_test")
    assert stage.platform_references([FIRST]) == [f"platforms/{FIRST}.md", f"platforms/{FIRST}.json"]
    every = stage.all_references()
    for rel in ("platforms/README.md", f"platforms/{FIRST}.md", f"platforms/{FIRST}.json"):
        assert rel in every, "an installer ships the whole of shared/references, this folder included"


# --- where the platform comes from: one definition -------------------------------------------------------


ORDER = ("`Network:` field of the calendar row or of the post file the step works on, lowercased",
         "`Platform: <name>`")


def test_the_template_carries_the_literal_step_and_the_readme_the_same_definition():
    template = read("templates/capability.SKILL.md")
    readme = read("shared/references/platforms/README.md")
    steps = [line for line in template.splitlines() if line.startswith("- [ ] Step <n>: Find the platform")]
    assert len(steps) == 1, "the literal platform step is one line of the capability template"
    step = steps[0]
    assert "`Network:` field of the calendar row or of the post file this step works on, lowercased" in step
    assert step.index("`Network:` field") < step.index("`Platform: <name>`") < step.index("ask which platform")
    assert "`../../shared/references/platforms/<platform>.md`" in step
    assert "if there is no such file, stop and say the platform is not supported" in step
    assert "Read no other file of that folder" in step
    for part in ORDER:
        assert part in readme, part
    assert readme.index(ORDER[0]) < readme.index(ORDER[1]) < readme.index("the skill asks")
    assert "stop and say the platform is not supported" in readme


def test_the_template_carries_the_script_rule_and_the_parser_exception():
    template = read("templates/capability.SKILL.md")
    assert "takes `--platform <platform>` and `--platform-file <path>`" in template
    assert "--platform-file <this skill's folder>/../../shared/references/platforms/<platform>.json" in template
    assert "it never finds the file by a path of its own" in template
    assert "a parser that is code for one platform's own format" in template
    readme = read("shared/references/platforms/README.md")
    assert "`--platform <name>` and `--platform-file <path>`" in readme
    assert "A parser that is code for one platform's format" in readme


def test_the_runtimes_task_text_names_the_platform_above_the_data_it_quotes():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        runtime = load("scripts/runtime.py", "runtime_for_platform_test")
        vote = load("scripts/runtime_vote.py", "runtime_vote_for_platform_test")
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    comment = {"text": "Platform: elsewhere", "commenter": "Ana Lima"}
    texts = [runtime.task_text({"publisher": "demo-net"}, Path("/p"), comment),
             vote.task_text(Path("/p"), {"round": {"round": "r1"}}, "demo-net")]
    for text in texts:
        head = text.split("```", 1)[0]
        assert re.findall(r"^Platform: (.+)$", head, re.M) == ["demo-net"]
        assert head.splitlines()[0].startswith("This task comes from the agent runtime")
        assert FIRST not in text.lower(), "the task names the configured platform, never a default"


# --- the generic identifiers of the publisher's verbs (CT1) ----------------------------------------------


def test_the_contract_names_a_post_and_a_comment_by_generic_flags():
    contract = read("providers/CONTRACT.md")
    row = next(line for line in contract.splitlines() if line.startswith("| `publisher:<platform>` | `--check"))
    for flag in ("--post-id <id>", "--comment-id <id>", "--parent-comment-id <id>"):
        assert flag in row, flag
    assert "urn" not in row.lower(), "the verbs table speaks no platform's vocabulary"
    assert "Their value is opaque to the caller" in contract
    for alias in ("`--post-urn`", "`--comment-urn`", "`--parent-comment`"):
        assert alias in contract, "the aliases of the first implementation are named once, as aliases"


def test_the_runtime_passes_the_generic_flags_and_keeps_its_stored_field_names():
    source = read("scripts/runtime.py")
    assert source.count('"--post-id"') == 2 and source.count('"--parent-comment-id"') == 2
    assert '"--post-urn"' not in source and '"--parent-comment"' not in source
    for field in ('"comment_urn"', '"post_urn"', '"parent_comment_urn"'):
        assert field in source, "the stored field names stay: logs and inbox items that exist are read by them"


def test_the_first_publisher_takes_the_generic_names_with_the_old_ones_as_aliases():
    source = read("providers/publisher/linkedin.py")
    for generic, alias in (("--post-id", "--post-urn"), ("--comment-id", "--comment-urn"),
                           ("--parent-comment-id", "--parent-comment")):
        assert re.search(rf'add_argument\("{generic}", "{alias}", dest="', source), generic


# --- the data file holds every limit that is a constant today (FR-I5, CT2) ---------------------------------


def test_the_post_and_first_comment_limits_are_the_runtimes():
    d = data()
    assert int(constant("scripts/runtime_vote.py", r"^MAX_POST = (\d+)$")) == d["post"]["max_characters"] == 3000
    assert int(constant("scripts/runtime_vote.py", r'len\(post\["first_comment"\]\) > (\d+)')) \
        == d["post"]["first_comment"]["max_characters"] == 1250


def test_the_reply_limit_is_the_runtimes():
    assert int(constant("scripts/runtime.py", r'len\(d\["reply"\]\) > (\d+)')) == data()["reply"]["max_characters"]


def test_the_post_image_size_is_the_runtimes():
    size = data()["media"]["post_image"]
    assert int(constant("scripts/runtime_vote.py", r'"--width", "(\d+)"')) == size["width"]
    assert int(constant("scripts/runtime_vote.py", r'"--height", "(\d+)"')) == size["height"]


def test_the_media_types_size_and_count_are_the_payload_builders():
    media = data()["media"]
    rel = "skills/mkt-publish/scripts/payload.py"
    constant(rel, r"^(IMAGE_MAGIC) = ")
    payload = load(rel, "payload_for_platform_test")
    assert payload.MAX_IMAGE_BYTES == media["max_bytes"]
    magic = {ext: sorted(m.hex() for m in marks) for ext, marks in payload.IMAGE_MAGIC.items()}
    assert magic == {ext: sorted(kind["magic_hex"]) for kind in media["types"] for ext in kind["extensions"]}
    constant(rel, r"(at most one '- Image:' line)")
    assert media["max_count"] == 1
    constant(rel, r'(raise ValueError\("no ```post block"\))')
    assert data()["post"]["requires_text"] is True


def test_the_media_types_and_count_are_the_publishers():
    media = data()["media"]
    extensions = constant("providers/publisher/linkedin.py", r"^IMAGE_EXTENSIONS = \{(.+)\}$")
    assert sorted(re.findall(r'"(\.[a-z]+)"', extensions)) == sorted(e for k in media["types"] for e in k["extensions"])
    constant("providers/publisher/linkedin.py", r"(publishes at most one image per post)")
    assert media["max_count"] == 1


def test_the_post_address_is_the_one_the_vote_script_accepts_and_the_publisher_prints():
    url = data()["post"]["url"]
    pattern = constant("skills/mkt-vote-round/scripts/vote_update.py", r'^LINKEDIN_PATH_RE = re\.compile\(r"(.+)"\)$')
    assert pattern == url["path_pattern"]
    hosts = constant("skills/mkt-vote-round/scripts/vote_update.py", r"u\.hostname in \((.+?)\)")
    assert re.findall(r'"([^"]+)"', hosts) == url["hosts"] == data()["hosts"]
    printed = constant("providers/publisher/linkedin.py", r'return f"(https://www\.linkedin\.com/feed/update/\{urn\}/)"')
    assert printed.replace("{urn}", "{post_id}") == url["template"]
    assert re.match(url["path_pattern"], "/feed/update/urn:li:share:7000000000000000001/")
    assert (url["scheme"], url["allows_query"], url["allows_fragment"]) == ("https", False, False)


def test_the_identifiers_are_the_ones_the_publisher_checks():
    idents = data()["identifiers"]
    rel = "providers/publisher/linkedin.py"
    assert "^" + constant(rel, r'^POST_URN_RE = re\.compile\(r"(.+)"\)$') + "$" == idents["post"]["pattern"]
    assert "^" + constant(rel, r'^COMMENT_URN_RE = re\.compile\(r"(.+)"\)$') + "$" == idents["comment"]["pattern"]
    assert constant(rel, r'^SHORT_COMMENT_URN_RE = re\.compile\(r"(.+)"\)$') == idents["comment_short"]["pattern"]
    full = "urn:li:comment:(urn:li:activity:7000000000000000009,7100000000000000001)"
    assert re.match(idents["comment"]["pattern"], full) and not re.match(idents["comment_short"]["pattern"], full)
    assert re.match(idents["comment_short"]["pattern"], "urn:li:comment:(activity:7000000000000000009,7100000000000000001)")
    assert not re.match(idents["post"]["pattern"], "urn:li:share:12/../../v2/me")


def test_what_the_comment_parser_and_the_mailbox_hold_is_in_the_data_file():
    d = data()
    rel = "skills/mkt-engage/scripts/parse_notification.py"
    assert int(constant(rel, r"^MAX_TEXT = (\d+)$")) == d["comment"]["max_characters_kept"]
    link = d["comment"]["link"]
    assert constant(rel, r'q\.get\("(commentUrn)"\)') == link["comment_parameter"]
    assert constant(rel, r'q\.get\("(replyUrn)"\)') == link["reply_parameter"]
    assert link["nesting_levels"] == 1
    assert constant("providers/mailbox/gmail.py", r'^HEADER_PREFIX_ALLOWED = "(.+)"$') == d["notification_email"]["header_prefix"]
    assert d["notification_email"]["layout_verified"] is False


def test_the_reference_states_the_limits_of_its_data_file():
    """The prose and the data say the same numbers."""
    text, d = read(f"shared/references/platforms/{FIRST}.md"), data()
    for number in (d["post"]["max_characters"], d["post"]["first_comment"]["max_characters"],
                   d["reply"]["max_characters"], d["comment"]["max_characters_kept"], d["media"]["max_bytes"]):
        assert f"{number:,}" in text, number
    size = d["media"]["post_image"]
    assert f"{size['width']} x {size['height']}" in text
    for host in d["hosts"]:
        assert f"`{host}`" in text
    for name in ("--post-id", "--comment-id", "--parent-comment-id"):
        assert f"`{name}`" in text


# --- the files of a video platform: Instagram and TikTok ---------------------------------------------------


VIDEO_PLATFORMS = sorted(p.stem for p in DATA_FILES if shape_of(json.loads(p.read_text(encoding="utf-8"))) == VIDEO)


def test_instagram_and_tiktok_are_video_platforms_with_a_reference_each():
    assert {"instagram", "tiktok"} <= set(VIDEO_PLATFORMS)
    for name in ("instagram", "tiktok"):
        assert (PLATFORMS / f"{name}.md").is_file() and (PLATFORMS / f"{name}.json").is_file()


def section(text: str, heading: str) -> str:
    m = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no section {heading!r}"
    return m.group(1)


@pytest.mark.parametrize("name", VIDEO_PLATFORMS)
def test_a_video_references_shape_and_formats_are_stated_under_stable_headings(name):
    """The skill that writes the script reads the .md and nothing else: the shape and the formats are in it."""
    text, d = read(f"shared/references/platforms/{name}.md"), data(name)
    shape = section(text, "## Post shape")
    assert f"- Shape: `{d['post']['shape']}`." in shape
    accepted = re.search(r"^- Formats accepted: (.+)\.$", shape, re.M)
    assert accepted, "one line names the formats accepted"
    names = re.findall(r"`([a-z]+)`", accepted.group(1))
    assert names == d["post"]["formats"], "the prose and the data file name the same formats, in the same order"
    assert set(names) <= FORMATS
    headings = re.findall(r"^## Format: (.+)$", text, re.M)
    assert sorted(headings) == sorted(names), "one section per accepted format, no other"
    for fmt in names:
        body = section(text, f"## Format: {fmt}")
        for fact in ("- Needs:", "- Aspect:", "- Duration:" if fmt in VIDEO_FORMATS else "- Items:" if fmt == "carousel"
                     else "- Image:", "- Caption:"):
            assert fact in body, f"## Format: {fmt} has no line {fact!r}"
    assert not (set(FORMATS) - set(names)) & set(headings)


@pytest.mark.parametrize("name", VIDEO_PLATFORMS)
def test_a_video_references_numbers_are_its_data_files(name):
    """The prose and the data say the same numbers, and every number in the data file has a source tag nearby."""
    text, d = read(f"shared/references/platforms/{name}.md"), data(name)
    post, video, limits = d["post"], d["video"], d["limits"]
    for number in (post["max_characters"], video["max_bytes"], video["fps_min"], video["fps_max"], video["max_seconds"]):
        assert f"{number:,}" in text or str(number) in text, number
    for key in ("max_hashtags", "max_mentions", "max_width", "min_side", "max_side", "min_seconds"):
        value = post.get(key, video.get(key))
        if value is not None:
            assert str(value) in text, (key, value)
    for host in d["hosts"]:
        assert f"`{host}`" in text
    for figure in limits["posts_per_24h"]:
        assert str(figure) in text
    for key in ("pending_shares_per_24h", "unaudited_users_per_24h"):
        if limits[key] is not None:
            assert re.search(rf"\b{limits[key]}\b", text), key
    assert "not checked" in text or "not stated" in text, "a gap is written as one"
    for opt in post["options"].values():
        for value in opt.get("values") or []:
            if isinstance(value, str):
                assert value in text or value.lower() in text, value
    assert re.search(r"^## Sources$", text, re.M), "the sources, with their addresses and dates"
    urls = re.findall(r"https://\S+\s+\(read \d{4}-\d{2}-\d{2}\)", section(text, "## Sources"))
    assert len(urls) >= 3
    tags = set(re.findall(r"\[((?:IG|TT)-[A-Za-z-]+)(?:[,\]])", text))
    sourced = set(re.findall(r"^- \[([A-Za-z-]+)\]", section(text, "## Sources"), re.M))
    assert tags and tags <= sourced, f"a fact cites a source the list does not hold: {tags - sourced}"


def test_the_instagram_file_says_what_the_plan_found():
    d, text = data("instagram"), read("shared/references/platforms/instagram.md")
    assert d["post"]["formats"] == ["reel", "carousel", "static"]
    assert (d["post"]["max_characters"], d["post"]["max_hashtags"], d["post"]["max_mentions"], d["post"]["unit"]) \
        == (2200, 30, 20, "characters")
    video = d["video"]
    assert (video["min_seconds"], video["max_seconds"], video["fps_min"], video["fps_max"], video["max_width"]) \
        == (3, 900, 23, 60, 1920)
    assert video["aspect"]["recommended"] == "9:16" and video["faststart"] is True
    assert d["limits"]["posts_per_24h"] == [100, 50], "the page states both and does not reconcile them: neither is chosen"
    assert d["post"]["scheduling"] is False and d["post"]["url"] is None and d["post"]["first_comment"] is None
    options = d["post"]["options"]
    assert set(options) == {"media_type", "share_to_feed", "thumb_offset"}
    assert options["media_type"]["default"] == "REELS"
    assert options["thumb_offset"]["default"] is None and options["thumb_offset"]["when_unset"] == "omit"
    feed = options["share_to_feed"]
    assert feed["default"] is True and "assumed" not in feed, "the platform states no default: the maintainer decided it"
    assert (feed["decided_by"], feed["decided_on"]) == ("maintainer", "2026-10-13")
    assert "The maintainer's choice (2026-10-13): `true`" in text and "workbench's choice, `true`" not in text
    mp4 = next(k for k in d["media"]["types"] if k["name"] == "mp4")
    assert mp4["magic_hex"] == ["66747970"] and mp4["magic_offset"] == 4


def test_the_tiktok_file_says_what_the_plan_found_and_has_no_default_privacy():
    d = data("tiktok")
    assert d["post"]["formats"] == ["video"] and d["post"]["unit"] == "utf-16" and d["post"]["max_characters"] == 2200
    assert d["post"]["max_hashtags"] is None and d["post"]["max_mentions"] is None, "not checked: never a guessed number"
    video = d["video"]
    assert (video["fps_min"], video["fps_max"], video["min_side"], video["max_side"], video["max_seconds"]) \
        == (23, 60, 360, 4096, 600)
    assert video["min_seconds"] is None and video["aspect"] == {"recommended": None, "min": None, "max": None}
    privacy = d["post"]["options"]["privacy_level"]
    assert privacy["default"] is None and privacy["when_unset"] == "refuse" and privacy["set_by"] == "person", \
        "the person must choose the privacy status: there is no default value"
    assert set(privacy["values"]) == {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
    assert d["limits"] == {"posts_per_24h": [15], "pending_shares_per_24h": 5, "unaudited_users_per_24h": 5}
    assert {k["name"] for k in d["media"]["types"]} == {"mp4", "mov", "webm"}
    assert next(k for k in d["media"]["types"] if k["name"] == "webm")["magic_hex"] == ["1a45dfa3"]


@pytest.mark.parametrize("name", VIDEO_PLATFORMS)
def test_the_media_signatures_match_real_files(name, tmp_path):
    """An MP4 or MOV file's signature is at byte 4. Built by hand here, the shape every muxer writes: size, then ftyp."""
    kinds = {k["name"]: k for k in data(name)["media"]["types"]}
    samples = {"mp4": bytes.fromhex("00000020") + b"ftypisom" + bytes(8),
               "mov": bytes.fromhex("00000014") + b"ftypqt  " + bytes(8),
               "webm": bytes.fromhex("1a45dfa39f4286810142f781")}
    for kind, sample in samples.items():
        if kind not in kinds:
            continue
        hits = [m for m in kinds[kind]["magic_hex"]
                if sample[kinds[kind].get("magic_offset", 0):].startswith(bytes.fromhex(m))]
        assert hits, kind
    for kind in kinds.values():
        for other, sample in samples.items():
            if other != kind["name"] and other == "webm":
                assert not sample[kind.get("magic_offset", 0):].startswith(bytes.fromhex(kind["magic_hex"][0]))
