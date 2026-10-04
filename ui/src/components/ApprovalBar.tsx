import { useEffect, useRef, useState } from "react";

export interface Pending {
  kind: string;
  preview: string;       // der exakte Text, so wie er ausgeführt würde
  digest: string;        // Hash dieses Textes: entschieden wird nur dafür
  expires_in: number;    // Sekunden
  sends_data_out: boolean;
}

const KIND_TITLE: Record<string, string> = {
  research: "Recherche im Internet",
  start: "Claude soll im Projekt arbeiten",
  answer: "Antwort an Claude",
  folder: "Ordner für Claude freigeben",
};

const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

interface Props {
  pending: Pending;
  onDecide: (approve: boolean) => void;
}

/** Freigabe-Leiste: exakte Vorschau, Restzeit, zwei gleich große Knöpfe. Standardfokus auf Ablehnen, Esc lehnt ab.
 *  Kein "Immer erlauben", nichts vorausgefüllt, nach Ablauf sind beide Knöpfe aus. */
export function ApprovalBar({ pending, onDecide }: Props) {
  const [left, setLeft] = useState(pending.expires_in);
  const deny = useRef<HTMLButtonElement>(null);

  useEffect(() => { setLeft(pending.expires_in); }, [pending.digest, pending.expires_in]);
  useEffect(() => {
    const id = setInterval(() => setLeft((v) => Math.max(0, v - 1)), 1000);
    return () => clearInterval(id);
  }, [pending.digest]);
  useEffect(() => { deny.current?.focus(); }, [pending.digest]);

  const expired = left <= 0;
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Escape") onDecide(false); };

  return (
    <section className="approval" role="alertdialog" aria-labelledby="ap-title" aria-describedby="ap-prev" onKeyDown={onKey}>
      <h2 id="ap-title">{KIND_TITLE[pending.kind] ?? "Freigabe nötig"}</h2>
      {pending.sends_data_out && <span className="chip" title="Dieser Text verlässt deinen Rechner">⇧ Sendet Daten nach außen</span>}
      <p className="ap-note">Dieser Text wird so ausgeführt:</p>
      <pre id="ap-prev" className="ap-preview" tabIndex={0}>{pending.preview}</pre>
      <p className="ap-time" aria-live="off">{expired ? "Abgelaufen" : `Läuft ab in ${mmss(left)}`}</p>
      <div className="ap-actions">
        <button ref={deny} type="button" className="ap-btn" disabled={expired} onClick={() => onDecide(false)}>Ablehnen</button>
        <button type="button" className="ap-btn primary" disabled={expired} onClick={() => onDecide(true)}>Erlauben</button>
      </div>
    </section>
  );
}
