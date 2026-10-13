"""Offline tests of skills/mkt-engage/scripts/parse_notification.py: a pasted comment link, a reply, a digest, the
exact host check and the platform's data file, and the call form the agent runtime still uses."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PARSER = REPO / "skills/mkt-engage/scripts/parse_notification.py"
DATA = REPO / "shared/references/platforms/linkedin.json"
POST = "7000000000000000001"
LINK = (f"https://www.linkedin.com/feed/update/urn:li:activity:{POST}?commentUrn=urn%3Ali%3Acomment%3A%28activity%3A"
        f"{POST}%2C7100000000000000004%29&dashCommentUrn=x")
REPLY = LINK + f"&replyUrn=urn%3Ali%3Acomment%3A%28activity%3A{POST}%2C7100000000000000009%29"
FULL = f"urn:li:comment:(urn:li:activity:{POST},7100000000000000004)"


def run(message, *flags, env=None):
    stdin = message if isinstance(message, str) else json.dumps(message)
    r = subprocess.run([sys.executable, str(PARSER), *map(str, flags)], input=stdin, capture_output=True, text=True,
                       timeout=60, env=env)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def parse(message, *extra):
    return run(message, "--platform", "linkedin", "--platform-file", DATA, *extra)


def pasted(link=LINK, **kw):
    return {"link": link, "commenter": "Lucas Moreau", "text": "TTL in 960 lines? Sounds like a toy.", **kw}


def test_help_exits_0_and_waits_for_nothing():
    r = subprocess.run([sys.executable, str(PARSER), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "--platform-file" in r.stdout


def test_a_pasted_link_gives_the_comment_and_its_post():
    code, out, err = parse(pasted())
    assert code == 0, err
    assert out["parsed"] is True and out["source"] == "pasted" and out["platform"] == "linkedin"
    assert out["comment_id"] == out["parent_comment_id"] == FULL
    assert out["post_id"] == f"urn:li:activity:{POST}"
    assert (out["comment_urn"], out["parent_comment_urn"], out["post_urn"]) == \
        (out["comment_id"], out["parent_comment_id"], out["post_id"]), "the runtime's stored names, same values"
    assert out["commenter"] == "Lucas Moreau" and out["on_own_post"] is True


def test_a_reply_is_answered_under_its_top_level_comment():
    code, out, err = parse(pasted(REPLY))
    assert code == 0 and out["parsed"], err
    assert out["comment_id"] == f"urn:li:comment:(urn:li:activity:{POST},7100000000000000009)"
    assert out["parent_comment_id"] == FULL


@pytest.mark.parametrize("link", [
    LINK.replace("www.linkedin.com", "notlinkedin.com"),
    LINK.replace("www.linkedin.com", "www.linkedin.com.evil.example"),
    LINK.replace("https://", "http://"),
    f"https://www.linkedin.com/feed/update/urn:li:activity:{POST}/",
    LINK.replace(f"urn:li:activity:{POST}?", "urn:li:activity:7000000000000000002?"),
    LINK.replace("%2C7100000000000000004", "%2Cabc"),
])
def test_a_link_that_is_not_a_comment_link_of_the_platform_is_not_parsed(link):
    code, out, err = parse(pasted(link))
    assert code == 0 and out["parsed"] is False and "comment link" in out["reason"] and "commentUrn" in out["reason"], err


def test_a_pasted_comment_needs_its_commenter_and_text():
    code, out, _ = parse(pasted(commenter=" "))
    assert code == 0 and out["parsed"] is False and "commenter and text" in out["reason"]


def test_the_text_is_kept_up_to_the_data_files_limit_and_hidden_characters_go():
    code, out, _ = parse(pasted(text="\u200bhi " + "x" * 5000))
    assert code == 0 and out["text"].startswith("hi ") and len(out["text"]) == 3000


def test_from_an_email_only_the_link_is_trusted():
    code, out, _ = parse({"subject": "Lucas commented on your post", "links": [{"href": LINK}], "received_at": "t"})
    assert code == 0 and out["parsed"] is False and "not verified" in out["reason"]
    assert out["partial"]["comment_id"] == FULL and out["partial"]["on_own_post"] is None
    code, out, _ = parse({"links": [{"href": LINK}, {"href": REPLY}]})
    assert out["parsed"] is False and "digest" in out["reason"]
    code, out, _ = parse({"links": [{"href": "https://code.example/x"}]})
    assert out["parsed"] is False and "no linkedin comment link" in out["reason"]


@pytest.mark.parametrize("stdin,message", [("not json", "stdin is not JSON"), ("[1]", "a JSON object")])
def test_bad_input_exits_2(stdin, message):
    code, out, err = parse(stdin)
    assert code == 2 and message in err and out is None


def test_the_data_file_must_be_the_platforms(tmp_path):
    other = tmp_path / "demo-net.json"
    other.write_text(json.dumps({**json.loads(DATA.read_text()), "platform": "demo-net"}))
    code, _, err = run(pasted(), "--platform", "linkedin", "--platform-file", other)
    assert code == 2 and "not the data file of 'linkedin'" in err
    code, _, err = run(pasted(), "--platform", "demo-net", "--platform-file", other)
    assert code == 2 and "no parser" in err
    code, _, err = run(pasted(), "--platform", "linkedin")
    assert code == 2 and "go together" in err


def test_the_hosts_come_from_the_data_file(tmp_path):
    data = json.loads(DATA.read_text())
    data["hosts"] = ["www.linkedin.com.example"]
    f = tmp_path / "linkedin.json"
    f.write_text(json.dumps(data))
    code, out, _ = run(pasted(LINK.replace("www.linkedin.com", "www.linkedin.com.example")),
                       "--platform", "LinkedIn", "--platform-file", f)
    assert code == 0 and out["parsed"] is True
    code, out, _ = run(pasted(), "--platform", "linkedin", "--platform-file", f)
    assert out["parsed"] is False


def test_the_runtimes_call_without_flags_reads_the_data_file_of_this_checkout():
    env = {k: v for k, v in os.environ.items() if k != "WORKBENCH_ROOT"}
    code, out, err = run(pasted(), env=env)
    assert code == 0 and out["parsed"] is True and "old call form" in err and str(DATA) in err
    code, out, err = run(pasted(), env={**env, "WORKBENCH_ROOT": "/nonexistent"})
    assert code == 0 and out["parsed"] is True and "written with" in err
    code, out, _ = run(pasted("https://www.linkedin.com/feed/"), env={**env, "WORKBENCH_ROOT": "/nonexistent"})
    assert out["parsed"] is False and "commentUrn" in out["reason"]


def test_the_old_call_forms_values_are_the_data_files():
    spec = importlib.util.spec_from_file_location("parse_notification_values", PARSER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = json.loads(DATA.read_text())
    old = module.OLD_CALL_DATA
    assert old["platform"] == data["platform"] and old["hosts"] == data["hosts"]
    assert old["comment"] == data["comment"] and old["identifiers"] == data["identifiers"]


@pytest.mark.parametrize("platform", ["instagram", "tiktok"])
@pytest.mark.parametrize("message", [
    {"link": "https://www.example.com/post?comment=1", "commenter": "Ana Lima", "text": "Great video"},
    {"subject": "New comment", "from": "no-reply@example.com", "text": "x", "links": [{"href": "https://www.example.com/c/1"}]},
    {},
], ids=["pasted", "mailbox", "empty"])
def test_a_video_platform_with_a_data_file_and_no_parser_is_refused_without_a_crash(platform, message):
    """The data files of these platforms carry no comment-link patterns, and this script has no parser for their
    links (comments on these platforms are out of scope): exit 2, the reason on stderr, nothing on stdout."""
    data_file = REPO / "shared/references/platforms" / f"{platform}.json"
    assert data_file.is_file()
    r = subprocess.run([sys.executable, str(PARSER), "--platform", platform, "--platform-file", str(data_file)],
                       input=json.dumps(message), capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and r.stdout == ""
    assert "no parser for the links" in r.stderr and repr(platform) in r.stderr
    assert "Traceback" not in r.stderr
    # the flag is case-insensitive, as for the platform that has a parser
    code, out, err = run(message, "--platform", platform.upper(), "--platform-file", data_file)
    assert code == 2 and out is None and "no parser for the links" in err


def test_the_data_file_of_one_video_platform_is_not_the_other_ones():
    code, _, err = run(pasted(), "--platform", "instagram", "--platform-file", REPO / "shared/references/platforms/tiktok.json")
    assert code == 2 and "not the data file of 'instagram'" in err
