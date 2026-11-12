import type { Block } from "../../lib/stage";

// Linien- und Balkendiagramm als eigenes SVG (kein Paket). Zeichnet nur die Punkte, die Claude geliefert hat; es wird
// nichts geglättet oder hochgerechnet. Reihen unterscheiden sich in Farbe UND Strichart, die Legende nennt sie mit Namen.

type D = Extract<Block, { typ: "diagramm" }>;
const W = 640, H = 300, L = 56, R = 16, T = 16, B = 44;
const DASH = ["", "7 4", "2 4", "10 4 2 4"];
const SERIES = ["var(--arc)", "var(--amber)", "var(--text)", "var(--text-muted)"];
const fmt = (v: number) => v.toLocaleString("de-DE", { maximumFractionDigits: Math.abs(v) < 10 ? 2 : 0 });

function ticks(lo: number, hi: number, n = 5): number[] {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.001; v += step) out.push(Number(v.toFixed(10)));
  return out;
}

export function Chart({ d }: { d: D }) {
  const numericX = d.reihen.every((r) => r.punkte.every((p) => typeof p[0] === "number"));
  const cats = numericX ? [] : [...new Set(d.reihen.flatMap((r) => r.punkte.map((p) => String(p[0]))))].slice(0, 500);
  const xs = numericX ? d.reihen.flatMap((r) => r.punkte.map((p) => p[0] as number)) : [];
  const ys = d.reihen.flatMap((r) => r.punkte.map((p) => p[1]));
  const yt = ticks(d.form === "balken" ? Math.min(0, ...ys) : Math.min(...ys), Math.max(...ys));
  const y0 = yt[0], y1 = yt[yt.length - 1];
  const x0 = numericX ? Math.min(...xs) : 0, x1 = numericX ? Math.max(...xs) : Math.max(1, cats.length - 1);
  const band = (W - L - R) / Math.max(1, cats.length);
  const px = (x: number | string) => numericX
    ? L + ((x as number) - x0) / (x1 - x0 || 1) * (W - L - R)
    : L + band * (cats.indexOf(String(x)) + 0.5);
  const py = (y: number) => T + (1 - (y - y0) / (y1 - y0 || 1)) * (H - T - B);
  const xLabels = numericX ? ticks(x0, x1, 6) : cats.filter((_, i) => i % Math.ceil(cats.length / 8) === 0);
  const label = `Diagramm${d.y_titel ? `: ${d.y_titel}` : ""}${d.x_titel ? ` über ${d.x_titel}` : ""}, ${d.reihen.map((r) => r.name).join(", ")}`;

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} preserveAspectRatio="xMidYMid meet">
        {yt.map((v) => (
          <g key={`y${v}`}>
            <line x1={L} x2={W - R} y1={py(v)} y2={py(v)} className="chart-grid" />
            <text x={L - 8} y={py(v)} className="chart-tick" textAnchor="end" dominantBaseline="middle">{fmt(v)}</text>
          </g>
        ))}
        {xLabels.map((x) => (
          <text key={`x${x}`} x={px(x)} y={H - B + 18} className="chart-tick" textAnchor="middle">{typeof x === "number" ? fmt(x) : x}</text>
        ))}
        <line x1={L} x2={W - R} y1={H - B} y2={H - B} className="chart-axis" />
        {d.reihen.map((r, i) => d.form === "linie" ? (
          <polyline key={r.name + i} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeDasharray={DASH[i]} strokeLinejoin="round"
            points={r.punkte.map((p) => `${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join(" ")} />
        ) : (
          <g key={r.name + i}>
            {r.punkte.map((p, j) => {
              const w = band / (d.reihen.length + 1), x = px(p[0]) - band / 2 + w * (i + 0.5), top = Math.min(py(p[1]), py(0)), h = Math.abs(py(p[1]) - py(0));
              return <rect key={j} x={x} y={top} width={w * 0.9} height={Math.max(1, h)} fill={SERIES[i]} fillOpacity={i % 2 ? 0.55 : 0.9}
                stroke={SERIES[i]} strokeDasharray={DASH[i]} />;
            })}
          </g>
        ))}
        {d.y_titel && <text x={8} y={T - 4} className="chart-title">{d.y_titel}</text>}
        {d.x_titel && <text x={W - R} y={H - 6} className="chart-title" textAnchor="end">{d.x_titel}</text>}
      </svg>
      <figcaption className="chart-legend">
        {d.reihen.map((r, i) => (
          <span key={r.name + i} className="chart-key">
            <svg width="28" height="10" aria-hidden="true"><line x1="0" x2="28" y1="5" y2="5" stroke={SERIES[i]} strokeWidth="2" strokeDasharray={DASH[i]} /></svg>
            {r.name}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
