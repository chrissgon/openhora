# providers/script: the runner of a project's own script

The provider of the class `script:project` (runtime only; no skill may require it). The page `docs/architecture/platform/scripts.md` is the map and `providers/CONTRACT.md` has the verbs; this file is the folder's index.

| File | What it is |
|---|---|
| `container.py` | The host side: the commands (`run_command`, `proxy_command`, `build_command`), the network of a step (`Egress`), the frames, `run_script`, `build_deps`, `reap_all`, and the verbs `--check`, `build`, `run`, `deps`, `reap` |
| `_inner.py` | The program that runs inside the image: runs the script as a child with a short environment, reads its result back, prints frames; or installs the wheels of a hashed lock file |
| `egress_proxy.py` | The per-step egress proxy, the same image: CONNECT to the declared `host:port` pairs only, by name and by frozen address |
| `Dockerfile`, `.dockerignore` | The one image, from a base pinned by digest and a dated snapshot of the package archive |
| `tests/` | Offline tests; `test_script_docker.py` needs a local daemon and `WB_SCRIPT_DOCKER_TESTS=1` |

Build the image once, as a step you start: `python3 providers/script/container.py build --confirmed`.
