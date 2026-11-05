"""Tests of the language choice on the page (package LANGUAGE): the pure words of interface/js/language.js, the request form's language select
(the project's language first and selected, a short list, a typed tag that the page checks with the service's rule), what the form reports and
what `createRequest` and the client send, and the plan card's one line before approval (interface/js/cards/plan-rows.js languageLine). No browser,
no model and no service; the fake document of the Lobby's tests. The service's own check of a tag is in test_project_language.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_language.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st
from test_interface_lobby import FAKE_EXTRA, JS, needs_node, run_node  # noqa: F401  (FAKE_EXTRA: the module is read by run_node)

language = st.load("language")

PIECES = r"""
import { FakeNode, find, byClass, textOf } from "@FAKE@";
import * as lang from "@JS@/language.js";
import * as rows from "@JS@/cards/plan-rows.js";
import { createForm } from "@JS@/views/lobby-form.js";
import { createRequest } from "@JS@/views/lobby-actions.js";

const out = {};

// the pure words
out.options = [lang.languageOptions(null), lang.languageOptions("pt-BR"), lang.languageOptions("portuguese")];
out.chosen = ["", "en", "pt-BR"].map((s) => lang.chosenLanguage(s, "")).concat([lang.chosenLanguage("en", " it "), lang.chosenLanguage("en", "pt_BR"), lang.chosenLanguage("", "EN"), lang.chosenLanguage(undefined, undefined)]);
out.rule = ["en", "pt-BR", "pt_BR", "pt-br", "es-419", "zh-Hant-TW", "e", ""].map((t) => lang.TAG_RULE.test(t));

// the plan card's line
const task = (over = {}) => ({ key: "a", title: "A", skill: "demo-a", depends_on: [], ...over });
const item = (tasks, project = "pt-BR") => ({ payload: { tasks, ...(project ? { project_language: project } : {}) } });
out.line = [rows.languageLine(item([task(), task({ key: "b" })])), rows.languageLine(item([task({ language: "en" }), task({ key: "b", language: "en" })])),
  rows.languageLine(item([task({ language: "en" }), task({ key: "b" }), task({ key: "c", step: "ingest" })])), rows.languageLine(item([task(), task({ key: "b", language: "es" }), task({ key: "c" })])),
  rows.languageLine(item([task()], null)), rows.languageLine({}), rows.languageLine(item([{ key: "s", step: "ingest" }]))];

// the form
const made = [];
const form = createForm({ onCreate: (v) => made.push(v) });
const selects = find(form.el, (n) => n.tagName === "SELECT");
const language = selects.find((n) => n.attrs.id === "wb-new-lang");
const other = find(form.el, (n) => n.attrs.id === "wb-new-lang-other")[0] || find(form.el, (n) => n.tagName === "INPUT").find((n) => n.attrs.id === "wb-new-lang-other");
const text = find(form.el, (n) => n.tagName === "TEXTAREA")[0];
const submit = () => (find(form.el, (n) => n.tagName === "FORM")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
out.first = { options: language.children.map((o) => [o.attrs.value, textOf(o)]), labels: find(form.el, (n) => n.tagName === "LABEL").map((n) => n.children[0].textContent), hint: byClass(form.el, "wb-hint").map(textOf).filter((t) => t.includes("language"))[0] };
form.setLanguage("pt-BR");
out.project = language.children.map((o) => [o.attrs.value, textOf(o)])[0];
text.value = "Plan the launch";
submit();                                   // nothing chosen: no language is sent, the project's decides
language.value = "pt-BR"; submit();
language.value = "en"; other.value = "  it  "; submit();      // a typed tag wins over the list
other.value = "pt_BR"; submit();                              // refused here, with the rule's own words; nothing is sent
out.error = { text: byClass(form.el, "wb-card-error")[0].textContent, shown: !byClass(form.el, "wb-card-error")[0].hidden };
out.sent = made.map((v) => v.language);
form.setLanguage("es");                     // the project's setting changed under the open form: the choice stays while it is listed
out.kept = [language.value, language.children[0].textContent];
form.reset();
out.reset = [language.value, other.value];
form.set({ creating: true });
out.disabled = [language.disabled, other.disabled];

// what is sent
const sent = [];
const api = { request: async (project, body, options) => { sent.push(options); return { request: 7 }; } };
await createRequest(api, "p1", { text: "Do it", flow: "", language: "pt-BR" }, { route: false });
await createRequest(api, "p1", { text: "Do it", flow: "", language: "" }, { route: false });
await createRequest(api, "p1", { text: "Do it", flow: "" }, { route: false });
out.api = sent.map((o) => o.language);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_form_the_words_and_the_card_line(tmp_path):
    got = run_node(tmp_path, PIECES)
    assert got["options"][0][0] == {"value": "", "label": "Project language (en)"} and got["options"][1][0]["label"] == "Project language (pt-BR)"
    assert got["options"][2][0]["label"] == "Project language (en)", "a setting the rule would refuse is not shown"
    assert [o["value"] for o in got["options"][1]] == ["", "en", "pt-BR", "es", "fr", "de"]
    assert got["chosen"] == [{"value": ""}, {"value": "en"}, {"value": "pt-BR"}, {"value": "it"},
                             {"problem": "A language is two lower-case letters, optionally a hyphen and two upper-case letters, such as en or pt-BR."},
                             {"problem": "A language is two lower-case letters, optionally a hyphen and two upper-case letters, such as en or pt-BR."}, {"value": ""}]
    assert got["rule"] == [True, True, False, False, False, False, False, False], "the page's rule is the service's"
    assert got["line"] == ["Language: pt-BR", "Language: en (requested)", "Language: en (requested) for task 1; pt-BR for task 2",
                           "Language: pt-BR for tasks 1, 3; es (requested) for task 2", "", "", "Language: pt-BR"]
    first = got["first"]
    assert first["options"][0] == ["", "Project language (en)"] and [o[0] for o in first["options"]] == ["", "en", "pt-BR", "es", "fr", "de"]
    assert first["labels"][:4] == ["What do you want done?", "Flow", "Model", "Language"], "the language select is beside the model select"
    assert first["hint"].startswith("The language the deliverables are written in.")
    assert got["project"] == ["", "Project language (pt-BR)"]
    assert got["sent"] == [None, "pt-BR", "it"], "an empty choice sends nothing; a typed tag wins; a refused text sends nothing at all"
    assert got["error"] == {"text": "A language is two lower-case letters, optionally a hyphen and two upper-case letters, such as en or pt-BR.", "shown": True}
    assert got["kept"] == ["en", "Project language (es)"] and got["reset"] == ["", ""] and got["disabled"] == [True, True]
    assert got["api"] == ["pt-BR", None, None]


def test_the_client_and_the_form_name_the_language_the_service_takes():
    client = (JS / "api.js").read_text(encoding="utf-8")
    assert "{ body: { text, flow, title, after, model, language }" in client
    assert 'form.setLanguage(got.language)' in (JS / "views" / "lobby.js").read_text(encoding="utf-8")
    tag = re.search(r"TAG_RULE = /(.+)/;", (JS / "language.js").read_text(encoding="utf-8")).group(1)
    assert tag == language.RULE.pattern, "one rule on the page and in the runtime"
