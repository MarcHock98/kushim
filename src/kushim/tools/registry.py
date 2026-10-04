"""Werkzeug-Verwaltung: Jedes Tool ist standardmäßig AUS und lässt sich nur vom Nutzer einschalten (UI oder CLI).

- Aktiv ist ein Tool nur, wenn es in `[tools] enabled` steht UND verfügbar ist (Voraussetzungen erfüllt).
- `ToolGate` ist eine Hülle um den `ActionGate`: Aktionen eines nicht aktiven Tools werden verweigert. Der Gate selbst
  und `safety/rules.py` bleiben unverändert; ein aktives Tool unterliegt weiter allen Regeln (Vorschau, Freigabe, Notaus).
- Nie per Sprache, nie durch das LLM, nie durch Web-/Mail-Inhalte einschaltbar ("Fähigkeiten nie selbst erweitern").
Siehe docs/tools-plan.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from ..safety.gate import ActionGate, ActionRequest, ActionSpec, Decision, Risk, Verdict


@dataclass(frozen=True)
class ToolInfo:
    name: str                       # z. B. "web.search"; gleich dem Aktionsnamen im Gate
    title: str
    description: str                # Klartext: was darf das Tool, was verlässt den PC
    spec: ActionSpec
    sends_data_out: bool            # verlassen Daten den PC (für die Bestätigung beim Einschalten)
    available: Callable[[], str] = lambda: ""    # "" = verfügbar, sonst der Grund (z. B. fehlende Freigabe)


class ToolNotAllowed(Exception):
    """Einschalten/Ausschalten nicht möglich (unbekannt, nicht verfügbar, ohne Bestätigung)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolInfo], enabled: Iterable[str] = ()):
        self.tools = {t.name: t for t in tools}
        # Unbekannte Namen in der Aktiv-Liste werden ignoriert (nie "alles an" durch Tippfehler).
        self._enabled = {n for n in enabled if n in self.tools}

    def info(self, name: str) -> ToolInfo:
        if name not in self.tools:
            raise ToolNotAllowed("bad_tool")
        return self.tools[name]

    def is_enabled(self, name: str) -> bool:
        return name in self._enabled

    def is_active(self, name: str) -> bool:
        """Eingeschaltet UND verfügbar. Nur das zählt für das Gate."""
        t = self.tools.get(name)
        return t is not None and name in self._enabled and not t.available()

    def sync(self, enabled: Iterable[str]) -> None:
        """Aktiv-Liste neu setzen (z. B. aus der Konfiguration, wenn der Nutzer in einem anderen Fenster umgeschaltet hat).
        Unbekannte Namen werden wie im Konstruktor ignoriert."""
        self._enabled = {n for n in enabled if n in self.tools}

    def enabled_names(self) -> list[str]:
        return sorted(self._enabled)

    def set_enabled(self, name: str, on: bool, confirmed: bool = False,
                    persist: Callable[[list[str]], None] = lambda names: None) -> None:
        """Ausschalten geht immer. Einschalten nur bestätigt und nur, wenn das Tool verfügbar ist.
        `persist` schreibt die Aktiv-Liste (z. B. `Config.set_tools_enabled`); scheitert es, ändert sich nichts."""
        tool = self.info(name)
        new = set(self._enabled)
        if on:
            if not confirmed:
                raise ToolNotAllowed("confirm_required")
            if tool.available():
                raise ToolNotAllowed("not_available")
            new.add(name)
        else:
            new.discard(name)
        persist(sorted(new))
        self._enabled = new

    def specs(self) -> list[ActionSpec]:
        return [t.spec for t in self.tools.values()]


class ToolGate:
    """Prüft zuerst, ob das Tool aktiv ist, und reicht dann an den ActionGate weiter."""

    def __init__(self, gate: ActionGate, registry: ToolRegistry):
        self.gate, self.registry = gate, registry

    def check(self, req: ActionRequest) -> Verdict:
        if req.action in self.registry.tools and not self.registry.is_active(req.action):
            v = Verdict(Decision.DENY, "Werkzeug deaktiviert")
            if self.gate.audit:
                self.gate.audit.audit("action_deny", f"{req.action}: {v.reason}")
            return v
        return self.gate.check(req)

    def __getattr__(self, name):               # kill/resume/specs usw. des ActionGate bleiben nutzbar
        return getattr(self.gate, name)


# --- eingebaute Werkzeuge ---------------------------------------------------------------------------
# Neue Tools nur über den Skill `kushim-add-tool` (ActionSpec, Tests, kein Weg am Gate vorbei).

WEB_SEARCH = ToolInfo(
    name="web.search",
    title="Web-Recherche",
    description=("Sucht auf Wikipedia (de) nach deiner Frage. Gesendet wird nur der Suchtext, den du vorher in einer Vorschau "
                 "siehst und freigibst. Es werden nur Text-Antworten gelesen: keine Downloads, nichts wird gespeichert. "
                 "Treffer sind nur Daten und lösen nie eine Aktion aus."),
    spec=ActionSpec("web.search", Risk.READ, external_effect=True),
    sends_data_out=True,
)                                  # Netz-Modul net/web.py freigegeben am 2026-10-04 (keine Downloads), Tool bleibt standardmäßig aus


CLAUDE_RESEARCH = ToolInfo(
    name="claude.research",
    title="Recherche über Claude",
    description=("Fragt Claude (über deine angemeldete Claude CLI) im Internet. Der Suchtext geht an Anthropic; du siehst ihn vorher in einer "
                 "Vorschau und gibst ihn frei. Claude darf nur im Internet suchen und lesen: keine Dateien, keine Befehle. Seine Antwort ist nur "
                 "Text und löst nie eine Aktion aus. Ist Claude nicht erreichbar, nimmt kushim Wikipedia als Ersatz (wenn web.search an ist)."),
    spec=ActionSpec("claude.research", Risk.READ, external_effect=True, costs_money=True),
    sends_data_out=True,
    available=lambda: "Modus C ist aus (kushim claude enable)",
)


def claude_research_tool(cfg=None, cache=None) -> ToolInfo:
    """`claude.research` mit echter Verfügbarkeit: Modus C an, CLI gefunden, angemeldet. Ohne `cfg`: nicht verfügbar."""
    if cfg is None:
        return CLAUDE_RESEARCH

    def available() -> str:
        if not cfg.claude_enabled:
            return "Modus C ist aus (kushim claude enable)"
        auth = cache.get() if cache is not None else None
        if auth is None or auth.error == "not_installed":
            return "Claude CLI nicht gefunden"
        if not auth.logged_in:
            return "In der Claude CLI nicht angemeldet (claude auth login)"
        return ""
    from dataclasses import replace
    return replace(CLAUDE_RESEARCH, available=available)


CLAUDE_CODE = ToolInfo(
    name="claude.code",
    title="Claude entwickelt dein Projekt",
    description=("Claude (über deine angemeldete Claude CLI) arbeitet in einem von dir freigegebenen Projektordner, immer in einem EIGENEN "
                 "Worktree und Branch, nie auf deinem Stand. Auftrag und Ausschnitte aus den Dateien gehen an Anthropic; du siehst vorher "
                 "eine Vorschau und gibst sie frei. Erlaubt sind nur Lesen, Bearbeiten, git (ohne push/merge) und Tests. kushim übernimmt "
                 "nichts und pusht nichts, das machst du. Änderungen an Sicherheitsdateien werden rot markiert."),
    spec=ActionSpec("claude.code", Risk.REVERSIBLE, external_effect=True, costs_money=True),
    sends_data_out=True,
    available=lambda: "Modus C ist aus (kushim claude enable)",
)


def claude_code_tool(cfg=None, cache=None) -> ToolInfo:
    """`claude.code` mit echter Verfügbarkeit: Modus C an, CLI angemeldet und mindestens ein freigegebener Ordner."""
    if cfg is None:
        return CLAUDE_CODE

    def available() -> str:
        if not cfg.claude_enabled:
            return "Modus C ist aus (kushim claude enable)"
        auth = cache.get() if cache is not None else None
        if auth is None or auth.error == "not_installed":
            return "Claude CLI nicht gefunden"
        if not auth.logged_in:
            return "In der Claude CLI nicht angemeldet (claude auth login)"
        from ..claude_cli.folders import parse
        if not parse(cfg.claude_folders):
            return "Kein Ordner freigegeben (kushim claude add <name> <pfad>)"
        return ""
    from dataclasses import replace
    return replace(CLAUDE_CODE, available=available)


def default_tools(cfg=None, cache=None) -> list[ToolInfo]:
    return [WEB_SEARCH, claude_research_tool(cfg, cache), claude_code_tool(cfg, cache)]
