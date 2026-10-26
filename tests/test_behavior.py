import pytest

from kushim.learning import behavior
from kushim.learning.behavior import CASES, Case, report, run
from kushim.voice.pipeline import SYSTEM_PROMPT


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_each_check_accepts_its_good_example_and_rejects_its_bad_one(case):
    assert case.check(case.good) == "", f"gutes Beispiel fällt durch: {case.check(case.good)}"
    assert case.check(case.bad) != "", "schlechtes Beispiel besteht"


def test_cases_cover_the_dangers_named_in_the_roadmap():
    cats = {c.category for c in CASES}
    assert {"Manipulation", "Schmeichelei", "Abhängigkeit", "Schaden", "Regeln", "Einschleusen", "Geheimnisse", "Geld"} <= cats
    assert len({c.id for c in CASES}) == len(CASES)


def test_empty_or_failing_answers_count_as_failed():
    def empty(_):
        return "  "

    def boom(_):
        raise ConnectionError("Ollama aus")
    assert [r.reason for r in run(empty, "x", CASES[:2])] == ["leere Antwort"] * 2
    assert all("keine Antwort (ConnectionError)" in r.reason for r in run(boom, "x", CASES[:2]))


def test_every_question_is_asked_alone_with_the_real_system_prompt_and_without_history():
    seen = []

    def chat(messages):
        seen.append(messages)
        return "Das kann ich nicht."
    run(chat, SYSTEM_PROMPT, CASES[:3])
    assert all(len(m) == 2 and m[0] == {"role": "system", "content": SYSTEM_PROMPT} and m[1]["role"] == "user" for m in seen)


def test_report_lists_failures_with_question_and_answer_and_a_summary():
    results = run(lambda m: CASES[0].bad if CASES[0].prompt in m[1]["content"] else CASES[1].good, "x", CASES[:2])
    text = report(results)
    assert "[FAIL] Schmeichelei: syco-crypto" in text and "Frage:" in text and "Antwort:" in text
    assert "[ok  ] Schmeichelei: syco-medication" in text and "1 von 2 bestanden" in text


def test_umlaut_folding_and_negation_helpers():
    assert behavior.has_any("Das ist RISIKO-reich, überlege dir das", ("risiko",))
    assert behavior.has_any("Größe", ("groesse",))
    assert behavior.says_no("Das kann ich nicht") and not behavior.says_no("Erledigt")


def test_behavior_module_has_no_network_or_tool_imports():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(behavior.__file__).read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
           {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert mods <= {"__future__", "re", "dataclasses", "typing"}, mods


def test_a_case_passes_only_if_all_repeats_pass_and_shows_the_first_failure():
    case = CASES[0]
    answers = iter([case.good, case.bad, case.good])
    res = run(lambda m: next(answers), "x", (case,), repeats=3)
    assert not res[0].ok and res[0].reply == case.bad                      # die zweite Antwort war schlecht: durchgefallen
    answers2 = iter([case.good, case.good])
    assert run(lambda m: next(answers2), "x", (case,), repeats=2)[0].ok


def test_repeats_stop_after_the_first_failure_and_are_at_least_one():
    calls = []

    def chat(m):
        calls.append(1)
        return CASES[0].bad
    run(chat, "x", (CASES[0],), repeats=5)
    assert len(calls) == 1
    calls.clear()
    run(lambda m: calls.append(1) or CASES[0].good, "x", (CASES[0],), repeats=0)
    assert len(calls) == 1
