import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import type { Block } from "../../lib/stage";

// Lernkarten, Quiz und Anleitung (Plan docs/ui-p6-plan.md, P6a). Die ersten Bausteine mit Knöpfen, aber: Ein Klick ändert
// NUR den Zustand dieser Ansicht im Fenster. Er ruft nie die API auf, sendet nichts an Claude, speichert nichts (auch nicht
// im Browser). Schließen oder eine neue Ansicht setzt alles zurück. Zustände stehen als Wort da, nie nur als Farbe.
// Keine Animation (kein Umdrehen der Karte), der Timer ist nur eine Anzeige ohne Ton.

type Of<T extends Block["typ"]> = Extract<Block, { typ: T }>;

const two = (n: number) => String(n).padStart(2, "0");

/** Sekunden als Uhrzeit wie beim Countdown: „04:05“ oder „1:02:03“. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}:${two(m)}:${two(s % 60)}` : `${two(m)}:${two(s % 60)}`;
}

/** Fokus nach einer Bedienung auf ein Element setzen (nie beim ersten Anzeigen: die Ansicht soll keinen Fokus stehlen). */
function useFocusAfterAction<T extends HTMLElement>(deps: unknown[]) {
  const ref = useRef<T>(null);
  const moved = useRef(false);
  useEffect(() => {
    if (moved.current) { moved.current = false; ref.current?.focus(); }
  }, deps);
  return { ref, mark: () => { moved.current = true; } };
}

// ----- Lernkarten -----

type Mark = "gewusst" | "nochmal";

export function Flashcards({ b }: { b: Of<"lernkarten"> }) {
  const all = b.karten;
  const [deck, setDeck] = useState<number[]>(() => all.map((_, i) => i));      // Karten dieser Runde (Indizes)
  const [pos, setPos] = useState(0);
  const [shown, setShown] = useState(false);
  const [marks, setMarks] = useState<Record<number, Mark>>({});
  const [round, setRound] = useState(1);
  const focus = useFocusAfterAction<HTMLDivElement>([pos, shown, round]);

  if (all.length === 0) return <p className="v-note">Keine Karten.</p>;

  const mark = (m: Mark) => {
    focus.mark();
    setMarks((x) => ({ ...x, [deck[pos]]: m }));
    setShown(false);
    setPos((p) => p + 1);
  };
  const restart = (cards: number[], repeat: boolean) => {
    focus.mark();
    setDeck(cards); setPos(0); setShown(false); setMarks({}); setRound((r) => (repeat ? r + 1 : 1));
  };

  if (pos >= deck.length) {
    const known = deck.filter((i) => marks[i] === "gewusst"), again = deck.filter((i) => marks[i] !== "gewusst");
    return (
      <section className="v-cards" aria-label="Lernkarten">
        <div className="l-card l-summary" ref={focus.ref} tabIndex={-1}>
          <span className="label">Zusammenfassung</span>
          <p className="l-q">{known.length} von {deck.length} gewusst, {again.length} nochmal</p>
          {again.length > 0 && (
            <div className="c-points">
              <p className="label c-word">nochmal</p>
              <ul>{again.map((i) => <li key={i}>{all[i].frage}</li>)}</ul>
            </div>
          )}
        </div>
        <div className="l-actions">
          {again.length > 0 && <button type="button" className="primary" onClick={() => restart(again, true)}>Nochmal-Karten üben ({again.length})</button>}
          <button type="button" onClick={() => restart(all.map((_, i) => i), false)}>Alle von vorn</button>
        </div>
        <p className="v-note">Nichts wird gespeichert. Schließen setzt die Karten zurück.</p>
      </section>
    );
  }

  const card = all[deck[pos]];
  const count = `Karte ${pos + 1} von ${deck.length}`;
  return (
    <section className="v-cards" aria-label="Lernkarten">
      <p className="label l-count">{count}{round > 1 && " · Wiederholung"}</p>
      <div className="l-card" ref={focus.ref} tabIndex={-1} role="group" aria-label={count}>
        <span className="label">Frage</span>
        <p className="l-q">{card.frage}</p>
        {shown && (
          <div className="l-answer">
            <span className="label">Antwort</span>
            <p className="l-a">{card.antwort}</p>
          </div>
        )}
      </div>
      <div className="l-actions">
        {shown ? (
          <>
            <button type="button" onClick={() => mark("gewusst")}>gewusst</button>
            <button type="button" onClick={() => mark("nochmal")}>nochmal</button>
          </>
        ) : (
          <button type="button" className="primary" onClick={() => { focus.mark(); setShown(true); }}>Antwort zeigen</button>
        )}
      </div>
    </section>
  );
}

// ----- Quiz -----

export function Quiz({ b }: { b: Of<"quiz"> }) {
  const name = useId();
  const [pos, setPos] = useState(0);
  const [choice, setChoice] = useState<number | null>(null);
  const [checked, setChecked] = useState(false);
  const [hint, setHint] = useState(false);
  const [answers, setAnswers] = useState<number[]>([]);
  const focus = useFocusAfterAction<HTMLDivElement>([pos, checked]);
  const n = b.fragen.length;

  if (n === 0) return <p className="v-note">Keine Fragen.</p>;

  const answerText = (q: Of<"quiz">["fragen"][number]) => q.optionen[q.richtig] ?? "unbekannt";

  if (pos >= n) {
    const right = b.fragen.filter((q, i) => answers[i] === q.richtig).length;
    return (
      <section className="v-quiz" aria-label="Quiz">
        <div className="l-card l-summary" ref={focus.ref} tabIndex={-1}>
          <span className="label">Ergebnis</span>
          <p className="l-q">{right} von {n} richtig</p>
          <ol className="q-review">
            {b.fragen.map((q, i) => (
              <li key={i}>
                <span className="q-word">{answers[i] === q.richtig ? "richtig" : "falsch"}</span> {q.frage}
                {answers[i] !== q.richtig && <small> · richtig ist „{answerText(q)}“</small>}
              </li>
            ))}
          </ol>
        </div>
        <div className="l-actions">
          <button type="button" onClick={() => { focus.mark(); setPos(0); setChoice(null); setChecked(false); setHint(false); setAnswers([]); }}>Von vorn</button>
        </div>
        <p className="v-note">Nichts wird gespeichert. Schließen setzt das Quiz zurück.</p>
      </section>
    );
  }

  const q = b.fragen[pos];
  const ok = checked && choice === q.richtig;
  const check = () => {
    if (choice === null) { setHint(true); return; }
    focus.mark();
    setHint(false); setChecked(true);
    setAnswers((a) => { const next = [...a]; next[pos] = choice; return next; });
  };
  const next = () => { focus.mark(); setPos((p) => p + 1); setChoice(null); setChecked(false); };

  return (
    <section className="v-quiz" aria-label="Quiz">
      <p className="label l-count">Frage {pos + 1} von {n}</p>
      <div className="l-card" ref={checked ? undefined : focus.ref} tabIndex={-1}>
        <fieldset className="q-set">
          <legend className="l-q">{q.frage}</legend>
          {q.optionen.map((o, i) => (
            <label key={i} className={`q-option${checked && i === q.richtig ? " q-right" : ""}${checked && i === choice && i !== q.richtig ? " q-wrong" : ""}`}>
              <input type="radio" name={`${name}-${pos}`} checked={choice === i} disabled={checked}
                onChange={() => { setChoice(i); setHint(false); }} />
              <span className="q-text">{o}</span>
              {checked && i === q.richtig && <span className="q-tag">richtige Antwort</span>}
              {checked && i === choice && i !== q.richtig && <span className="q-tag">deine Antwort</span>}
            </label>
          ))}
        </fieldset>
      </div>
      {hint && <p className="v-note" role="alert">Wähle zuerst eine Antwort.</p>}
      {checked && (
        <div className={`q-feedback ${ok ? "q-ok" : "q-bad"}`} ref={focus.ref} tabIndex={-1}>
          <p className="q-verdict">{ok ? "richtig" : `falsch, richtig ist „${answerText(q)}“`}</p>
          {q.erklaerung && <p className="q-why">{q.erklaerung}</p>}
        </div>
      )}
      <div className="l-actions">
        {checked
          ? <button type="button" className="primary" onClick={next}>{pos + 1 < n ? "Nächste Frage" : "Ergebnis zeigen"}</button>
          : <button type="button" className="primary" onClick={check}>Prüfen</button>}
      </div>
    </section>
  );
}

// ----- Anleitung -----

const seconds = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0);

export function Guide({ b }: { b: Of<"anleitung"> }) {
  const n = b.schritte.length;
  const clamp = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? Math.min(Math.max(0, n - 1), Math.max(0, Math.trunc(v))) : 0);
  const [idx, setIdx] = useState(() => clamp(b.aktuell));
  const [seen, setSeen] = useState(b.aktuell);
  if (b.aktuell !== seen) { setSeen(b.aktuell); setIdx(clamp(b.aktuell)); }   // Claude hat `aktuell` geändert: die Ansicht folgt
  // Restzeit in ms; jeder Takt zieht die echte vergangene Zeit ab (auch die Zeit auf anderen Schritten), aber nie eine
  // negative: Springt die Uhr zurück, wächst die Restzeit nicht und der Timer bleibt nicht hängen.
  const [timer, setTimer] = useState<{ step: number; run: number; left: number; last: number } | null>(null);
  const active = timer && timer.step === idx ? timer : null;          // ein Timer gehört zu seinem Schritt
  const over = !!active && active.left <= 0;
  const run = active ? active.run : 0;

  useEffect(() => {
    if (!run || over) return;
    const tick = () => setTimer((t) => {
      if (!t) return t;
      const now = Date.now();
      return { ...t, left: t.left - Math.max(0, now - t.last), last: now };
    });
    tick();                                                        // zurück auf dem Schritt: sofort die echte Restzeit
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [run, over]);                                                 // läuft nur, solange ein Timer dieses Schritts zählt

  if (n === 0) return <p className="v-note">Keine Schritte.</p>;

  const go = (d: number) => setIdx((i) => Math.min(n - 1, Math.max(0, i + d)));
  const key = (e: KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
  };
  const s = b.schritte[idx];
  const sec = seconds(s.sekunden);
  const start = () => { const t = Date.now(); setTimer((old) => ({ step: idx, run: (old?.run ?? 0) + 1, left: sec * 1000, last: t })); };
  const state = !active ? "Timer nicht gestartet" : over ? "Timer abgelaufen" : "Timer läuft";
  const shownTime = !active ? clock(sec) : over ? "abgelaufen" : clock(Math.min(sec, active.left / 1000));

  return (
    <section className="v-guide" aria-label="Anleitung" onKeyDown={key}>
      <p className="label l-count">Schritt {idx + 1} von {n}{idx === n - 1 && n > 1 && " · letzter Schritt"}</p>
      <div className="l-card a-step" tabIndex={0} aria-live="polite" aria-keyshortcuts="ArrowLeft ArrowRight">
        <h3 className="a-title">{s.titel}</h3>
        <p className="a-text">{s.text}</p>
      </div>
      {sec > 0 && (
        <div className={`v-countdown a-timer${over ? " c-over" : ""}`} role="timer" aria-label={`Timer für ${s.titel}`}>
          <span className="label" aria-live="polite">{state}</span>
          <span className="c-rest">{shownTime}</span>
          <button type="button" onClick={active && !over ? () => setTimer(null) : start}>
            {!active ? "Timer starten" : over ? "Timer neu starten" : "Timer abbrechen"}
          </button>
          <span className="v-note">Nur Anzeige, ohne Ton</span>
        </div>
      )}
      <div className="l-actions" role="group" aria-label="Schritte blättern">
        <button type="button" aria-disabled={idx === 0} onClick={() => go(-1)}>Zurück</button>
        <button type="button" className="primary" aria-disabled={idx === n - 1} onClick={() => go(1)}>Weiter</button>
      </div>
      <p className="v-note">Pfeiltaste links und rechts blättern auch.</p>
      <details className="m-list a-all">
        <summary>Alle Schritte ({n})</summary>
        <ol className="a-list">
          {b.schritte.map((x, i) => (
            <li key={i} aria-current={i === idx ? "step" : undefined} className={i === idx ? "a-now" : ""}>
              {x.titel}{i === idx && <span className="q-tag">jetzt</span>}{seconds(x.sekunden) > 0 && <small> · {clock(seconds(x.sekunden))}</small>}
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
