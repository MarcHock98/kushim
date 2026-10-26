"""Hook für Claude Code: lange Testausgaben auf Fehlschläge und Ergebnis kürzen (spart Kontext, Roadmap Z5).

Zwei Rollen in einer Datei:
- Ohne Argument ist es ein `PreToolUse`-Hook für das Bash-Werkzeug. Ist der Befehl ein einfacher Testlauf (pytest, npm test,
  vitest, cargo test) ohne eigene Umleitung, gibt es ihn umgeschrieben zurück: Ausgabe durch den Filter, Exit-Code bleibt
  (`set -o pipefail`). Sonst gibt es nichts aus und Claude Code führt den Befehl unverändert aus. Es setzt nie eine
  Freigabe (`permissionDecision`): Rückfragen und Regeln des Nutzers bleiben, wie sie sind.
- Mit `--filter` liest es die Testausgabe von stdin. Kurze Ausgaben bleiben ganz; lange werden auf Fehlerzeilen und das
  Ende gekürzt, mit einem Hinweis, wie viel weggelassen wurde.

Format laut eingebauter Beschreibung von Claude Code 2.1.310 (`hookSpecificOutput.updatedInput`). Nur Standardbibliothek,
kein Netz, schreibt keine Dateien. Eingerichtet wird es mit `py scripts\\claude_setup.py --test-hook`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

KEEP_ALL = 80            # bis zu so vielen Zeilen bleibt die Ausgabe ganz
MAX_HITS = 120           # höchstens so viele Fehlerzeilen
TAIL = 15                # das Ende (Zusammenfassung) bleibt immer

RUNNER = re.compile(r"^\s*(?:\S*python(?:3)?(?:\.exe)?\s+-m\s+pytest|\S*pytest(?:\.exe)?|npm\s+(?:run\s+)?test|npx\s+vitest"
                    r"|cargo\s+test)(?:\s|$)", re.I)
UNSAFE = re.compile(r"[|<>;&`\n]|\$\(")       # schon umgeleitet oder verkettet: nicht anfassen
IMPORTANT = re.compile(r"FAILED|ERROR|Error|Traceback|assert|failed|passed|panicked|✗|×|^E\s", re.M)


def is_simple_test_run(command: str) -> bool:
    return bool(RUNNER.match(command)) and not UNSAFE.search(command)


def wrap(command: str, python: str = sys.executable, script: Path = Path(__file__).resolve()) -> str:
    return f'set -o pipefail; {command} 2>&1 | "{Path(python).as_posix()}" -I "{script.as_posix()}" --filter'


def hook_reply(event: object, python: str = sys.executable, script: Path = Path(__file__).resolve()) -> dict | None:
    if not isinstance(event, dict) or event.get("tool_name") != "Bash":
        return None
    tool_input = event.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not is_simple_test_run(command):
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "updatedInput": {**tool_input, "command": wrap(command, python, script)}}}


def trim(lines: list[str]) -> list[str]:
    if len(lines) <= KEEP_ALL:
        return lines
    head = len(lines) - TAIL
    hits = [l for l in lines[:head] if IMPORTANT.search(l)][:MAX_HITS]
    note = f"[gekürzt: {len(lines)} Zeilen, gezeigt werden Fehlerzeilen ({len(hits)}) und die letzten {TAIL}]"
    return [note, *hits, "...", *lines[head:]]


def _out(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8"))      # Claude Code liest UTF-8, Windows-Pipes wären cp1252
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    if argv[:1] == ["--filter"]:
        _out("\n".join(trim(raw.splitlines())) + "\n")
        return 0
    try:
        reply = hook_reply(json.loads(raw or "{}"))
    except ValueError:
        reply = None
    if reply is not None:
        _out(json.dumps(reply, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
