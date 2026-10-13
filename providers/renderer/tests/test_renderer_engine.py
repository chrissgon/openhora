"""The HTML overlay engine: the DevTools-pipe driver, the served-from-memory origin, the determinism contract, the browser's
process group and its sandbox. Browser tests skip with a reason where no headless Chromium is found."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time

import pytest

import renderer_kit as K
import _cdp
import _frames
import _lint
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
CFG = {"colors": {"accent": "#07B6F0"}, "fonts": {}, "images": {}}
needs_browser = pytest.mark.skipif(not K.BROWSER, reason=K.SKIP_BROWSER)
TEMPLATES = sorted(glob.glob(os.path.join(str(K.RENDERER), "templates", "*.html")))


def page_html(body):
    return ("<!doctype html><meta charset=utf-8><body><div id=a></div><script>%s</script>" % body).encode()


@pytest.fixture
def work():
    path = tempfile.mkdtemp(prefix="renderer-engine-")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def chrome(work, serve, **kw):
    return _cdp.Chrome(K.BROWSER, serve, work, **kw)


# ---------------------------------------------------------------- the determinism contract and the templates

def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_every_template_is_clean_and_pinned_and_each_forbidden_construct_is_refused():
    pins = _frames.template_pins()
    assert {os.path.basename(p) for p in TEMPLATES} == set(pins)
    for path in TEMPLATES:
        assert _lint.lint(read(path)) == [], path
        assert hashlib.sha256(open(path, "rb").read()).hexdigest() == pins[os.path.basename(path)], path
    cases = {"css-keyframes": "<style>@keyframes a{}</style>", "css-transition": "<style>p{transition: all 1s}</style>", "css-animation": "<style>p{animation: a 1s}</style>",
             "date": "<script>new Date()</script>", "performance-now": "<script>performance.now()</script>", "math-random": "<script>Math.random()</script>",
             "raf": "<script>requestAnimationFrame(f)</script>", "timers": "<script>setTimeout(f,1)</script>", "media-element": "<video></video>",
             "network": "<script>fetch('x')</script>", "worker": "<script>new Worker('w.js')</script>", "dynamic-import": "<script>import('x')</script>",
             "external-src": '<img src="https://x.example/a.png">', "markup-injection": "<script>el.innerHTML = x</script>"}
    for rule, html in cases.items():
        assert rule in _lint.lint(html), rule
    for html in ("<audio></audio>", "<iframe></iframe>", "<script>new XMLHttpRequest()</script>", "<script>new WebSocket('x')</script>",
                 "<style>p{background:url(x)}</style>", "<script>setInterval(f,1)</script>", "<script>document.write('x')</script>", '<a href="file:///etc/hosts">x</a>'):
        assert _lint.lint(html), html


def test_a_template_outside_the_folder_or_with_a_changed_hash_is_refused(tmp_path):
    folder = tmp_path / "t"
    shutil.copytree(os.path.join(str(K.RENDERER), "templates"), folder)
    serve, _ = _frames.load_templates(["keyword.html"], str(folder))
    assert "/t/keyword.html" in serve
    for bad in ("../keyword.html", "/etc/passwd", "sub/keyword.html", "unknown.html"):
        with pytest.raises(Refusal) as e:
            _frames.load_templates([bad], str(folder))
        assert e.value.code == "template_not_pinned"
    (folder / "keyword.html").write_text(read(str(folder / "keyword.html")) + "\n<!-- changed -->")
    with pytest.raises(Refusal) as e:
        _frames.load_templates(["keyword.html"], str(folder))
    assert e.value.code == "template_hash"
    _frames.write_pins(str(folder))                                     # a reviewed change is pinned again ...
    (folder / "list.html").write_text(read(str(folder / "list.html")).replace("</script>", "setTimeout(f,1);</script>"))
    _frames.write_pins(str(folder))
    with pytest.raises(Refusal) as e:                                    # ... but it still has to pass the determinism lint
        _frames.load_templates(["list.html"], str(folder))
    assert e.value.code == "template_lint"
    link = folder / "pip.html"
    link.unlink()
    os.symlink("/etc/hosts", link)
    with pytest.raises(Refusal):                                         # a template that is a link is not read
        _frames.load_templates(["pip.html"], str(folder))


def test_the_templates_presets_and_declared_parameters_are_equal():
    assert {os.path.basename(p) for p in TEMPLATES} == {s["template"] for s in DATA["presets"].values()} | {DATA["caption"]["template"]}
    for name, cfg in DATA["presets"].items():
        html = read(os.path.join(str(K.RENDERER), "templates", cfg["template"]))
        params = re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1)
        looks = re.search(r'<meta name="pv-looks" content="([^"]*)">', html).group(1)
        assert set(filter(None, params.split(","))) == set(VOCAB["presets"][name]["params"]), name
        assert set(filter(None, looks.split(","))) == set(cfg["looks"]), name
        assert re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == name
        assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) <= set(VOCAB["presets"][name]["params"]), name
        assert set(re.findall(r"\bL\.([a-z0-9_]+)", html)) <= set(cfg["looks"]), name
        assert "innerHTML" not in html


def test_the_dot_that_keeps_frames_rgba_and_the_zone_marks_are_in_the_driver_and_the_templates():
    assert "clipPath" in _cdp.SETUP_JS and "data-zone" in _cdp.SETUP_JS
    for name in ("keyword", "list", "number", "quote"):
        assert "dataset.zone = 'card'" in read(os.path.join(str(K.RENDERER), "templates", name + ".html"))
    assert "dataset.zone = 'caption'" in read(os.path.join(str(K.RENDERER), "templates", "caption.html"))


# ---------------------------------------------------------------- the sandbox

def test_the_browsers_own_sandbox_is_on_everywhere_but_the_image_and_a_failed_start_is_not_retried(tmp_path, monkeypatch):
    log = tmp_path / "argv.log"
    fake = tmp_path / "fake-browser"
    fake.write_text("#!/bin/sh\necho \"$@\" >> %s\nexit 1\n" % log)
    fake.chmod(0o755)
    for env in ({}, {"RENDERER_IN_CONTAINER": "1"}):                      # the variable alone, without the image's marker file, changes nothing
        monkeypatch.delenv("RENDERER_IN_CONTAINER", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        assert _cdp.container_mode() is False
        c = _cdp.Chrome(str(fake), {}, str(tmp_path / "w"), time_limit=20)
        with pytest.raises(_cdp.CDPError):
            c.start()
        c.close()
        assert c.sandbox == "on"
    runs = log.read_text().splitlines()
    assert len(runs) == 2 and not any("--no-sandbox" in r for r in runs)   # started once per attempt: no second try without the sandbox


def test_inside_the_image_the_sandbox_is_off_and_says_so(tmp_path, monkeypatch):
    log = tmp_path / "argv.log"
    fake = tmp_path / "fake-browser"
    fake.write_text("#!/bin/sh\necho \"$@\" >> %s\nexit 1\n" % log)
    fake.chmod(0o755)
    marker = tmp_path / "marker"
    marker.write_text("image")
    monkeypatch.setattr(_cdp, "IMAGE_MARKER", str(marker))
    monkeypatch.setenv("RENDERER_IN_CONTAINER", "1")
    assert _cdp.container_mode() is True
    c = _cdp.Chrome(str(fake), {}, str(tmp_path / "w"), time_limit=20)
    with pytest.raises(_cdp.CDPError):
        c.start()
    c.close()
    assert c.sandbox == "off" and "--no-sandbox" in log.read_text() and "--disable-dev-shm-usage" in log.read_text()
    monkeypatch.delenv("RENDERER_IN_CONTAINER")
    assert _cdp.container_mode() is False


def test_a_hung_browser_is_killed_with_its_whole_group_past_the_limit(tmp_path):
    pidfile = tmp_path / "child.pid"
    fake = tmp_path / "hang-browser"
    fake.write_text("#!/bin/sh\nsleep 600 &\necho $! > %s\nsleep 600\n" % pidfile)
    fake.chmod(0o755)
    c = _cdp.Chrome(str(fake), {}, str(tmp_path / "w"), time_limit=1)
    started = time.time()
    with pytest.raises(_cdp.CDPError):
        c.start()
    assert time.time() - started < 15
    c.close()
    child = int(pidfile.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(c.proc.pid, 0)


# ---------------------------------------------------------------- the page, in a real browser

@needs_browser
def test_markup_in_data_is_drawn_as_text(work):
    serve = {"/t/x.html": (page_html("window.renderAt=(t,d)=>{document.getElementById('a').textContent=d.text}"), "text/html")}
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        pg.open("/t/x.html", CFG)
        sig = pg.frame(0, {"text": "<img src=x onerror=alert(1)>"})["html"]
        assert "&lt;img src=x onerror=alert(1)&gt;" in sig and "<img" not in sig


@needs_browser
@pytest.mark.parametrize("url", ["https://example.com/a.png", "http://127.0.0.1:9/a.png", "file:///etc/hosts", "https://render.invalid/not-served.png"])
def test_a_network_or_file_request_fails_the_render(work, url):
    body = "var i=new Image();i.src=%s;window.renderAt=()=>{}" % json.dumps(url)
    serve = {"/t/x.html": (page_html(body), "text/html")}
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        if url.startswith("file:"):
            try:                                                          # the browser itself refuses file: from an https page; either way nothing is drawn
                pg.open("/t/x.html", CFG)
            except _cdp.RenderBlocked:
                pass
            assert ch.blocked == [] or all(u.startswith("file:") for u in ch.blocked)
        else:
            with pytest.raises(_cdp.RenderBlocked):
                pg.open("/t/x.html", CFG)


@needs_browser
def test_a_csp_violation_fails_the_render(work):
    body = "document.body.appendChild(document.createElement('iframe')).src='data:text/html,x';window.renderAt=()=>{}"
    serve = {"/t/x.html": (page_html(body), "text/html")}
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        with pytest.raises(_cdp.RenderBlocked):
            pg.open("/t/x.html", CFG)


@needs_browser
def test_timers_clock_and_random_throw(work):
    serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        pg.open("/t/x.html", CFG)
        for expr in ("setTimeout(()=>{},1)", "Date.now()", "new Date()", "Math.random()", "performance.now()", "requestAnimationFrame(()=>{})", "fetch('x')"):
            with pytest.raises(_cdp.CDPError):
                pg.evaluate(expr)


@needs_browser
def test_a_running_css_animation_fails_the_assertion(work):
    body = ("var s=document.createElement('style');s.textContent='@keyframes k{from{opacity:0}to{opacity:1}}#a{animation:k 1s infinite}';"
            "document.head.appendChild(s);window.renderAt=()=>{}")
    with chrome(work, {"/t/x.html": (page_html(body), "text/html")}) as ch:
        pg = ch.new_page(200, 200)
        pg.open("/t/x.html", CFG)
        with pytest.raises(_cdp.CDPError):
            pg.frame(0, {})


@needs_browser
def test_a_missing_font_or_image_fails_before_frame_zero(work):
    serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        cfg = {"colors": {}, "fonts": {"display": {"url": _cdp.ORIGIN + "/fonts/none.woff2", "weight": 800, "fallback": "serif"}}, "images": {}}
        with pytest.raises((_cdp.CDPError, _cdp.RenderBlocked)):
            pg.open("/t/x.html", cfg)
    with chrome(work, serve) as ch:
        pg = ch.new_page(200, 200)
        with pytest.raises((_cdp.CDPError, _cdp.RenderBlocked)):
            pg.open("/t/x.html", {"colors": {}, "fonts": {}, "images": {"s": _cdp.ORIGIN + "/assets/none.png"}})


@needs_browser
def test_the_browser_group_is_killed_on_close(work):
    serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
    with chrome(work, serve) as ch:
        pid = ch.proc.pid
        ch.new_page(200, 200).open("/t/x.html", CFG)
    time.sleep(0.3)
    assert subprocess.run(["ps", "-o", "pid=", "-g", str(pid)], capture_output=True, text=True).stdout.strip() == ""


@needs_browser
def test_two_browsers_draw_byte_identical_frames(work):
    body = ("window.renderAt=(t,d)=>{var a=document.getElementById('a');a.textContent='t'+t.toFixed(2);"
            "a.style.cssText='font:60px sans-serif;color:#07b6f0;position:absolute;left:'+Math.round(t*40)+'px;top:10px'}")
    shots = []
    for k in range(2):
        with chrome(os.path.join(work, str(k)), {"/t/x.html": (page_html(body), "text/html")}) as ch:
            pg = ch.new_page(400, 200)
            pg.open("/t/x.html", CFG)
            pg.frame(0.5, {})
            shots.append(hashlib.sha256(pg.screenshot()).hexdigest())
    assert shots[0] == shots[1]


# ---------------------------------------------------------------- every preset, in a real browser

def zones_data(face):
    z = DATA["zones"]
    return {"card": [z["card_top"], face["y"] - z["gap"]], "caption": [face["y"] + face["h"] + z["gap"], z["caption_bottom"]]}


FACES = [{"x": 240, "y": 620, "w": 600, "h": 560}, {"x": 150, "y": 800, "w": 780, "h": 520}, {"x": 300, "y": 540, "w": 480, "h": 600}]
BEATS = {"keyword": {"text": "Name every dollar", "icon": "coin"}, "list": {"items": "Review | Adjust | Celebrate | Repeat every single week"},
         "number": {"value": "1.234,56", "label": "euros saved in one month, every month"}, "quote": {"text": "Small steps beat big plans, every single time you try.", "author": "A wise friend"}}


@needs_browser
@pytest.mark.parametrize("face", FACES)
def test_no_card_and_no_caption_ever_touches_the_face_box_and_each_stays_in_its_band(work, face):
    z = zones_data(face)
    serve, _ = _frames.load_templates([c["template"] for c in DATA["presets"].values() if c["template"].split(".")[0] in BEATS] + [DATA["caption"]["template"]])
    with chrome(work, serve) as ch:
        for name, params in list(BEATS.items()) + [("caption", None)]:
            tpl = DATA["caption"]["template"] if name == "caption" else DATA["presets"][name]["template"]
            pg = ch.new_page(1080, 1920)
            pg.open("/t/" + tpl, {"colors": DATA["theme"]["colors"], "fonts": {}, "images": {}})
            for t in (0.0, 0.1, 0.3, 0.6, 1.0, 1.6, 2.2):
                if name == "caption":
                    data = {"duration": 2.4, "anchor": "bottom", "zones": z, "margin": DATA["zones"]["caption_margin"],
                            "words": [{"text": "Planning", "start": 0.0, "end": 0.4}, {"text": "a trip", "start": 0.5, "end": 0.9}, {"text": "without stress", "start": 1.0, "end": 1.6}]}
                    zone = z["caption"]
                else:
                    data = {"params": params, "look": DATA["presets"][name]["looks"], "zones": z, "duration": 2.4}
                    zone = z["card"]
                result = pg.frame(t, data)
                assert _frames.face_hit(result["boxes"], face) is None, (name, t)
                for b in result["boxes"]:
                    assert b["y"] >= zone[0] - 1 and b["y"] + b["h"] <= zone[1] + 1 and 0 <= b["x"] and b["x"] + b["w"] <= 1080, (name, t, b, zone)


@needs_browser
def test_a_card_drawn_over_the_face_fails_the_frame_loop(tmp_path):
    folder = tmp_path / "t"
    shutil.copytree(os.path.join(str(K.RENDERER), "templates"), folder)
    html = read(str(folder / "keyword.html"))
    bad = html.replace("pos.style.top = z[0] + 'px';", "pos.style.top = '650px';")
    assert bad != html
    (folder / "keyword.html").write_text(bad)
    _frames.write_pins(str(folder))
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "e" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    import _edl
    import _render
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [],
             "overlays": [{"id": "b1", "beat": 1, "preset": "keyword", "params": {"text": "Hello"}, "word_from": 0, "word_to": 3, "score": 1.0}]}
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    serve, _ = _frames.load_templates(["keyword.html", "caption.html"], str(folder))
    with pytest.raises(Refusal) as e:
        _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls={}, assets={}, browser=K.BROWSER, jobs_n=1,
                            frames_dir=str(tmp_path / "frames"), workdir=str(tmp_path / "w"), time_limit=120,
                            templates={"caption": "caption.html", "keyword": "keyword.html"}, png_blank=_render.blank_png)
    assert e.value.code == "overlay_hits_face"


@needs_browser
def test_a_template_that_reaches_for_a_file_url_draws_nothing_and_fails_the_render(tmp_path):
    folder = tmp_path / "t"
    shutil.copytree(os.path.join(str(K.RENDERER), "templates"), folder)
    html = read(str(folder / "keyword.html"))
    bad = html.replace("window.renderAt = function (t, data) {", "window.renderAt = function (t, data) {\n  var i = new Image(); i['sr' + 'c'] = 'file:///etc/hosts';", 1)
    assert bad != html and _lint.lint(bad) == []                           # the lint cannot see it: the origin must stop it
    (folder / "keyword.html").write_text(bad)
    _frames.write_pins(str(folder))
    import _edl
    import _render
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "e" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [],
             "overlays": [{"id": "b1", "beat": 1, "preset": "keyword", "params": {"text": "Hello"}, "word_from": 0, "word_to": 3, "score": 1.0}]}
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    serve, _ = _frames.load_templates(["keyword.html", "caption.html"], str(folder))
    with pytest.raises(Refusal) as e:
        _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls={}, assets={}, browser=K.BROWSER, jobs_n=1,
                            frames_dir=str(tmp_path / "frames"), workdir=str(tmp_path / "w"), time_limit=120,
                            templates={"caption": "caption.html", "keyword": "keyword.html"}, png_blank=_render.blank_png)
    assert e.value.code in ("blocked_request", "frame_failed")


def test_fonts_come_only_from_the_allow_list_and_are_hash_checked(tmp_path, monkeypatch):
    fonts = tmp_path / "assets" / "fonts"
    fonts.mkdir(parents=True)
    data = b"wOF2" + b"\x00" * 64
    (fonts / "test-800.woff2").write_bytes(data)
    (fonts / "allowlist.json").write_text(json.dumps({"version": 1, "fonts": [
        {"id": "test-800", "file": "test-800.woff2", "sha256": hashlib.sha256(data).hexdigest(), "weight": 800, "licence": "fictional", "source": "fictional"}]}))
    monkeypatch.setenv("RENDERER_TEST", "1")
    monkeypatch.setenv("RENDERER_ASSETS_DIR", str(tmp_path / "assets"))
    allow = _frames.font_allowlist()
    assert set(allow) == {"test-800"}
    serve, used = _frames.load_fonts({"display": {"id": "test-800", "weight": 800}, "text": {"id": "default", "weight": 500}}, allow, 1 << 20)
    assert used == {"display": "test-800", "text": "system default"} and "/fonts/display.woff2" in serve
    with pytest.raises(Refusal) as e:
        _frames.load_fonts({"display": {"id": "comic-sans", "weight": 800}}, allow, 1 << 20)
    assert e.value.code == "font_not_allowed"
    (fonts / "test-800.woff2").write_bytes(data + b"x")                      # swapped after it was listed
    with pytest.raises(Refusal) as e:
        _frames.load_fonts({"display": {"id": "test-800", "weight": 800}}, allow, 1 << 20)
    assert e.value.code == "font_hash"
    monkeypatch.delenv("RENDERER_TEST")
    assert _frames.fonts_dir().endswith(os.path.join("renderer", "assets", "fonts"))      # outside test mode the folder is not redirectable


def test_the_shipped_allow_list_is_empty_until_the_maintainer_chooses_a_font():
    assert _frames.font_allowlist() == {}


def test_images_are_checked_by_their_bytes_dimensions_and_hash(tmp_path):
    limits = DATA["limits"]
    png = lambda w, h, extra=b"": (b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + b"\0" * 4
                                  + extra + (0).to_bytes(4, "big") + b"IDAT" + b"\0" * 4)
    good = tmp_path / "a.png"
    good.write_bytes(png(100, 200))
    assert _frames.load_assets({"beat1": str(good)}, {}, limits)["beat1"]["kind"] == "png"
    digest = hashlib.sha256(good.read_bytes()).hexdigest()
    assert _frames.load_assets({"beat1": str(good)}, {"beat1": digest}, limits)
    cases = {"oversize side": (png(9000, 10), "asset_dimensions"), "oversize pixels": (png(7000, 7000), "asset_dimensions"),
             "animated": (png(10, 10, (0).to_bytes(4, "big") + b"acTL" + b"\0" * 4), "asset_type"), "not an image": (b"GIF89a" + b"\0" * 40, "asset_type"),
             "wrong bytes for its name": (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "asset_type")}
    for what, (data, code) in cases.items():
        p = tmp_path / ("x-%s.png" % what.replace(" ", "-"))
        p.write_bytes(data)
        with pytest.raises(Refusal) as e:
            _frames.load_assets({"beat1": str(p)}, {}, limits)
        assert e.value.code == code, what
    with pytest.raises(Refusal) as e:
        _frames.load_assets({"beat1": str(good)}, {"beat1": "0" * 64}, limits)
    assert e.value.code == "asset_hash"
    link = tmp_path / "link.png"
    os.symlink(good, link)
    with pytest.raises(Refusal) as e:
        _frames.load_assets({"beat1": str(link)}, {}, limits)
    assert e.value.code == "asset_unreadable"
    for bad in ("../x", "Beat 1", ""):
        with pytest.raises(Refusal):
            _frames.load_assets({bad: str(good)}, {}, limits)
