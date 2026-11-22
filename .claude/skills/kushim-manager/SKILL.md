---
name: kushim-manager
description: Use when a kushim work package should be built with several agents in parallel and Claude acts as manager (plan, decide, distribute, check, merge). Gives the cut into packages, model and effort per agent, brief templates, the review chain (test-manager, safety-auditor, browser) and the merge steps.
---

# kushim-Manager (Arbeitspaket mit Agenten)

Du planst, entscheidest, verteilst und prüfst. Du schreibst selbst nur Kleinigkeiten (ein, zwei Zeilen), Zusammenführungen und die
Dokumente. Es gelten alle Grenzen aus `kushim-routine` (kein Push, kein Netz, keine MCP-Konnektoren, Sicherheitsregeln nicht lockern,
UI nur nach freigegebenem Plan, Branches und Worktrees nur auf Wunsch des Nutzers aufräumen).

## 1. Schneiden
- Ein Paket je Agent, **keine zwei Agenten ändern dieselbe Datei**. Typischer Schnitt für einen neuen Baustein der Bühne:
  1. Python: `stage/schema.py`, `channel/server.py`, `tests/test_stage.py` (Agent `stage-schema-dev`).
  2. Reine Rechen- oder Anordnungslogik der Oberfläche als eigene neue Dateien in `ui/src/lib/` mit Tests (allgemeiner Agent).
  3. Ansicht: neue Komponente, `stage.ts`, `ViewCard.tsx`, `mock.ts`, `app.css`, Tests (Agent `ui-builder`), erst wenn 2 steht.
- 1 und 2 laufen gleichzeitig. Dafür gibst **du den Vertrag vor**: Feldnamen, Einheiten, Grenzen, Standardwerte, Zählweise (ab 0).
  Meldet der Schema-Agent ergänzte Standardwerte, reichst du sie dem UI-Agenten nach (`SendMessage`).
- Reine Pläne (kein Code) macht der Agent `Plan`; du speicherst den Text als `docs/ui-<paket>-plan.md`.

## 2. Modell und Aufwand
| Aufgabe | Agent | Modell | Aufwand |
|---|---|---|---|
| Schema, sicherheitsnah | `stage-schema-dev` | opus | mittel |
| Algorithmus (Anordnung, Physik) | general-purpose | opus | mittel bis hoch |
| Ansicht mit Bedienung | `ui-builder` | opus | hoch |
| Detailplan | `Plan` | opus | hoch |
| Testfälle abgleichen | `test-manager` | sonnet | mittel |
| Sicherheitsprüfung | `safety-auditor` | sonnet | – |
| Mechanische Test-Ergänzung in einer Datei | general-purpose | sonnet | niedrig |

## 3. Auftrag an einen schreibenden Agenten (immer enthalten)
- Was zuerst zu lesen ist (Plan-Abschnitte, Nachbardateien, `tests/test_no_egress.py`, `tests/test_ui_rules.py`).
- Genau welche Dateien er anfassen darf, und welche ausdrücklich nicht.
- Der Vertrag (Felder, Grenzen, Standardwerte) und die Liste der Tests.
- Feste Regeln: eigener Worktree (`isolation: worktree`), dort `git switch -c routine/<paket>`; nie im Hauptordner arbeiten oder
  Branches wechseln, nie pushen; CRLF und Edit-Werkzeug; kein Netz außer `npm ci`; Python immer mit `PYTHONPATH=src` und dem
  Interpreter aus dem Hauptordner; node-Befehle einzeln als `cd ui && ...`; Commit nur bei grünen Tests.
- Verlangter Bericht: Branch, Commit, Worktree, Testzahlen, Abweichungen vom Auftrag mit Grund, was nicht geprüft ist. Bei
  Bibliotheken zusätzlich die exportierten Signaturen wörtlich.

## 4. Prüfkette vor jedem Merge
1. **`test-manager`** je fertigem Branch (Plan-Zeile gegen Test). Lücken als EIN Paket je Datei zurück an den Agenten, der sie
   gebaut hat (`SendMessage`, er hat den Kontext); bei großem Kontext lieber ein frischer kleiner Agent im selben Worktree.
   Ist der Agententyp nicht aufrufbar: allgemeiner Agent, der `.claude/agents/test-manager.md` liest.
2. **`safety-auditor`**: Schema immer, Oberfläche einmal über den zusammengeführten Stand. Auftrag mit „kein `git switch`,
   `checkout`, `stash`“. Bei „nicht freigegeben“: Funde beheben lassen, **denselben** Auditor erneut fragen, erst dann mergen.
   Kommt nach dem Audit noch Code dazu, im Bericht an den Nutzer sagen, was nicht mehr vom Audit gedeckt ist.
3. **Selbst nachmessen**: die Zahlen der Agenten sind Berichte. Nach dem Merge die Suiten im Hauptordner selbst laufen lassen.
4. **Browser**: Skill `kushim-ui-check`.

## 5. Zusammenführen
- UI-Branches erst auf einem gemeinsamen Branch `routine/<paket>-ui` von `master` zusammenführen (`git merge --no-ff`), dort testen
  und ansehen, dann nach `master`. Vor `npm ci` im Hauptordner den Dev-Server stoppen (`preview_stop`).
- Reihenfolge: Schema zuerst nach `master` (nach Freigabe), dann die Oberfläche.
- Danach: `docs/routine-state.md` (Eintrag, offene Fragen), Plan-Dokument („gebaut am …“), `docs/CHANGELOG-routine.md`, wenn Skills
  oder Agenten geändert wurden.

## 6. Entscheiden und berichten
- Kleine, umkehrbare Fragen ohne Sicherheits-, Kosten- oder Datenbezug entscheidest du (strenger ist erlaubt) und nennst sie dem
  Nutzer. Alles andere ist eine Frage an ihn.
- Nach jeder Fertigmeldung ein kurzer Stand: was fertig ist (mit „laut Agent“ oder „selbst gemessen“), was läuft, was nicht geprüft ist.
- Im Loop: Agenten wecken den Loop selbst; `ScheduleWakeup` nur als Rückfall (1800 s).
