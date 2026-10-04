# Plan: Claude über die Claude CLI steuern (Modus C), nur in freigegebenen Ordnern

Stand 2026-10-04. Wunsch des Nutzers: "nutze Claude um das Projekt weiterzuentwickeln" per Sprache; Claude soll **nur in angegebenen, in der UI
einstellbaren Ordnern** arbeiten; kushim soll Claude **steuern** können (starten, beobachten, stoppen, Ergebnis ansehen). Claude läuft über die
installierte Claude CLI. Ist der Nutzer dort angemeldet (`claude auth status`: `loggedIn: true`, bei dir claude.ai-Abo), braucht kushim **keinen API-Schlüssel**
und fasst keine Zugangsdaten an.

Geprüft am 2026-10-04 (lokal, `claude --help`, CLI 2.1.289): `-p/--print` (ohne Rückfragen), `--permission-mode` (acceptEdits, auto, bypassPermissions, manual,
dontAsk, plan), `--permission-prompts none` (alles, was fragen müsste, wird automatisch abgelehnt), `--allowedTools`/`--disallowedTools`, `--max-budget-usd`,
`--output-format stream-json`, `-w/--worktree [name]` (eigener Git-Worktree), `--append-system-prompt`, `--no-session-persistence`.

## Gefahren (ehrlich)
Claude Code kann Dateien ändern und Befehle ausführen. Über kushim per Sprache gestartet ist das mächtig und riskant:
1. **Selbstveränderung:** Im Ordner `kushim` könnte Claude die Sicherheitsregeln, die Egress-Sperre oder die Skills verändern ("Regeln ändert nur der Nutzer").
2. **Abfluss:** Claude liest Dateien und sendet Auszüge an Anthropic (das ist bei Modus C unvermeidlich und wird beim Einschalten klar gesagt).
3. **Fremde Befehle:** Eine falsch erkannte oder nachgesprochene Stimme darf so etwas nie starten.
4. **Ergebnis als Anweisung:** Was Claude ausgibt, darf kushim nie zu Aktionen veranlassen.
5. **Unbegrenzt laufen:** Zeit, Kosten, mehrere Läufe, Weiterlaufen nach Notaus.

## Sicherheitsmodell
1. **Tool `claude.code` ist standardmäßig aus** und nur verfügbar, wenn **beides** gilt: Modus C ist vom Nutzer eingeschaltet (`[privacy] claude_enabled = true`), die CLI ist
   gefunden und angemeldet, und mindestens ein Ordner ist freigegeben. Einschalten nur in der UI/CLI mit Bestätigung, nie per Sprache.
2. **Ordner-Freigabe (`[claude] folders`)**: Liste `name|pfad` in `config.toml`, in der UI bearbeitbar (Hinzufügen nur mit Bestätigung, Entfernen sofort). Ein Ordner muss
   absolut, vorhanden, ein **Git-Repository** und aufgelöst (keine Verknüpfung nach außen) sein. **Verboten:** Laufwerkswurzel, Benutzerordner selbst, Windows/Programme,
   AppData, `.ssh`, `.claude` des Benutzers, der Vault-Ordner und alles, was ihn enthält oder darin liegt. Claude startet immer **im** freigegebenen Ordner, nie darüber.
3. **Isolation per Worktree:** Jeder Lauf nutzt `claude -w <name>`, also einen **eigenen Branch und Arbeitsordner**. `master`/der aktuelle Stand des Nutzers bleibt unberührt.
   kushim **mergt nie** und pusht nie; das entscheidet der Nutzer nach der Prüfung.
4. **Berechtigungen:** `-p`, `--permission-mode acceptEdits`, `--permission-prompts none` (nichts außerhalb der Liste läuft), `--allowedTools` nur Lesen/Bearbeiten und eine feste Liste
   harmloser Befehle (git status/diff/log/add/commit, pytest), `--disallowedTools` u. a. `git push`, `merge`, `checkout`, `reset`, `rebase`, `worktree`, Löschen, `curl`, `wget`, `pip install`,
   Web-Werkzeuge. **Nie** `bypassPermissions` oder `--dangerously-skip-permissions` (Test sperrt das).
5. **Geschützte Dateien:** Nach dem Lauf prüft kushim den Diff gegen den Ausgangsstand. Änderungen an `safety/`, `net/`, `privacy.py`, `tests/test_no_egress.py`, `.claude/`, `CLAUDE.md`
   werden **rot markiert** ("sicherheitsrelevant, bitte prüfen") und nie automatisch übernommen. Dazu fester Systemzusatz (`--append-system-prompt`): kein Push, kein Merge, keine Geheimnisse,
   Sicherheitsregeln nicht abschwächen, Tests laufen lassen, lokal committen, am Ende ehrlich berichten.
6. **Wer startet:** nur die **stark verifizierte** Stimme oder die UI/CLI. Start ist immer `ASK`: exakte Vorschau (Ordner, genauer Auftragstext, Rechteprofil, Zeit- und Budgetgrenze, Branch),
   Freigabe einmalig und hash-gebunden (`ApprovalQueue`), per Klick oder gesprochenem "ja" (stark verifiziert). Läuft über `EgressGate` (Modus C, nur auf ausdrücklichen Befehl, Audit).
7. **Begrenzen:** ein Lauf gleichzeitig, `--max-budget-usd`, harte Zeitgrenze (Standard 45 min), `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL` und alle `KUSHIM_*`/Geheimnis-Variablen werden **aus der
   Umgebung entfernt** (es zählt nur die Anmeldung des Nutzers, nie ein fremder Schlüssel oder Umleiter).
8. **Notaus** beendet den Claude-Prozess samt Kindern sofort (`kill_tree`). Stoppen per Sprache ist immer erlaubt (auch ohne Verifikation), wie der Notaus.
9. **Ausgabe ist `Untrusted`:** Claudes Text wird angezeigt und vom lokalen Modell über den **werkzeuglosen** Pfad zusammengefasst; er löst in kushim nie eine Aktion, Suche oder einen Claude-Start aus.
10. **Audit:** Start/Ende/Stopp mit Ordnername, Länge des Auftrags, Exit-Code (nie Inhalt oder Pfade nach außen).

## Steuerung (Sprache, UI, CLI)
| Befehl | Sprache (Beispiel) | Verifikation | Wirkung |
|---|---|---|---|
| Starten | "Nutze Claude um das Projekt kushim weiterzuentwickeln" (optional "… und baue den Timer") | stark + Freigabe | Worktree, Lauf im Hintergrund |
| Status | "Was macht Claude?" | verifiziert | Zustand, Dauer, letzte Schritte (zusammengefasst) |
| Stoppen | "Stopp Claude" | keine nötig | beendet den Lauf, Branch bleibt |
| Ergebnis | "Was hat Claude gemacht?" | verifiziert | Zusammenfassung, geänderte Dateien, rote Markierung bei geschützten Dateien |
| Antworten | "Antwort an Claude: nimm Variante zwei" / "ja" / "nein" | verifiziert (Rechte: stark) | nächster Zug derselben Sitzung (`--resume`) |
| Weitermachen | "Mach mit dem ersten Vorschlag weiter" | stark + Freigabe | nächster Zug mit dem gewählten nächsten Schritt |
| Übernehmen | **nur UI/CLI** (`kushim claude review`, danach selbst mergen) | Nutzer | kushim mergt nie selbst |
Ohne Auftrag nutzt kushim einen festen Standardauftrag: "Nimm den nächsten offenen Punkt der Roadmap bzw. README, arbeite auf diesem Branch, teste, committe lokal, pushe nicht."

## Rückfragen und Übersichten (Nutzerwunsch 2026-10-04)
kushim soll Rückfragen von Claude weitergeben und nach jedem Schritt eine kurze Übersicht geben: was getan wurde und was man als Nächstes tun kann.

**Ablauf in Zügen.** Ein Claude-Lauf (`claude -p`) ist ein **Zug**. Er endet mit einem Ergebnis (`stream-json`: `result` mit `session_id`, `is_error`, `permission_denials`, Kosten).
Die Sitzung bleibt gespeichert (kein `--no-session-persistence`); der nächste Zug ist `claude -p "<Antwort des Nutzers>" --resume <session_id>`. So kann Claude fragen, kushim liest die
Frage vor, du antwortest per Sprache oder UI, und es geht weiter, ohne dass ein Terminal offen sein muss.

**Zwei Arten von Rückfragen:**
1. **Inhaltliche Frage:** Der feste Systemzusatz verlangt am Ende jeder Antwort einen Block `## Zusammenfassung` (höchstens 3 Sätze), `## Rückfrage` (leer oder genau eine kurze Frage) und
   `## Nächste Schritte` (höchstens 3 Stichpunkte). kushim liest die Frage vor ("Claude fragt: …").
2. **Verweigerte Berechtigung:** Wollte Claude etwas tun, das nicht erlaubt ist (`permission_denials`), fragt kushim: "Claude wollte <Befehl> ausführen. Für diese Sitzung erlauben?"
   Angeboten wird das **nur** für eine kleine Positivliste harmloser Erweiterungen (z. B. weitere Testbefehle). Gefährliches (push, merge, Löschen, Netzwerk-Werkzeuge, Rechteumgehung) wird nie angeboten
   und bleibt verweigert. Erlauben braucht die stark verifizierte Stimme oder einen Klick und gilt nur für diese Sitzung.

**Antwort des Nutzers = vertrauenswürdig, Claudes Text = `Untrusted`.** Deine Antwort geht als nächster Auftrag an Claude. Claudes Text dagegen wird nur vorgelesen/angezeigt, nie als Befehl
für kushim gelesen und löst nie selbst einen Zug, eine Freigabe oder ein Tool aus.

**Übersicht nach jedem Zug** (gesprochen höchstens 5 Zeilen, ausführlich in der UI), aus drei getrennten Quellen:
- **Getan** (laut Claude): seine Zusammenfassung, gekürzt und bereinigt. Fehlt das Format, fasst das lokale Modell über den werkzeuglosen Pfad zusammen und kennzeichnet es.
- **Fakten von kushim** (unabhängig von Claudes Aussagen, aus Git): Branch, Zahl geänderter und neuer Dateien und Zeilen, **geschützte Dateien rot**, ob uncommittete Änderungen übrig sind, Dauer, Kosten.
  Aussagen wie "Tests grün" stehen als "laut Claude", nie als Tatsache.
- **Nächste Schritte:** Claudes Vorschläge plus feste Optionen von kushim: Rückfrage beantworten, mit Vorschlag 1/2/3 weitermachen, Änderungen ansehen, **übernehmen (nur du, UI/CLI)**, verwerfen
  (Worktree löschen), stoppen.

## Bausteine
- `claude_cli/folders.py` (Ordner prüfen, Namen auflösen), `claude_cli/command.py` (Argumente, Umgebung, Vorschau, Rechteprofil), `claude_cli/session.py` (ein Lauf: Start, Status, Stopp, Notaus,
  Zeitgrenze, Ausgabe-Puffer, Zustandsdatei `run/claude-session.json`), `claude_cli/review.py` (Diff, geschützte Dateien), `claude_cli/report.py` (Zug-Ergebnis lesen: Zusammenfassung, Rückfrage, nächste Schritte, verweigerte Berechtigungen; Übersicht aus Claude-Text plus Git-Fakten).
- Registry-Tool `claude.code` (Modus C), API-Typen `claude.folders.*`, `claude.status`, `claude.stop`, `claude.start` (ASK), `claude.review`; CLI `kushim claude ...`; Sprachbefehle analog `wake_commands`.
- Tests mit gefälschtem Prozess (kein echter Claude-Aufruf in Tests).

## Offene Entscheidungen des Nutzers
1. ~~Unbeaufsichtigt oder sichtbar?~~ Entschieden durch den Nutzerwunsch: Hintergrund in Zügen, Rückfragen und Übersichten über kushim (siehe oben). Ein sichtbares Terminal bleibt optional (`kushim claude attach`).
2. **Rechteprofil:** Ist die Liste der erlaubten Befehle (git status/diff/log/add/commit, pytest) richtig, oder soll mehr/weniger erlaubt sein?
3. **Budget und Zeit:** `--max-budget-usd` (Standard 2) und 45 min Zeitgrenze passend? (Bei Abo-Anmeldung zählt vor allem dein Nutzungskontingent.)
4. **Ordner:** Welche Projekte (Alias und Pfad) sollen freigegeben werden? Der Ordner `kushim` selbst nur mit der Auflage "geschützte Dateien rot markieren, nie automatisch übernehmen".
