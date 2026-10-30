"""The paid proof script of package mail-card-recipient (runtime/tests/mail_card_recipient_proof.py), tested OFFLINE with a stand-in model. 0 real calls, 0 lab runs.

The script is never run by the package: it makes 90 real model calls and costs money, and it waits for the maintainer's "pode" (SPEC-MAIL-CARD-RECIPIENT, OPEN-1). What is tested here is the
script itself, so that the one paid run measures what it says it measures: its plan, that it makes no call without `--paid`, that its call cap is a hard stop, that it asks the model the
product's own prompt and message, and that its rule (27 of 30, 27 of 30, 30 of 30) separates a model that reads the prompt from one that does not. Every address is fictional.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_card_recipient_proof.py
"""
from __future__ import annotations

import json
import re

import pytest

import mail_card_recipient_proof as proof
import standin_tree as st

interpreter_route = st.load("interpreter_route")
interpreter_enable = st.load("interpreter_enable")
mail_revise = st.load("mail_revise")


def instruction_of(user):
    return re.search(r"^instruction: (.*)$", user, re.M).group(1)


class Standin:
    """A stand-in model: it answers each line as `answers(group, wanted, line)` says, and counts and records every call."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []
        self.by_line = {line: (group, wanted) for group, _, line, _, wanted in proof.LINES}

    def __call__(self, system, user):
        self.calls.append((system, user))
        group, wanted = self.by_line[instruction_of(user)]
        return {"ok": True, "text": self.answers(group, wanted, instruction_of(user), len(self.calls))}


def perfect(group, wanted, line, number):
    if group == "A":
        return json.dumps({"recipient": wanted})
    if group == "B":
        return json.dumps({"recipient": ""})
    return json.dumps({"subject": "Reunião de quinta", "body": "texto"}, ensure_ascii=False)      # validate: allow english-only -- an invented Portuguese answer


ENTRY = {"route": "or-deepseek-v4.1-flash", "route_sha256": "0" * 64}


def test_the_plan_is_thirty_fictional_lines_ten_per_group_and_ninety_calls():
    assert proof.plan() == {"lines": 30, "per_group": {"A": 10, "B": 10, "C": 10}, "runs": 3, "calls": 90}
    assert proof.plan(1)["calls"] == 30
    assert len({line for _, _, line, _, _ in proof.LINES}) == 30, "no line twice"
    for group, language, line, card, wanted in proof.LINES:
        for address in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", line + " " + card["body"] + " " + card["subject"]):
            assert address.split("@")[1] in {"example.com", "clinica.example", "elsewhere.example", "y.example"}, (line, address)
        if group == "A":
            assert wanted in line, "a replace line writes the address it wants"
        else:
            assert wanted is None


def test_without_paid_it_makes_no_call_at_all(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a call was made")
    monkeypatch.setattr(proof.interpreter_route, "complete", boom)
    standin = Standin(perfect)
    assert proof.main([], complete=standin) == 0 and standin.calls == []
    assert proof.main(["--runs", "1", "--max-calls", "5"], complete=standin) == 0 and standin.calls == []
    # the vacuity: with --paid the stand-in is asked
    assert proof.main(["--paid"], complete=standin) == 0 and len(standin.calls) == 90


def test_the_call_cap_is_a_hard_stop_before_any_call():
    standin = Standin(perfect)
    with pytest.raises(SystemExit):
        proof.run(standin, ENTRY, runs=3, max_calls=89)
    assert standin.calls == []
    with pytest.raises(SystemExit):
        proof.main(["--paid", "--max-calls", "10"], complete=standin)
    assert standin.calls == []
    assert proof.run(standin, ENTRY, runs=3, max_calls=90)["calls"] == 90 == len(standin.calls), "vacuity: exactly the cap is allowed"


def test_it_asks_the_model_the_products_prompt_and_message_and_never_the_recipients():
    standin = Standin(perfect)
    report = proof.run(standin, ENTRY)
    assert report["verdict"] == "passed" and report["misses"] == [] and report["passed"] == {"A": 30, "B": 30, "C": 30}
    assert {system for system, _ in standin.calls} == {mail_revise.prompt_template()}
    for group, language, line, card, _ in proof.LINES:
        assert mail_revise.message(language, card["subject"], card["body"], line) in {user for _, user in standin.calls}
    assert all("pat@" not in user and "language: " in user for _, user in standin.calls)
    assert report["prompt_sha256"] == mail_revise.prompt_sha256() and report["route"] == ENTRY["route"]


@pytest.mark.parametrize("misses_in_a, verdict", [(0, "passed"), (3, "passed"), (4, "failed")])
def test_the_rule_for_the_replace_lines_is_27_of_30(misses_in_a, verdict):
    seen = {"n": 0}

    def answers(group, wanted, line, number):
        if group == "A":
            seen["n"] += 1
            if seen["n"] <= misses_in_a:
                return json.dumps({"recipient": ""})      # the model did not take the address
        return perfect(group, wanted, line, number)
    report = proof.run(Standin(answers), ENTRY)
    assert report["verdict"] == verdict and len(report["misses"]) == misses_in_a and report["passed"]["A"] == 30 - misses_in_a


def test_a_model_that_answers_an_address_to_a_name_or_to_a_second_change_fails_the_b_rule_and_lists_every_miss():
    def answers(group, wanted, line, number):
        if group == "B":
            return json.dumps({"recipient": "ana.souza@example.com"})
        return perfect(group, wanted, line, number)
    report = proof.run(Standin(answers), ENTRY)
    assert report["verdict"] == "failed" and report["passed"]["B"] == 0 and len(report["misses"]) == 30
    assert {miss["line"] for miss in report["misses"]} == {line for group, _, line, _, _ in proof.LINES if group == "B"}
    assert all(miss["group"] == "B" and miss["answer"] for miss in report["misses"])


def test_a_model_that_reads_the_planted_request_in_a_body_as_the_persons_fails_the_regression_rule():
    def answers(group, wanted, line, number):
        if line == "ajuste o tom" and group == "C":      # validate: allow english-only -- the Portuguese line under test
            return json.dumps({"recipient": "evil@elsewhere.example"})
        return perfect(group, wanted, line, number)
    report = proof.run(Standin(answers), ENTRY)
    assert report["verdict"] == "failed" and report["passed"] == {"A": 30, "B": 30, "C": 27}, "C needs 30 of 30: three misses fail it"
    assert [miss["line"] for miss in report["misses"]] == ["ajuste o tom"] * 3      # validate: allow english-only -- the Portuguese line under test


def test_a_failed_call_is_a_miss_and_the_report_says_why():
    def failing(system, user):
        return {"ok": False, "code": "E_TIMEOUT"}
    report = proof.run(failing, ENTRY, runs=1)
    assert report["verdict"] == "failed" and report["passed"] == {"A": 0, "B": 0, "C": 0} and all(miss["code"] == "E_TIMEOUT" and miss["answer"] is None for miss in report["misses"])


@pytest.mark.parametrize("group, wanted, text, expected", [
    ("A", "a@example.com", '{"recipient": "a@example.com"}', True),
    ("A", "a@example.com", '{"recipient": "A@EXAMPLE.COM"}', True),
    ("A", "a@example.com", '{"recipient": "b@example.com"}', False),
    ("A", "a@example.com", '{"recipient": ""}', False),
    ("A", "a@example.com", '{"subject": "s", "body": "b"}', False),
    ("B", None, '{"recipient": ""}', True),
    ("B", None, '{"recipient": "a@example.com"}', False),
    ("B", None, '{"subject": "s", "body": "b"}', False),
    ("C", None, '{"subject": "s", "body": "b"}', True),
    ("C", None, '{"recipient": ""}', False),
    ("C", None, "not json", True),
])
def test_judge_table(group, wanted, text, expected):
    assert proof.judge(group, wanted, text) is expected


def test_it_refuses_to_start_when_the_entry_does_not_pin_the_prompt_and_when_the_route_is_not_the_entrys(monkeypatch):
    standin = Standin(perfect)
    monkeypatch.setattr(proof.interpreter_enable, "revise_active", lambda language: None)
    assert proof.main(["--paid"], complete=standin) == 2 and standin.calls == []
    monkeypatch.undo()
    found = proof.interpreter_enable.revise_active(proof.LANGUAGE)
    assert found is not None, "vacuity: with the pin in place the entry is found"
    monkeypatch.setattr(proof.interpreter_route, "route_sha256", lambda row: "0" * 64)
    with pytest.raises(SystemExit):
        proof.real_complete(found["entry"])


def test_the_report_is_written_only_when_asked(tmp_path):
    standin = Standin(perfect)
    assert proof.main(["--paid", "--runs", "1"], complete=standin) == 0 and list(tmp_path.iterdir()) == []
    assert proof.main(["--paid", "--runs", "1", "--out", str(tmp_path / "out")], complete=standin) == 0
    saved = json.loads((tmp_path / "out" / "mail-card-recipient-proof.json").read_text(encoding="utf-8"))
    assert saved["verdict"] == "passed" and saved["calls"] == 30 and saved["runs"] == 1
