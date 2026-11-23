# Plan P7: Selbst erweitern (Simulation als Daten, Rezeptbuch, Werkstatt)

Stand 2026-11-23. Teil von `docs/ui-dynamic-plan.md`, nach P5 (`docs/ui-p5-plan.md`) und P6 (`docs/ui-p6-plan.md`). Roadmap: Phase F.
**Stufe 1 (Python-Seite und UI-Engine) gebaut am 2026-11-23 nach den Entscheidungen des Nutzers vom selben Tag.** Stufe 1b und
Stufe 2 sind geplant, nicht gebaut.

Ziel: Wenn kein eingebautes Modell passt, kann Claude Code eine **eigene Simulation als Daten** beschreiben (Stufe 1). Später kommen
fertige Rezepte (Stufe 1b) und eine sichtbare **Werkstatt**, in der Claude Code kushim selbst erweitert, nur nach Freigabe (Stufe 2).

## 1. Entscheidungen des Nutzers (2026-11-23)

1. **Formelsprache erlaubt.** Das hebt `docs/ui-p5-plan.md` Abschnitt 2 („kein Formel-Parser“) **nur für `sim_eigen`** auf (Nachtrag
   dort). Eigene Datei `src/kushim/stage/formel.py` mit eigener fester Importliste `{__future__, math, re, typing}`;
   `tests/test_no_egress.py` wird dafür nur **verschärfend** ergänzt (eine neue feste Liste für `formel.py`, kein `ast`, kein `eval`;
   `schema.py` darf genau die eine relative Importzeile `from . import formel`). Die ALLOWLIST bleibt unverändert.
2. **Stufe 2** baut ein sichtbares Fenster „kushim-Werkstatt“: eine eigene Claude-Code-Sitzung im Repo (Opus, ohne Channel, ohne MCP,
   ohne Web, Standard-Freigabemodus), gestartet erst nach einem Klick in der Oberfläche.
3. **Übernahme (Merge) macht die Werkstatt selbst**, nach dem Freigabedialog von Claude Code im Werkstatt-Fenster. Das kushim-Backend
   merged nie. Die Schutzprüfung im Backend zeigt nur an; durchgesetzt wird über Deny-Regeln in `.claude/settings.json` und die
   Schutzprüfung im Werkstatt-Skill.
4. Ein drittes Werkzeug **`entwickle`** (nur ein Vorschlag, führt nichts aus) darf vorab erlaubt werden, zusammen mit Deny-Regeln für
   geschützte Pfade und `run/**` in `.claude/settings.json`.

## 2. Stufe 1: Simulation als Daten (gebaut)

### 2.1 Datenfluss

`zeige {art: simulation, bausteine: [{typ: "sim_eigen", … Formeltexte …}]}` → `server.py` prüft mit `schema.validate` →
`formel.py`: Text → Zeichen → Pratt-Parser mit Tiefenzähler → Baum → Namensprüfung je Platz → festes RPN `[[op, arg], …]`, TeX und
Kosten → **Probe** bei t0 = 0 (Ableitungen und Kräfte nicht endlich = abgelehnt) → die geprüfte Ansicht enthält je Formel nur
`{rpn, tex}` und je Platz die Namensliste `env`, **nie den Formeltext** → Bridge prüft ein zweites Mal (RPN neu geprüft, TeX, env,
Kosten und Integrator neu berechnet und verglichen) → UI `formel.ts`: Strukturprüfung der RPN (bekannte Befehle, Indizes im Bereich,
kein Unterlauf, am Ende genau ein Wert) und Stapelmaschine auf `Float64Array` → `eigenSim.ts` (RK4, Verlet oder halbimplizites Euler)
in der Taktschleife → `EigenSimulation.tsx`. **Die Oberfläche parst nie Formeltext.**

### 2.2 Grammatik (nur ASCII)

```
formel  := vergl
vergl   := summe (("<"|"<="|">"|">="|"=="|"!=") summe)?        Ergebnis 1 oder 0, nicht verkettbar
summe   := produkt (("+"|"-") produkt)*
produkt := unaer (("*"|"/") unaer)*
unaer   := ("-"|"+") unaer | potenz
potenz  := atom ("^" unaer)?                                      rechtsassoziativ: 2^3^2 = 512, -2^2 = -4
atom    := zahl | name | name "(" formel ("," formel){0,2} ")" | "(" formel ")"
zahl    := [0-9]+("."[0-9]+)?([eE][+-]?[0-9]{1,3})?                endlich, höchstens 1e12
name    := [a-zA-Z][a-zA-Z0-9_]{0,23}                              Groß- und Kleinschreibung zählt
```

Funktionen mit fester Stelligkeit: `sin cos tan asin acos atan sinh cosh tanh exp log log10 sqrt abs sign floor ceil` (je 1),
`atan2 min max hypot mod` (je 2), `clamp(x,a,b) wenn(b,a,c)` (je 3). Konstante `pi`. `log` ist der natürliche Logarithmus. Erlaubte
Zeichen: Ziffern, ASCII-Buchstaben, `_ . + - * / ^ ( ) , < > = !` und das Leerzeichen. Alles andere (Unicode, Homoglyphen, Tab,
Zeilenumbruch, Steuer- und Richtungszeichen) wird **abgelehnt, nicht gesäubert**.

### 2.3 Festes RPN-Format (Python und UI setzen genau dieses um)

- Jede Formel wird zu `{"rpn": [[op, arg], ...], "tex": str}`. Ausgewertet wird mit einem Stapel von links nach rechts.
- `["c", zahl]` legt eine Konstante ab (endlich, 0 bis 1e12, nie negativ; `pi` wird zur Zahl 3.141592653589793).
- `["v", i]` legt `env[i]` ab (`i` ganz, 0 ≤ i < Länge von env).
- `["o", s]` mit `s` aus `+ - * / ^ neg < <= > >= == !=`. Zweistellig: nimmt b, dann a vom Stapel und legt `a s b` ab; `neg` ist
  einstellig (`-a`). Vergleiche ergeben 1.0 oder 0.0. `^` ist `Math.pow`.
- `["f", name]` mit fester Stelligkeit (siehe 2.2). Die Argumente liegen in Schreibreihenfolge auf dem Stapel (das letzte oben).
  `mod(a,b) = a - b*floor(a/b)`, `clamp(x,a,b) = min(max(x,a),b)`, `wenn(b,a,c)`: `b != 0` ergibt `a`, sonst `c`; beide Zweige werden
  ausgewertet, `NaN != 0` gilt als wahr.
- Am Ende liegt genau ein Wert auf dem Stapel. Höchstens 64 Befehle, Baumtiefe höchstens 16.
- Mathematik wie IEEE 754 und JavaScript `Math.*`: Division durch 0 ergibt ±Infinity oder NaN, `sqrt(-1)`, `log(-1)`, `asin(2)`,
  `1^NaN`, `max(1, NaN)` ergeben NaN. Das ist kein Fehler; die Laufzeit hält bei nicht endlichen Werten an.
- `env` je Platz (das Schema schreibt es als Feld `env` in die geprüfte Ansicht):
  - ODE: `env.ode = [t, zustand..., parameter..., hilf...]`. Hilfsgrößen werden der Reihe nach ausgewertet und in env geschrieben;
    Hilfsgröße j sieht nur env bis vor sich selbst (dadurch gibt es keinen Zyklus).
  - Teilchen-Kraft: `env.kraft = [t, x, y, vx, vy, m, parameter...]`. `m` ist die Teilchenmasse aus dem Feld `masse`.
  - Paarkraft: `env.paar = [r, parameter...]`; r ist der Abstand, nie kleiner als `mindestabstand`.
- Testvektoren: `tests/fixtures/formel_vektoren.json` (115 Einträge, Python und UI lesen dieselbe Datei). Je Eintrag `name`,
  `formel`, `env_namen`, `env` (Werte), `rpn`, `tex`, `wert`; nicht endliche Sollwerte als `"nan"`, `"inf"`, `"-inf"`. Vergleich mit
  relativer Toleranz 1e-12 (die Bibliotheken für `sin`, `exp` usw. dürfen sich im letzten Bit unterscheiden).

### 2.4 Baustein `sim_eigen`

| Feld | Regel |
|---|---|
| `name` | Text ≤ 60, Pflicht |
| `beschreibung` | Text ≤ 400 (leer) |
| `form` | `ode` oder `teilchen`, Pflicht |
| `parameter` | 0 bis 12 `{name, wert, min, max, einheit?}`; min < max, min ≤ wert ≤ max, Beträge ≤ 1e12; `einheit` ≤ 20 |
| `darstellung` | 1 bis 2; ODE: `koerper {x, y: Formeln, anker?: [x,y] oder null}`, `zeitreihe {groessen: [Zustandsnamen] 1 bis 4}`, `phasenraum {x, y: Zustandsnamen}`; Teilchen: `koerper` oder `pfeile` (Geschwindigkeiten), ohne weitere Felder |
| `dt` | 1e-5 bis 1 s (ODE 0,01, Teilchen 0,005) |
| `laufzeit` | 5 bis 60 s (30) |
| `tempo` | 0,1 bis 100 (1) |
| `spur` | ja/nein (ja) |
| **ODE** `zustand` | 1 bis 12 `{name, start, einheit?}`, Start-Betrag ≤ 1e9 |
| `hilf` | 0 bis 12 `{name, formel}`, nur frühere Hilfsgrößen |
| `ableitungen` | Objekt `{zustandsname: formel}`, genau eine je Zustand; Ausgabe in Zustandsreihenfolge |
| `kennwerte` | 0 bis 4 `{name ≤ 40, formel, einheit?}` (nur Anzeige, keine Probe) |
| `erhaltung` | Formel oder null; Drift über 1 % gibt einen Hinweis (nur Anzeige, keine Probe) |
| **Teilchen** `anzahl` | 1 bis 300, mit `paar` 1 bis 100 |
| `kasten` | `[b, h]`, je 0,1 bis 1000, Seitenverhältnis ≤ 10; reicht von 0 bis b und 0 bis h |
| `start` | `linie`, `gitter`, `zufall` (mit `startwert`, mulberry32) oder `liste` (`linie`) |
| `punkte` | nur bei `liste`: genau `anzahl` Einträge `[x, y]` oder `[x, y, vx, vy]` im Kasten, Geschwindigkeit ≤ 1e6; Ausgabe immer `[x, y, vx, vy]`, sonst `[]` |
| `startwert` | 0 bis 2 147 483 647 (1) |
| `masse` | > 0 bis 1e6 (1) |
| `kraft` | `{fx, fy}` (Formeln im Kraft-Platz) oder null; Beschleunigung = Kraft / m |
| `paar` | `{f_r, reichweite, mindestabstand?}` oder null; 0 < reichweite ≤ längere Kastenseite, 0 < mindestabstand < reichweite (reichweite/100); f_r > 0 stößt ab, ab der Reichweite 0 |
| `federn` | `{kette: true}` oder `{paare: [[i, j], …]}` (1 bis 400, Indizes vorhanden, nicht auf sich selbst, nicht doppelt), dazu `k` (> 0 bis 1e6), `l0` (0 bis 1000), `daempfung` (0 bis 10 000, 0); Ausgabe immer als `paare`, oder null |
| `fest` | Indizes, eindeutig ([]) |
| `waende` | `keine`, `reflektieren` oder `periodisch` (`reflektieren`) |
| `kennwerte`, `erhaltung` | bei Teilchen abgelehnt (es gibt dafür kein env); Ausgabe `[]` und null |

Gesamt je Simulation ≤ 600 Knoten. **Abgeleitete Felder**, die das Schema schreibt (bei der zweiten Prüfung müssen sie gleich sein):
`env`, `kosten` (Knotenauswertungen je Schritt) und `integrator` (`rk4` für ODE; bei Teilchen `verlet`, wenn keine Kraft `vx`/`vy`
liest und die Federn ungedämpft sind, sonst `euler_semi`). Kosten = Knoten × Stufen (RK4: 4) × Körper bzw. Paare, bei Teilchen dazu
1 je Teilchen, je Feder und je Paar (auch ohne Formeln nie 0); über 150 000 je Schritt wird abgelehnt (die UI rechnet bei mehr als
150 000 Knoten oder 4000 Körper × Schritten je Bild in „Zeitlupe“). Zählt gegen `MAX_SIM_PRO_ANSICHT = 2`.
`_claims_system` prüft wie bei jedem Baustein alle Texte, also auch `name` und `beschreibung`; Unterstriche zählen als Leerzeichen, und
die zusammengesetzten Beschriftungen der Oberfläche („name (einheit)“, Regler, Listen der Beschreibung) werden zusätzlich geprüft.
Nachtrag nach der Prüfung (2026-11-23): Parameter brauchen eine Spanne `max − min ≥ 1e-9 · max(1, |min|, |max|)`; zwei `liste`-Punkte
an derselben Stelle werden abgelehnt.

Namen: Form wie in 2.2, nicht `pi` und keine Funktion, eindeutig über Zustand, Parameter und Hilfsgrößen. Im ODE-Platz ist `t` belegt,
im Teilchen-Platz `t x y vx vy m r` (darum heißt ein Parameter dort nie `m`).

**Probe bei t0 = 0:** ODE mit Startwerten und Parameterwerten: jede Hilfsgröße, jede Ableitung und `koerper.x/y` müssen endlich sein.
Teilchen: `fx` und `fy` in der Kastenmitte (Geschwindigkeit 0) und an jeder Startlage aus `punkte`; `f_r` bei `mindestabstand` und bei
`reichweite`. Was die Laufzeit danach tut, prüft die UI (Betrag über 1e9 oder nicht endlich: „instabil, angehalten“).

**Fehler:** `ViewError.code` bleibt kurz und fest (`bad_block_N`, höchstens 20 Zeichen); dazu `detail` mit festem Pfad, Grund und
Stelle, z. B. `ableitungen.1:unbekannter_name@14`. Pfade nennen nur Feldnamen des Schemas und Indizes (bei `ableitungen` den Index des
Zustands), nie Namen oder Text aus der Eingabe. Claude bekommt `Ansicht abgelehnt (bad_block_1:ableitungen.1:unbekannter_name@14).`

Beispiel der Ausgabe (aus `{name: "Zerfall", form: "ode", zustand: [{name: "u", start: 1}], ableitungen: {u: "-u"},
darstellung: [{form: "zeitreihe", groessen: ["u"]}]}`):

```json
{"typ": "sim_eigen", "form": "ode", "name": "Zerfall", "beschreibung": "", "parameter": [], "dt": 0.01, "laufzeit": 30,
 "tempo": 1, "spur": true, "zustand": [{"name": "u", "start": 1, "einheit": ""}], "hilf": [],
 "ableitungen": {"u": {"rpn": [["v", 1], ["o", "neg"]], "tex": "-u"}}, "kennwerte": [], "erhaltung": null,
 "darstellung": [{"form": "zeitreihe", "groessen": ["u"]}], "env": {"ode": ["t", "u"]}, "integrator": "rk4", "kosten": 8}
```

### 2.5 Beispiele (gültig, in den Tests und in `mock.ts`)

- **Gedämpftes Pendel:** Parameter g 9,81 [0,1; 30], l 1 [0,1; 10], d 0,2 [0; 5]; Zustand phi 1,2, w 0; `phi: "w"`,
  `w: "-g/l*sin(phi) - d*w"`; Darstellung `koerper` x `l*sin(phi)`, y `-l*cos(phi)`, Anker [0, 0], und `zeitreihe [phi]`; Kennwert
  Energie `0.5*(l*w)^2 + g*l*(1-cos(phi))`.
- **Räuber und Beute:** a 1,1, b 0,4, c 0,4, dd 0,1 (alle [0; 5]); B 10, R 5; `B: "a*B - b*B*R"`, `R: "dd*B*R - c*R"`; Erhaltung
  `dd*B - c*log(B) + b*R - a*log(R)`; `zeitreihe [B, R]`, `phasenraum B/R`.
- **Lorenz:** dt 0,005; s 10 [0; 50], r 28 [0; 100], bb 2,6667 [0; 10]; x, y, z = 1; `x: "s*(y-x)"`, `y: "x*(r-z) - y"`,
  `z: "x*y - bb*z"`; `phasenraum x/z`, `zeitreihe [x]`.
- **Federkette:** Teilchen, anzahl 12, `linie`, Kasten [4, 3], `reflektieren`, fest [0, 11], **masse 0,1**; Parameter g 9,81, c 0,3;
  Kraft `fx: "-c*vx"`, `fy: "-m*g - c*vy"`; Federn `kette`, k 40, l0 0,25, Dämpfung 0,05; Darstellung `koerper`.
  (Präzisierung: In der Plan-Eingabe war m ein Parameter. Im Teilchen-Platz ist `m` die Masse aus `masse`, darum dort kein Parameter `m`.)

### 2.6 Oberfläche (UI-Seite, eigener Branch)

Fester Hinweis „Eigene Simulation, von kushim beschrieben, nicht geprüft. Simulation, keine Messung“, von der Oberfläche gesetzt.
Gleichungen immer als TeX (`Tex.tsx`, `trust: false`). Budget 150 000 Knotenauswertungen je Bild, sonst „Zeitlupe“. Zufall nur
mulberry32(startwert). Regeltests: nur `formel.ts` führt Opcodes aus, kein Text-Parser in `formel.ts` und `eigenSim.ts`.

### 2.7 Anweisungen an Claude

`INSTRUCTIONS`: zuerst immer ein eingebautes Modell; nur wenn keines passt, `sim_eigen`. Dem Nutzer sagen, dass es eine eigene, nicht
geprüfte Simulation ist, keine Messung. Bei Ablehnung höchstens zweimal still nach dem Fehlercode korrigieren, dann kurz sagen.
„Nie Formeln oder Code“ gilt weiter für alles außer `sim_eigen`. Die Beschreibung von `zeige` hat einen knappen Block mit Feldern,
Grammatik-Kurzform und einem Beispiel.

### 2.8 Sicherheit

- Kein `eval`, kein `ast`, keine Rekursion über die feste Tiefe (Parser 40 Ebenen, Baum 16): 10 000 Ebenen werden in Millisekunden
  abgelehnt, nie ein `RecursionError`. Die Formel ist Daten für eine Stapelmaschine mit festen Befehlen, kein Code.
- Die UI bekommt keinen Text zum Parsen, nur RPN, die sie selbst noch einmal prüft.
- Last begrenzt im Backend (Knoten, Kosten, Teilchen, Federn) und in der UI (Budget je Bild, Stopp, Abbruch bei nicht endlichen Werten).
- Prüfung zweimal (Channel und Bridge); die zweite Prüfung bekommt die geprüfte Form und rechnet alles Abgeleitete neu.
- Keine neue Fähigkeit für kushim: nichts wird ausgeführt, gespeichert oder gesendet.

### 2.9 Tests

`tests/test_formel.py` (Grammatik, jede Grenze ±1, Zeichen, Tiefe 10 000 unter 50 ms, Namen, RPN der zweiten Prüfung, Auswertung wie
JavaScript, Vektoren, Zufallstest mit 2000 Formeln), `tests/test_formel_parity.py` (Opcode- und Funktionslisten in `ui/src/lib/formel.ts`,
übersprungen, solange die Datei fehlt), `tests/test_stage.py` (Baustein: Standardwerte, Beispiele, Grenzen, Probe, Namen, Typen, zweite
Prüfung, Manipulation, JSON-Grenze, Zufallstest, Channel und Bridge), `tests/test_channel.py`, `tests/test_no_egress.py` (verschärft).

## 3. Stufe 1b: Rezeptbuch (geplant)

`src/kushim/stage/rezepte/*.json` und `rezepte.py`: fertige, geprüfte `sim_eigen`-Beschreibungen (Lorenz, Räuber und Beute, Pendel,
Federkette …). Claude schickt nur `{typ: "sim_eigen", rezept: "lorenz", parameter: {…}}`; das Schema setzt das Rezept ein und prüft es
wie in Stufe 1. Vorteil: weniger Formeltext, geprüfte Gleichungen, kürzere Beschreibung von `zeige`.

## 4. Stufe 2: Werkstatt (geplant)

1. Werkzeug **`entwickle`** (`stage/auftrag.py`): nur ein Vorschlag mit Beschreibung, höchstens 5 offen.
2. UI-Karte „Annehmen / Ablehnen“: Fokus auf Ablehnen, 700 ms Sperre nach jedem Wechsel, Hash des Auftrags, **nie per Stimme**.
3. `werkstatt/launch.py` startet das sichtbare Fenster „kushim-Werkstatt“: `claude --strict-mcp-config` (leer), `--model opus --effort high`,
   `--permission-mode default`, `--disallowedTools WebFetch,WebSearch`; der Auftrag liegt als Datendatei bei.
4. Skill `kushim-werkstatt`: Manager-Kette, Vorschau; `status.json` nur zur Anzeige; `schutz.py` zeigt die Schutzprüfung.
5. Merge im Werkstatt-Fenster nach dem Dialog von Claude Code; danach neu bauen oder neu starten. Rückgängig per Revert (auch über die CLI).
6. Ein Notaus-Wächter beendet die Werkstatt.
7. **Geschützte Pfade:** `safety/**`, `channel/**`, `werkstatt/**`, `net/**`, `claude_cli/**`, `tests/test_no_egress*.py`,
   `tests/test_ui_rules.py`, `tests/test_rules.py`, `tests/test_killswitch.py`, `tests/test_werkstatt_*.py`, `conftest.py`, `pyproject.toml`,
   `ui/package*.json`, `ui/vite.config.ts`, `ui/index.html`, `ui/src-tauri/**`, `ui/src/test-setup.ts`, `.claude/**`, `scripts/**`,
   `install.ps1`, `config*.toml`, `wakewords*.toml`, `.gitignore`, `.git*`. Bestehende Tests: 0 gelöschte Zeilen, keine neuen
   `skip`/`xfail`/`.only`/`.skip`/`todo`; keine neuen Pakete; `Read(run/**)` gesperrt.

## 5. Was ohne dich nicht prüfbar ist

1. Ob Claude Code im echten Aufruf zuerst ein eingebautes Modell wählt und `sim_eigen` nur nimmt, wenn keines passt.
2. Ob die Beschreibung von `zeige` reicht, damit Claude gültige Formeln und Felder schreibt (höchstens zwei stille Korrekturen).
3. Last im echten Fenster neben Whisper bei teuren Paarkräften (100 Teilchen, 30 Knoten).
4. Ob `sin`, `exp` usw. in WebView2 im letzten Bit genauso rechnen wie Python (die Vektoren erlauben 1e-12 relativ).
