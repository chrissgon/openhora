"""Offline tests of the HyperFrames engine's image definition (providers/renderer/hyperframes-image/, package V3a-image): the manifest that
scopes its tag (review finding F11), the build context, the pins of both architectures, the lockfile, the fonts, the rules of the
Dockerfile, the build command, and the checks of a built image read through a fake container. No docker, no network: docker is never
started, and a test that would reach it fails.

Run: uv run --with pytest==9.1.1 pytest providers/renderer/tests/test_hf_image.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "providers" / "renderer"
FOLDER = RENDERER / "hyperframes-image"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hf = load("hf_image_under_test", FOLDER / "hf_image.py")
box = hf.box

NOT_IN_DEFINITION = {"hf_image.py", "README.md", "NOTICE.md", "LICENSE-registry-Apache-2.0.txt"}
READ_BY_DOCKER_ITSELF = {"manifest.json", "Dockerfile", ".dockerignore", "pins.json"}
OFFICIAL_CHROME = "https://storage.googleapis.com/chrome-for-testing-public/"
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
BUILD_ARGS = {"DEFINITION_HASH", "CHROME_VERSION", "CHROME_URL", "CHROME_SIZE", "CHROME_MD5", "CHROME_SHA256", "CHROME_BINARY",
              "FFMPEG_URL", "FFMPEG_SHA256", "FFMPEG_VERSION", "DEBIAN_SNAPSHOT", "HYPERFRAMES_VERSION", "GSAP_VERSION"}
FONT_SHA256 = {"inter-500.woff2": "f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f",
               "inter-800.woff2": "a7d0a50f15d389cad679238466bdb5fc9787aa0715719064ce25abaff042820d",
               "jetbrains-mono-500.woff2": "cb182feeed4d798ff6961d3c79f7026279448fca0676438aaecb21f3fc39553a"}


@pytest.fixture(autouse=True)
def no_docker(monkeypatch):
    """No test reaches docker or starts a process: a test that needs an answer of docker replaces these itself."""
    monkeypatch.setattr(box, "docker", lambda *a, **k: pytest.fail("docker was asked: %r" % (a,)))
    monkeypatch.setattr(box, "run", lambda *a, **k: pytest.fail("a container was started"))
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **k: pytest.fail("a process was started"))


def folder_files(folder=FOLDER):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def copy_folder(tmp_path):
    target = tmp_path / "renderer" / "hyperframes-image"
    shutil.copytree(FOLDER, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


# --- the manifest and the build context ------------------------------------------------------------------------------------------


def test_the_manifest_lists_every_file_of_the_folder_but_the_build_driver_and_the_documents():
    listed = hf.manifest_files()
    assert listed == sorted(set(listed)) and "manifest.json" in listed
    assert set(folder_files()) == set(listed) | NOT_IN_DEFINITION
    for name in listed:
        assert (FOLDER / name).is_file() and not (FOLDER / name).is_symlink(), name


def dockerignore_admits(folder=FOLDER):
    """The files .dockerignore lets into the build context. It must be `*` and then `!<name>` lines only (comments aside)."""
    lines = [line.strip() for line in (folder / ".dockerignore").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")]
    if not lines or lines[0] != "*" or not all(line.startswith("!") for line in lines[1:]):
        return None
    admitted = set()
    for entry in lines[1:]:
        path = folder / entry[1:]
        if path.is_dir():
            admitted |= {p.relative_to(folder).as_posix() for p in path.rglob("*") if p.is_file()}
        else:
            admitted.add(entry[1:])
    return admitted


def test_the_build_context_is_the_manifest_less_the_files_docker_reads_itself(tmp_path):
    assert dockerignore_admits() == set(hf.manifest_files()) - READ_BY_DOCKER_ITSELF
    folder = copy_folder(tmp_path)                                               # vacuity: a context that lets more in is seen
    (folder / ".dockerignore").write_text("*\n!_fetch_browser.py\n!fetch_ffmpeg.py\n!package.json\n!package-lock.json\n!fonts\n!hf_image.py\n")
    assert dockerignore_admits(folder) != set(hf.manifest_files(str(folder))) - READ_BY_DOCKER_ITSELF
    (folder / ".dockerignore").write_text("!fonts\n")
    assert dockerignore_admits(folder) is None


def test_the_tag_hashes_the_listed_files_and_nothing_else(tmp_path):
    folder = copy_folder(tmp_path)
    base = hf.definition_hash(str(folder))
    assert base == hf.definition_hash() and re.fullmatch(r"[0-9a-f]{64}", base)
    assert hf.image_tag(str(folder)) == "openhora-hyperframes:" + base[:12]
    for name in sorted(NOT_IN_DEFINITION) + ["unlisted.txt"]:
        path = folder / name
        path.write_bytes((path.read_bytes() if path.exists() else b"") + b"\n# changed\n")
        assert hf.definition_hash(str(folder)) == base, name
    (folder.parent / "ffmpeg.py").write_text("# a sibling engine\n")
    (folder.parent / "blocks").mkdir()
    (folder.parent / "blocks" / "block.json").write_text("{}\n")
    assert hf.definition_hash(str(folder)) == base
    for name in hf.manifest_files(str(folder)):
        path = folder / name
        before = path.read_bytes()
        path.write_bytes(before + b"\n")
        assert hf.definition_hash(str(folder)) != base, name
        path.write_bytes(before)
    assert hf.definition_hash(str(folder)) == base


@pytest.mark.parametrize("files", [["Dockerfile"], ["manifest.json", "../x"], ["manifest.json", "/etc/passwd"],
                                   ["manifest.json", "manifest.json"], "manifest.json", ["manifest.json", "a//b"], ["manifest.json", 3]])
def test_a_manifest_that_is_not_a_plain_list_of_its_own_files_is_refused(tmp_path, files):
    folder = copy_folder(tmp_path)
    (folder / "manifest.json").write_text(json.dumps({"files": files}))
    with pytest.raises(hf.ProviderError):
        hf.manifest_files(str(folder))


def test_a_listed_file_that_is_missing_is_refused(tmp_path):
    folder = copy_folder(tmp_path)
    (folder / "fetch_ffmpeg.py").unlink()
    with pytest.raises(hf.ProviderError) as e:
        hf.definition_hash(str(folder))
    assert "fetch_ffmpeg.py" in str(e.value)


# --- the pins ------------------------------------------------------------------------------------------------------------------------


def pin_problems(pins, dockerfile_text):
    """Every way pins.json fails the rules of condition 7 (supply chain), as sentences; [] when it holds."""
    problems = []
    browser, ffmpeg = pins.get("browser", {}), pins.get("ffmpeg", {})
    if browser.get("version") != "155.0.8059.39" or set(browser.get("platforms", {})) != {"arm64", "amd64"}:
        problems.append("browser version or architectures")
    for arch, spec in browser.get("platforms", {}).items():
        if not str(spec.get("url", "")).startswith(OFFICIAL_CHROME + str(browser.get("version")) + "/"):
            problems.append("browser url " + arch)
        if not (isinstance(spec.get("size"), int) and spec["size"] > 0 and re.fullmatch(r"[0-9a-f]{32}", str(spec.get("md5")))):
            problems.append("browser size or md5 " + arch)
        if not re.fullmatch(r"[0-9a-f]{64}", str(spec.get("sha256"))):
            problems.append("browser sha256 " + arch)
        if not str(spec.get("binary", "")).endswith("/chrome-headless-shell"):
            problems.append("browser binary " + arch)
    if ffmpeg.get("version") != "n8.0.1-66-g27b8d1a017" or set(ffmpeg.get("platforms", {})) != {"arm64", "amd64"}:
        problems.append("ffmpeg version or architectures")
    for arch, spec in ffmpeg.get("platforms", {}).items():
        url = str(spec.get("url", ""))
        if not url.startswith(BTBN) or ("/ffmpeg-%s-" % ffmpeg.get("version")) not in url:
            problems.append("ffmpeg url " + arch)
        if not re.fullmatch(r"[0-9a-f]{64}", str(spec.get("sha256"))):
            problems.append("ffmpeg sha256 " + arch)
    if not re.fullmatch(r"\d{8}T\d{6}Z", str(pins.get("debian_snapshot"))):
        problems.append("debian snapshot")
    if pins.get("npm") != {"hyperframes": "0.9.19", "gsap": "3.14.2", "lockfile_packages": 127}:
        problems.append("npm versions")
    base = pins.get("base", {})
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(base.get("index_digest"))):
        problems.append("base digest")
    first_from = next((line for line in dockerfile_text.splitlines() if line.startswith("FROM ")), "")
    if first_from != "FROM %s@%s" % (base.get("reference"), base.get("index_digest")):
        problems.append("the Dockerfile's FROM is not the pinned base")
    return problems


def test_every_download_is_pinned_by_sha256_for_both_architectures():
    pins = hf.load_pins()
    assert pin_problems(pins, (FOLDER / "Dockerfile").read_text(encoding="utf-8")) == []
    chrome = pins["browser"]["platforms"]
    assert (chrome["amd64"]["size"], chrome["amd64"]["md5"]) == (124203329, "042794dd01c0d40a7388ef8701caba43")
    assert (chrome["arm64"]["size"], chrome["arm64"]["md5"]) == (124553121, "1b40e7a8dfd195ccc27a9608d516ff75")
    assert chrome["arm64"]["sha256"] == "9fb86f7c0b2734c5febc0bbb4e85f37da43553f3f8a7970949828c5713e87e94"
    assert pins["ffmpeg"]["platforms"]["arm64"]["sha256"] == "d72cc324cb65dd92a9ffe699cc95ccbacfef4def8d3ad9fe2b5164a6a71b9595"
    assert pins["ffmpeg"]["platforms"]["amd64"]["sha256"] == "26d2ecd0cefba99f9d1ea92252a3a4f743a58df4c1c3cf9f8bbaaa40b1fca5b0"
    assert pins["base"] == {"reference": "node:22.23.4-bookworm-slim",
                            "index_digest": "sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d"}
    assert pins["debian_snapshot"] == "20261006T000000Z"


def test_the_pin_rules_catch_a_missing_sha256_a_foreign_url_and_a_base_that_differs():
    dockerfile = (FOLDER / "Dockerfile").read_text(encoding="utf-8")
    for change, expected in ((lambda p: p["browser"]["platforms"]["amd64"].update(sha256=None), "browser sha256 amd64"),
                             (lambda p: p["ffmpeg"]["platforms"]["arm64"].update(url="https://example.com/ffmpeg.tar.xz"), "ffmpeg url arm64"),
                             (lambda p: p["browser"]["platforms"].pop("amd64"), "browser version or architectures"),
                             (lambda p: p["npm"].update(gsap="3.14.3"), "npm versions"),
                             (lambda p: p["base"].update(index_digest="sha256:" + "0" * 64), "the Dockerfile's FROM is not the pinned base")):
        pins = hf.load_pins()
        change(pins)
        assert expected in pin_problems(pins, dockerfile)


def test_the_build_refuses_an_architecture_whose_pin_has_no_sha256(tmp_path):
    folder = copy_folder(tmp_path)
    pins = json.loads((folder / "pins.json").read_text(encoding="utf-8"))
    pins["browser"]["platforms"]["amd64"]["sha256"] = None
    (folder / "pins.json").write_text(json.dumps(pins))
    with pytest.raises(hf.ProviderError) as e:
        hf.build_command("amd64", str(folder))
    assert e.value.code == 3 and "browser" in str(e.value) and "amd64" in str(e.value)
    assert "linux/arm64" in hf.build_command("arm64", str(folder))           # the other architecture still builds
    for arch in ("riscv64", "x86_64", ""):
        with pytest.raises(hf.ProviderError) as e:
            hf.build_command(arch, str(folder))
        assert e.value.code == 3


# --- the lockfile --------------------------------------------------------------------------------------------------------------------


def lock_problems(lock, package, count):
    """Every way the lockfile fails condition 7, as sentences; [] when it holds."""
    want = {"hyperframes": "0.9.19", "gsap": "3.14.2"}
    problems = []
    if package.get("dependencies") != want or lock.get("lockfileVersion") != 3:
        problems.append("package.json dependencies or lockfile version")
    if lock.get("packages", {}).get("", {}).get("dependencies") != want:
        problems.append("the lockfile's root dependencies")
    rows = {k: v for k, v in lock.get("packages", {}).items() if k}
    if len(rows) != count:
        problems.append("package count %d" % len(rows))
    for key, row in rows.items():
        if not key.startswith("node_modules/"):
            problems.append("not under node_modules: " + key)
        if not str(row.get("resolved", "")).startswith("https://registry.npmjs.org/"):
            problems.append("not from the npm registry: " + key)
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", str(row.get("integrity", ""))):
            problems.append("no sha512 integrity: " + key)
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", str(row.get("version", ""))):
            problems.append("not an exact version: " + key)
    if rows.get("node_modules/hyperframes", {}).get("version") != "0.9.19" or rows.get("node_modules/gsap", {}).get("version") != "3.14.2":
        problems.append("hyperframes or gsap version")
    return problems


def test_the_lockfile_pins_every_package_with_an_integrity_hash_from_the_npm_registry():
    lock = json.loads((FOLDER / "package-lock.json").read_text(encoding="utf-8"))
    package = json.loads((FOLDER / "package.json").read_text(encoding="utf-8"))
    assert lock_problems(lock, package, hf.load_pins()["npm"]["lockfile_packages"]) == []
    assert hashlib.sha256((FOLDER / "package-lock.json").read_bytes()).hexdigest() == \
        "fc53164e07795e4c75699a7ac309323cd46036915c43455085b53532b2b7b055"           # the lockfile S2 measured, byte for byte


def test_the_lock_rules_catch_a_git_source_a_missing_integrity_and_a_range():
    lock = json.loads((FOLDER / "package-lock.json").read_text(encoding="utf-8"))
    package = json.loads((FOLDER / "package.json").read_text(encoding="utf-8"))
    rows = [k for k in lock["packages"] if k]
    lock["packages"][rows[0]]["resolved"] = "git+https://example.com/x.git"
    del lock["packages"][rows[1]]["integrity"]
    lock["packages"][rows[2]]["integrity"] = "sha1-" + "A" * 27 + "="
    package["dependencies"]["gsap"] = "^3.14.2"
    found = lock_problems(lock, package, 127)
    assert "not from the npm registry: " + rows[0] in found and "no sha512 integrity: " + rows[1] in found
    assert "no sha512 integrity: " + rows[2] in found and "package.json dependencies or lockfile version" in found


# --- the fonts -----------------------------------------------------------------------------------------------------------------------


def test_the_fonts_are_the_three_pinned_files_with_their_licences():
    sums = hf.font_sums()
    assert set(sums) == {"Inter-OFL.txt", "JetBrainsMono-OFL.txt"} | set(FONT_SHA256)
    for name, digest in sums.items():
        assert hashlib.sha256((FOLDER / "fonts" / name).read_bytes()).hexdigest() == digest, name
    assert {name: sums[name] for name in FONT_SHA256} == FONT_SHA256
    assert sorted(p.name for p in (FOLDER / "fonts").iterdir() if p.suffix.startswith((".woff", ".ttf", ".otf"))) == sorted(hf.FONT_FILES)
    assert sorted(hf.FONT_FILES) == sorted(FONT_SHA256)


def test_the_fonts_equal_the_ffmpeg_engines_allow_list_when_it_is_in_the_checkout():
    allow = RENDERER / "assets" / "fonts" / "allowlist.json"
    if not allow.is_file():
        pytest.skip("the ffmpeg engine's fonts are not in this checkout yet (package V1a)")
    rows = {row["file"]: row["sha256"] for row in json.loads(allow.read_text(encoding="utf-8"))["fonts"]}
    assert {name: rows.get(name) for name in hf.FONT_FILES} == FONT_SHA256


def test_the_browser_pin_equals_the_ffmpeg_engines_when_it_is_in_the_checkout():
    other = RENDERER / "browser-pin.json"
    if not other.is_file():
        pytest.skip("the ffmpeg engine's browser pin is not in this checkout yet (package V1a)")
    theirs, ours = json.loads(other.read_text(encoding="utf-8")), hf.load_pins()["browser"]
    assert theirs["version"] == ours["version"]
    for mine, key in (("arm64", "linux-arm64"), ("amd64", "linux64")):
        a, b = ours["platforms"][mine], theirs["platforms"][key]
        assert (a["url"], a["size"], a["md5"], a["binary"]) == (b["url"], b["size"], b["md5"], b["binary"]), mine
        assert b["sha256"] in (None, a["sha256"]), mine


def test_the_browser_download_script_is_the_ffmpeg_engines_when_it_is_in_the_checkout():
    other = RENDERER / "_fetch_browser.py"
    if not other.is_file():
        pytest.skip("the ffmpeg engine's _fetch_browser.py is not in this checkout yet (package V1a)")
    assert (FOLDER / "_fetch_browser.py").read_bytes() == other.read_bytes()


# --- the Dockerfile ------------------------------------------------------------------------------------------------------------------


def instructions(text):
    """The Dockerfile's instructions, each on one line: comments dropped, continuation lines joined."""
    out, current = [], ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        current += (" " if current else "") + (stripped[:-1].strip() if stripped.endswith("\\") else stripped)
        if not stripped.endswith("\\"):
            out.append(current)
            current = ""
    return out + ([current] if current else [])


def dockerfile_problems(text, build_arg_names):
    """Every way the Dockerfile breaks a rule of the image, as sentences; [] when it holds."""
    steps = instructions(text)
    runs = [s for s in steps if s.startswith("RUN ")]
    problems = []
    if not any("npm ci --ignore-scripts" in s for s in runs) or any(re.search(r"\bnpm (install|i|update)\b", s) for s in runs):
        problems.append("npm ci --ignore-scripts")
    if any(re.search(r"\b(curl|wget)\b|\|\s*(sh|bash)\b", s) for s in runs):
        problems.append("a download outside the pinned scripts")
    first_run = next(i for i, s in enumerate(steps) if s.startswith("RUN "))
    early = " ".join(s for s in steps[:first_run] if s.startswith("ENV "))
    if "HYPERFRAMES_NO_TELEMETRY=1" not in early or "DO_NOT_TRACK=1" not in early:
        problems.append("telemetry is not off before the first RUN")
    users = [s for s in steps if s.startswith("USER ")]
    if not users or users[-1] != "USER 10001:10001":
        problems.append("the last USER is not 10001:10001")
    purge = runs[-1] if runs else ""
    if "dpkg --purge --force-depends fonts-dejavu-core" not in purge or "diff /opt/hf-build/font-files.expected /opt/hf-build/font-files.txt" not in purge:
        problems.append("the font purge is not the last RUN")
    if any("fonts-" in s for s in runs[:-1]):
        problems.append("a font package outside the purge")
    if "# Hook for V3b" not in text:
        problems.append("the registry hook is not marked")
    no_default = {s.split()[1] for s in steps if s.startswith("ARG ") and "=" not in s}
    if no_default != set(build_arg_names) - {"DEFINITION_HASH"}:
        problems.append("the ARGs without a default are not the build arguments")
    return problems


def test_the_dockerfile_keeps_the_rules_of_the_image():
    names = BUILD_ARGS
    assert dockerfile_problems((FOLDER / "Dockerfile").read_text(encoding="utf-8"), names) == []


def test_the_dockerfile_rules_catch_each_break():
    text = (FOLDER / "Dockerfile").read_text(encoding="utf-8")
    for old, new, expected in (
            ("npm ci --ignore-scripts --no-audit", "npm install --no-audit", "npm ci --ignore-scripts"),
            ("USER 10001:10001", "USER root", "the last USER is not 10001:10001"),
            ("    DO_NOT_TRACK=1 \\\n    NPM_CONFIG", "    NPM_CONFIG", "telemetry is not off before the first RUN"),
            ("WORKDIR /work", "WORKDIR /work\nRUN true", "the font purge is not the last RUN"),
            ("python3 ca-certificates \\", "python3 ca-certificates fonts-noto \\", "a font package outside the purge"),
            ("# Hook for V3b", "# Hook", "the registry hook is not marked"),
            ("ARG GSAP_VERSION\n", "", "the ARGs without a default are not the build arguments"),
            ("COPY fonts/ /opt/fonts/", "RUN curl -fsSL -o /tmp/x https://example.com/x\nCOPY fonts/ /opt/fonts/", "a download outside the pinned scripts")):
        assert old in text, old
        assert expected in dockerfile_problems(text.replace(old, new, 1), BUILD_ARGS), expected


# --- the build command ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("arch", ["arm64", "amd64"])
def test_the_dry_run_prints_the_build_with_every_pin_of_the_architecture(arch, capsys):
    assert hf.main(["build", "--dry-run", "--arch", arch]) == 0
    out = json.loads(capsys.readouterr().out)
    command, digest, pins = out["would"]["command"], hf.definition_hash(), hf.load_pins()
    assert out["would"]["arch"] == arch and out["would"]["tag"] == "openhora-hyperframes:" + digest[:12]
    assert command[:7] == ["docker", "build", "--progress=plain", "--platform", "linux/" + arch, "--label",
                           "org.openhora.definition=" + digest]
    assert command[-3:-1] == ["-t", "openhora-hyperframes:" + digest[:12]] and os.path.realpath(command[-1]) == str(FOLDER)
    args = dict(command[i + 1].split("=", 1) for i, word in enumerate(command) if word == "--build-arg")
    assert set(args) == BUILD_ARGS and args["DEFINITION_HASH"] == digest
    assert args["CHROME_SHA256"] == pins["browser"]["platforms"][arch]["sha256"] and args["CHROME_URL"] == pins["browser"]["platforms"][arch]["url"]
    assert args["FFMPEG_SHA256"] == pins["ffmpeg"]["platforms"][arch]["sha256"] and args["FFMPEG_URL"] == pins["ffmpeg"]["platforms"][arch]["url"]
    assert (args["HYPERFRAMES_VERSION"], args["GSAP_VERSION"], args["DEBIAN_SNAPSHOT"]) == ("0.9.19", "3.14.2", "20261006T000000Z")


@pytest.mark.parametrize("argv", [["build"], ["build", "--dry-run", "--confirmed"], ["build", "--confirmed", "--arch", "amd64"],
                                  ["build", "--dry-run", "--arch", "x86_64"], ["build", "--dry-run", "--arch"], ["selfcheck", "--jobs", "0"],
                                  ["selfcheck", "--jobs", "two"], ["nothing"], ["--check", "build"], []])
def test_a_wrong_command_line_is_a_usage_error_and_reaches_no_docker(argv):
    assert hf.main(argv) == 2


def test_build_confirmed_runs_the_dry_runs_command_on_the_daemons_architecture(monkeypatch, capsys):
    started = []
    monkeypatch.setattr(hf, "local_daemon", lambda: None)
    monkeypatch.setattr(hf, "daemon_arch", lambda: "arm64")
    monkeypatch.setattr(hf, "image_id", lambda tag: "sha256:" + "a" * 64)
    monkeypatch.setattr(box, "docker_binary", lambda: "/usr/local/bin/docker")
    monkeypatch.setattr(hf.subprocess, "run", lambda command, **k: started.append((command, k)) or subprocess.CompletedProcess(command, 0, None, b""))
    assert hf.main(["build", "--confirmed"]) == 0
    command, options = started[0]
    assert command == ["/usr/local/bin/docker"] + hf.build_command("arm64")[1:] and options["timeout"] == hf.BUILD_TIMEOUT
    assert json.loads(capsys.readouterr().out) == {"built": True, "arch": "arm64", "tag": hf.image_tag(), "image": "sha256:" + "a" * 64}
    monkeypatch.setattr(hf.subprocess, "run", lambda command, **k: subprocess.CompletedProcess(command, 1, None, b"step 7: sha256_differs_from_pin"))
    assert hf.main(["build", "--confirmed"]) == 1
    assert "sha256_differs_from_pin" in capsys.readouterr().err


def test_the_check_names_the_build_command_when_the_image_is_not_here(monkeypatch, capsys):
    monkeypatch.setattr(hf, "local_daemon", lambda: None)
    monkeypatch.setattr(box, "docker", lambda args, timeout=60: subprocess.CompletedProcess(args, 1, "", "No such image"))
    assert hf.main(["--check"]) == 3
    assert "hf_image.py build --confirmed" in capsys.readouterr().err


# --- the checks of a built image, through a fake container ---------------------------------------------------------------------------

IMAGE = "sha256:" + "e" * 64


def good_answers():
    sums = hf.font_sums()
    return {
        "hyperframes telemetry": (0, "Status: disabled\nSource: HYPERFRAMES_NO_TELEMETRY\nTracked commands: 0\n", ""),
        "hyperframes --version": (0, "0.9.19\n", ""),
        "find": (1, "/opt/fonts/inter-500.woff2\n/opt/fonts/jetbrains-mono-500.woff2\n/opt/fonts/inter-800.woff2\n"
                    "/opt/hf/node_modules/fictional-pkg/fonts/sample.woff2\n", "find: '/root': Permission denied\n"),
        "sha256sum": (0, "".join("%s  /opt/fonts/%s\n" % (sums[n], n) for n in hf.FONT_FILES), ""),
        "node": (0, "lo\n", ""),
    }


def fake_run(answers, seen):
    def run(command, name, timeout, stdout_cap=None):
        seen.append(command)
        inner = command[command.index(IMAGE) + 1:]
        key = "hyperframes " + inner[1] if inner[0] == "hyperframes" else inner[0]
        answer = answers[key]
        if isinstance(answer, Exception):
            raise answer
        code, out, err = answer
        return box.Finished(code, err, False, out.encode())
    return run


def test_selfcheck_passes_a_good_image_and_runs_every_check_with_no_network():
    seen = []
    result = hf.selfcheck(IMAGE, run=fake_run(good_answers(), seen), jobs=5)
    assert result["ok"] is True and [c["check"] for c in result["checks"]] == ["telemetry", "version", "font_files", "font_sha256", "network"]
    assert all(c["ok"] for c in result["checks"])
    assert "1 inside HyperFrames' node_modules" in result["checks"][2]["detail"]
    assert len(seen) == 5
    for command in seen:
        for flag in (["--network", "none"], ["--pull", "never"], ["--cap-drop", "ALL"]):
            assert command[command.index(flag[0]) + 1] == flag[1]
        assert "--read-only" in command and not any(word == "-v" for word in command)


@pytest.mark.parametrize("key, answer, failed", [
    ("hyperframes telemetry", (0, "Status: enabled\n", ""), "telemetry"),
    ("hyperframes --version", (0, "0.9.18\n", ""), "version"),
    ("hyperframes --version", (0, "0.9.190\n", ""), "version"),
    ("find", (0, "/opt/fonts/inter-500.woff2\n/opt/fonts/inter-800.woff2\n/opt/fonts/jetbrains-mono-500.woff2\n"
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf\n", ""), "font_files"),
    ("find", (0, "/opt/fonts/inter-500.woff2\n/opt/fonts/inter-800.woff2\n", ""), "font_files"),
    ("find", (2, "", "find: bad option"), "font_files"),
    ("sha256sum", (0, "%s  /opt/fonts/inter-500.woff2\n" % ("0" * 64), ""), "font_sha256"),
    ("node", (0, "eth0,lo\n", ""), "network"),
    ("node", box.ContainerError("time_limit", "container"), "network"),
])
def test_selfcheck_fails_the_one_check_whose_answer_is_wrong(key, answer, failed):
    answers = good_answers()
    answers[key] = answer
    result = hf.selfcheck(IMAGE, run=fake_run(answers, []), jobs=1)
    assert result["ok"] is False
    assert [c["check"] for c in result["checks"] if not c["ok"]] == [failed]


def test_selfcheck_reads_an_answer_printed_on_stderr():
    answers = good_answers()
    answers["hyperframes telemetry"] = (0, "", "Status: disabled, Source: HYPERFRAMES_NO_TELEMETRY\n")
    answers["hyperframes --version"] = (0, "", "hyperframes 0.9.19\n")
    assert hf.selfcheck(IMAGE, run=fake_run(answers, []), jobs=1)["ok"] is True


# --- build_image, the seam of the provider's build record (V3a-2), and the inner entry in the definition -------------------------------------

def test_build_image_runs_exactly_the_build_command_and_returns_the_four_keys_of_the_record(monkeypatch):
    seen = []
    monkeypatch.setattr(hf, "image_id", lambda tag: "sha256:" + "a" * 64)
    done = hf.build_image("arm64", run=lambda command: seen.append(command) or subprocess.CompletedProcess(command, 0, None, b""))
    assert seen == [hf.build_command("arm64")]
    assert done == {"image_id": "sha256:" + "a" * 64, "tag": hf.image_tag(), "definition": hf.definition_hash(), "arch": "arm64"}


def test_build_image_refuses_a_failed_build_with_the_tail_of_its_stderr_and_a_build_that_cannot_start(monkeypatch):
    monkeypatch.setattr(hf, "image_id", lambda tag: pytest.fail("the image was asked for after a failed build"))
    with pytest.raises(hf.ProviderError, match="step 7: sha256_differs_from_pin"):
        hf.build_image("amd64", run=lambda command: subprocess.CompletedProcess(command, 1, None, b"step 7: sha256_differs_from_pin"))

    def cannot_start(command):
        raise OSError("no docker")

    with pytest.raises(hf.ProviderError, match="did not run"):
        hf.build_image("amd64", run=cannot_start)
    with pytest.raises(hf.ProviderError) as unpinned:
        hf.build_image("riscv", run=lambda command: pytest.fail("a build was started for an architecture that is not pinned"))
    assert unpinned.value.code == hf.EXIT_NOT_CONFIGURED


def test_the_inner_entry_is_in_the_definition_the_build_context_and_the_dockerfile_after_the_purge():
    assert "hf_render.py" in hf.manifest_files() and "!hf_render.py" in (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    steps = instructions((FOLDER / "Dockerfile").read_text(encoding="utf-8"))
    last_run = max(i for i, s in enumerate(steps) if s.startswith("RUN "))
    copy = steps.index("COPY hf_render.py /opt/hf-run/hf_render.py")
    assert copy > last_run and not any(s.startswith("RUN ") for s in steps[copy:])
    first_label = next(i for i, s in enumerate(steps) if s.startswith("LABEL "))
    assert copy < first_label


def test_the_measure_script_is_in_the_definition_the_build_context_and_the_dockerfile_after_the_purge_beside_the_inner_entry():
    assert "hf_measure.mjs" in hf.manifest_files() and "!hf_measure.mjs" in (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    steps = instructions((FOLDER / "Dockerfile").read_text(encoding="utf-8"))
    last_run = max(i for i, s in enumerate(steps) if s.startswith("RUN "))
    copy = steps.index("COPY hf_measure.mjs /opt/hf-run/hf_measure.mjs")
    assert copy > last_run and copy == steps.index("COPY hf_render.py /opt/hf-run/hf_render.py") + 1 and not any(s.startswith("RUN ") for s in steps[copy:])
    assert copy < next(i for i, s in enumerate(steps) if s.startswith("LABEL "))
