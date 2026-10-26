// Kleine Symbole als SVG (Linien in currentColor, 24er Raster). Keine Emoji, keine Schriften, keine Netzzugriffe.
// Sie sind Beiwerk: Text oder aria-label steht immer daneben, die Symbole selbst sind für Screenreader verborgen.
import type { ReactNode } from "react";

function Svg({ children, size = 22 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const IconHome = () => <Svg><circle cx="12" cy="12" r="8.5" /><path d="M10 8v8M10 12l4-4M10 12l4 4" /></Svg>;
export const IconOverview = () => <Svg><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></Svg>;
export const IconMemory = () => <Svg><path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H19v15H7.5A2.5 2.5 0 0 0 5 20.5z" /><path d="M5 20.5A2.5 2.5 0 0 0 7.5 23H19v-5" /><path d="M9 8h6" /></Svg>;
export const IconShield = () => <Svg><path d="M12 3l7.5 3v5.5c0 4.5-3.2 8-7.5 9.5-4.3-1.5-7.5-5-7.5-9.5V6z" /><path d="M9 12l2.2 2.2L15.5 10" /></Svg>;
export const IconThumbUp = () => <Svg size={18}><path d="M7 11v9H4v-9zM7 11l4-7c1.5 0 2.5 1 2.2 2.5L12.6 9H19a2 2 0 0 1 2 2.4l-1.2 6A2 2 0 0 1 17.8 19H7" /></Svg>;
export const IconThumbDown = () => <Svg size={18}><path d="M7 13V4H4v9zM7 13l4 7c1.5 0 2.5-1 2.2-2.5L12.6 15H19a2 2 0 0 0 2-2.4l-1.2-6A2 2 0 0 0 17.8 5H7" /></Svg>;
export const IconArrowUp = () => <Svg size={16}><path d="M12 19V5M6 11l6-6 6 6" /></Svg>;
export const IconCheck = () => <Svg size={16}><path d="M5 12.5l4.5 4.5L19 7.5" /></Svg>;
export const IconWarn = () => <Svg size={16}><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17v.5" /></Svg>;
export const IconCross = () => <Svg size={16}><path d="M6 6l12 12M18 6L6 18" /></Svg>;
