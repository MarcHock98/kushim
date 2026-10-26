"""Statische Prüfung der Claude-Code-Konfiguration im Projekt: Skills, Agents und MCP-Server schicken nichts nach außen.

Nutzerwunsch 2026-10-26: Einzige Verbindung nach außen ist Claude Code selbst zu Anthropic. MCP-Server laufen nur lokal
(stdio, Befehl auf dem PC), Skills und Agents nutzen weder Web-Werkzeuge noch Konnektoren (Slack, Atlassian, Trello, Docs).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE = ROOT / ".claude"
# Werkzeuge, die Daten nach außen tragen. Skills/Agents dürfen sie nur in einer Verbotsregel nennen (Zeile mit "kein"/"nie").
EGRESS_TOOLS = re.compile(r"WebSearch|WebFetch|mcp__(?!github)\w+|slack_\w+", re.IGNORECASE)
FORBIDDING = re.compile(r"\b(kein|keine|nie|nicht|verboten|no)\b", re.IGNORECASE)
CONNECTORS = {"mcp__Slack", "mcp__Atlassian", "mcp__Trello", "mcp__Claude_Docs"}


def _instruction_files():
    return sorted([*CLAUDE.glob("skills/**/*.md"), *CLAUDE.glob("agents/*.md")])


def test_skills_and_agents_use_no_egress_tools():
    bad = []
    for f in _instruction_files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if EGRESS_TOOLS.search(line) and not FORBIDDING.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    assert not bad, "Skills/Agents nennen Werkzeuge mit Außenwirkung:\n" + "\n".join(bad)


def test_agents_have_no_web_tools():
    for f in CLAUDE.glob("agents/*.md"):
        head = f.read_text(encoding="utf-8").split("---")[1]
        tools = re.search(r"^tools:(.*)$", head, re.MULTILINE)
        assert tools is None or not EGRESS_TOOLS.search(tools.group(1)), f.name
        assert tools is not None, f"{f.name}: ohne 'tools:' erbt der Agent alle Werkzeuge, auch Web und Konnektoren"


def test_project_mcp_servers_are_local_only():
    cfg = ROOT / ".mcp.json"
    if not cfg.exists():
        return
    servers = json.loads(cfg.read_text(encoding="utf-8")).get("mcpServers", {})
    for name, s in servers.items():
        assert s.get("type", "stdio") == "stdio" and "url" not in s, f"{name}: nur lokale stdio-Server erlaubt"


def test_settings_keep_egress_switches():
    s = json.loads((CLAUDE / "settings.json").read_text(encoding="utf-8"))
    assert s["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"      # keine Telemetrie, Fehlerberichte, Auto-Updates
    assert s.get("enableAllProjectMcpServers") is False
    assert CONNECTORS <= set(s["permissions"]["deny"])
    assert not s["permissions"].get("allow"), "Erlaubnisse gehören nicht in die Projekt-Einstellungen"
