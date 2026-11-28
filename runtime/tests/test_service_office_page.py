"""The office of the local interface, served by the real service (eng-integration-tests): the page names the stylesheet before the scene's, and every file the
office is made of, and every module it imports, is served with the page's policy and the content type the service gives the page's other modules.
The service is started the way the terminal starts it (`service.serve` through `run_serve`), over the repository's own `interface/` folder, and read
with raw HTTP on its own port. No browser here: the page drawn from this service is looked at by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_office_page.py
"""
from __future__ import annotations

import posixpath
import re
import socket

import pytest

import standin_tree as st
from test_service import WAIT, Standin, run_serve, service

INTERFACE = st.REPO / "interface"
POLICY = "default-src 'self'; img-src 'self' blob:; media-src 'self' blob:; frame-ancestors 'none'"   # test_service.py asserts the same line
OFFICE_FILES = ["css/office.css", "js/views/office.js"] + sorted(f"js/office/{p.name}" for p in (INTERFACE / "js" / "office").glob("*.js"))
IMPORT = re.compile(r"""^\s*(?:import|export)\s[^;]*?\bfrom\s*["']([^"']+)["']|^\s*import\s*["']([^"']+)["']""", re.M)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    base = tmp_path_factory.mktemp("office-service")
    project = base / "alpha"
    project.mkdir()
    holder = run_serve(Standin(base / "data"), [str(project)], service.Server, interface_dir=str(INTERFACE))
    yield holder
    assert holder.finish() == 0


def get(run, path):
    """One raw GET (no token: the page's files need none): (status, headers, body)."""
    with socket.create_connection(("127.0.0.1", run.service.port), timeout=WAIT) as s:
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{run.service.port}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = {k.lower(): v for k, v in (line.split(": ", 1) for line in lines[1:])}
    return int(lines[0].split()[1]), headers, body


def test_the_service_serves_the_office_files_with_the_page_policy(run):
    status, headers, body = get(run, "/index.html")
    assert status == 200 and headers["content-security-policy"] == POLICY and headers["content-type"].startswith("text/html")
    page = body.decode("utf-8")
    assert './css/office.css' in page and page.index('./css/office.css') < page.index('./scene.css'), "the office's stylesheet loads before the scene's"
    assert page.index('./css/control.css') < page.index('./css/office.css')
    main = get(run, "/js/main.js")
    assert main[0] == 200
    for path in OFFICE_FILES:
        got_status, got_headers, got_body = get(run, "/" + path)
        assert got_status == 200 and got_body == (INTERFACE / path).read_bytes(), path
        expected = main[1]["content-type"] if path.endswith(".js") else "text/css; charset=utf-8"
        assert got_headers["content-type"] == expected, path
        assert got_headers["cache-control"] == "no-store" and got_headers["x-content-type-options"] == "nosniff", path
    assert len(OFFICE_FILES) == 10, "the stylesheet, the view and the eight modules are there"


def test_every_module_the_office_imports_is_served(run):
    seen, todo = set(), ["js/views/office.js"]
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        status, headers, body = get(run, "/" + path)
        assert status == 200 and headers["content-type"].startswith("text/javascript"), path
        for first, second in IMPORT.findall(body.decode("utf-8")):
            ref = first or second
            assert ref.startswith(("./", "../")), f"{path} imports {ref}"
            todo.append(posixpath.normpath(posixpath.join(posixpath.dirname(path), ref)))
    assert {"js/office/astar.js", "js/office/scene.js", "js/scene/loop.js", "js/scene/cull.js", "js/floor-model.js", "js/model.js"} <= seen
    assert not any("three" in name or "engine" in name for name in seen), "the office pulls in no 3D module"
