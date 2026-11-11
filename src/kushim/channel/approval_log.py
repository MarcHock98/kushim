"""Freigabe-Protokoll (Roadmap v2 C5): jede Freigabe-Entscheidung lokal im verschlüsselten Vault (Audit-Tabelle).

Ein Eintrag: Zeit (vom Vault), was (die gesprochene Kurzbeschreibung), Werkzeug, Ergebnis, Quelle (Stimme/Oberfläche),
Sprecher-Prüfung (verifiziert, stark, Score). Nie Audio, nie die rohe Eingabe von Claude. Fehler beim Schreiben werden
geschluckt (das Protokoll darf nie eine Antwort verhindern) und nur gezählt.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .server import clean_text

EVENT = "freigabe"
MAX_DETAIL = 1000
_TEXT_FIELDS = {"request_id": 100, "tool": 80, "what": 240, "result": 40, "source": 20, "reason": 120}
_FLAG_FIELDS = ("verified", "strong")


def sanitize(entry: dict[str, Any]) -> dict[str, Any]:
    """Nur bekannte Felder, Texte eine Zeile und begrenzt, Zahlen endlich und gerundet."""
    out: dict[str, Any] = {}
    for key, limit in _TEXT_FIELDS.items():
        v = entry.get(key)
        if isinstance(v, str) and v:
            out[key] = clean_text(v)[:limit]
    for key in _FLAG_FIELDS:
        if isinstance(entry.get(key), bool):
            out[key] = entry[key]
    score = entry.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool) and -1.0 <= float(score) <= 1.0:
        out["score"] = round(float(score), 3)
    return out


class ApprovalLog:
    """Aufrufbar als `on_decision`. `opener()` liefert einen Vault (je Eintrag geöffnet und geschlossen: thread-sicher)."""

    def __init__(self, opener: Callable[[], Any], on_fail: Callable[[], None] = lambda: None):
        self.opener, self.on_fail = opener, on_fail     # on_fail: Hinweis, damit ein Verlust nicht still bleibt
        self.failures = 0

    def __call__(self, entry: dict[str, Any]) -> None:
        detail = json.dumps(sanitize(entry), ensure_ascii=False, sort_keys=True)[:MAX_DETAIL]
        try:
            store = self.opener()
            try:
                store.audit(EVENT, detail)
            finally:
                store.close()
        except Exception:                           # noqa: BLE001 (nie die Antwort verhindern)
            self.failures += 1
            try:
                self.on_fail()
            except Exception:                       # noqa: BLE001
                pass


def recent(store: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Die letzten Protokoll-Einträge (älteste zuerst) mit Zeit `ts`; kaputte Einträge werden übersprungen."""
    rows = []
    for ts, event, detail in store.audit_tail(200):
        if event != EVENT:
            continue
        try:
            data = json.loads(detail)
        except ValueError:
            continue
        if isinstance(data, dict):
            rows.append({"ts": ts, **sanitize(data)})
    return rows[-max(1, int(limit)):]


RESULTS_DE = {"asked": "gefragt", "allowed": "erlaubt", "not_sent": "nein gesagt", "weak": "Stimme zu unsicher",
              "no_voice": "fremde Stimme", "blocked": "gesperrt", "timeout": "keine Antwort", "replaced": "überholt",
              "terminal_only": "nur Terminal", "gone": "schon erledigt", "kill": "Notaus", "denied": "abgelehnt"}


def format_row(row: dict[str, Any]) -> str:
    """Eine Zeile für das Terminal, z. B. „2026-11-11 14:03  Stimme  erlaubt  (0.84, stark)  Claude möchte …“."""
    import time
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(row.get("ts", 0)))
    source = {"voice": "Stimme", "ui": "Oberfläche"}.get(row.get("source", ""), row.get("source", "?"))
    result = RESULTS_DE.get(row.get("result", ""), row.get("result", "?"))
    voice = ""
    if "score" in row:
        voice = f"  ({row['score']:.2f}{', stark' if row.get('strong') else ''})"
    reason = f"  [{row['reason']}]" if row.get("reason") else ""
    return f"{when}  {source:<10} {result:<18}{voice}  {row.get('what', '')}{reason}"
