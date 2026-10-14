"""The size of a button, a chip and a badge is the library's (interface/vendor/perfectui): the page's stylesheets set no padding and no font size on them, and the old size
classes (`wb-small-button`, `wb-chip-small`, `wb-chip-11`, `wb-chip-12`) are gone. The page keeps its own layout classes (wrapping, width, alignment) and the 44 px touch target
at a phone's width, which is a minimum height on a layout class (`wb-touch`, `wb-rev-button`...), never a padding.

An action is a `pui-btn` with its variant (`pui-solid pui-theme`, `pui-surface pui-outline`); a compact clickable item is a `pui-chip` button; a status label is a `pui-badge`.

What the test reads. A rule is checked when its last compound selector names a library class (`.pui-btn`, `.pui-chip`, `.pui-badge`) OR any `wb-*` class the page's scripts put on
the same element as one of them: `.wb-tab` on a `pui-btn` is as much an override of the button as `.pui-btn { padding }` is. The properties are padding, font and font size, and the
library's own tokens for them (`--pui-space*`, `--pui-font-size*`). No browser here: the rules and the class lists are read from the files.

PENDING below is a list of what is NOT settled: custom controls that sit on a library element and override its size on purpose. The maintainer has not decided whether each is a
button, a tab or a row that follows PerfectUI, so they are listed with that, one reason each, and the test fails when a class outside the list gets such a rule or when an entry no
longer has one (so the list only shrinks). Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_button_sizes.py
"""
from __future__ import annotations

import re

from test_interface_floor import INTERFACE, needs_node

OLD = ("wb-small-button", "wb-chip-small", "wb-chip-11", "wb-chip-12")
LIBRARY = ("pui-btn", "pui-chip", "pui-badge")
SIZE = re.compile(r"(?<![\w-])(padding(?:-[a-z]+)*|font-size|font|--pui-space[a-z0-9-]*|--pui-font-size[a-z0-9-]*)\s*:")

TABS = "PENDING DECISION, tabs: the tab bar is a segmented control with its own metrics (not a plain button); is a tab a PerfectUI button or its own component?"
LINKS = "PENDING DECISION, link-style buttons (`pui-link`): a disclosure row or a text link drawn as a button with no padding of its own; do they follow the button's size?"
FRAME = "PENDING DECISION, frame controls: an icon or square button of the top bar, the bottom bar or the switcher, sized to the bar; do they follow the button's size?"
PENDING = {
    "wb-tab": TABS,
    "wb-reply-toggle": LINKS, "wb-task-head": LINKS, "wb-task-toggle": LINKS, "wb-earlier-toggle": LINKS, "wb-path-btn": LINKS, "wb-path-button": LINKS,
    "wb-cancel-link": LINKS, "wb-lobby-cancel-link": LINKS, "wb-track-open": LINKS, "wb-req-step": LINKS, "wb-rq-cancel": LINKS, "wb-rq-open": LINKS,
    "wb-lobby-request-title": "PENDING DECISION, the Lobby's request title: a `pui-link` button cut to one line with an ellipsis, not an action; is it a row?",
    "wb-lobby-tab-count": "PENDING DECISION, the count in a Lobby tab: a badge drawn as a bare number inside the tab; is it a badge?",
    "wb-req-chip": "PENDING DECISION, the request chip of the tracking bar: a clickable chip with its own size; is it a chip, a button or a row?",
    "wb-back": FRAME, "wb-camera-btn": FRAME, "wb-door": FRAME, "wb-mode-btn": FRAME, "wb-state-btn": FRAME, "wb-switch-chevron": FRAME, "wb-switch-main": FRAME,
    "wb-wait-btn": FRAME, "wb-foot-row": FRAME, "wb-floor-step": FRAME,
    "wb-muted": "PENDING DECISION, a text helper that the scripts also put on a badge in one table cell: only its font size in `.wb-cap-agent` is in question",
}


def sources():
    for pattern in ("js/**/*.js", "demo/**/*.js", "*.html", "demo/*.html"):
        for path in sorted(INTERFACE.glob(pattern)):
            if "vendor" not in path.parts:
                yield path


def classes_on_library_elements() -> set:
    """Every wb-* or tk-* class a script puts on the same element as a library class (a class literal of an element, its parts joined by the template's holes)."""
    found = set()
    for path in sources():
        text = path.read_text(encoding="utf-8")
        lists = re.findall(r"\[((?:\"[A-Za-z0-9_ -]+\"\s*,\s*)+\"[A-Za-z0-9_ -]+\")\]", text)      # a class list built as an array of words, joined later
        for literal in re.findall(r"class:\s*(`[^`]*`|\"[^\"]*\")", text) + re.findall(r"setAttribute\(\"class\",\s*(`[^`]*`|\"[^\"]*\")", text) + lists:
            names = re.findall(r"[A-Za-z0-9_-]+", re.sub(r"\$\{[^}]*\}", "", literal))
            if any(n in LIBRARY for n in names):
                found |= {n for n in names if n.startswith(("wb-", "tk-"))}
    return found


def rules():
    for path in sorted((INTERFACE / "css").glob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            if not selector.strip().startswith("@"):
                yield path.name, selector.strip(), body


def overrides() -> dict:
    """{class: [rule text]} for every rule that sets a size on a library class or on a class the page puts on one."""
    reach = classes_on_library_elements() | set(LIBRARY)
    found: dict = {}
    for name, selector, body in rules():
        property_ = SIZE.search(body)
        if not property_:
            continue
        for part in selector.split(","):
            last = re.split(r"[\s>+~]+", part.strip())[-1]
            if "::" in last:      # the text a rule puts before or after the element is not the element's size
                continue
            for cls in set(re.findall(r"\.([A-Za-z0-9_-]+)", last)) & reach:
                found.setdefault(cls, []).append(f"{name}: {part.strip()[:70]} {{ {property_.group(1)} }}")
    return found


def test_the_check_reads_something_the_library_and_the_classes_on_its_elements():
    reach = classes_on_library_elements()
    assert {"wb-card-button", "wb-rev-word", "wb-tab", "wb-touch"} <= reach, "the class lists of the scripts were read"
    found = overrides()
    assert "wb-tab" in found and "wb-reply-toggle" in found, "and a known override is seen: the check is not vacuous"


def test_no_rule_sets_a_padding_or_a_font_size_on_a_button_a_chip_or_a_badge_except_the_listed_pending_decisions():
    found = overrides()
    unlisted = {cls: rules_ for cls, rules_ in found.items() if cls not in PENDING}
    assert not unlisted, "PerfectUI has no size modifier: the component's own size stands. Overrides that are not on the pending list:\n" + "\n".join(
        f"{cls}: {', '.join(rules_)}" for cls, rules_ in sorted(unlisted.items()))


def test_the_pending_list_only_shrinks_every_entry_still_has_a_rule_and_says_it_is_a_pending_decision():
    found = overrides()
    stale = sorted(set(PENDING) - set(found))
    assert not stale, f"these classes no longer override a size: take them off the pending list: {stale}"
    assert all(reason.startswith("PENDING DECISION") for reason in PENDING.values())


def test_the_old_size_classes_are_gone_from_the_scripts_and_the_stylesheets():
    found = []
    for path in list(sources()) + sorted((INTERFACE / "css").glob("*.css")):
        text = path.read_text(encoding="utf-8")
        found += [f"{path.relative_to(INTERFACE)}: {name}" for name in OLD if name in text]
    assert not found, f"size classes that overrode a PerfectUI component: {found}"


def test_a_phone_keeps_the_touch_target_on_layout_classes_and_not_on_the_components():
    css = "\n".join(path.read_text(encoding="utf-8") for path in sorted((INTERFACE / "css").glob("*.css")))
    assert re.search(r"\.wb-touch\b[^{}]*\{[^{}]*min-height: 44px", css), "the layout class that carries the 44 px minimum"
    assert re.search(r"\.wb-rev-button, \.wb-video-button \{ min-height: 44px; \}", css)


SHAPES = r"""
import { createVideoCard } from "@JS@/floor/video-card.js";
const card = { recording: "@RID@", status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null, caption: null, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] };
const video = createVideoCard({ project: "@PROJECT@", recording: "@RID@", api: { videoCard: async () => card }, loopback: true });
const review = make();
await Promise.all([video.load(), review.load()]); await settle();
const lib = (n) => n.cls().filter((c) => c.startsWith("pui-")).sort().join(" ");
out.again = [lib(find(video.el, "[data-key=reload]")), lib(find(review.el, "[data-key=reload]"))];
out.actions = [...new Set(all(review.el, "button.wb-rev-button").map(lib))].sort();
out.words = [...new Set(all(review.el, ".wb-rev-word").map(lib))];
out.sizes = all(review.el, ".wb-rev-sizes button").map((n) => [n.attrs["data-key"], lib(n)]);
out.sizeClasses = [video.el, review.el].flatMap((root) => [...root.walk()].filter((n) => (n.attrs.class || "").match(/wb-small-button|wb-chip-/)).map((n) => n.attrs.class));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_review_and_the_video_card_draw_their_actions_alike_words_and_sizes_as_chips_and_no_size_class(tmp_path):
    from test_interface_captions import run
    got = run(tmp_path, SHAPES)
    assert got["again"][0] == got["again"][1] == "pui-btn pui-outline pui-surface", "\"Check again\" is drawn alike in the review and in the video card"
    assert set(got["actions"]) <= {"pui-btn pui-outline pui-surface", "pui-btn pui-solid pui-theme"}, got["actions"]
    assert got["words"] == ["pui-chip pui-outline pui-surface"], "a word of the transcript is a chip"
    assert got["sizes"] == [["size-small", "pui-chip pui-outline pui-surface"], ["size-medium", "pui-chip pui-solid pui-theme"], ["size-large", "pui-chip pui-outline pui-surface"]], "the face-box sizes are chips"
    assert got["sizeClasses"] == []
