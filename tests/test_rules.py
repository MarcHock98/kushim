"""Grundregeln (`safety/rules.py`) bleiben nach dem Umbau (Roadmap v2 A5) erhalten; die alten Werkzeug-Gates kommen nicht zurück."""
from pathlib import Path

from kushim import safety
from kushim.safety.rules import PRIME_DIRECTIVE, PRINCIPLES, Harm

SRC = Path(__file__).resolve().parents[1] / "src" / "kushim"


def test_prime_directive_is_the_first_principle_and_forbids_harm():
    assert PRINCIPLES[0] == PRIME_DIRECTIVE and "Schäden jeder Art sind verboten" in PRIME_DIRECTIVE
    assert any("Fähigkeiten nie selbst erweitern" in p for p in PRINCIPLES)
    assert {h.value for h in Harm} >= {"seelisch", "finanziell"}


def test_safety_package_exports_only_the_rules():
    assert set(safety.__all__) == {"PRIME_DIRECTIVE", "PRINCIPLES", "Harm"}


def test_old_tool_gates_are_gone_and_not_imported_anywhere():
    for gone in ("safety/gate.py", "safety/approvals.py", "privacy.py", "tools", "api/tools_api.py", "api/tasks_api.py"):
        assert not (SRC / gone).exists(), gone
    users = [f.relative_to(SRC).as_posix() for f in SRC.rglob("*.py")
             if any(m in f.read_text(encoding="utf-8") for m in ("safety.gate", "safety.approvals", "kushim.privacy",
                                                                   "from ..privacy", "from .privacy", "tools.registry"))]
    assert users == [], users
