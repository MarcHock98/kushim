# Werkstatt: Entwurf der Sperrregeln für `.claude/settings.json`

Stand: Entwurf für Stufe 2 („Werkstatt“, `docs/ui-p7-plan.md` Abschnitt 4). Die Datei `.claude/settings.json` ist hier **nicht**
geändert; der Manager übernimmt die Regeln nach Prüfung. Einträge mit **zu prüfen** sind nicht aus der Doku belegt, sondern
abgeleitet; sie einmal im Wegwerf-Repo live ausprobieren (`/permissions` zeigt, ob Claude Code eine Regel angenommen hat).

## 1. Wozu, und was die Regeln nicht leisten

- Die Sperrregeln sind die **erste** Schicht: Claude Code fragt in der Werkstatt gar nicht erst, sondern lehnt ab.
- Die **zweite** Schicht ist `src/kushim/werkstatt/schutz.py` (`pruefe_commits(repo, master, zweig)`): Sie prüft den fertigen
  Zweig vor dem Merge und den neuen master-Stand danach. Nur sie sieht auch Änderungen, die an den Regeln vorbei entstehen.
- `Read(...)`/`Edit(...)`-Regeln gelten für die eingebauten Datei-Werkzeuge (Read, Edit, Write, NotebookEdit; Read-Regeln laut
  Doku „best effort“ auch für Grep/Glob). Sie gelten **nicht** für Befehle in `Bash`/`PowerShell` (`cat run/channel.json`,
  `Set-Content src/kushim/safety/x.py`). Dagegen hilft nur `--permission-mode default` (jeder Shell-Befehl wird gefragt) und die
  Schutzprüfung beim Merge.
- Verbote (`deny`) haben Vorrang vor `allow` und vor `.claude/settings.local.json` (dort steht `PowerShell(pip *)` erlaubt).

## 2. Schreibweise (aus Doku und Repo-Erfahrung)

- Pfadmuster folgen der gitignore-Schreibweise. `/pfad` = ab Projektwurzel der Einstellungsdatei, `pfad` oder `./pfad` = ab dem
  aktuellen Ordner, `//pfad` = absolut, `~/pfad` = Home. `**` = beliebig tief.
  **Zu prüfen:** ob `/pfad` in der Projekt-`settings.json` wirklich die Projektwurzel meint (ältere Doku: „relativ zur
  Einstellungsdatei“). Im Entwurf steht deshalb `/pfad`; greift es nicht, dieselben Muster ohne führenden `/` eintragen.
- `Edit(...)` gilt für alle eingebauten Werkzeuge, die Dateien schreiben (Write, Edit, NotebookEdit); `Write(pfad)` wird nicht
  ausgewertet (Hilfetext der CLI 2.1.329, siehe 3.3). Derselbe Text nennt `Edit(/**)` als „auf den Arbeitsbereich begrenzte“
  Regel, was für `/pfad` = Projektwurzel spricht.
- Bash: Erfahrung aus diesem Repo (`.claude/skills/kushim-add-tool/SKILL.md`): `Bash(git add)` **und** `Bash(git add *)`,
  Leerzeichen vor dem Stern; `Bash(git add*)` griff nicht. Der eingebaute Hilfetext der installierten CLI (2.1.329) sagt:
  Präfixregeln sind reine Textvergleiche ohne Prüfung der Optionen, das Leerzeichen vor `*` erzwingt eine Wortgrenze,
  `Bash(cmd sub*)` passt auch auf `cmd subx`, ein `:*` am Ende ist gleichwertig. Deshalb steht jeder Befehl in beiden Formen
  (ohne und mit ` *`); das Beispiel `Bash(git push*)` aus dem Auftrag ist bewusst ersetzt. Beispiele aus demselben Hilfetext:
  `Bash(npm run build)`, `Edit(docs/**)`, `Read(~/.zshrc)`. **Zu prüfen:** ob `PowerShell(...)`-Regeln dieselbe Schreibweise haben
  (im Repo belegt ist nur `PowerShell(pip *)` als `allow`).
- Bash-Regeln sind Präfix-Regeln. `git -C . push` oder `& git push` passen nicht auf `Bash(git push *)`. Sie sind eine Bremse,
  keine Grenze; die Grenze ist „default“-Modus plus Schutzprüfung.
- **Zu prüfen:** Ob Pfadregeln unter Windows Groß-/Kleinschreibung (`SRC/Kushim/Safety/x.py`), Backslashes und absolute Pfade
  (`C:\...\src\kushim\safety\x.py`) mitfangen. Die Schutzprüfung fängt das beim Merge in jedem Fall.

## 3. Vorschlag

### 3.1 Ergänzung von `permissions.deny` (vorhandene Einträge bleiben)

```json
{
  "enableAllProjectMcpServers": false,
  "permissions": {
    "deny": [
      "mcp__Slack",
      "mcp__Atlassian",
      "mcp__Trello",
      "mcp__Claude_Docs",

      "WebFetch",
      "WebSearch",

      "Read(/run/**)",
      "Read(/vault/**)",
      "Read(/voice-data/**)",
      "Read(/config.toml)",
      "Read(/wakewords.toml)",
      "Read(/.claude/settings.local.json)",

      "Edit(/src/kushim/safety/**)",
      "Edit(/src/kushim/channel/**)",
      "Edit(/src/kushim/werkstatt/**)",
      "Edit(/src/kushim/net/**)",
      "Edit(/src/kushim/claude_cli/**)",
      "Edit(/src/kushim/safety.*)",
      "Edit(/src/kushim/channel.*)",
      "Edit(/src/kushim/werkstatt.*)",
      "Edit(/src/kushim/net.*)",
      "Edit(/src/kushim/claude_cli.*)",
      "Edit(/tests/test_no_egress*.py)",
      "Edit(/tests/test_ui_rules.py)",
      "Edit(/tests/test_rules.py)",
      "Edit(/tests/test_killswitch.py)",
      "Edit(/tests/test_werkstatt_*.py)",
      "Edit(**/conftest.py)",
      "Edit(**/pytest.ini)",
      "Edit(**/.pytest.ini)",
      "Edit(**/tox.ini)",
      "Edit(**/setup.cfg)",
      "Edit(**/setup.py)",
      "Edit(**/sitecustomize.py)",
      "Edit(**/usercustomize.py)",
      "Edit(**/*.pth)",
      "Edit(**/vite.config.*)",
      "Edit(**/vitest.config.*)",
      "Edit(**/vitest.workspace.*)",
      "Edit(/pyproject.toml)",
      "Edit(/ui/package.json)",
      "Edit(/ui/package-lock.json)",
      "Edit(/ui/index.html)",
      "Edit(/ui/src-tauri/**)",
      "Edit(/ui/src/test-setup.ts)",
      "Edit(/.claude/**)",
      "Edit(/scripts/**)",
      "Edit(/bin/**)",
      "Edit(/install.ps1)",
      "Edit(**/config*.toml)",
      "Edit(**/wakewords*.toml)",
      "Edit(**/.git*)",
      "Edit(**/.git/**)",
      "Edit(/.github/**)",
      "Edit(/run/**)",
      "Edit(/models/**)",
      "Edit(/tools/**)",
      "Edit(**/requirements*.txt)",
      "Edit(**/package.json)",
      "Edit(**/package-lock.json)",
      "Edit(**/.npmrc)",

      "Bash(git push)",
      "Bash(git push *)",
      "Bash(git fetch)",
      "Bash(git fetch *)",
      "Bash(git pull)",
      "Bash(git pull *)",
      "Bash(git clone *)",
      "Bash(git remote *)",
      "Bash(git submodule *)",
      "Bash(git config *)",
      "Bash(git stash)",
      "Bash(git stash *)",
      "Bash(git update-ref *)",
      "Bash(git filter-branch *)",
      "Bash(git -c *)",
      "Bash(curl *)",
      "Bash(wget *)",
      "Bash(ssh *)",
      "Bash(scp *)",
      "Bash(pip *)",
      "Bash(pip3 *)",
      "Bash(python -m pip *)",
      "Bash(uv *)",
      "Bash(npm install)",
      "Bash(npm install *)",
      "Bash(npm i)",
      "Bash(npm i *)",
      "Bash(npm ci)",
      "Bash(npm ci *)",
      "Bash(npm update *)",
      "Bash(npx *)",
      "Bash(pnpm *)",
      "Bash(yarn *)",
      "Bash(cargo *)",
      "Bash(winget *)",
      "Bash(choco *)",

      "PowerShell(git push)",
      "PowerShell(git push *)",
      "PowerShell(git fetch *)",
      "PowerShell(git pull *)",
      "PowerShell(git clone *)",
      "PowerShell(git remote *)",
      "PowerShell(git submodule *)",
      "PowerShell(git config *)",
      "PowerShell(git stash *)",
      "PowerShell(pip *)",
      "PowerShell(npm install *)",
      "PowerShell(npm i *)",
      "PowerShell(npx *)",
      "PowerShell(Invoke-WebRequest *)",
      "PowerShell(Invoke-RestMethod *)",
      "PowerShell(iwr *)",
      "PowerShell(irm *)",
      "PowerShell(Start-BitsTransfer *)",
      "PowerShell(curl *)",
      "PowerShell(wget *)"
    ]
  }
}
```

### 3.2 Begründung der Gruppen

| Gruppe | Warum |
|---|---|
| `WebFetch`, `WebSearch` | Werkstatt arbeitet ohne Netz; zusätzlich zu `--disallowedTools WebFetch,WebSearch` beim Start. |
| `Read(/run/**)` u. a. | `run/` enthält Laufzeitdaten (Channel-Token in `channel.json`, Logs); `vault/`, `voice-data/`, `config.toml`, `wakewords.toml` sind Nutzerdaten. Plan: „`Read(run/**)` gesperrt“. |
| `Edit(...)` Pfade | Genau die geschützten Pfade aus `schutz.py` (`GESCHUETZTE_ORDNER`, `GESCHUETZTE_DATEIEN`, `GESCHUETZTE_MUSTER`, `GESCHUETZTE_NAMEN`), dazu Paketlisten. `safety.*` usw.: ein Modul neben dem Paket. |
| `Edit(**/.git/**)` | Die `.git`-Ablage (Hooks, `config` mit `core.fsmonitor`/`core.hooksPath`) würde Befehle ausführen, die nie im Diff auftauchen. |
| `git push/fetch/pull/clone/remote/submodule` | Kein Netz, keine fremden Repos, keine Submodule. Der Nutzer pusht selbst. |
| `git config`, `git -c *` | Würde `core.hooksPath`, `core.fsmonitor`, `diff.external` setzen. |
| `git stash` | Der Stash ist zwischen allen Worktrees geteilt. |
| `git update-ref`, `git filter-branch` | Würden master am Merge-Dialog vorbei verschieben. |
| Paketmanager | „Keine neuen Pakete“: Installation nie aus der Werkstatt. Überstimmt das `allow` `PowerShell(pip *)` aus `settings.local.json`. |
| Downloader | Kein Netz aus der Shell (`curl`, `Invoke-WebRequest` ...). |

### 3.3 Keine `Write(...)`-Regeln

Der Auftrag nannte `Write(...)`. Der eingebaute Hilfetext der installierten CLI (2.1.329) sagt dazu sinngemäß: Pfadregeln für
alle schreibenden Werkzeuge (Write, Edit, NotebookEdit) heißen `Edit(pfad)`; `Write(pfad)`- und `NotebookEdit(pfad)`-Regeln werden
von der Dateiprüfung **nicht** ausgewertet. Sie würden also nur Schutz vortäuschen und stehen deshalb nicht im Entwurf. Ein
nacktes `"Write"` (ohne Pfad) würde das Werkzeug ganz sperren; das ist nicht gewollt.

## 4. Bewusst **nicht** gesperrt

- `Bash(git merge *)`, `Bash(git commit *)`, `Bash(git checkout *)`: Der Merge geschieht im Werkstatt-Fenster nach dem Dialog von
  Claude Code (Nutzerfreigabe Stufe 2). Im Modus `default` fragt Claude Code jeden dieser Befehle einzeln.
- `Bash(git revert *)`: Rückgängig per Revert ist im Plan vorgesehen.
- `Read(/src/**)`, `Read(/tests/**)`: Lesen der geschützten Dateien ist erlaubt, nur Ändern nicht.

## 5. Ablauf beim Merge (Vorschlag)

1. Vor dem Merge: `pruefe_commits(repo, "master", "<zweig>")` → nur bei `ok` den Merge-Dialog anbieten; die Gründe (Code + Pfad)
   in der Werkstatt-Karte zeigen.
2. Nach dem Merge: `pruefe_commits(repo, "<alter master-SHA>", "master")` → bei Ablehnung sofort `git revert` anbieten (ein
   Merge-Commit mit Konfliktlösung könnte sonst geschützte Dateien ändern, die im Zweig unberührt waren).
3. `base` muss Vorfahr von `head` sein (sonst `BASIS_KEIN_VORFAHR`); Namen wie `HEAD~1` oder `@{1}` lehnt der Leser ab, SHA oder
   Zweigname übergeben.
