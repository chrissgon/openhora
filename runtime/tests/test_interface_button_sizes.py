"""The size of a button, a chip and a badge is the library's (interface/vendor/perfectui): the page's stylesheets set no padding and no font size on `.pui-btn`,
`.pui-chip` or `.pui-badge`, and the old size classes (`wb-small-button`, `wb-chip-small`, `wb-chip-11`, `wb-chip-12`) are gone. The page keeps its own layout classes
(wrapping, width, alignment) and the 44 px touch target at a phone's width, which is a minimum height on a layout class (`wb-touch`, `wb-rev-button`...), never a padding.

An action is a `pui-btn` with its variant (`pui-solid pui-theme`, `pui-surface pui-outline`); a compact clickable item is a `pui-chip` button; a status label is a
`pui-badge`. No browser here: the rules are read from the files.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_button_sizes.py
"""
from __future__ import annotations

import re

from test_interface_floor import INTERFACE, needs_node

OLD = ("wb-small-button", "wb-chip-small", "wb-chip-11", "wb-chip-12")
SIZE = re.compile(r"(?<![\w-])(padding(?:-[a-z]+)*|font-size|font)\s*:")
COMPONENT = re.compile(r"\.pui-(btn|chip|badge)(?![\w-])")


def rules():
    for path in sorted((INTERFACE / "css").glob("*.css")):
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            yield path.name, selector.strip(), body


def test_no_rule_sets_a_padding_or_a_font_size_on_a_button_a_chip_or_a_badge():
    found = [f"{name}: {selector[:80]} {{ {body.strip()[:80]} }}" for name, selector, body in rules()
             if not selector.startswith("@") and COMPONENT.search(selector) and SIZE.search(body)]
    assert not found, "PerfectUI has no size modifier: the component's own size stands (padding, font size). Offending rules:\n" + "\n".join(found)


def test_the_old_size_classes_are_gone_from_the_scripts_and_the_stylesheets():
    found = []
    for pattern in ("js/**/*.js", "demo/**/*.js", "css/*.css", "*.html", "demo/*.html"):
        for path in sorted(INTERFACE.glob(pattern)):
            if "vendor" in path.parts:
                continue
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
