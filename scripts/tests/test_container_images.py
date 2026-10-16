"""Tests of the removal of the images of earlier definitions (providers/_container.py, scripts/doctor.py `--remove-old-images`, the `images`
row of the unattended checks). Every container command goes to a fake tool: the real docker is never asked, and no `wb-eval` object is
named as anything but an image that must be left alone.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_container_images.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


box = load("container_images_under_test", ROOT / "providers" / "_container.py")
doctor = load("doctor_images_under_test", ROOT / "scripts" / "doctor.py")
import doctor_ops  # noqa: E402  (scripts/ is on the path: doctor.py put it there)

CURRENT = "c" * 64
OLD_A, OLD_B, OLD_C = "a" * 64, "b" * 64, "d" * 64
MIB = 1024 * 1024


class FakeImages:
    """A container client with invented images: `image ls`, `image inspect`, `image rm` and `version`, and nothing else. It answers `ls`
    with every image it has (a real client filters by the label; the selection must not depend on that), records every command, and
    fails the test on `--force`, `prune` or any other command."""

    def __init__(self, images, in_use=(), down=False, change_on_second_look=()):
        self.images = {ref: dict(facts) for ref, facts in images.items()}
        self.in_use, self.down, self.changes = set(in_use), down, set(change_on_second_look)
        self.calls, self.looked = [], {}

    def __call__(self, *args):
        self.calls.append(args)
        assert "--force" not in args and "-f" not in args and "prune" not in args and "rmi" not in args, args
        if self.down:
            return 127, ""
        if args[:1] == ("version",):
            return 0, "27.0.0"
        if args[:2] == ("image", "ls"):
            return 0, "\n".join(self.images) + "\n"
        if args[:2] == ("image", "inspect"):
            ref = args[-1]
            if ref.startswith("sha256:"):       # by id: any tag of the image answers
                owner = next((r for r, f in self.images.items() if self.id_of(r) == ref), None)
                return (0, ref) if owner else (1, "")
            if ref not in self.images:
                return 1, ""
            self.looked[ref] = self.looked.get(ref, 0) + 1
            facts = self.images[ref]
            labels = facts.get("labels")
            if ref in self.changes and self.looked[ref] > 1:
                labels = {"org.openhora.definition": CURRENT}   # it became the current definition between the look and the removal
            return 0, json.dumps(labels) + "\t" + str(facts["size"]) + "\t" + self.id_of(ref)
        if args[:2] == ("image", "rm"):
            ref = args[-1]
            if ref in self.in_use:
                return 1, ""
            del self.images[ref]
            return 0, ""
        raise AssertionError(f"a command the removal must not send: {args}")

    def id_of(self, ref):
        return self.images[ref].get("id") or "sha256:" + format(abs(hash(ref.split(":")[0] + ref.split(":")[-1])) % 16 ** 12, "012x") * 5

    def sent(self, verb):
        return [c for c in self.calls if c[:2] == ("image", verb)]


def label(value):
    return {"org.openhora.definition": value}


def shelf():
    return {
        f"openhora-converter:{CURRENT[:12]}": {"labels": label(CURRENT), "size": 100 * MIB},          # the current definition
        f"openhora-converter:{OLD_A[:12]}": {"labels": label(OLD_A), "size": 90 * MIB},               # earlier ones
        f"openhora-converter:{OLD_B[:12]}": {"labels": label(OLD_B), "size": 80 * MIB},
        "openhora-converter:homemade": {"labels": None, "size": 70 * MIB},                           # no label: not ours to judge
        "openhora-converter:<none>": {"labels": label(OLD_C), "size": 60 * MIB},                     # untagged
        f"wb-eval-image:{OLD_C[:12]}": {"labels": label(OLD_C), "size": 500 * MIB},                  # the harness's, with the label
        f"openhora-exporter:{OLD_A[:12]}": {"labels": label(OLD_A), "size": 50 * MIB},               # another provider's repository
        f"openhora-converter-extra:{OLD_A[:12]}": {"labels": label(OLD_A), "size": 40 * MIB},         # a repository that only starts the same
    }


def test_the_current_definition_an_unlabelled_an_untagged_a_harness_and_another_repository_image_are_kept_and_earlier_ones_removed_by_tag():
    tool = FakeImages(shelf())
    done = box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=False)
    assert sorted(i["image"] for i in done["removed"]) == [f"openhora-converter:{OLD_A[:12]}", f"openhora-converter:{OLD_B[:12]}"]
    assert done["kept"] == [] and done["dry_run"] is False and sum(i["size"] for i in done["removed"]) == 170 * MIB
    assert all(i["freed"] for i in done["removed"])
    assert sorted(c[-1] for c in tool.sent("rm")) == sorted(i["image"] for i in done["removed"])      # by tag, nothing else
    assert set(tool.images) == {f"openhora-converter:{CURRENT[:12]}", "openhora-converter:homemade", "openhora-converter:<none>",
                                f"wb-eval-image:{OLD_C[:12]}", f"openhora-exporter:{OLD_A[:12]}", f"openhora-converter-extra:{OLD_A[:12]}"}


def test_removing_a_tag_of_an_image_that_has_another_tag_is_not_counted_as_freed(capsys):
    shared = "sha256:" + "e" * 64
    images = shelf()
    images[f"openhora-converter:{OLD_A[:12]}"]["id"] = shared
    images["openhora-converter:keepme"] = {"labels": None, "size": 90 * MIB, "id": shared}      # the same image under another name
    tool = FakeImages(images)
    done = box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=False)
    by = {i["image"]: i for i in done["removed"]}
    assert by[f"openhora-converter:{OLD_A[:12]}"]["freed"] is False and by[f"openhora-converter:{OLD_B[:12]}"]["freed"] is True
    code = doctor.remove_old_images(["--remove-old-images", "--confirmed"], tool=FakeImages(images), families=FAMILIES[:1], box=box)
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["freed_bytes"] == 80 * MIB                                         # only the image whose id went


def test_an_image_in_use_or_refused_is_reported_kept_with_the_reason():
    ref = f"openhora-converter:{OLD_A[:12]}"
    tool = FakeImages(shelf(), in_use=[ref])
    done = box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=False)
    assert [k["image"] for k in done["kept"]] == [ref] and "in use" in done["kept"][0]["reason"]
    assert [r["image"] for r in done["removed"]] == [f"openhora-converter:{OLD_B[:12]}"] and ref in tool.images


def test_each_image_is_looked_at_again_just_before_its_removal():
    ref = f"openhora-converter:{OLD_A[:12]}"
    tool = FakeImages(shelf(), change_on_second_look=[ref])
    done = box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=False)
    assert [k["image"] for k in done["kept"]] == [ref] and "no longer" in done["kept"][0]["reason"]
    assert ref not in [c[-1] for c in tool.sent("rm")] and ref in tool.images


def test_a_dry_run_sends_no_removal_and_names_what_would_go():
    tool = FakeImages(shelf())
    done = box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=True)
    assert tool.sent("rm") == [] and done["removed"] == [] and done["dry_run"] is True
    assert sorted(i["image"] for i in done["would_remove"]) == [f"openhora-converter:{OLD_A[:12]}", f"openhora-converter:{OLD_B[:12]}"]
    assert box.remove_old_definition_images(tool, "openhora-converter", CURRENT)["dry_run"] is True       # the default


def test_a_client_that_cannot_be_asked_finds_nothing():
    assert box.old_definition_images(FakeImages(shelf(), down=True), "openhora-converter", CURRENT) == []


def test_no_command_the_helpers_send_is_anything_but_ls_inspect_and_rm_by_tag():
    tool = FakeImages(shelf())
    box.remove_old_definition_images(tool, "openhora-converter", CURRENT, dry_run=False)
    assert {c[:2] for c in tool.calls} <= {("image", "ls"), ("image", "inspect"), ("image", "rm")}


# --- the doctor ------------------------------------------------------------------------------------------------------------------------


FAMILIES = [{"family": "converter", "repository": "openhora-converter", "hash": CURRENT, "tag": f"openhora-converter:{CURRENT[:12]}"},
            {"family": "exporter", "repository": "openhora-exporter", "hash": CURRENT, "tag": f"openhora-exporter:{CURRENT[:12]}"}]


def run_doctor(argv, tool, capsys):
    code = doctor.remove_old_images(argv, tool=tool, families=FAMILIES, box=box)
    return code, capsys.readouterr()


def test_the_command_needs_exactly_one_of_dry_run_and_confirmed(capsys):
    tool = FakeImages(shelf())
    for argv in (["--remove-old-images"], ["--remove-old-images", "--dry-run", "--confirmed"], ["--remove-old-images", "--confirmed", "--json"]):
        code, seen = run_doctor(argv, tool, capsys)
        assert code == 2 and "exactly one of --dry-run" in seen.err and seen.out == ""
    assert tool.calls == []


def test_the_dry_run_prints_one_object_and_sends_no_removal(capsys):
    tool = FakeImages(shelf())
    code, seen = run_doctor(["--remove-old-images", "--dry-run"], tool, capsys)
    out = json.loads(seen.out)
    assert code == 0 and out["dry_run"] is True and out["removed"] == [] and tool.sent("rm") == []
    assert sorted((i["family"], i["image"]) for i in out["would_remove"]) == [
        ("converter", f"openhora-converter:{OLD_A[:12]}"), ("converter", f"openhora-converter:{OLD_B[:12]}"),
        ("exporter", f"openhora-exporter:{OLD_A[:12]}")]


def test_confirmed_removes_the_earlier_images_of_each_family_and_reports_what_was_freed(capsys):
    tool = FakeImages(shelf(), in_use=[f"openhora-exporter:{OLD_A[:12]}"])
    code, seen = run_doctor(["--remove-old-images", "--confirmed"], tool, capsys)
    out = json.loads(seen.out)
    assert code == 0 and out["dry_run"] is False and out["freed_bytes"] == 170 * MIB
    assert sorted(i["image"] for i in out["removed"]) == [f"openhora-converter:{OLD_A[:12]}", f"openhora-converter:{OLD_B[:12]}"]
    assert [(k["family"], k["image"]) for k in out["kept"]] == [("exporter", f"openhora-exporter:{OLD_A[:12]}")] and "in use" in out["kept"][0]["reason"]
    assert "wb-eval" not in " ".join(c[-1] for c in tool.sent("rm"))


def test_without_a_docker_the_command_says_so_and_removes_nothing(capsys):
    tool = FakeImages(shelf(), down=True)
    code, seen = run_doctor(["--remove-old-images", "--confirmed"], tool, capsys)
    assert code == 1 and "docker cannot be asked" in json.loads(seen.out)["error"] and tool.sent("rm") == []


def test_the_command_is_reached_from_main_and_no_other_mode_sends_a_removal(monkeypatch, capsys):
    tool = FakeImages(shelf())
    monkeypatch.setattr(doctor_ops, "docker_tool", tool)
    monkeypatch.setattr(doctor, "image_families", lambda: FAMILIES)
    assert doctor.main(["--remove-old-images", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["would_remove"] and tool.sent("rm") == []


def test_the_images_row_counts_the_earlier_images_names_the_command_and_is_never_a_warning():
    tool = FakeImages(shelf())
    row = doctor_ops.images_check(tool, FAMILIES, box)
    assert row["status"] == "ok" and row["count"] == 3 and row["bytes"] == 220 * MIB
    assert row["fix"] == "python3 scripts/doctor.py --remove-old-images --dry-run" and "220 MiB" in row["detail"] and "--confirmed" in row["detail"]
    assert tool.sent("rm") == []                                                    # the row removes nothing
    none = doctor_ops.images_check(FakeImages({f"openhora-converter:{CURRENT[:12]}": {"labels": label(CURRENT), "size": MIB}}), FAMILIES, box)
    assert none["status"] == "ok" and none["count"] == 0
    assert doctor_ops.images_check(FakeImages(shelf(), down=True), FAMILIES, box)["status"] == "unverified"
    assert doctor_ops.images_check(tool, [], box)["status"] == "na"


def test_the_images_row_leaves_the_exit_code_of_the_doctor_alone(monkeypatch, capsys, tmp_path):
    # the same doctor run with and without earlier images: the exit code under --strict is the same
    monkeypatch.setattr(doctor, "collect_requires", lambda: {})
    monkeypatch.setattr(doctor, "image_state", lambda: {"state": "local-only", "detail": "x"})
    monkeypatch.setattr(doctor, "secrets_report", lambda classes: [])
    monkeypatch.setattr(doctor, "store_probe", lambda: {"state": "ok", "detail": ""})
    monkeypatch.setattr(doctor, "load_project_config", lambda p: {"data_dir": str(tmp_path), "sources_dir": str(tmp_path)})
    monkeypatch.setattr(doctor, "image_families", lambda: FAMILIES)
    monkeypatch.setattr(doctor, "container_box", lambda: box)
    codes = {}
    for name, images in (("none", {}), ("old", shelf())):
        tool = FakeImages(images)
        monkeypatch.setattr(doctor_ops, "docker_tool", tool)
        monkeypatch.setattr(doctor_ops, "_run", lambda argv, timeout=15: (0, "", "") if argv[0] != "docker" else (0, "", ""))
        monkeypatch.setattr(doctor_ops, "linger_check", lambda **k: {"status": "ok", "detail": "x"})
        monkeypatch.setattr(doctor_ops, "proxy_logs_check", lambda tool=None: {"status": "ok", "detail": "x"})
        monkeypatch.setattr(doctor_ops, "secret_store_check", lambda probe: {"status": "ok", "detail": "x"})
        monkeypatch.setattr(doctor_ops, "password_manager_check", lambda probe: {"status": "ok", "detail": "x"})
        monkeypatch.setattr(doctor, "manager_probe", lambda: {"state": "na", "detail": ""})
        monkeypatch.setattr(doctor_ops, "disk_check", lambda *a, **k: {"status": "ok", "detail": "x"})
        monkeypatch.setattr(doctor_ops, "sources_access_check", lambda *a, **k: {"status": "ok", "detail": "x"})
        codes[name] = doctor.main(["--unattended", "--project", str(tmp_path), "--strict", "--json"])
        report = json.loads(capsys.readouterr().out)["unattended"]["images"]
        assert report["status"] == "ok" and report["count"] == (3 if name == "old" else 0) and tool.sent("rm") == []
    assert codes == {"none": 0, "old": 0}


def test_the_families_are_the_providers_that_build_an_image_here_with_their_current_definition():
    families = doctor.image_families()
    assert [f["family"] for f in families] == ["converter", "exporter"]            # a provider that builds an image adds itself to doctor.IMAGE_FAMILIES
    for family in families:
        assert family["tag"] == f"{family['repository']}:{family['hash'][:12]}" and len(family["hash"]) == 64
    assert {f["repository"] for f in families} == {"openhora-converter", "openhora-exporter"}
