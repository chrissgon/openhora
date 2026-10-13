"""Offline tests for the Markdown rendering of providers/messenger/telegram.py (render_html and the send path around it).

Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import html
import html.parser
import importlib.util
import json
import random
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "telegram.py"
TOKEN = "123456789:FAKE-token-AAAAAAAAAAAAAAAAAAAA-never-print-me"
spec = importlib.util.spec_from_file_location("messenger_telegram_format_under_test", SCRIPT)
telegram = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = telegram
spec.loader.exec_module(telegram)
render = telegram.render_html
ALLOWED = {"b", "s", "code", "pre", "blockquote"}


class Checker(html.parser.HTMLParser):
    """Parses with a stack: only allowed tags, always closed in order, a blockquote never inside another, no code or
    pre inside b or s."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED or attrs:
            self.errors.append(f"tag {tag} {attrs}")
        if tag in ("code", "pre") and any(t in ("b", "s") for t in self.stack):
            self.errors.append("code inside a mark")
        if tag == "blockquote" and "blockquote" in self.stack:
            self.errors.append("nested blockquote")
        if tag == "b" and "b" in self.stack or tag == "s" and "s" in self.stack:
            self.errors.append("a mark inside itself")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"crossing or stray </{tag}> over {self.stack}")
        else:
            self.stack.pop()


def check(out: str) -> None:
    parser = Checker()
    parser.feed(out)
    parser.close()
    assert not parser.errors and not parser.stack, (out, parser.errors, parser.stack)


def test_the_maintainers_card_renders_headings_bullets_and_code():
    text = ("## Nome: demo-brand (auditoria, rascunho)\n- **Registrado:** `demo.example`\n  - sub item with `docs/brand/a_b.md`\n"
            "* last one\n\nSee **bold** and ~~gone~~.")
    out = render(text)
    assert out == ("<b>Nome: demo-brand (auditoria, rascunho)</b>\n• <b>Registrado:</b> <code>demo.example</code>\n"
                   "  • sub item with <code>docs/brand/a_b.md</code>\n• last one\n\nSee <b>bold</b> and <s>gone</s>.")
    check(out)


HOSTILE = ["<b>x</b>", '<a href="http://evil.example">y</a>', "&lt;", "<script>alert(1)</script>", "a & b < c > d", "&amp;lt;",
           '<b onclick="x">', "</pre><b>", "```\n</pre><b>boom\n```", "| <i> |", "> <u>quote</u>", "# <b>h</b>", "[<b>t</b>](http://e.example)"]


@pytest.mark.parametrize("text", HOSTILE)
def test_hostile_text_is_escaped_and_shown_literally(text):
    out = render(text)
    check(out)
    assert "<script" not in out and "<a " not in out and "<u>" not in out and "<i>" not in out
    assert "<b>x</b>" not in render("<b>x</b>")


def test_random_mixes_of_marks_never_produce_a_tag_outside_the_set_nor_a_longer_text():
    pieces = ["**", "~~", "`", "```", "\n", "> ", "- ", "* ", "# ", "|", "<b>", "</b>", "&", "<", ">", "[a](http://x.example)", " ", "word",
              "snake_case", "src/**/*.py", "_", "*", "\r\n", "[", "](", ")", "é", "•"]
    rng = random.Random(7)
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 25)))
        out = render(text)
        check(out)
        assert len(telegram.visible_text(out)) <= len(text.replace("\r\n", "\n").replace("\r", "\n")), (text, out)


def test_a_link_is_text_with_its_address_never_an_anchor():
    assert render("[site](https://evil.example/path)") == "site (https://evil.example/path)"
    assert "<a" not in render("go to [here](http://x.example?a=1&b=2) now")
    assert render("see https://bare.example/x") == "see https://bare.example/x"


def test_nothing_inside_code_a_fence_or_a_table_is_read():
    assert render("`**x** <b>`") == "<code>**x** &lt;b&gt;</code>"
    assert render("```py\n**x** <b> `y`\n```") == "<pre>**x** &lt;b&gt; `y`</pre>"
    assert render("| a | **b** |\n| - | - |\nafter") == "<pre>| a | **b** |\n| - | - |</pre>\nafter"
    assert render("snake_case_name and __init__ and src/**/*.py and skills/*/SKILL.md") == \
        "snake_case_name and __init__ and src/**/*.py and skills/*/SKILL.md"
    assert render("an **unclosed bold and ~~strike") == "an **unclosed bold and ~~strike"
    assert render("*not italic* and _not italic_") == "*not italic* and _not italic_"
    assert render("``a ` b``") == "<code>a ` b</code>"


def test_an_unclosed_fence_is_ordinary_text_and_the_footer_stays_outside():
    cut = "intro\n```python\ndef f():\n    return 1\n\n(continues on the page)"
    out = render(cut)
    check(out)
    assert "<pre>" not in out and out.endswith("(continues on the page)")
    split = "```\nline one\nline two"  # a say reply split in the middle of a fence
    assert "<pre>" not in render(split)


def test_marks_do_not_cross_nor_hold_code():
    for text in ("**a ~~b** c~~", "~~a **b~~ c**", "**a `x` b**", "**a **b** c**", "~~**both**~~", "**bold ~~and strike~~ ok**"):
        check(render(text))
    assert render("**a `x` b**") == "**a <code>x</code> b**"
    assert render("~~**both**~~") == "<s><b>both</b></s>"
    assert render("## Using `foo` here") == "<b>Using </b><code>foo</code><b> here</b>"
    assert render("## **Name**") == "<b>Name</b>"


def test_bold_opens_after_space_or_a_parenthesis_and_closes_before_punctuation():
    assert render("(**yes**), and **no**.") == "(<b>yes</b>), and <b>no</b>."
    assert render("a**b**c") == "a**b**c"
    assert render("** spaced **") == "** spaced **"


def test_quote_runs_are_one_blockquote_each_and_crlf_is_one_newline():
    out = render("> one\r\n> two with `code`\r\nplain\r\n> again")
    assert out == "<blockquote>one\ntwo with <code>code</code></blockquote>\nplain\n<blockquote>again</blockquote>"
    check(out)
    assert render(">not a quote") == "&gt;not a quote"


COMMANDS = ["python3 /w/ops.py approve --project /p/northwind-shop --id 7 --sha256 " + "e" * 64,
            "run '/p/_a_/__init__/*' \"q\" 'a b' <x> & y", "echo `hi`", "echo ``hi``", "`lead", "trail`", "a ` b `` c ``` d",
            "'/p/a`b' --id 7", " spaced "]


@pytest.mark.parametrize("command", COMMANDS)
def test_a_real_effect_card_shows_its_command_byte_for_byte_in_code_on_the_last_line(command):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime"))
    import messaging_cards as cards  # noqa: E402
    import operations  # noqa: E402
    caps = dict(telegram.CAPABILITIES)
    policy = {"messaging": {"approve": True}}
    item = {"kind": "effect", "id": 7, "title": "Pull request", "text": "Open a pull request", "actions": ["approved", "rejected"],
            "payload_sha256": "e" * 64}
    card = cards.build("northwind-shop", item, caps, policy, "text", None, operations=operations, effect_command=command)
    text = card["message"]["text"]
    out = render(text)
    check(out)
    last = out.rstrip().split("\n")[-1]
    assert last.startswith("<code>") and last.endswith("</code>")
    assert html.unescape(last[len("<code>"):-len("</code>")]) == command
    assert command in telegram.visible_text(out)


# --- the send path ------------------------------------------------------------------------------------------------

class Answer:
    def __init__(self, result):
        self.body = json.dumps({"ok": True, "result": result}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Opener:
    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, request.data))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return Answer(answer)


def http_400(description):
    body = json.dumps({"ok": False, "error_code": 400, "description": description}).encode("utf-8")
    import io
    return urllib.error.HTTPError(f"https://api.telegram.org/bot{TOKEN}/sendMessage", 400, "Bad Request", {}, io.BytesIO(body))


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MESSENGER_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("MESSENGER_TELEGRAM_API_BASE", raising=False)


def go(monkeypatch, capsys, tmp_path, opener, message):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(message))
    monkeypatch.setattr(telegram, "OPENER", opener)
    code = telegram.main(["send", "--platform", "telegram", "--chat", "4242", "--message-file", str(path)])
    out, err = capsys.readouterr()
    assert TOKEN not in out and TOKEN not in err
    return code, out, err


KEYS = [{"id": "7:approve", "label": "Approve"}]


def test_send_posts_html_mode_and_disables_the_link_preview(monkeypatch, capsys, tmp_path):
    opener = Opener({"message_id": 5})
    code, out, _ = go(monkeypatch, capsys, tmp_path, opener, {"text": "## Title\n- **a** [x](https://l.example)", "actions": KEYS})
    assert code == 0 and json.loads(out) == {"message_id": "5"}
    sent = json.loads(opener.requests[0][1])
    assert sent["parse_mode"] == "HTML" and sent["link_preview_options"] == {"is_disabled": True}
    assert sent["text"] == "<b>Title</b>\n• <b>a</b> x (https://l.example)"
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "7:approve"


def test_a_parse_refusal_is_resent_once_as_plain_text_with_the_same_keyboard(monkeypatch, capsys, tmp_path):
    opener = Opener(http_400("Bad Request: can't parse entities: Unsupported start tag at byte offset 5"), {"message_id": 6})
    code, out, err = go(monkeypatch, capsys, tmp_path, opener, {"text": "**secret-ish text**", "actions": KEYS})
    assert code == 0 and json.loads(out) == {"message_id": "6"}
    first, second = (json.loads(r[1]) for r in opener.requests)
    assert first["parse_mode"] == "HTML" and "parse_mode" not in second
    assert second["text"] == "**secret-ish text**" and second["reply_markup"] == first["reply_markup"]
    assert second["link_preview_options"] == {"is_disabled": True}
    assert err.strip() == "Telegram refused the formatted text; sent as plain text" and "secret-ish" not in err


def test_another_400_is_the_old_error_and_is_not_resent(monkeypatch, capsys, tmp_path):
    opener = Opener(http_400("Bad Request: chat not found"))
    code, _, err = go(monkeypatch, capsys, tmp_path, opener, {"text": "hello"})
    assert code == 1 and "answered 400" in err and len(opener.requests) == 1


def test_a_text_with_nothing_to_show_once_rendered_is_sent_plain(monkeypatch, capsys, tmp_path):
    opener = Opener({"message_id": 8})
    code, _, _ = go(monkeypatch, capsys, tmp_path, opener, {"text": "```\n```"})
    sent = json.loads(opener.requests[0][1])
    assert code == 0 and "parse_mode" not in sent and sent["text"] == "```\n```"
    assert sent["link_preview_options"] == {"is_disabled": True}


def test_check_message_still_caps_the_raw_text_at_4096(monkeypatch, capsys, tmp_path):
    opener = Opener()
    code, _, err = go(monkeypatch, capsys, tmp_path, opener, {"text": "x" * 4097})
    assert code == 2 and "4096" in err and not opener.requests
