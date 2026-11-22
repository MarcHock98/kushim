---
name: kushim-ui-check
description: Use after UI changes in kushim to look at the result in the built-in browser. Steps for the mock demo, the three widths (375, 800, 1440 px), overflow measurement, opening older demo views, keyboard and timer checks, and what only the user can verify.
---

# kushim-Oberfläche im Browser ansehen

Tests in jsdom finden keine Überlappung, keinen Wortbruch und kein abgeschnittenes Wort. Darum nach jeder sichtbaren Änderung ansehen.

## Vorbereiten
1. Stand zusammenführen und `cd ui && npx vitest run`, `npx tsc --noEmit`, `npm run build` grün haben.
2. Dev-Server: `preview_start` mit Name `kushim-ui` (`.claude/launch.json`, Port 1420). Vor einem `npm ci` vorher `preview_stop`.
3. Adresse `http://localhost:1420/?mock&demo`. Die Demo spielt alle Beispiele nacheinander ab und braucht je nach Zahl der
   Beispiele mehrere Minuten (Zeitpunkte stehen in `MockSocket.demo()` in `ui/src/lib/mock.ts`). Warten in Stapeln von höchstens
   etwa 190 s je Aufruf.
4. **Geänderte Dateien lädt der Browser nicht von selbst nach:** nach jeder Korrektur neu laden (die Demo beginnt von vorn).

## Ansichten öffnen
- Die Reiter zeigen nur die letzten fünf Ansichten. Ältere: links „Übersicht“, dort in der Liste „Zeigen“.
- Während die Demo läuft, schließt „Ich höre zu …“ die Ansicht. Erst prüfen, wenn der Kopf „Bereit“ zeigt.
- Nach einem Klick auf einen Reiter 2 s warten (Überblendung), dann erst das Bild nehmen. Refs aus `find` veralten nach jedem
  Wechsel: neu suchen oder per Skript klicken.

Hilfsskript (nur zum Ansehen, über `javascript_tool`):
```js
window.__show = async (name) => {
  const nav = [...document.querySelectorAll('button,a,nav *')].find(e => e.textContent.trim() === 'Übersicht');
  nav.click(); await new Promise(r => setTimeout(r, 500));
  const btn = [...document.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Zeigen')
    .find(b => b.parentElement.textContent.includes(name));
  if (!btn) return 'no button';
  btn.click(); await new Promise(r => setTimeout(r, 1200));
  const d = document.documentElement;
  return { name, sw: d.scrollWidth, cw: d.clientWidth };
};
```

## Prüfen, je Ansicht
- **Drei Breiten** mit `resize_window`: 375 × 812, 800 × 900, 1440 × 900. Am Ende `preset: "desktop"` setzen.
- **Überlauf messen, nicht schätzen:** `scrollWidth` gleich `clientWidth` der Seite. Breite Inhalte (Tabelle, Diagramm) dürfen nur
  in ihrem eigenen Rahmen scrollen (dort `scrollWidth` größer als `clientWidth` ist in Ordnung).
- **Bild ansehen** bei 375 und 1440 px: kein Wortbruch mitten im Wort, nichts überlagert, Beschriftungen lesbar, Zustand als Wort.
  Für Einzelheiten `zoom` auf den Ausschnitt.
- **Bedienung:** jeden neuen Knopf einmal klicken, Tastatur (Tab, Enter, Leertaste, Pfeile), sichtbarer Fokus. Timer und
  Animationen 3 s laufen lassen und den Text lesen.
- **Konsole:** `read_console_messages` mit `onlyErrors`. Bekannt und harmlos im Dev-Server: die CSP-Meldung zu
  `ws://localhost:1420` (Vite) und „Transition was skipped“.
- **Leistung** (bei Animationen): Zeit je Bild per `performance.now()` um Rechnen und Zeichnen messen und nennen.

## Bericht
Was bei welcher Breite angesehen wurde, was nur gemessen wurde, gefundene und behobene Fehler, und ehrlich, was fehlt.
Nur der Nutzer kann prüfen: echtes Tauri-Fenster (WebView2), Vorleser, GPU-Last neben Whisper, echter Aufruf durch Claude Code.
