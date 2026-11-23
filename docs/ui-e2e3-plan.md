# Plan E2 und E3: kleines Fenster und Setup-Assistent

Stand 2026-11-23. Roadmap Phase E, nach E1 („UI bleibt“, 2026-11-12). **Gebaut am 2026-11-23 nach allen Empfehlungen aus Abschnitt 9.** Ziel: Das vorhandene Fenster
bekommt einen **kompakten Modus** (Avatar, letzter Befehl, Freigabe, NOTAUS, Verbrauch). Dazu kommt ein **Setup-Assistent** in der
Oberfläche (Systemcheck, Mikrofon, Wake Words, Claude-Anmeldung, Arbeitsordner).
E2 und E3 brauchen **keinen neuen Netzzugang**, **kein neues Paket**, **keine Änderung an CSP oder Tauri-Rechten** (empfohlen).
Kein UI-Code vor deinem OK.

## 1. Was es schon gibt

| Teil | Stand | Datei |
|---|---|---|
| Fenster | ein Fenster 1000 x 760, Mindestgröße 360 x 480, CSP nur `self` und `ws://127.0.0.1:*`, Rechte nur `core:default` | `ui/src-tauri/tauri.conf.json`, `capabilities/default.json` |
| Rustteil | ein Befehl `api_info` (liest `run/api.json`), sonst nichts | `ui/src-tauri/src/main.rs` |
| Avatar | `Core3D.tsx` (three.js, Größe per `size`, ruht bei verdecktem Fenster), Ersatz `Avatar.tsx` (Canvas 2D) | `ui/src/components/` |
| Freigabe-Leiste | `PermissionBar.tsx`: exakter Text, Hash, Ablehnen mit Standardfokus, 700 ms Sperre, bei gekürztem Text nur Ablehnen; Backend `approvals.get/decide` | `App.tsx`, `api/approvals_api.py` |
| NOTAUS | Knopf oben rechts, Strg+Umschalt+K (nur wenn das Fenster den Fokus hat), Banner mit bestätigtem Aufheben | `KillButton.tsx`, `setup_api.py` (`safety.*`) |
| Letzter Befehl | `transcript.get` liefert `heard`, `reply`, `outcome` (nur mit `kushim talk --ui`); gezeigt nur in der Übersicht | `api/transcript_api.py`, `Transcript.tsx` |
| Verbrauch | nur die Statuszeile von Claude Code (`scripts/statusline.py`: Modell, Kontext %, 5h/7d %, Kosten falls vorhanden). Das Skript schreibt nichts, kushim sieht die Daten nicht | `scripts/statusline.py`, Roadmap Z4/D1 |
| Setup-Backend | `setup.status/skip/reopen/done`, Zustand in `run/setup-state.json`, vier Schritte (`system`, `audio_voice`, `wake_words`, `safety`), `kushim setup` (Text) | `setup/state.py`, `setup/status.py`, `api/setup_api.py` |
| Setup-Oberfläche | **fehlt ganz** (kein Aufruf von `setup.*` in `ui/src`) | |
| Geräteliste | `audio.list_devices()` gibt es, aber `_api_start` reicht sie nicht an `register_setup` weiter: `audio.devices` antwortet **immer „unavailable“** | `voice/audio.py`, `cli.py` Z. 258 |
| Systemcheck | `doctor.run_checks` (Pakete, Modelle, GPU, Notaus, Vault), `claude_checks` (installiert, Version ≥ 2.1.234, angemeldet über `claude auth status --json`, `AuthCache` 30 s) | `doctor.py`, `claude_cli/base.py` |
| Pegel | `kushim voice level [--apply]` (öffnet das Mikrofon selbst), `levels.suggest`; im Betrieb meldet `voice.state` den Pegel 0..1 | `cli.py`, `voice/levels.py`, `voice/statefile.py` |
| Wake Words | `wakeconfig.load/validate/save` (geprüft, atomar, höchstens 12, mindestens eines aktiv); gilt ab dem nächsten Start | `voice/wakeconfig.py`, `wakewords.toml` |
| Mikrofonwahl | nur `--mic`/`--out` je Start, **nirgends gespeichert** | `cli.py` (`start`, `talk`) |
| Arbeitsordner | `claude.folder_*` mit Vorschlag und `confirm`, Oberfläche `FolderManager.tsx` in der Übersicht | `api/folders_api.py` |

Hinweise aus dem Code: Eine Umgebungsvariable reicht nicht, um die kushim-Sitzung in der Statuszeile zu erkennen (`clean_env()` entfernt
alle `KUSHIM_*`). Fenster-Funktionen gehen über eigene Rust-Befehle ohne neue Tauri-Rechte (wie `api_info`). Ein globaler Hotkey
bräuchte ein neues Paket (`test_ui_rules.py` verbietet `tauri-plugin`).

## 2. Vorschlag: Schnitt

| Teil | Inhalt | Aufwand | Besonderheit |
|---|---|---|---|
| **E2a** | kompakter Modus: Avatar, Zustand, letzter Befehl, Freigabe, NOTAUS | mittel | zwei kleine Rust-Befehle, sonst CSS und React |
| **E3a** | Assistent mit Schritten, die nur lesen oder vorhandene Schreibwege nutzen: Systemcheck, Claude, Ordner, Sicherheit, Geräteliste | mittel | Fehler bei `audio.devices` beheben |
| **E3b** | schreibende Schritte: Mikrofon merken, Pegeltest mit Übernahme, Wake Words ändern und testen | mittel | neue API-Typen mit `confirm` |
| **E2b** | Verbrauch im Fenster | klein | braucht dein Ja zur Änderung an `scripts/statusline.py` |

Empfehlung: E2a, dann E3a, E3b, zuletzt E2b. E2b nur, wenn du Entscheidung 5 mit Ja beantwortest.

## 3. E2a: kompakter Modus

**Ein Fenster, zwei Größen** (Entscheidung 1). Ein Knopf „Klein“ im Kopf und Strg+Umschalt+M schalten um. Der Rustteil bekommt zwei
Befehle, die nur das eigene Fenster ändern: `set_compact(on)` (Größe, Mindestgröße, „immer im Vordergrund“ an oder aus, Entscheidung 2)
und `attention()` (Taskleiste blinkt). Eigene Befehle brauchen keine neuen Tauri-Rechte. Im Browser (Mock) schaltet nur eine CSS-Klasse um.

| Bereich | Inhalt im kleinen Fenster (etwa 400 x 200) |
|---|---|
| links | Kern klein (`Core3D` mit `size` um 72 px, Ersatz 2D wie bisher), Zustandswort darunter |
| Mitte | **letzter Befehl** („Du: …“) und erste Zeile der Antwort, gekürzt per CSS, ganzer Text als `title`; ohne Sprachdienst „Kein Sprachdienst“ |
| unten | Verbrauch (ab E2b), sonst nichts; nie erfundene Zahlen |
| rechts oben | **NOTAUS** in voller Größe (44 px, rot, ein Klick), daneben „Groß“ |

- **Freigabe im kleinen Fenster** (Entscheidung 4): Das Fenster wächst auf 420 x 640 und zeigt dieselbe `PermissionBar` mit dem
  **ganzen exakten Text**, mit denselben Regeln (Sperre 700 ms, Fokus auf Ablehnen, Esc lehnt ab, gekürzter Text nur Ablehnen). Die
  Taskleiste blinkt. Das Fenster **holt sich keinen Fokus**. Nach der Entscheidung zurück auf klein. Erlauben ohne den Text gibt es nicht.
- Notaus aktiv: Kopf rot, Banner „NOTAUS aktiv“ mit „Aufheben“ passt ins kleine Fenster.
- Bühne und Ansichten (`zeige`) bleiben im großen Fenster. Im kleinen steht nur „Neue Ansicht von Claude“ mit Knopf „Groß“.
- Der Hotkey wirkt **nur, wenn das Fenster den Fokus hat**, wie Strg+Umschalt+K heute (Entscheidung 3).

## 4. E2b: Verbrauch

Claude Code reicht die Statusdaten **nur an das Statuszeilen-Skript** weiter, nach jeder Antwort. kushim sieht sie heute nicht.

| Weg | Bewertung |
|---|---|
| A. `statusline.py` schreibt zusätzlich `run/usage.json`, **nur wenn** `session_id` gleich `run/claude-session.txt` ist; kushim liest es mit neuem Typ `usage.get` | Empfehlung. Andere Claude-Sitzungen schreiben nichts |
| B. kein Verbrauch im Fenster, Hinweis „Verbrauch: Statuszeile oder `/usage` im Claude-Fenster“ | sicher, aber E2 unvollständig |
| C. Claudes Verlaufsdateien (`~/.claude/projects/*.jsonl`) lesen | abgelehnt: enthält Gesprächstext, internes Format, fremde Dateien |

- Inhalt von `usage.json`: nur Modellname (≤ 40 druckbare Zeichen), Kontext %, 5h %, 7d %, Kosten falls geliefert, Zeitstempel.
  Atomar geschrieben, keine Token, keine Pfade.
- Anzeige: „Opus · Kontext 42 % · 5h 30 % · 7d 12 %“ und **„Stand 14:05“**; älter als 30 min gedämpft mit „veraltet“; ohne Datei
  der Hinweis aus Weg B. Die Werte ändern sich nur nach einer Antwort.
- Die Änderung an `scripts/statusline.py` und das Einrichten der Statuszeile (`claude_setup.py --statusline`, Roadmap Z4) brauchen **dein Ja**.

## 5. E3: Setup-Assistent

Erscheint beim Start, solange `first_start` gilt, später über „Einrichtung“ in der Sicherheitsansicht. Links die Schritte mit Status als
Wort, rechts der Inhalt, unten **Zurück / Überspringen / Weiter**. Beim Überspringen steht die Folge in einem Satz da. Nur im großen Fenster.

| Schritt | Was er zeigt | Was er ändern darf | Teil |
|---|---|---|---|
| 1 Systemcheck | `run_checks` plus `claude_checks` als Ampel mit Wort und Hinweis (neuer Typ `setup.checks`, nur lesen) | nichts; Vault: Hinweis „`kushim memory init` im eigenen Terminal“ (Entscheidung 7) | E3a |
| 2 Claude | installiert, Version, angemeldet (`AuthCache`, ein Aufruf je 30 s) | nichts; Anmelden oder Aktualisieren nur als Hinweis | E3a |
| 3 Mikrofon | Geräteliste (Fehler bei `audio.devices` behoben), Pegel live als Balken mit Zahl | Wahl merken in `config.toml` `[audio] mic/out` (Entscheidung 6); Pegeltest mit Vorschlag, „Übernehmen“ schreibt über `wakeconfig.save` (`confirm`) | E3a Liste, E3b Rest |
| 4 Wake Words | Liste aus `wakewords.toml` mit Schaltern, Wort hinzufügen oder entfernen | nur `wakewords.toml` über `wakeconfig.save` (`confirm`); Test „Sag jetzt ein Wake Word“ | E3b |
| 5 Arbeitsordner | vorhandener `FolderManager` | nur über `claude.folder_*`, wie heute | E3a |
| 6 Sicherheit | Grundregeln, wo NOTAUS ist, Strg+Umschalt+K, Freigaben nur im Terminal oder in der Leiste | nur `setup-state.json` („verstanden“); kein echter Notaus (Entscheidung 8) | E3a |

- Messung und Test laufen im Sprachprozess (`kushim talk --ui`), der das Mikrofon ohnehin hält: kein zweiter Zugriff aufs Mikrofon.
  Für den Wake-Word-Test bekommt `voice-state.json` einen Zähler und den Namen des zuletzt erkannten Worts (nur Name, kein Audio).
- Änderungen an Gerät, Pegel oder Wake Words gelten ab dem nächsten `kushim start`; das steht beim Speichern im Fenster.
- `setup/status.py` bekommt die Schritte `claude` und `folder`; der Schlüssel `audio_voice` bleibt.
- Bei aktivem Notaus sind alle schreibenden Setup-Typen gesperrt.

## 6. Sicherheit

- **Kein neuer handelnder Code.** Der kompakte Modus ändert nur Größe und Lage des eigenen Fensters. Der Assistent schreibt nur Dateien,
  die kushim schon schreibt (`wakewords.toml`, `run/setup-state.json`, `config.toml`), geprüft, atomar, mit `confirm: true`.
  `setup.checks` startet wie `kushim doctor` die lokale `claude`-CLI nur zum Lesen von Version und Anmeldung.
- **Kein neuer Netzzugang.** Kein neuer Port, keine Tauri-Plugins, CSP, `capabilities/default.json` und ALLOWLIST unverändert.
  Der Rustteil bleibt ohne Netz, Prozess und Dateischreiben.
- **Freigaben nur über den vorhandenen Weg**: dieselbe `PermissionBar`, derselbe `approvals.decide` mit Hash und `confirm`; kein Erlauben
  ohne vollen Text, kein Fokus-Klau, kein „immer erlauben“.
- **Geheimnisse bleiben, wo sie sind** (Token in `run/`, Entscheidung C7). Vault-Schlüssel und Claude-Anmeldedaten nie im Fenster.
- **`usage.json` gilt als fremd** (Claude könnte sie im kushim-Ordner schreiben): feste Felder, Zahlen 0 bis 100, ≤ 1 KB, nur als Text.

## 7. Tests und Dateien

- **Python**: `audio.devices` angeschlossen; `setup.checks` ohne Pfade oder Token; neue Schritte `claude`/`folder`; `wake.get`/`wake.set`
  mit Grenzen, `confirm`, Notaus-Sperre, letztes aktives Wort nicht abschaltbar; Pegel-Vorschlag und Übernahme; `[audio]` in `config.toml`;
  Zähler des Wake-Word-Tests; `statusline.py` schreibt nur bei passender `session_id`; `usage.get` mit kaputter, alter, zu großer Datei.
- **Regeln** (`test_ui_rules.py`): Rechte weiter nur `core:default`, kein `tauri-plugin`, Rustteil ohne Netz, Prozess und Schreiben.
- **Vitest**: Umschalten; NOTAUS im kleinen Fenster; Freigabe im kleinen Fenster (wächst, voller Text, Sperre, Fokus auf Ablehnen);
  letzter Befehl; Verbrauch mit „Stand“ und „veraltet“; Assistent (Erststart, Überspringen, Zurück, Tastatur, kein Schlüssel im DOM).
- **Ansehen** (Skill `kushim-ui-check`): kleines Fenster 400 x 200 und 420 x 640, Assistent bei 375, 800 und 1440 px.
- **Dateien**: `ui/src-tauri/src/main.rs`, `ui/src/App.tsx`, neu `CompactBar.tsx` und `SetupWizard.tsx`, `mock.ts`, `app.css`;
  `api/setup_api.py`, `setup/status.py`, `setup/state.py`, neu `api/usage_api.py`, `voice/statefile.py`, `cli.py`, `config.py`;
  `scripts/statusline.py` (nur mit Ja), `config.example.toml`, Tests.

## 8. Was nur du prüfen kannst

- Echtes Tauri-Fenster unter Windows 11: Umschalten, „immer im Vordergrund“, Blinken der Taskleiste, zwei Bildschirme, Skalierung 125/150 %.
- Ob Claude Code das Statuszeilen-Skript in der kushim-Sitzung aufruft und `usage.json` entsteht.
- Pegeltest und Wake-Word-Test mit deinem Mikrofon und deiner Stimme.
- `claude auth status` auf deinem Rechner; Vorleser im Assistenten.

## 9. Entscheidungen für dich

1. **Kleines Fenster**: kompakter Modus desselben Fensters (Empfehlung) oder ein zweites Tauri-Fenster (mehr Rechte, zweite Verbindung)?
2. **Immer im Vordergrund** im kleinen Modus: an, mit Knopf abschaltbar (Empfehlung), oder aus?
3. **Hotkey**: nur im Fenster, Strg+Umschalt+M (Empfehlung), oder global über `tauri-plugin-global-shortcut` (neues Paket, Regeltest muss gelockert werden)?
4. **Freigabe im kleinen Fenster**: Fenster wächst auf die volle Leiste und blinkt, ohne Fokus zu holen (Empfehlung), oder automatisch zurück ins große Fenster?
5. **Verbrauch**: `statusline.py` schreibt `run/usage.json` nur für die kushim-Sitzung (Empfehlung, Weg A, braucht dein Ja), oder kein Verbrauch im Fenster (Weg B)?
6. **Mikrofon merken**: neue Einträge `[audio] mic/out` in `config.toml`, die `kushim start` ohne `--mic` nutzt (Empfehlung), oder nur den passenden Befehl anzeigen?
7. **Vault anlegen**: weiter nur im Terminal mit `kushim memory init` (Empfehlung), oder ein Knopf im Assistenten?
8. **Notaus im Setup**: nur erklären und „verstanden“ (Empfehlung), oder echt auslösen und danach neu starten?
9. **Schnitt**: E2a, E3a, E3b, dann E2b (Empfehlung), oder zuerst den Assistenten?
