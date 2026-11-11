import { useEffect, useRef } from "react";

/** Freigabe-Anfrage von Claude Code (Channel). Alle Texte sind fremd: nur anzeigen, nie ausführen. */
export interface PermissionRequest {
  request_id: string;
  tool_name: string;
  description: string;
  input_preview: string;   // exakter Text der Anfrage
  digest: string;          // Hash dieses Textes: entschieden wird nur dafür
  summary: string;         // kurze Hörhilfe, maßgeblich ist der genaue Text
  truncated?: boolean;     // Vorschau gekürzt: Erlauben nur im Terminal, Ablehnen geht
}

interface Props {
  request: PermissionRequest;
  more: number;            // weitere offene Anfragen
  onDecide: (approve: boolean) => void;
}

/** Freigabe-Leiste für Claudes Anfragen: exakter Text, zwei gleich große Knöpfe, Standardfokus auf Ablehnen, Esc lehnt ab.
 *  Kein "Immer erlauben", nichts vorausgefüllt. Entschieden wird nur per Klick. */
export function PermissionBar({ request, more, onDecide }: Props) {
  const deny = useRef<HTMLButtonElement>(null);
  useEffect(() => { deny.current?.focus(); }, [request.digest]);
  const onKey = (e: React.KeyboardEvent) => { if (e.key === "Escape") onDecide(false); };
  const exact = [`Werkzeug: ${request.tool_name || "(unbekannt)"}`, request.description && `Beschreibung: ${request.description}`,
    request.input_preview && `Eingabe: ${request.input_preview}`].filter(Boolean).join("\n");

  return (
    <section className="approval" role="alertdialog" aria-labelledby="ap-title" aria-describedby="ap-prev" onKeyDown={onKey}>
      <h2 id="ap-title">Claude bittet um Freigabe</h2>
      {request.summary && <p className="ap-note">{request.summary}</p>}
      <p className="ap-note">Genauer Text von Claude (nur zur Ansicht):</p>
      <pre id="ap-prev" className="ap-preview" tabIndex={0}>{exact}</pre>
      {more > 0 && <p className="ap-time">Noch {more} weitere Anfrage(n) offen.</p>}
      {request.truncated && <p className="ap-note">Der Text ist gekürzt. Erlauben bitte im Terminal, hier geht nur Ablehnen.</p>}
      <div className="ap-actions">
        <button ref={deny} type="button" className="ap-btn" onClick={() => onDecide(false)}>Ablehnen</button>
        {!request.truncated &&
          <button type="button" className="ap-btn primary" onClick={() => onDecide(true)}>Erlauben</button>}
      </div>
    </section>
  );
}
