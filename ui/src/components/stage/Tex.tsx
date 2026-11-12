import { useEffect, useRef, useState } from "react";
import "katex/dist/katex.min.css";

/** Formel mit KaTeX (lokal gebündelt). `katex.render` baut DOM-Knoten (kein innerHTML); `trust: false` verbietet
 *  \href, \url und HTML-Befehle. Fehlerhafte Formeln erscheinen als Text mit dem Wort „Formel fehlerhaft“. */
export function Tex({ tex, block = false }: { tex: string; block?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [bad, setBad] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.textContent = tex;                                // bis KaTeX geladen ist (und als Ersatz): der Rohtext
    let alive = true;
    void import("katex").then(({ default: katex }) => {
      if (!alive) return;
      try {
        katex.render(tex, el, { displayMode: block, throwOnError: true, trust: false, strict: "ignore", maxSize: 20, maxExpand: 200 });
        setBad(false);
      } catch {
        el.textContent = tex;
        setBad(true);
      }
    }).catch(() => { if (alive) setBad(true); });
    return () => { alive = false; };
  }, [tex, block]);

  return (
    <span className={`tex${block ? " tex-block" : ""}`}>
      <span ref={ref} />
      {bad && <span className="tex-bad"> (Formel fehlerhaft)</span>}
    </span>
  );
}
