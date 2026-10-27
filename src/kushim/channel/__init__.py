"""Brücke zu Claude Code (Roadmap v2 Phase B): ein Channel-Server, den Claude Code selbst startet (MCP über stdio).

kushim gibt erkannte Befehle über `POST 127.0.0.1` (mit Token) an den Channel, der sie in die laufende Sitzung schiebt.
"""
