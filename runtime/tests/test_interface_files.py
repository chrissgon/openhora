"""Tests of the files of the local interface (interface/): what the page's own files call and load, the rules they keep
about the token and the markup, and the vendored libraries' hashes. The files are static: nothing here starts a server
or a browser. The service's own rules are tested in test_service.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_files.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import standin_tree as st
from interface_css import css_paths, interface_css

service = st.load("service")

INTERFACE = st.REPO / "interface"
VENDOR = INTERFACE / "vendor"
CLIENT = INTERFACE / "js" / "api.js"
SUFFIXES = (".html", ".css", ".js")
SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
LITERAL_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
# OH-3: the one colour literal of the stylesheets, the brand pair of the library's one primary token (light, then dark).
BRAND_PAIR = "light-dark(#6B4429, #C99A6E)"
BRAND_LINE = re.compile(r"^[ \t]*--pui-theme: " + re.escape(BRAND_PAIR) + r";[^\n]*$", re.M)


def own_files():
    """The page's own html, css and js files: everything under interface/ that is not vendored."""
    return sorted(p for p in INTERFACE.rglob("*") if p.is_file() and p.suffix in SUFFIXES and VENDOR not in p.parents)


def vendored_files():
    return sorted(p for p in VENDOR.rglob("*") if p.is_file() and p.suffix in SUFFIXES)


def rel(path: Path) -> str:
    return str(path.relative_to(st.REPO))


def inside_interface(target: Path) -> bool:
    root = os.path.realpath(INTERFACE)
    real = os.path.realpath(target)
    return real == root or real.startswith(root + os.sep)


def resolves(source: Path, reference: str) -> bool:
    """True when a relative reference from `source` names an existing file inside interface/."""
    path = reference.split("#", 1)[0].split("?", 1)[0]
    if not path:
        return True  # a hash link to the same page
    target = (source.parent / path)
    return inside_interface(target) and target.is_file()


def call_text(source: str, start: int) -> str:
    """The text of the call whose opening parenthesis is at `start`, up to its matching closing one."""
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    return source[start:]


# --- the client and the service's routes -------------------------------------------------------------------------------


def client_calls():
    """Every call `send("<METHOD>", <path>, ...)` of the client: [(method, path template, whole call text)]."""
    source = CLIENT.read_text(encoding="utf-8")
    out = []
    for found in re.finditer(r'\bsend\(\s*"(GET|POST)"\s*,\s*(["`])([^"`]*)\2', source):
        out.append((found.group(1), found.group(3), call_text(source, source.index("(", found.start()))))
    return source, out


def shape(path: str) -> tuple:
    """A path as its segments, each parameter (`{p}` of a route, `${...}` of the client) as a star."""
    return tuple("*" if re.fullmatch(r"\{\w+\}|\$\{.*\}", part) else part for part in path.split("/"))


def test_every_route_the_interface_files_call_is_a_route_of_the_service():
    source, calls = client_calls()
    prefix = re.search(r'const PREFIX = "([^"]+)"', source)
    assert prefix and prefix.group(1) == service.PREFIX, "the client's prefix is the service's"
    assert len(calls) >= 20, "the client's calls were not found: did the form of `send(...)` change?"
    routes = [(r["method"], shape(r["pattern"]), r) for r in service.ROUTES]
    seen = set()
    for method, template, text in calls:
        found = [r for m, s, r in routes if m == method and s == shape(template)]
        assert found, f"api.js calls {method} {template}, which is not a route of the service"
        route = found[0]
        seen.add((method, route["pattern"]))
        if re.search(r"\bquery\s*:", text):
            assert method == "GET" and not route["own"] and route["take"] != (), \
                f"api.js sends a query to {method} {template}, a route that takes none"
        for part in re.findall(r"\$\{([^}]*)\}", template):
            assert re.fullmatch(r"enc\(\w+\)", part), f"a path part of {template} is not encoded with enc(): {part}"
    assert ("GET", "/projects") in seen and ("GET", "/jobs/{id}") in seen, "the project list and the job route are called"


def test_the_client_sends_the_token_only_as_a_bearer_header_and_a_post_as_json():
    source = CLIENT.read_text(encoding="utf-8")
    assert "`Bearer ${token}`" in source and '"Content-Type"] = "application/json"' in source
    assert 'credentials: "omit"' in source and 'cache: "no-store"' in source
    assert not re.search(r"\btoken\b[^\n]*(?:url|query)\b", source.replace("const token = getToken();", "")), \
        "the token is not put in the url or the query"
    for name in ("token.js", "api.js"):
        assert "console." not in (INTERFACE / "js" / name).read_text(encoding="utf-8"), f"{name} logs nothing"


# --- nothing from another host -----------------------------------------------------------------------------------------


def references(path: Path, text: str):
    """What a file of the page loads or links: [(kind, reference)]."""
    out = []
    if path.suffix == ".html":
        out += [("html attribute", m.group(2)) for m in re.finditer(r'\b(src|href|action|poster|data)\s*=\s*"([^"]*)"', text)]
        out += [("html attribute", m.group(2)) for m in re.finditer(r"\b(src|href|action|poster|data)\s*=\s*'([^']*)'", text)]
        for block in re.findall(r'<script[^>]*type\s*=\s*"importmap"[^>]*>(.*?)</script>', text, re.S):
            imports = json.loads(block).get("imports", {})
            out += [("import map entry", v) for v in imports.values()]
    if path.suffix == ".css":
        out += [("css import", m.group(1)) for m in re.finditer(r'@import\s+(?:url\()?\s*["\']?([^"\')\s;]+)', text)]
        out += [("css url", m.group(1)) for m in re.finditer(r'url\(\s*["\']?([^"\')]+)', text)]
    if path.suffix == ".js":
        out += [("js import", m.group(1)) for m in re.finditer(r'\bimport\s*(?:[^"\';()]*?\sfrom\s*)?["\']([^"\']+)["\']', text)]
        out += [("js export from", m.group(1)) for m in re.finditer(r'\bexport\s[^"\';]*?\sfrom\s*["\']([^"\']+)["\']', text)]
        out += [("js dynamic import", m.group(1)) for m in re.finditer(r'\bimport\(\s*["\']([^"\']+)["\']', text)]
        out += [("js fetch", m.group(1)) for m in re.finditer(r'\bfetch\(\s*["\'`]([^"\'`]+)', text)]
        out += [("js worker or socket", m.group(1)) for m in re.finditer(r'\bnew\s+(?:Worker|SharedWorker|WebSocket|EventSource)\(\s*["\'`]([^"\'`]+)', text)]
    return out


def test_the_interface_files_load_nothing_from_another_host():
    files = own_files()
    assert {p.name for p in files} >= {"index.html", "base.css", "frame.css", "token.css", "city.css", "building.css", "floor.css", "lobby.css", "control.css", "main.js", "api.js"}, "the page's files are there"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://|(?<![:\w])//[A-Za-z0-9.-]+\.[A-Za-z]", text), \
            f"{rel(path)} names a host: the page's own files load nothing from another host"
        for kind, reference in references(path, text):
            assert not SCHEME.match(reference), f"{rel(path)}: {kind} {reference!r} is not a relative path"
            if kind in ("js import", "js export from", "js dynamic import"):
                assert reference.startswith(("./", "../")), f"{rel(path)}: {kind} {reference!r} is a bare name (no import map is possible)"
                assert resolves(path, reference), f"{rel(path)}: {kind} {reference!r} is not a file inside interface/"
            elif kind == "js fetch":
                assert reference.startswith(("/api/", "./", "../")) or reference == "/api", f"{rel(path)}: fetch of {reference!r}"
            elif kind in ("html attribute", "css import", "css url", "import map entry"):
                assert resolves(path, reference), f"{rel(path)}: {kind} {reference!r} is not a file inside interface/"
    # The vendored libraries are not read line by line (they are not ours), but they must not load a script or fetch
    # from another host, and what they import by a path stays in their folder.
    other_host = re.compile(r"""<script[^>]*\ssrc\s*=\s*["']?(?:https?:)?//|\bfetch\(\s*["'`](?:https?:)?//|\bnew\s+(?:Worker|WebSocket|EventSource)\(\s*["'`](?:https?:|wss?:)?//|@import\s+(?:url\()?\s*["']?(?:https?:)?//""")
    for path in vendored_files():
        text = path.read_text(encoding="utf-8")
        assert not other_host.search(text), f"{rel(path)} loads from another host"
        for match in re.finditer(r"^import\s[^\n]*?from\s*['\"]([^'\"]+)['\"]", text, re.M):
            assert match.group(1).startswith("./") and resolves(path, match.group(1)), f"{rel(path)} imports {match.group(1)}"


# --- the vendored files and their hashes -------------------------------------------------------------------------------

ROW = re.compile(r"^\| `([^`]+)` \| (\d+) \| `([0-9a-f]{64})` \|$", re.M)


def vendored_folders():
    return sorted(p for p in VENDOR.iterdir() if p.is_dir())


def test_the_vendored_files_match_the_hashes_their_readmes_record():
    folders = vendored_folders()
    assert len(folders) >= 2, "two libraries are vendored, each in a folder of its own"
    for folder in folders:
        readme = folder / "README.md"
        assert readme.is_file(), f"{rel(folder)} has no README.md"
        text = readme.read_text(encoding="utf-8")
        if folder.name == "fonts":      # C-13: the brand typefaces; each family has its own version in the table, and the licence is the SIL OFL 1.1
            assert re.search(r"^- Package: ", text, re.M) and re.search(r"^- Licence: SIL OFL 1\.1", text, re.M), f"{rel(readme)} says its source and licence"
        else:
            assert re.search(r"^- Package: ", text, re.M) and re.search(r"^- Version: \*\*[0-9][^*]*\*\*", text, re.M) \
                and re.search(r"^- Licence: MIT", text, re.M), f"{rel(readme)} says its package, exact version and licence"
        rows = ROW.findall(text)
        assert rows, f"{rel(readme)} records no hash"
        recorded = {name: (int(size), digest) for name, size, digest in rows}
        assert len(recorded) == len(rows), f"{rel(readme)} lists a file twice"
        present = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()} - {"README.md"}
        assert present == set(recorded), \
            f"{rel(folder)}: files without a recorded hash {sorted(present - set(recorded))}, hashes without a file {sorted(set(recorded) - present)}"
        for name, (size, digest) in recorded.items():
            data = (folder / name).read_bytes()
            assert len(data) == size, f"{rel(folder / name)} has {len(data)} bytes; its README records {size}"
            assert hashlib.sha256(data).hexdigest() == digest, f"{rel(folder / name)} is not the file its README records"
        assert any(name.upper().startswith("LICENSE") for name in recorded), f"{rel(folder)} holds the licence text"


# --- the page's markup and the token -----------------------------------------------------------------------------------

FORBIDDEN_IN_MODULES = (
    (r"\blocalStorage\b", "localStorage"), (r"\bdocument\.cookie\b", "document.cookie"), (r"\binnerHTML\b", "innerHTML"),
    (r"\bouterHTML\b", "outerHTML"), (r"\binsertAdjacentHTML\b", "insertAdjacentHTML"), (r"\bdocument\.write", "document.write"),
    (r"\bnew\s+Function\b", "new Function"), (r"[?&]token\b", "a token in a query"),
    (r"\beval\s*\(", "eval("),  # security-scan: allow dynamic-eval -- a pattern that forbids a call of the page's modules; nothing runs it
    (r"\btoken=", "token= in a url"), (r"""setAttribute\(\s*["']style["']""", "an inline style"), (r"\.cssText\b", "cssText"),
    (r"\bindexedDB\b", "indexedDB"),
)


def test_the_page_sets_no_inline_script_and_no_token_in_a_url_or_storage_other_than_session():
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert re.search(r'\ssrc\s*=\s*"\./', tag), f"index.html has a script with no relative src (an inline script is refused by the policy): {tag}"
    for block in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S):
        assert not block.strip(), "index.html has inline script text"
    assert not re.search(r"<style\b|\sstyle\s*=|\son[a-z]+\s*=", html), "index.html has an inline style or an event attribute"
    for path in own_files():
        if path.suffix != ".js":
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, name in FORBIDDEN_IN_MODULES:
            assert not re.search(pattern, text), f"{rel(path)} uses {name}"
        if path.name != "token.js":
            assert "sessionStorage" not in text, f"{rel(path)}: the token module is the only one that touches sessionStorage"
    token = (INTERFACE / "js" / "token.js").read_text(encoding="utf-8")
    assert "sessionStorage" in token and "document.cookie" not in token
    # Text of the service is put in the page as text: the builder never takes markup, and refuses a style or an event attribute.
    dom = (INTERFACE / "js" / "dom.js").read_text(encoding="utf-8")
    assert "textContent" in dom and "FORBIDDEN" in dom


def test_the_page_is_one_policy_safe_html_document_with_the_library_and_its_own_modules():
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in html and "<title>" in html
    assert re.search(r'href="\./vendor/[a-z]+/[a-z]+\.css"', html) and 'src="./js/main.js"' in html
    assert not (INTERFACE / "package.json").exists() and not (INTERFACE / "node_modules").exists(), "no build step, no package"
    linked = [path.name for path in css_paths()]
    assert linked == ["base.css", "frame.css", "token.css", "city.css", "building.css", "floor.css", "lobby.css", "control.css"], "the page's stylesheets are linked in the cascade's order: the shared ones, the frame, then one file per screen"
    assert sorted(path.name for path in (INTERFACE / "css").glob("*.css")) == sorted(linked), "every stylesheet of interface/css is linked, and nothing else is there"
    assert html.index('href="./css/' + linked[-1] + '"') < html.index('href="./scene.css"'), "the scene's own stylesheet loads after the page's"
    assert not (INTERFACE / "style.css").exists(), "the one stylesheet was split by screen: no file of that name is left behind"
    css = interface_css()
    assert "prefers-reduced-motion" in css and "16px" in css
    assert not LITERAL_COLOUR.search(BRAND_LINE.sub("", css)), "the stylesheets set no colour of their own but the brand pair: the library's tokens decide"


# --- what the screens call, and when they read ---------------------------------------------------------------------------------


def test_every_client_function_the_screens_call_exists_and_the_city_only_reads():
    exported = set(re.findall(r"^export (?:async )?function (\w+)", CLIENT.read_text(encoding="utf-8"), re.M))
    writes = {"answer", "release", "approve", "reject", "request", "route", "cancel", "retry", "handOver", "verdict", "setMode", "say", "sync", "dispatch"}
    used = {}
    used_outside_floor = {}
    for path in own_files():
        if path.suffix != ".js" or path == CLIENT:
            continue
        for name in re.findall(r"\bapi\.(\w+)\(", path.read_text(encoding="utf-8")):
            used.setdefault(name, set()).add(path.name)
            if "floor" not in path.relative_to(INTERFACE / "js").parts[:-1]:
                used_outside_floor.setdefault(name, set()).add(path.name)
    assert {"projects", "status", "agents", "task"} <= set(used), "the City reads the project list, the status, the agents and one task"
    for name, files in used.items():
        assert name in exported or name == "onAuthFailure", f"{sorted(files)} call api.{name}, which api.js does not export"
    # WP-9.3b: the decision cards, the Agent tab and the request line send the page's writes, and they live in js/floor/ (their
    # client is handed to them through their environment); the City, the Building, the frame and the views only read.
    LOBBY_WRITERS = {p.name for p in (INTERFACE / "js" / "views").glob("lobby*.js")} | {p.name for p in (INTERFACE / "js" / "cards").glob("*.js")}
    lobby_only = {n: {f for f in files if f not in LOBBY_WRITERS} for n, files in used_outside_floor.items()}
    assert not ({n for n, files in lobby_only.items() if files} & writes), f"only js/floor/ and the Lobby's modules write: {sorted(n for n, f in lobby_only.items() if f and n in writes)}"


def test_the_page_is_kept_current_by_the_watcher_and_asks_nothing_while_hidden():
    # WP-9.13: the 5 s poll of WP-9.2a is gone; the watcher (watch.js, tested with a fake clock in test_interface_live.py) reads the
    # change signal every second while the document is visible, and the page reloads when a number moved, after any write, and once on return.
    main = (INTERFACE / "js" / "main.js").read_text(encoding="utf-8")
    assert "POLL_MS" not in main and "RETRY_MS" not in main and "setInterval" not in main
    assert 'from "./watch.js"' in main and "createWatcher({" in main and "read: versionKey" in main
    assert re.search(r"hidden: \(\) => document\.hidden", main), "the watcher is told whether the document is hidden"
    assert 'addEventListener("visibilitychange"' in main and "watcher.visibilityChanged()" in main and "stopPolling()" in main
    assert re.search(r"api\.onWrite\(\(\) => \{\s*if \(frame\) reload\(\);", main), "any write the page sends is answered by a reload at once"
    for view in ("building", "floor", "lobby", "control"):
        assert re.search(rf"view\.{view}\.update\(\{{[^}}]*reload: reloads", main), f"the {view} is given the reload stamp"
    assert "refresh(snapshot, lastFollowed, { force: true })" in main, "a reload ignores the cached task bodies"
    watch = (INTERFACE / "js" / "watch.js").read_text(encoding="utf-8")
    assert "setInterval" not in watch and not re.search(r"\bfetch\(|import .* from \"\./(api|views)", watch), "the watcher reads and keeps time only through what it is given"
    assert "const EVERY_MS = 1000;" in watch and "const SAFETY_MS = 30000;" in watch


def test_every_screen_that_reads_takes_the_reload_stamp_and_none_polls_on_its_own():
    views = INTERFACE / "js" / "views"
    for name in ("floor.js", "building.js", "lobby.js", "control.js"):
        text = (views / name).read_text(encoding="utf-8")
        assert re.search(r"reloaded !== null && (data\.reload|reload|state\.reload) !== reloaded", text), f"{name} reads again when the stamp moves"
    for name in ("lobby-desk.js", "lobby-agent.js"):
        assert re.search(r"reload\(\) \{", (views / name).read_text(encoding="utf-8")), f"{name} marks what it holds stale on a reload"
    assert "visibilitychange" not in (views / "control.js").read_text(encoding="utf-8"), "the page reloads on return; the control room does not read by itself"
    for path in sorted(views.glob("*.js")):
        assert "setInterval" not in path.read_text(encoding="utf-8"), path.name


def test_the_screens_keep_no_state_in_a_global_and_the_token_stays_in_the_token_module():
    for path in own_files():
        if path.suffix != ".js":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bwindow\.__|\bglobalThis\.\w+\s*=", text), f"{rel(path)} keeps state in a global"
        if path.name not in ("token.js", "api.js", "main.js"):
            assert not re.search(r"\b(?:getToken|setToken)\(", text), f"{rel(path)} touches the token"


# --- WP-9.3b: the Building and the Floor ----------------------------------------------------------------------------------------

FLOOR_FILES = ("floor-model.js", "floor/actions.js", "floor/agent-tab.js", "floor/cards.js", "floor/desk-tab.js", "floor/inbox.js",
               "floor/viewer.js", "floor/widgets.js", "views/building.js", "views/floor.js",
               "scene/building.js", "scene/world.js", "scene/tower.js", "scene/furniture.js", "scene/plates.js",
               "scene/owl-build.js", "scene/owl-motion.js", "scene/room-frame.js", "scene/room-words.js")   # R-41, R-23: the figure is gone, the owl and the room's measures are new


def test_the_building_and_the_floor_are_files_of_the_page_and_the_page_routes_to_them():
    for name in FLOOR_FILES:
        assert (INTERFACE / "js" / name).is_file(), f"interface/js/{name} is a file of the page"
    main = (INTERFACE / "js" / "main.js").read_text(encoding="utf-8")
    assert "createBuildingView" in main and "createFloorView" in main, "the page opens the Building and the Floor, not a placeholder"
    router = (INTERFACE / "js" / "router.js").read_text(encoding="utf-8")
    assert "deskHash" in router and "/desk/" in router, "a document of the desk has a hash of its own"
    assert 'import("' not in main and "import(" not in "".join((INTERFACE / "js" / n).read_text(encoding="utf-8") for n in FLOOR_FILES), "no dynamic import: every file is a static module of the page"


def test_only_the_floor_folder_sends_a_write_and_it_takes_every_write_from_one_object():
    # ADJ-I2: `goAhead` (a task that waits) and `route` (the unrecognised-route card routes a request with a flow) are writes; `flows` is the one read the
    # same object carries, for the flow list of that card.
    writes = {"answer", "release", "approve", "reject", "verdict", "cancel", "setMode", "retry", "handOver", "goAhead", "route"}
    reads = {"pollJob", "flows"}
    actions = (INTERFACE / "js" / "floor" / "actions.js").read_text(encoding="utf-8")
    assert set(re.findall(r"^\s+(\w+): api\.(\w+),$", actions, re.M)) == {(w, w) for w in writes | reads}, "actions.js names each write once"
    for name in FLOOR_FILES:
        text = (INTERFACE / "js" / name).read_text(encoding="utf-8")
        if name.startswith(("views/", "scene/")) or name == "floor-model.js":
            assert not (set(re.findall(r"\bapi\.(\w+)\(", text)) & writes), f"{name} only reads"
        if name.startswith("floor/") and name not in ("floor/actions.js", "floor/cards.js", "floor/agent-tab.js"):
            sends = re.findall(r"(?:\bapi\(\)|\bapi|\bactions)\.(\w+)\(", text)
            assert not (set(sends) & writes), f"{name} sends no write: only cards.js and agent-tab.js do, through their environment ({sorted(set(sends) & writes)})"
        if name in ("floor/cards.js", "floor/agent-tab.js"):
            assert 'from "../api.js"' not in text, f"{name} sends through its environment (a client it is given), not through a client of its own"
            assert set(re.findall(r"\bapi\(?\)?\.(\w+)\(", text)) <= writes | reads, f"{name} calls only the operations of its panel"


def test_a_card_sends_the_hash_it_shows_read_back_from_its_own_text_and_nothing_decides_for_the_person():
    cards = (INTERFACE / "js" / "floor" / "cards.js").read_text(encoding="utf-8")
    assert cards.count("state.hashNode.textContent") >= 2, "an effect and a plan are approved with the hash read from the page's own text"
    assert re.search(r"shown !== it\.payload_sha256", cards) and re.search(r"shown !== \(it\.payload && it\.payload\.plan_sha256\)", cards), \
        "a hash that is not the decision's is refused before any request"
    assert "api().approve(env.project, it.id, shown)" in cards and "api().approve(env.project, it.id)" in cards, "an acceptance sends no hash"
    assert not re.search(r"\.trim\(\)\s*\)\s*return\s+refuse", cards) or "typed.answer.trim()" in cards, "an empty answer is not sent"
    for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "eval("):  # security-scan: allow dynamic-eval -- a pattern that forbids a call; nothing runs it
        assert forbidden not in cards, f"cards.js builds text with textContent only: {forbidden}"


def test_the_ids_the_scenes_register_are_the_ids_the_screens_open():
    building = (INTERFACE / "js" / "scene" / "world.js").read_text(encoding="utf-8")   # the world draws the buildings: it registers the floors and the door
    room = (INTERFACE / "js" / "scene" / "world.js").read_text(encoding="utf-8")
    floor_view = (INTERFACE / "js" / "views" / "floor.js").read_text(encoding="utf-8")
    building_view = (INTERFACE / "js" / "views" / "building.js").read_text(encoding="utf-8")
    for hit in re.findall(r'hits\.push\(\{[^}]*id: "([a-z-]+)"', room):
        if hit in ("agent", "desk", "tray", "tasks"):
            assert f'"{hit}"' in floor_view, f"the Floor opens something for the room's {hit}"
    # R-31: the room's ways in are the owl (`agent`, or `tray` when it asks something), the board (`tasks`) and the bookcase (`desk`); a document is no longer an object of its own
    # (R-23: no table of sheets). The board is a way in (R-23b, R-31): the Floor and the Lobby open the Tasks tab for its id `tasks` (the loop above).
    assert '"tasks"' in room and 'asks ? "tray" : "agent"' in room and "sheet:" not in room
    assert "floor:" in building and "floor:" in building_view and '"door"' in building and "door" in building_view


def test_every_wb_class_the_new_modules_build_is_styled_or_a_hook_the_scripts_read():
    css = interface_css()
    hooks = {"wb-tabpanel", "wb-floor-normal", "wb-label-name", "wb-label-sub", "wb-state-box", "wb-cancel-dialog", "wb-share", "wb-y", "wb-request", "wb-chip", "wb-panel-building"}   # M-3: the Building panel's class named a rule only in the docked band, which is gone; a prefix of a built name, or a custom property
    missing = {}
    for name in FLOOR_FILES:
        text = (INTERFACE / "js" / name).read_text(encoding="utf-8")
        for cls in set(re.findall(r"\bwb-[a-z0-9]+(?:-[a-z0-9]+)*", text)):
            if cls.startswith(("wb-icon", "wb-i1")) or cls in hooks:
                continue
            if not re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css) and f'"{cls}"' not in text.replace("class:", ""):
                missing.setdefault(cls, []).append(name)
    assert not missing, f"classes the modules build that the stylesheets never name: {missing}"


def test_escape_leaves_a_draft_alone_and_leaving_the_inbox_keeps_a_card_whose_job_runs():
    floor = (INTERFACE / "js" / "views" / "floor.js").read_text(encoding="utf-8")
    escape = (INTERFACE / "js" / "frame" / "escape.js").read_text(encoding="utf-8")
    assert 'if (field) return { step: "none" };' in escape, "Escape does nothing while the person types in a field (the frame's one handler)"
    assert "Escape" not in floor, "the Floor has no Escape handler of its own"
    assert "!inbox.busy()" in floor, "the Inbox is reset only when no card has a request in flight"
    inbox = (INTERFACE / "js" / "floor" / "inbox.js").read_text(encoding="utf-8")
    cards = (INTERFACE / "js" / "floor" / "cards.js").read_text(encoding="utf-8")
    assert "isBusy()" in inbox and "isBusy()" in cards


# --- the Lobby (WP-9.4): its own checks are in test_interface_lobby.py; these are the rules read from the files --------------------


def test_the_lobby_calls_only_routes_of_the_service_and_every_hash_it_links_to_is_a_form_of_the_router():
    names = ("lobby.js", "lobby-actions.js", "lobby-request.js", "plan.js")
    files = [p for p in own_files() if p.name in names]
    assert {p.name for p in files} == set(names), "the Lobby's modules are where the package puts them"
    exported = set(re.findall(r"^export (?:async )?function (\w+)", CLIENT.read_text(encoding="utf-8"), re.M))
    wanted = {"say", "conversation", "request", "route", "cancel", "approve", "reject", "flows", "task", "pollJob"}
    assert wanted <= exported, "the client has the Lobby's calls"
    routes = {(r["method"], r["pattern"]) for r in service.ROUTES}
    for route in (("POST", "/projects/{p}/conversation"), ("GET", "/projects/{p}/conversation"), ("POST", "/projects/{p}/requests"),
                  ("POST", "/projects/{p}/requests/{id}/route"), ("POST", "/projects/{p}/requests/{id}/cancel"), ("GET", "/projects/{p}/flows"),
                  ("GET", "/projects/{p}/tasks/{id}"), ("POST", "/projects/{p}/pending/{id}/approve"), ("POST", "/projects/{p}/pending/{id}/reject")):
        assert route in routes, f"{route} is not a route of the service"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r'href: ([^,}]+)', text):
            assert target.strip().startswith("router.") or target.strip().startswith('"#'), f"{path.name}: a link that is not built by the router: {target}"


def test_the_lobby_shows_what_came_as_text_only_and_keeps_no_state_outside_its_view():
    for name in ("lobby.js", "lobby-thread.js", "lobby-request.js", "lobby-composer.js", "lobby-form.js", "plan.js"):
        path = next(p for p in own_files() if p.name == name)
        text = path.read_text(encoding="utf-8")
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "createContextualFragment" not in text, name
        assert not re.search(r"\.style\b|setAttribute\(\s*[\"']style", text), f"{name} writes no style"
    lobby = (INTERFACE / "js" / "views" / "lobby.js").read_text(encoding="utf-8")
    assert "setInterval" not in lobby, "the conversation is read by a timeout that the visibility rule can stop"
    assert "localStorage" not in lobby and "sessionStorage" not in lobby


# --- WP-9.4b: the Lobby's Inbox, Desk and Agent tabs reuse the Floor's modules ---------------------------------------------------

LOBBY_TAB_FILES = ("views/lobby-inbox.js", "views/lobby-desk.js", "views/lobby-agent.js")


def test_the_lobbys_tabs_are_the_floors_modules_with_no_card_of_their_own_and_no_write_path_of_their_own():
    texts = {name: (INTERFACE / "js" / name).read_text(encoding="utf-8") for name in LOBBY_TAB_FILES}
    assert 'from "../floor/inbox.js"' in texts["views/lobby-inbox.js"] and 'from "../floor/actions.js"' in texts["views/lobby-inbox.js"]
    assert 'from "../floor/desk-tab.js"' in texts["views/lobby-desk.js"] and 'from "../floor/viewer.js"' in texts["views/lobby-desk.js"]
    assert 'from "../floor/agent-tab.js"' in texts["views/lobby-agent.js"] and 'from "../floor/actions.js"' in texts["views/lobby-agent.js"]
    writes = {"answer", "release", "approve", "reject", "request", "route", "cancel", "retry", "handOver", "verdict", "setMode", "say", "sync", "dispatch"}
    for name, text in texts.items():
        assert not (set(re.findall(r"\bapi\.(\w+)\(", text)) & writes), f"{name} sends no write: the Floor's modules do, through floor/actions.js"
        assert not re.search(r"\bfetch\(|createCard\(|createPlanCard\(", text), f"{name} has no client and no card of its own"
        assert not re.search(r"innerHTML|insertAdjacentHTML|\.style\b", text), name
    reads = set()
    for text in texts.values():
        reads |= set(re.findall(r"\bapi\.(\w+)\(", text))
    assert reads == {"artifacts", "task"}, f"the tabs read only the documents and a task's body: {sorted(reads)}"
    assert {"artifacts", "artifact", "task", "pendingItem"} <= set(re.findall(r"^export (?:async )?function (\w+)", CLIENT.read_text(encoding="utf-8"), re.M))
    routes = {(r["method"], r["pattern"]) for r in service.ROUTES}
    for route in (("GET", "/projects/{p}/artifacts"), ("GET", "/projects/{p}/artifact"), ("GET", "/projects/{p}/pending/{id}"), ("GET", "/projects/{p}/tasks/{id}"),
                  ("POST", "/projects/{p}/agents/{name}/mode")):
        assert route in routes, f"{route} is not a route of the service"


def test_the_lobbys_tabs_link_only_through_the_router_and_the_floors_modules_change_only_by_a_parameter():
    inbox = (INTERFACE / "js" / "views" / "lobby-inbox.js").read_text(encoding="utf-8")
    for target in re.findall(r"href: ([^,}]+)", inbox):
        assert target.strip().startswith("router."), f"lobby-inbox.js links without the router: {target}"
    assert "router.lobbyDeskHash(project, path)" in inbox, 'a returned path opens in the Lobby\'s Desk, never in a floor "planning"'
    # the Floor's own view calls the model, the Inbox and the Agent tab as it did: no option, no emptyText
    floor_view = (INTERFACE / "js" / "views" / "floor.js").read_text(encoding="utf-8")
    assert "lobby: true" not in floor_view and "emptyText" not in floor_view
    model = (INTERFACE / "js" / "floor-model.js").read_text(encoding="utf-8")
    assert "name === PLANNING && !options.lobby" in model, "the planning agent is found only when the Lobby asks"
    inbox_module = (INTERFACE / "js" / "floor" / "inbox.js").read_text(encoding="utf-8")
    assert 'last.emptyText || "Nothing waits for you on this floor."' in inbox_module, "the Floor's empty line is the default"


def test_no_lobby_module_takes_a_write_out_of_the_client_by_name_or_by_destructuring():
    writes = {"answer", "release", "approve", "reject", "request", "route", "cancel", "retry", "handOver", "verdict", "setMode", "say", "sync", "dispatch"}
    for path in sorted((INTERFACE / "js" / "views").glob("lobby*.js")):
        text = path.read_text(encoding="utf-8")
        for names in re.findall(r"import\s*\{([^}]*)\}\s*from\s*[\"'][./]*api\.js[\"']", text):
            assert not ({n.strip().split(" as ")[0] for n in names.split(",")} & writes), f"{path.name} imports a write of the client by name"
        for names in re.findall(r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*api\b", text):
            assert not ({n.strip().split(":")[0].strip() for n in names.split(",")} & writes), f"{path.name} destructures a write out of the client"
        assert not re.search(r"\bapi\s*\[", text), f"{path.name} picks an operation of the client by a computed name"
        for name in writes:
            assert not re.search(rf"=\s*api\.{name}\b(?!\()", text), f"{path.name} takes api.{name} as a value"


# --- the Control room (WP-9.5): what it calls, and that every class it uses is drawn by the stylesheet ---------------------------


def control_modules():
    return sorted((INTERFACE / "js" / "views").glob("control*.js"))


def client_functions():
    """{function name: (method, path template)} of every exported function of the client that makes one call."""
    source = CLIENT.read_text(encoding="utf-8")
    out = {}
    for found in re.finditer(r"export (?:async )?function (\w+)\([^)]*\)\s*\{\s*return send\(\s*\"(GET|POST)\"\s*,\s*(?:\"|`)([^\"`]*)", source):
        out[found.group(1)] = (found.group(2), found.group(3))
    return out


def test_the_control_room_calls_only_the_four_reads_it_needs_and_each_is_a_get_route_of_the_service():
    files = control_modules()
    assert len(files) >= 6, "the Control room's modules are there"
    used = set()
    for path in files:
        used |= set(re.findall(r"\bapi\.(\w+)\(", path.read_text(encoding="utf-8")))
    assert used == {"skills", "costs", "connections", "agents"}, f"the Control room reads skills, costs, connections and agents: {sorted(used)}"
    functions = client_functions()
    routes = [(r["method"], shape(r["pattern"]), r) for r in service.ROUTES]
    for name in sorted(used):
        method, template = functions[name]
        assert method == "GET", f"api.{name} is a read"
        found = [r for m, s, r in routes if m == method and s == shape(template)]
        assert found, f"api.{name} calls {template}, which is not a route of the service"
        assert found[0]["pattern"].rsplit("/", 1)[-1] == name, f"api.{name} is the route of the operation of the same name"
    assert "since" in re.search(r"export function costs\([^)]*\)", CLIENT.read_text(encoding="utf-8")).group(0), "the Costs tab sends the date through the client's one query"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bfetch\(|XMLHttpRequest|\bEventSource\b|\bsendBeacon\b", text), f"{path.name} has a second way to reach the service"
        assert not re.search(r"\bapi\.(?:%s)\(" % "|".join(sorted(["answer", "release", "approve", "reject", "request", "route", "cancel", "retry", "handOver", "verdict", "setMode", "say", "sync", "dispatch"])), text), f"{path.name} writes"


def test_the_control_room_imports_the_client_only_as_a_namespace_and_escape_leaves_a_typed_field_alone():
    for path in control_modules():
        text = path.read_text(encoding="utf-8")
        imports = re.findall(r'^import\s+(.+?)\s+from\s+"\.\./api\.js";', text, re.M)
        assert all(found == "* as api" for found in imports), f"{path.name} imports the client other than as `* as api`: {imports}"
        assert not re.search(r'import\s*\{[^}]*\}\s*from\s*"\.\./api\.js"|api\.js"\)', text), f"{path.name}: a named or dynamic import of the client would escape the read-only check"
    control = (INTERFACE / "js" / "views" / "control.js").read_text(encoding="utf-8")
    assert "Escape" not in control, "the Control room has no Escape handler of its own (the frame's one goes up)"


# --- a function that is called must be declared, imported or global (WP-9.15a: the Floor's Close called a function a refactor had deleted) ---

# The globals a page module may call without declaring them: the language's, the browser's. A name that is not here and not declared in
# the file is a call to nothing.
KNOWN_GLOBALS = frozenset("""
Array Boolean Date Error Event Map Number Object Promise RangeError RegExp Set String Symbol TypeError Uint8Array Float32Array Float64Array
Uint16Array Uint32Array Int32Array ArrayBuffer WeakMap WeakSet BigInt Intl JSON Math Reflect Proxy
AbortController CustomEvent KeyboardEvent MouseEvent MutationObserver ResizeObserver IntersectionObserver URL URLSearchParams Image TextEncoder TextDecoder
fetch setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame requestIdleCallback queueMicrotask structuredClone
parseInt parseFloat isNaN isFinite encodeURIComponent decodeURIComponent atob btoa getComputedStyle matchMedia
if for while switch catch function async return typeof await new import super delete void yield do else DOMException
""".split())

_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
_WORD = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)(?![\w$])")


def strip_js(source: str) -> str:
    """The code of a module with its comments removed, its strings and regular expressions emptied, and each template literal reduced to the
    code of its `${}` parts: what is left is only what can name something."""
    out: list[str] = []
    i, n = 0, len(source)

    def scan_template(at: int) -> int:
        nonlocal out
        at += 1
        while at < n and source[at] != "`":
            if source[at] == "\\":
                at += 2
            elif source.startswith("${", at):
                depth, start = 1, at + 2
                at = start
                while at < n and depth:
                    depth += {"{": 1, "}": -1}.get(source[at], 0)
                    at += 1
                out.append(" (" + strip_js(source[start:at - 1]) + ") ")
            else:
                at += 1
        return at + 1

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            i = source.find("\n", i)
            i = n if i < 0 else i
        elif source.startswith("/*", i):
            i = source.find("*/", i)
            i = n if i < 0 else i + 2
        elif c in "\"'":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            out.append('""')
            i = j + 1
        elif c == "`":
            i = scan_template(i)
        elif c == "/" and re.search(r"[(,=:\[!&|?{};]\s*$|^\s*$|\breturn\s*$", "".join(out)[-40:]):
            j, in_class = i + 1, False
            while j < n and (source[j] != "/" or in_class):
                if source[j] == "\\":
                    j += 1
                elif source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                j += 1
            out.append("/r/")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def undeclared_calls(source: str) -> list[str]:
    """Names that the module calls and never mentions otherwise (not declared, imported, a parameter, a property or a known global)."""
    code = strip_js(source)
    calls, others = set(), set()
    for match in _WORD.finditer(code):
        name, start = match.group(1), match.start(1)
        before = code[:start].rstrip()
        if before.endswith(".") or before.endswith("..."):
            if before.endswith("...") and not code[match.end():].lstrip().startswith("("):
                others.add(name)
            continue
        after = code[match.end():]
        if after.lstrip().startswith("(") and not before.endswith(("function", "function*", "get", "set")):
            depth, k = 0, match.end() + len(after) - len(after.lstrip())
            while k < len(code):
                depth += {"(": 1, ")": -1}.get(code[k], 0)
                k += 1
                if depth == 0:
                    break
            if code[k:].lstrip().startswith("{"):      # a definition: method shorthand, `if (...) {`, `for (...) {`
                others.add(name)
            else:
                calls.add(name)
        else:
            others.add(name)
    return sorted(calls - others - KNOWN_GLOBALS)


def test_the_scan_for_calls_to_nothing_finds_one_and_passes_what_is_declared():
    bad = 'import { a } from "./a.js";\nconst viewer = createViewer({ onClose: () => closeViewer() });\n'
    assert undeclared_calls(bad) == ["closeViewer", "createViewer"]
    good = '''import { createViewer } from "./v.js";
function closeViewer() { go(); }
const go = () => {};
export function make({ onClose }, items) {
  const text = `${items.map((x) => fmt(x)).join(",")} and ${onClose()}`;
  for (const item of items) { if (item) { run(item); } }
  return { start() { setTimeout(run, 0); }, run(x) { return /["']\\//.test(x); } };
  function fmt(x) { return String(x); }
  function run(x) { return x; }
}
const viewer = createViewer({ onClose: () => closeViewer() });
'''
    assert undeclared_calls(good) == []


def test_no_module_of_the_page_calls_a_function_it_does_not_declare_import_or_get_from_the_browser():
    found = {rel(path): names for path in own_files() if path.suffix == ".js" for names in [undeclared_calls(path.read_text(encoding="utf-8"))] if names}
    assert found == {}, f"called and never declared, imported or known as a global: {found}"


# --- WP-9.16: the Tasks tab of a floor ------------------------------------------------------------------------------------------

TASKS_TAB_FILES = ("floor/tasks-model.js", "floor/tasks-tab.js", "floor/run-block.js")


def test_the_tasks_tab_is_the_fourth_tab_of_a_floor_and_a_tab_of_the_lobby_and_each_view_gives_it_the_floors_client_and_router_links():
    floor_view = (INTERFACE / "js" / "views" / "floor.js").read_text(encoding="utf-8")
    assert re.search(r'TABS = \[\{ id: "agent", label: "Agent" \}, \{ id: "inbox", label: "Inbox" \}, \{ id: "desk", label: "Desk" \}, \{ id: "tasks", label: "Tasks" \}\]', floor_view), \
        "the Floor's tabs are Agent, Inbox, Desk and Tasks, in that order"
    assert 'import { createTasksTab } from "../floor/tasks-tab.js";' in floor_view and "createTasksTab({" in floor_view
    lobby_model = (INTERFACE / "js" / "views" / "lobby-model.js").read_text(encoding="utf-8")
    assert '["desk", "Desk"], ["tasks", "Tasks"], ["agent", "Agent"]' in lobby_model, "the Lobby's Tasks tab is beside its Desk tab"
    lobby = (INTERFACE / "js" / "views" / "lobby.js").read_text(encoding="utf-8")
    assert 'import { createTasksTab } from "../floor/tasks-tab.js";' in lobby and "createTasksTab({" in lobby
    assert "reload: last.reload" in floor_view and "reload: reloaded" in lobby, "each view gives the tab the page's reload stamp (WP-9.13)"
    for name, text in (("floor.js", floor_view), ("lobby.js", lobby)):
        call = text[text.index("createTasksTab({"):]
        call = call[:call.index("});") + 3]
        assert re.search(r"\bapi: actions\b", call), f"{name} hands the tab the Floor's one object of writes"
        for target in re.findall(r"\b(?:request|inbox|open): \([^)]*\) => ([^,}]+)", call):
            assert target.strip().startswith("router."), f"{name} builds the tab's links with the router: {target}"


# --- OH-3: the brand colour, the favicon, the mark and the product's name --------------------------------------------------------

FAVICON = INTERFACE / "favicon.svg"
MARK = INTERFACE / "brand" / "openhora-mark.svg"
# The first path of each drawing, and the hash of the file as the page ships it (the maintainer's drawing with its provenance
# metadata block removed and nothing else changed). A new drawing changes these two lines on purpose.
FAVICON_FIRST_PATH = "M40 76 Q26 40 34 16 Q62 30 80 52Z"
FAVICON_SHA256 = "75f49e4b62fcb62729826d25023066036536f97365cf644d387fbbcc521b2da4"
MARK_FIRST_PATH = "M44 70 Q30 40 36 22 Q60 34 74 50Z"
MARK_SHA256 = "d00da3f5cbde96e252154f321d6c5b94d322518f014afc15b64874aca5bab242"


def test_the_brand_pair_is_the_one_primary_token_and_is_set_once_at_root():
    css = interface_css()
    lines = BRAND_LINE.findall(css)
    assert len(lines) == 1, "the brand pair is set on one line"
    assert re.findall(r"--pui-theme\s*:[^;]*;", css) == [f"--pui-theme: {BRAND_PAIR};"], "the primary token is declared once, with the pair, light then dark"
    root = re.search(r"^:root \{\n(.*?)^\}", css, re.S | re.M)
    assert root and lines[0].strip() in root.group(1), "the pair is set in the :root block, beside the other tokens"
    assert not re.search(r"--pui-(?!theme\b|radius\b)[a-z-]+\s*:", root.group(1)), "no other token of the library is set at :root by the page but the radius (R-12: 0.625 rem)"
    assert re.search(r"--pui-radius: 0\.625rem;", root.group(1)), "R-12: the corners are 0.625 rem (10 px)"
    comment = css[:css.index(lines[0].strip())].rsplit("/*", 1)[-1]
    assert "brand" in comment.lower() and "*/" in comment, "a comment above the line names it the brand pair"
    colours = LITERAL_COLOUR.findall(css)
    assert sorted(colours) == ["#6B4429", "#C99A6E"], f"the pair is the only colour literal of the stylesheet: {colours}"
    # the scene reads the one token (a probe element), so its selection outline and its running colour follow it, with no constant of their own
    palette = (INTERFACE / "js" / "scene" / "palette.js").read_text(encoding="utf-8")
    assert 'theme: "--pui-theme"' in palette
    engine = (INTERFACE / "js" / "scene" / "engine.js").read_text(encoding="utf-8")
    assert "outlineMaterial.color.copy(palette.T.theme)" in engine, "the selection outline takes the token's colour"
    for path in sorted((INTERFACE / "js").rglob("*.js")):
        if path.name == "owl.js":   # R-41: the owl is the mark's own drawing in its fixed palette, the brand's exception: its brown is the pair's light half, and only that
            assert not re.search(r"C99A6E", path.read_text(encoding="utf-8"), re.I), "owl.js holds the light brown of the pair only (the mark's brown), never the dark one"
            continue
        if path.name == "token-owl.js":
            continue      # R-15, R-41: the owl is the brand's drawing and keeps the mark's own fixed palette (the owl module of the scene is the second such file)
        assert not re.search(r"6B4429|C99A6E", path.read_text(encoding="utf-8"), re.I), f"{rel(path)} holds a copy of the brand colour: it reads the token"


def svg_text_without_namespaces(path: Path) -> str:
    return re.sub(r'\sxmlns(?::\w+)?="[^"]*"', "", path.read_text(encoding="utf-8"))


def first_path(path: Path) -> str:
    root = ET.parse(path).getroot()
    found = next(e for e in root.iter() if e.tag.endswith("}path") or e.tag == "path")
    return found.attrib["d"]


def test_the_favicon_is_the_simplified_mark_and_the_two_drawings_carry_nothing_but_drawing():
    assert first_path(FAVICON) == FAVICON_FIRST_PATH, "interface/favicon.svg is the simplified mark"
    assert first_path(MARK) == MARK_FIRST_PATH, "interface/brand/openhora-mark.svg is the full mark"
    assert hashlib.sha256(FAVICON.read_bytes()).hexdigest() == FAVICON_SHA256
    assert hashlib.sha256(MARK.read_bytes()).hexdigest() == MARK_SHA256
    for path in (FAVICON, MARK):
        text = path.read_text(encoding="utf-8")
        assert ET.parse(path).getroot().tag.endswith("}svg"), f"{rel(path)} is one SVG document"
        assert not re.search(r"<metadata|base64|c2pa", text, re.I), f"{rel(path)} carries no provenance block, not even its namespace"
        bare = svg_text_without_namespaces(path)
        assert not re.search(r"<script|<foreignObject|<style|<image|<use\b|\bhref\b|\bxlink:|data:|https?://|\son[a-z]+\s*=", bare, re.I), \
            f"{rel(path)} holds nothing but shapes: no script, no link, no external host, no embedded data"
        assert len(path.read_bytes()) < 4096, f"{rel(path)} is a small drawing"
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<link rel="icon" type="image/svg\+xml" href="\./favicon\.svg">', html)
    assert service.TYPES[".svg"] == "image/svg+xml", "the service serves the drawings, and /favicon.ico answers with the favicon"


def test_the_mark_file_is_named_in_one_module_that_builds_an_img_and_nowhere_else():
    named = [rel(p) for p in own_files() if "openhora-mark.svg" in p.read_text(encoding="utf-8")]
    assert named == ["interface/js/brand.js"], f"only the brand module names the mark file: {named}"
    brand = (INTERFACE / "js" / "brand.js").read_text(encoding="utf-8")
    assert 'const MARK_SRC = "./brand/openhora-mark.svg";' in brand and (INTERFACE / "brand" / "openhora-mark.svg").is_file()
    assert re.search(r'h\("img",\s*\{[^}]*\bsrc: MARK_SRC\b[^}]*\balt\b[^}]*\}', brand, re.S) and 'alt = "openhora"' in brand, "the mark is an <img> whose alt text is the product's name by default"
    assert 'markImage(24, "")' in (INTERFACE / "js" / "views" / "token-prompt.js").read_text(encoding="utf-8"), "on the prompt the name stands beside the mark as text, so the image has an empty alt"
    css = interface_css()
    assert "max-width: 711px" not in css, "R-1: the mark is in the top row's brand box, which a phone does not draw (D-3: the favicon carries the brand there); the 712 px rule is gone"
    assert not re.search(r"innerHTML|data:|createElementNS|insertAdjacentHTML", brand), "never markup from a string, never a data: URI"
    header = (INTERFACE / "js" / "frame" / "header.js").read_text(encoding="utf-8")
    prompt = (INTERFACE / "js" / "views" / "token-prompt.js").read_text(encoding="utf-8")
    assert 'from "../brand.js"' in header and "markImage(28" in header, "R-1: the top row's brand shows the mark at 28 px"
    assert 'from "../brand.js"' in prompt and "markImage(24" in prompt, "R-13: the token prompt's bar shows the mark at 24 px"
    css = interface_css()
    for cls in ("wb-mark", "wb-brand", "wb-wordmark"):
        assert re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css), f"{cls} is a rule of the stylesheet"


def test_the_page_is_named_openhora_and_the_token_prompts_heading_names_the_product():
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert "<title>openhora</title>" in html and "Workbench" not in html
    prompt = (INTERFACE / "js" / "views" / "token-prompt.js").read_text(encoding="utf-8")
    assert 'text: "Paste the openhora service token"' in prompt and 'text: "openhora"' in prompt, "the heading and the wordmark text name the product"
    assert "Paste the service token" not in prompt


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed: the modules are checked only by their text")
def test_every_module_of_the_page_parses_under_node_check():
    node = shutil.which("node")
    files = sorted((INTERFACE / "js").rglob("*.js"))
    assert len(files) >= 80, "the page's modules were found"

    def check(path: Path):
        done = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
        return rel(path), done.returncode, done.stderr.strip()

    with ThreadPoolExecutor(max_workers=8) as pool:
        failed = [r for r in pool.map(check, files) if r[1] != 0]
    assert failed == [], f"node --check fails on: {failed}"
