interface Props {
  onKill: () => void;
  onResume: () => void;
}

/** NOTAUS: immer sichtbar, ein Klick, keine Rückfrage. Aufheben ist ein getrennter, bestätigter Schritt. */
export function KillButton({ onKill }: Pick<Props, "onKill">) {
  return (
    <button type="button" className="kill" onClick={onKill} title="Notaus (Strg+Umschalt+K)">
      NOTAUS
    </button>
  );
}

export function HaltedBanner({ onResume }: Pick<Props, "onResume">) {
  return (
    <div className="banner" role="alert">
      <strong>NOTAUS aktiv.</strong>
      <span> Alle Dienste sind gestoppt.</span>
      <button type="button" className="ghost" onClick={() => {
        if (window.confirm("Alle Dienste dürfen wieder starten.")) onResume();
      }}>Notaus aufheben</button>
    </div>
  );
}
