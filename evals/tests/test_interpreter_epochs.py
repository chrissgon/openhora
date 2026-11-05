"""Offline tests of the catalog epochs of the interpreter's evidence (evals/interpreter/epochs.json; the reliability model, section 5):
the file's form, the served catalog's hash, and the generator's hash being the served epoch or one in pending-rerun. The real files are
checked too; the generator (runtime code) runs in a child process, so no module of runtime/ is imported here. No model is called."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import interpreter_fixtures as fx

REPO = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


el = load("evidence_lines_epochs_test", "evals/evidence_lines.py")
OLD, NEW, OTHER = fx.sha(fx.CATALOG), fx.sha(fx.CATALOG_2), "9" * 64


def tree(tmp_path, data=None, catalog=fx.CATALOG):
    fx.checkout(tmp_path, catalog=catalog)
    if data is not None:
        fx.put(tmp_path, "evals/interpreter/epochs.json", data)
    return str(tmp_path)


# --- the form of the file ---------------------------------------------------------------------------------------------------

def test_a_valid_epochs_file_has_no_problem(tmp_path):
    assert el.interpreter_epochs_file_problems(tree(tmp_path)) == []
    assert el.interpreter_epochs_file_problems(tree(tmp_path / "b", fx.epochs(OLD, (NEW, "pending-rerun"), (OTHER, "retired")))) == []


def test_each_rule_of_the_form_is_refused_when_broken(tmp_path):
    base = fx.epochs(OLD, (NEW, "pending-rerun"))
    bad = {
        "an extra key": {**base, "note": "x"},
        "a version": {**base, "v": 2},
        "served not a hash": {**base, "served": "abc"},
        "no epochs": {**base, "epochs": []},
        "two served": {**base, "epochs": base["epochs"] + [{"catalog_sha256": OTHER, "date": "2030-10-03", "state": "served"}]},
        "no served": {**base, "epochs": [base["epochs"][1]]},
        "served is another": {**base, "served": NEW},
        "a state": {**base, "epochs": [base["epochs"][0], {**base["epochs"][1], "state": "waiting"}]},
        "a date": {**base, "epochs": [base["epochs"][0], {**base["epochs"][1], "date": "soon"}]},
        "an epoch key": {**base, "epochs": [base["epochs"][0], {**base["epochs"][1], "why": "text"}]},
        "a repeated hash": {**base, "epochs": base["epochs"] + [dict(base["epochs"][1])]},
        "free text as hash": {**base, "epochs": [base["epochs"][0], {**base["epochs"][1], "catalog_sha256": "the catalog changed"}]},
    }
    for label, data in bad.items():
        assert el.interpreter_epochs_file_problems(tree(tmp_path / label.replace(" ", "-"), data)), label


# --- the served file and the generator -------------------------------------------------------------------------------------

def test_the_served_catalog_file_must_hash_to_the_served_epoch(tmp_path):
    root = tree(tmp_path)
    fx.put(root, "runtime/interpreter_catalog.json", fx.CATALOG_2)  # the snapshot was written and the epochs file was not
    found = el.interpreter_epochs_file_problems(root)
    assert len(found) == 1 and "served catalog file's hash is not the epoch named served" in found[0]
    (Path(root) / "runtime/interpreter_catalog.json").unlink()
    assert "is missing or not a JSON object" in el.interpreter_epochs_file_problems(root)[0]


def test_the_generator_must_return_the_served_epoch_or_one_pending_rerun(tmp_path):
    root = tree(tmp_path)
    assert el.interpreter_epochs_file_problems(root, OLD) == []                      # nothing changed
    assert el.interpreter_epochs_file_problems(root, NEW)                            # natural changed and nobody recorded it
    pending = tree(tmp_path / "p", fx.epochs(OLD, (NEW, "pending-rerun")))
    assert el.interpreter_epochs_file_problems(pending, NEW) == []                   # recorded, waiting for the rerun
    assert el.interpreter_epochs_file_problems(pending, OTHER)                       # a third catalog is not recorded
    retired = tree(tmp_path / "r", fx.epochs(OLD, (NEW, "retired")))
    assert el.interpreter_epochs_file_problems(retired, NEW)                         # a retired epoch is not a pending one
    served_new = tree(tmp_path / "s", {"v": 1, "served": NEW, "epochs": [
        {"catalog_sha256": OLD, "date": "2030-10-01", "state": "retired"}, {"catalog_sha256": NEW, "date": "2030-10-03", "state": "served"}]},
        catalog=fx.CATALOG_2)
    assert el.interpreter_epochs_file_problems(served_new, NEW) == []


def test_vacuity_a_rule_that_only_read_the_file_would_pass_a_stale_snapshot(tmp_path):
    root = tree(tmp_path / "v")
    assert el.interpreter_epochs_problems(json.loads((Path(root) / "evals/interpreter/epochs.json").read_text())) == []
    fx.put(root, "runtime/interpreter_catalog.json", fx.CATALOG_2)
    assert el.interpreter_epochs_problems(json.loads((Path(root) / "evals/interpreter/epochs.json").read_text())) == []  # the form alone passes
    assert el.interpreter_epochs_file_problems(root) != []                                                              # the rule does not


# --- the real files ---------------------------------------------------------------------------------------------------------

GENERATED = """
import runpy, sys
sys.path.insert(0, 'runtime')
module = runpy.run_path('runtime/interpreter_catalog.py')
print(module['sha256'](module['generate']()))
"""


def generated_hash():
    done = subprocess.run([sys.executable, "-c", GENERATED], cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_real_epochs_file_follows_the_rule_of_the_real_catalog():
    assert el.interpreter_epochs_file_problems(str(REPO), generated_hash()) == []
    data = json.loads((REPO / "evals/interpreter/epochs.json").read_text())
    served = [e for e in data["epochs"] if e["state"] == "served"]
    assert len(served) == 1 and served[0]["catalog_sha256"] == data["served"]
