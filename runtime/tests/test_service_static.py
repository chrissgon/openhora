"""The service's listen backlog (R4-C2): the page loads dozens of modules and icons, each on a connection of its own
(every response closes), and a burst of them must not be reset by a full accept queue."""

from __future__ import annotations

import socket
import threading

from test_service import WAIT, Standin, run_serve, service

BURST = 100


def test_the_server_listens_with_a_backlog_that_holds_a_pages_burst():
    # The class default is 5 (socketserver.TCPServer.request_queue_size); on some systems a connection that finds a
    # full queue is reset. The attribute is the portable check; the next test is the one that shows the reset.
    assert service.Server.request_queue_size >= 128


def test_a_burst_of_simultaneous_static_requests_is_all_served(tmp_path):
    for n in range(BURST):
        (tmp_path / f"m{n}.js").write_text(f"export const n = {n};\n", encoding="utf-8")
    project = tmp_path / "alpha"
    project.mkdir()
    run = run_serve(Standin(tmp_path / "data"), [str(project)], service.Server, interface_dir=str(tmp_path))
    outcomes = []
    gate = threading.Barrier(BURST)
    lock = threading.Lock()

    def one(n):
        try:
            gate.wait(WAIT)
            with socket.create_connection(("127.0.0.1", run.service.port), timeout=WAIT) as s:
                s.sendall(f"GET /m{n}.js HTTP/1.1\r\nHost: 127.0.0.1:{run.service.port}\r\nConnection: close\r\n\r\n".encode())
                data = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            result = "ok" if data.startswith(b"HTTP/1.") and b" 200 " in data.split(b"\r\n")[0] and data.endswith(f"{n};\n".encode()) else "bad"
        except (OSError, threading.BrokenBarrierError) as e:
            result = type(e).__name__
        with lock:
            outcomes.append(result)

    try:
        threads = [threading.Thread(target=one, args=(n,)) for n in range(BURST)]
        [t.start() for t in threads]
        [t.join(WAIT * 3) for t in threads]
    finally:
        assert run.finish() == 0
    assert sorted(outcomes) == ["ok"] * BURST, {o: outcomes.count(o) for o in set(outcomes)}
