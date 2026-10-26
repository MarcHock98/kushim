"""Richtet Claude Code für alle Projekte sparsam und ohne Datenabfluss ein (Windows, macOS, Linux).

Aufruf:
    py scripts\\claude_setup.py                 # global: Graphify, Einstellungen, Token-Regeln
    py scripts\\claude_setup.py --project PFAD  # zusätzlich ein Projekt mit Graphify verbinden
    py scripts\\claude_setup.py --dry-run       # nur anzeigen, nichts ändern
    py scripts\\claude_setup.py --statusline    # zusätzlich die Statuszeile (scripts/statusline.py) eintragen
    py scripts\\claude_setup.py --test-hook     # zusätzlich den Hook, der lange Testausgaben kürzt (scripts/trim_test_output.py)

Was es tut (wiederholbar, ändert nur eigene, markierte Teile, legt vorher Sicherungen an):
1. Installiert Graphify (PyPI-Paket `graphifyy`, feste Version) für den Benutzer und meldet den Skill in Claude Code an.
2. `~/.claude/settings.json`: schaltet Telemetrie, Fehlerberichte und Auto-Updates von Claude Code ab
   (`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`) und das Abfrageprotokoll von Graphify.
3. `~/.claude/CLAUDE.md`: kurzer Block mit Regeln zum Token-Sparen (zwischen festen Markierungen).
4. Mit `--project`: Code-Graph bauen (nur lokal, ohne KI, 0 Tokens), Graphify-Regeln und Such-Hooks im Projekt,
   Git-Hooks halten den Graphen aktuell, `graphify-out/` in `.gitignore`.

Netz nur in Schritt 1 (pypi.org). Graphify selbst arbeitet lokal; nie API-Schlüssel fremder Anbieter setzen
(GEMINI_API_KEY, OPENAI_API_KEY …), sonst würde Graphify Texte dorthin schicken.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

GRAPHIFY_PACKAGE = "graphifyy"
GRAPHIFY_VERSION = "0.9.96"

ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",   # keine Telemetrie, Fehlerberichte, Auto-Updates
    "GRAPHIFY_QUERY_LOG_DISABLE": "1",                 # Graphify schreibt keine Fragen mit
}

BEGIN = "<!-- kushim:token-regeln:begin -->"
END = "<!-- kushim:token-regeln:end -->"
RULES = f"""{BEGIN}
# Sparsam arbeiten (Token)
- Gibt es `graphify-out/graph.json`: zuerst `graphify query "<Frage>"`, `graphify explain "<Begriff>"` oder
  `graphify path "<A>" "<B>"`, erst danach gezielt Dateien lesen.
- Nur die nötigen Zeilen lesen (Bereich angeben), Dateien nicht erneut lesen, die schon im Kontext sind.
- Lange Ausgaben filtern: bei Tests nur Fehlschläge (`pytest -q`, `| tail`), bei Logs `grep`/`head`, nie ganze Logs.
- Viel Ausgabe (Tests, Logs, breite Suchen) an einen Subagenten geben, der nur eine kurze Zusammenfassung zurückgibt.
- Kurz antworten, keine Dateiinhalte oder Diffs wiederholen, nichts zusammenfassen, was der Nutzer gerade gesehen hat.
- Vor großen Erkundungen nachfragen, wenn die Aufgabe unklar ist; konkrete Suche statt Rundumschau.
- Keine Daten nach außen: keine Web-Recherche oder Konnektoren ohne ausdrückliche Bitte des Nutzers.

# Compact instructions
Beim Zusammenfassen behalten: Entscheidungen des Nutzers, offene Aufgaben, geänderte Dateien, Testergebnisse.
Weglassen: Erkundungsausgaben, gelesene Dateiinhalte, alte Fehlversuche.
{END}"""


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    dst = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, dst)
    return dst


def merge_settings(data: dict) -> dict:
    """Trägt die Umgebungsvariablen ein; alles andere bleibt, wie es ist."""
    out = dict(data)
    env = dict(out.get("env") or {})
    env.update(ENV)
    out["env"] = env
    return out


STATUSLINE_SCRIPT = Path(__file__).resolve().with_name("statusline.py")


def statusline_command(python: str = sys.executable, script: Path = STATUSLINE_SCRIPT) -> str:
    return f'"{python}" -I "{script}"'


def merge_statusline(data: dict, command: str) -> tuple[dict, str]:
    """Trägt die kushim-Statuszeile ein. Eine fremde Statuszeile bleibt unberührt. Gibt (Daten, Meldung) zurück."""
    current = data.get("statusLine")
    if current and not (isinstance(current, dict) and "statusline.py" in str(current.get("command", ""))):
        return dict(data), "Es gibt schon eine eigene Statuszeile; sie bleibt unverändert."
    out = dict(data)
    out["statusLine"] = {"type": "command", "command": command}
    return out, "Statuszeile: Modell, Kontext-Füllstand, Abo-Grenzen."


TEST_HOOK_SCRIPT = Path(__file__).resolve().with_name("trim_test_output.py")


def merge_test_hook(data: dict, command: str) -> dict:
    """Trägt den PreToolUse-Hook für Bash ein, der lange Testausgaben kürzt. Ersetzt nur den eigenen Eintrag."""
    out = dict(data)
    hooks = dict(out.get("hooks") or {})
    groups = [g for g in (hooks.get("PreToolUse") or []) if isinstance(g, dict)
              and not any("trim_test_output.py" in str(h.get("command", "")) for h in g.get("hooks") or [] if isinstance(h, dict))]
    groups.append({"matcher": "Bash", "hooks": [{"type": "command", "command": command}]})
    hooks["PreToolUse"] = groups
    out["hooks"] = hooks
    return out


def merge_rules(text: str) -> str:
    """Ersetzt den eigenen Block zwischen den Markierungen oder hängt ihn an. Fremder Text bleibt unberührt."""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        return head + RULES + tail
    sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + RULES + "\n"


def ensure_gitignore(text: str, entry: str = "graphify-out/") -> str:
    lines = text.splitlines()
    if entry in (l.strip() for l in lines):
        return text
    return text + ("" if not text or text.endswith("\n") else "\n") + entry + "\n"


def write_json(path: Path, data: dict, dry: bool) -> None:
    if dry:
        print(f"  [dry-run] {path} würde geschrieben")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    b = backup(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {path} aktualisiert" + (f" (Sicherung: {b.name})" if b else ""))


def write_text(path: Path, text: str, dry: bool) -> None:
    if dry:
        print(f"  [dry-run] {path} würde geschrieben")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    b = backup(path)
    path.write_text(text, encoding="utf-8")
    print(f"  {path} aktualisiert" + (f" (Sicherung: {b.name})" if b else ""))


def graphify_exe() -> str | None:
    return shutil.which("graphify")


def run(cmd: list[str], dry: bool, cwd: Path | None = None) -> None:
    print("  $ " + " ".join(cmd))
    if not dry:
        env = {k: v for k, v in os.environ.items() if k not in _FOREIGN_KEYS}
        env.update(ENV)
        subprocess.run(cmd, check=True, cwd=cwd, env=env)


# Schlüssel fremder KI-Anbieter: Graphify würde sie automatisch benutzen und Texte dorthin schicken.
_FOREIGN_KEYS = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "KIMI_API_KEY", "MOONSHOT_API_KEY",
                 "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"}


def install_graphify(dry: bool) -> None:
    print("== Graphify installieren")
    run([sys.executable, "-m", "pip", "install", "--user", "--upgrade", f"{GRAPHIFY_PACKAGE}=={GRAPHIFY_VERSION}"], dry)
    exe = graphify_exe() or "graphify"
    run([exe, "install"], dry)                       # Skill nach ~/.claude/skills/graphify, kurzer Eintrag in CLAUDE.md
    if not dry and graphify_exe() is None:
        print("  Hinweis: `graphify` liegt nicht im PATH. Den Scripts-Ordner von `py -m site --user-base` zum PATH hinzufügen.")


def setup_global(dry: bool, statusline: bool = False, test_hook: bool = False) -> None:
    base = claude_dir()
    print(f"== Einstellungen ({base})")
    sp = base / "settings.json"
    data = merge_settings(json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {})
    if statusline:
        data, note = merge_statusline(data, statusline_command())
        print(f"  {note}")
    if test_hook:
        data = merge_test_hook(data, statusline_command(script=TEST_HOOK_SCRIPT))
        print("  Hook: lange Testausgaben (pytest, npm test, vitest, cargo test) werden auf Fehler und Ergebnis gekürzt.")
    write_json(sp, data, dry)
    print("== Token-Regeln")
    cp = base / "CLAUDE.md"
    write_text(cp, merge_rules(cp.read_text(encoding="utf-8") if cp.exists() else ""), dry)


def setup_project(project: Path, dry: bool) -> None:
    project = project.resolve()
    if not (project / ".git").exists():
        raise SystemExit(f"{project} ist kein Git-Repository")
    print(f"== Projekt {project}")
    exe = graphify_exe() or "graphify"
    run([exe, "update", "."], dry, cwd=project)                 # Code-Graph, lokal, ohne KI
    run([exe, "claude", "install", "--project"], dry, cwd=project)   # Regeln in CLAUDE.md + Such-Hooks
    run([exe, "hook", "install"], dry, cwd=project)             # Git-Hooks: Graph nach Commits aktualisieren
    gi = project / ".gitignore"
    write_text(gi, ensure_gitignore(gi.read_text(encoding="utf-8") if gi.exists() else ""), dry)
    html = project / "graphify-out" / "graph.html"             # lädt beim Öffnen eine Bibliothek von unpkg.com
    if html.exists() and not dry:
        html.unlink()
        print("  graphify-out/graph.html entfernt (würde beim Öffnen Code aus dem Netz laden)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", type=Path, help="Projekt zusätzlich mit Graphify verbinden")
    ap.add_argument("--skip-install", action="store_true", help="Graphify nicht installieren (schon vorhanden)")
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, nichts ändern")
    ap.add_argument("--statusline", action="store_true", help="Statuszeile (Modell, Kontext, Abo-Grenzen) eintragen")
    ap.add_argument("--test-hook", action="store_true", help="Hook eintragen, der lange Testausgaben kürzt")
    a = ap.parse_args(argv)
    if not a.skip_install:
        install_graphify(a.dry_run)
    setup_global(a.dry_run, statusline=a.statusline, test_hook=a.test_hook)
    if a.project:
        setup_project(a.project, a.dry_run)
    print("Fertig. Claude Code neu starten, damit die Einstellungen greifen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
