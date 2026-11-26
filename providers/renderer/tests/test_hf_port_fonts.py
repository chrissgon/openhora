"""The faces of an admitted page resolve a weight the way the old engine's one family per typeface does (PF-a4g): `var(--font-display)` at `var(--weight-text)`
(the quote line of `hf:testimonial-card`) is the typeface's text file, not the display file drawn at the wrong weight. Offline: the declared faces, and, where
a headless Chromium is installed, the face the browser picks. The fonts are the allow-listed files; nothing is served and nothing is fetched."""
from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

import renderer_kit as K
import _assets
import _hf_host
from _vocab import load_data

DATA = load_data()
ALLOW = _assets.font_allowlist()
FONTS = {"display": {"id": "inter-800", "weight": 800}, "text": {"id": "inter-500", "weight": 500}, "mono": {"id": "jetbrains-mono-500", "weight": 500}}
SERVE = {"/fonts/display.woff2": (b"", ""), "/fonts/text.woff2": (b"", ""), "/fonts/mono.woff2": (b"", "")}
FILE_OF = {"display": "inter-800.woff2", "text": "inter-500.woff2", "mono": None}


def faces(fonts=FONTS, serve=SERVE, allow=ALLOW):
    return _hf_host.theme_fonts(serve, fonts, allow)


def test_the_allow_list_names_the_typeface_of_the_theme_fonts_the_tests_use():
    assert ALLOW["inter-800"]["family"] == ALLOW["inter-500"]["family"] == "Inter" and ALLOW[FONTS["mono"]["id"]]["family"] != "Inter"


def test_a_role_family_carries_the_files_of_the_other_roles_of_the_same_typeface_each_at_its_own_weight():
    got = [(f["family"], f["weight"], f["path"]) for f in faces()]
    assert got == [("oh-display", "800", "/fonts/display.woff2"), ("oh-display", "500", "/fonts/text.woff2"),
                   ("oh-mono", "500", "/fonts/mono.woff2"),
                   ("oh-text", "500", "/fonts/text.woff2"), ("oh-text", "800", "/fonts/display.woff2")]


def test_without_the_allow_list_or_a_family_a_role_declares_its_own_file_alone_as_before():
    own = [(f["family"], f["weight"]) for f in faces(allow=None)]
    assert own == [("oh-display", "800"), ("oh-mono", "500"), ("oh-text", "500")]
    assert [f["family"] for f in faces(allow={k: {kk: vv for kk, vv in v.items() if kk != "family"} for k, v in ALLOW.items()})] == ["oh-display", "oh-mono", "oh-text"]


def test_two_roles_on_the_same_file_declare_one_face_and_a_system_default_role_declares_none():
    both = dict(FONTS, text={"id": "inter-800", "weight": 800})
    assert [(f["family"], f["weight"]) for f in faces(both)] == [("oh-display", "800"), ("oh-mono", "500"), ("oh-text", "800")]
    assert [f["family"] for f in faces(serve={"/fonts/display.woff2": (b"", "")})] == ["oh-display"]


def test_the_page_font_check_lists_every_declared_face_so_the_extra_ones_are_loaded_and_counted():
    spec = _hf_host.fonts_spec(faces(), DATA["theme"]["system_fallback"])
    assert sorted(spec["faces"]) == sorted([["oh-display", "800", "normal"], ["oh-display", "500", "normal"], ["oh-mono", "500", "normal"],
                                             ["oh-text", "500", "normal"], ["oh-text", "800", "normal"]])


PAGE = """<!doctype html><meta charset=utf-8><style>%s</style><body><script>
const out = {};
Promise.all([['oh-display', 800], ['oh-display', 500], ['oh-text', 500], ['oh-text', 800]].map(([fam, w]) =>
  document.fonts.load(w + ' 20px ' + fam, 'a').then((list) => { out[fam + '@' + w] = list.map((f) => f.family + ' ' + f.weight); })))
  .then(() => { document.title = JSON.stringify(out); });
</script></body>"""


@pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
def test_in_the_browser_the_display_family_at_the_text_weight_is_the_text_file_not_the_bold_one(tmp_path):
    folder = _assets.fonts_dir()
    by_path = {"/fonts/display.woff2": "inter-800.woff2", "/fonts/text.woff2": "inter-500.woff2", "/fonts/mono.woff2": "inter-500.woff2"}
    css = "".join("@font-face{font-family:%s;src:url(file://%s) format('%s');font-weight:%s;font-style:normal}"
                  % (f["family"], os.path.join(folder, by_path[f["path"]]), f["format"], f["weight"]) for f in faces())
    page = tmp_path / "p.html"
    page.write_text(PAGE % css)
    run = subprocess.run([K.BROWSER, "--headless", "--no-sandbox", "--allow-file-access-from-files", "--virtual-time-budget=3000", "--dump-dom", "file://" + str(page)],
                         capture_output=True, text=True, timeout=60)
    title = re.search(r"<title>(.*?)</title>", run.stdout, re.S)
    assert title, run.stdout[-300:] + run.stderr[-300:]
    got = json.loads(title.group(1).replace("&quot;", '"'))
    assert got == {"oh-display@800": ["oh-display 800"], "oh-display@500": ["oh-display 500"], "oh-text@500": ["oh-text 500"], "oh-text@800": ["oh-text 800"]}


DEFAULT_THEME = {"display": {"id": "default", "weight": 800}, "text": {"id": "default", "weight": 500}, "mono": {"id": "default", "weight": 500}}


def default_served():
    """What `load_fonts` serves for the default theme (PF-b1, B2 (a)): the real allow-listed files, each checked by its sha256."""
    serve, used = _assets.load_fonts(DEFAULT_THEME, ALLOW, DATA["limits"]["font_max_bytes"])
    return serve, used


def test_the_default_theme_resolves_to_the_inter_and_mono_files_and_declares_the_same_faces_as_the_explicit_ids():
    serve, used = default_served()
    assert used == {"display": "inter-800", "text": "inter-500", "mono": "jetbrains-mono-500"}
    assert sorted(serve) == sorted(p for p in SERVE) or {p.rsplit(".", 1)[0] for p in serve} == {p.rsplit(".", 1)[0] for p in SERVE}
    assert _hf_host.theme_fonts(serve, DEFAULT_THEME, ALLOW) == _hf_host.theme_fonts(serve, FONTS, ALLOW)      # the grouping applies to the files `default` stands for
    got = [(f["family"], f["weight"]) for f in _hf_host.theme_fonts(serve, DEFAULT_THEME, ALLOW)]
    assert ("oh-display", "500") in got and ("oh-display", "800") in got and ("oh-text", "800") in got


def test_a_font_id_that_is_not_default_is_itself_and_default_is_the_roles_file():
    assert _assets.font_id_of("display", "default") == "inter-800" and _assets.font_id_of("text", "default") == "inter-500"
    assert _assets.font_id_of("mono", "default") == "jetbrains-mono-500" and _assets.font_id_of("display", "inter-500") == "inter-500"


@pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
def test_in_the_browser_under_the_default_theme_the_display_family_at_the_text_weight_is_inter_500(tmp_path):
    serve, _used = default_served()
    folder = _assets.fonts_dir()
    by_path = {"/fonts/display.woff2": "inter-800.woff2", "/fonts/text.woff2": "inter-500.woff2", "/fonts/mono.woff2": "jetbrains-mono-500.woff2"}
    declared = _hf_host.theme_fonts(serve, DEFAULT_THEME, ALLOW)
    css = "".join("@font-face{font-family:%s;src:url(file://%s) format('%s');font-weight:%s;font-style:normal}"
                  % (f["family"], os.path.join(folder, by_path[f["path"]]), f["format"], f["weight"]) for f in declared)
    page = tmp_path / "p.html"
    page.write_text(PAGE % css)
    run = subprocess.run([K.BROWSER, "--headless", "--no-sandbox", "--allow-file-access-from-files", "--virtual-time-budget=3000", "--dump-dom", "file://" + str(page)],
                         capture_output=True, text=True, timeout=60)
    title = re.search(r"<title>(.*?)</title>", run.stdout, re.S)
    assert title, run.stdout[-300:] + run.stderr[-300:]
    got = json.loads(title.group(1).replace("&quot;", '"'))
    assert got == {"oh-display@800": ["oh-display 800"], "oh-display@500": ["oh-display 500"], "oh-text@500": ["oh-text 500"], "oh-text@800": ["oh-text 800"]}
    assert {f["path"] for f in declared if f["family"] == "oh-display" and f["weight"] == "500"} == {"/fonts/text.woff2"}      # display@500 is the text file, inter-500
