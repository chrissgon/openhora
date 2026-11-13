"""How the class is registered and found (providers/resolve.py, providers/stock/): a source is two files and nothing else."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import Run, photo

REPO = Path(__file__).resolve().parents[3]
STOCK = REPO / "providers" / "stock"
sys.path.insert(0, str(REPO / "providers"))
import resolve  # noqa: E402

import _stock  # noqa: E402


VERBS = {"web": ("preview", "fetch")}      # the open-web source fetches a URL a model wrote: it has no search verb


def sources():
    return sorted(p.stem for p in (STOCK / "sources").glob("*.json"))


def test_the_class_resolves_to_the_implementations_that_have_a_source_file_and_nothing_else():
    names = resolve.implementations("stock:media")
    assert names == sources() and names and "_stock" not in names and "_net" not in names
    for name in names:
        assert resolve.serves_class("stock:media", name, strict=True)
        assert json.loads((STOCK / "sources" / (name + ".json")).read_text())["source"] == name


def test_the_class_is_runtime_only_with_the_variables_the_contract_names():
    assert "stock" in resolve.ROLES and "stock:media" not in resolve.LISTED
    assert resolve.variables("stock:media") == ["STOCK_MEDIA_PROVIDER", "STOCK_PROVIDER"]
    assert resolve.folder("stock:media") == "stock" and resolve.platform_of("stock:media") is None
    assert "stock:media" not in (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    contract = (REPO / "providers" / "CONTRACT.md").read_text(encoding="utf-8")
    assert contract.count("`stock:media`") >= 2 and "providers/stock/" in contract


def test_every_implementation_declares_the_class_and_its_verbs_as_text():
    for name in sources():
        tree = ast.parse((STOCK / (name + ".py")).read_text(encoding="utf-8"))
        values = {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
                  and t.id in ("SERVES", "SOURCE", "VERBS")}
        assert values["SERVES"] == "stock:media" and values["SOURCE"] == name and values["VERBS"] == VERBS.get(name, ("search", "fetch"))


def test_every_file_of_the_class_parses_as_python_3_9():
    for path in sorted(STOCK.glob("*.py")) + sorted((STOCK / "tests").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


def test_no_source_name_appears_in_the_runtime_or_the_renderer():
    names = [json.loads((STOCK / "sources" / (n + ".json")).read_text())["source"] for n in sources() if n != "web"]      # "web" is ordinary English in the runtime: its file names are checked below
    found = []
    for folder in ("runtime", "providers/renderer"):
        for path in sorted((REPO / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".md", ".js", ".html", ".txt") and "node_modules" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                found += [(str(path.relative_to(REPO)), n) for n in names if re.search(r"\b%s\b" % re.escape(n), text)]
    assert found == []
    for folder in ("runtime", "providers/renderer"):
        for path in sorted((REPO / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".md", ".js", ".html", ".txt") and "node_modules" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "providers/stock/web" not in text and "sources/web.json" not in text and "stock/web.py" not in text, str(path)


def test_the_two_licence_tuples_of_the_provider_and_the_runtime_are_equal_once_the_runtime_has_its_own():
    runtime = REPO / "runtime" / "media_stock.py"
    if not runtime.is_file():
        pytest.skip("runtime/media_stock.py lands with V9b-3")
    tree = ast.parse(runtime.read_text(encoding="utf-8"))
    values = {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)
              and t.id in ("LICENCES_ACCEPTED", "LICENCES_CREDIT")}
    assert values["LICENCES_ACCEPTED"] == _stock.LICENCES_ACCEPTED and values["LICENCES_CREDIT"] == _stock.LICENCES_CREDIT


def test_adding_a_source_is_two_files_and_no_other_change(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    shutil.copytree(REPO / "providers" / "stock", root / "providers" / "stock", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    shutil.copy2(REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    pexels = (root / "providers" / "stock" / "pexels.py").read_text(encoding="utf-8")
    (root / "providers" / "stock" / "aster.py").write_text(pexels.replace('SOURCE = "pexels"', 'SOURCE = "aster"').replace("STOCK_PEXELS_API_KEY", "STOCK_ASTER_API_KEY"), encoding="utf-8")
    (root / "providers" / "stock" / "sources" / "aster.json").write_text(json.dumps(kit.source(source="aster", secret="STOCK_ASTER_API_KEY")), encoding="utf-8")
    after = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert sorted(set(after) - set(before)) == ["providers/stock/aster.py", "providers/stock/sources/aster.json"] and set(before) <= set(after)
    assert resolve.implementations("stock:media", root=root, env={}) == sorted(sources() + ["aster"])
    # a fake find sees it with no other change
    spec = importlib.util.spec_from_file_location("aster", root / "providers" / "stock" / "aster.py")
    aster = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aster)
    assert aster.SOURCE == "aster" and aster.SERVES == "stock:media"
    (tmp_path / "run").mkdir()
    r = Run(tmp_path / "run", monkeypatch, kit.source(source="aster", secret="STOCK_ASTER_API_KEY"), impl=aster,
            resolver=kit.FakeResolver({"STOCK_ASTER_API_KEY": kit.KEY}))
    r.serve_search_image([photo(1001)])
    code, got = r.search()
    assert code == 0 and got["source"] == "aster" and got["candidates"][0]["preview"] == "prev-aster-1001.jpg"
    assert (r.tmp / "out" / "prev-aster-1001.jpg").is_file()


def test_the_readme_says_how_to_add_a_source():
    text = (STOCK / "README.md").read_text(encoding="utf-8")
    for needle in ("How to add a source", "sources/<name>.json", "REGISTRY", "licence policy", "unverified", "STOCK_MEDIA_PROVIDER"):
        assert needle in text, needle
