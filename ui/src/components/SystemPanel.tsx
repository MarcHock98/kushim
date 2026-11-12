import type { ReactNode } from "react";
import { IconWarn } from "./Icons";

// Panel „Systemzustand“ (Design „Jarvin Cockpit“): Kacheln für CPU, Arbeitsspeicher, GPU und Netz, Balken für Datenträger
// und Akku, darunter System und Laufzeit. Zeigt nur, was `system.stats` liefert; fehlt ein Wert, steht dort „unbekannt“.
// Ab dem Warnwert wird ein Wert bernsteinfarben und bekommt Symbol und Wort („hoch“), nie nur Farbe.

type Pct = { percent: number };
export interface SysData {
  cpu: Pct | null;
  memory: (Pct & { used_gb: number; total_gb: number }) | null;
  gpu: (Pct & { vram_used_mb: number; vram_total_mb: number; temp_c: number | null }) | null;
  disk: (Pct & { used_gb: number; total_gb: number }) | null;
  battery: { present: boolean; percent: number | null; on_ac: boolean | null } | null;
  net: { down_mbit: number; up_mbit: number } | null;
  system: { os: string | null; uptime_s: number | null };
  warn_at: number;
}

const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const obj = (v: unknown) => (v && typeof v === "object" ? (v as Record<string, unknown>) : null);
const nums = (o: Record<string, unknown> | null, keys: string[]) => !!o && keys.every((k) => num(o[k]));

/** Antwort des Backends prüfen, nicht blind vertrauen: jeder Teil, der nicht passt, wird „unbekannt“. */
export function parseSystem(r: Record<string, unknown>): SysData {
  const cpu = obj(r.cpu), mem = obj(r.memory), gpu = obj(r.gpu), disk = obj(r.disk), bat = obj(r.battery), net = obj(r.net), sys = obj(r.system);
  return {
    cpu: nums(cpu, ["percent"]) ? { percent: cpu!.percent as number } : null,
    memory: nums(mem, ["percent", "used_gb", "total_gb"]) ? (mem as unknown as SysData["memory"]) : null,
    gpu: nums(gpu, ["percent", "vram_used_mb", "vram_total_mb"])
      ? { ...(gpu as unknown as NonNullable<SysData["gpu"]>), temp_c: num(gpu!.temp_c) ? gpu!.temp_c : null } : null,
    disk: nums(disk, ["percent", "used_gb", "total_gb"]) ? (disk as unknown as SysData["disk"]) : null,
    battery: bat && typeof bat.present === "boolean"
      ? { present: bat.present, percent: num(bat.percent) ? bat.percent : null, on_ac: typeof bat.on_ac === "boolean" ? bat.on_ac : null } : null,
    net: nums(net, ["down_mbit", "up_mbit"]) ? (net as unknown as SysData["net"]) : null,
    system: { os: typeof sys?.os === "string" ? sys.os.slice(0, 40) : null, uptime_s: num(sys?.uptime_s) ? sys!.uptime_s as number : null },
    warn_at: num(r.warn_at) ? r.warn_at : 80,
  };
}

const de = (v: number, digits = 1) => v.toLocaleString("de-DE", { maximumFractionDigits: digits });
const clamp = (v: number) => Math.max(0, Math.min(100, v));
const UNKNOWN = "unbekannt";

function uptime(s: number): string {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d} T ${h} Std` : h > 0 ? `${h} Std ${m} Min` : `${m} Min`;
}

function Bar({ value, warn }: { value: number; warn: boolean }) {
  return <div className={`track${warn ? " is-warn" : ""}`} aria-hidden="true"><div className="fill" style={{ width: `${clamp(value)}%` }} /></div>;
}

function High() {
  return <span className="sys-high"><IconWarn /> hoch</span>;
}

function Tile({ label, big, warn, bar, children }: { label: string; big: string; warn?: boolean; bar?: number; children?: ReactNode }) {
  return (
    <div className={`sys-tile${warn ? " is-warn" : ""}`}>
      <span className="label">{label}</span>
      <span className="sys-big">{big}{warn && <High />}</span>
      {bar !== undefined && <Bar value={bar} warn={!!warn} />}
      {children}
    </div>
  );
}

export function SystemPanel({ data, unavailable = false }: { data: SysData | null; unavailable?: boolean }) {
  const head = (note: string) => (
    <div className="panel-head"><h2 id="sys-h">Systemzustand</h2><span className="label">{note}</span></div>
  );
  if (!data) {
    return (
      <section className="home-sys panel" aria-labelledby="sys-h">
        {head(unavailable ? "nicht verfügbar" : "lädt")}
        <p className="hint">{unavailable ? "Dieser Dienst liefert keine Systemwerte. Starte kushim neu (kushim app)." : "Systemwerte werden gelesen …"}</p>
      </section>
    );
  }
  const w = data.warn_at;
  const { cpu, memory: mem, gpu, disk, battery: bat, net } = data;
  const gpuHot = !!gpu && (gpu.percent >= w || (gpu.temp_c !== null && gpu.temp_c >= w));
  const high = [cpu && cpu.percent >= w, mem && mem.percent >= w, gpuHot, disk && disk.percent >= w].filter(Boolean).length;
  const known = [cpu, mem, gpu, disk, net].filter(Boolean).length;
  const note = known === 0 ? "Werte unbekannt" : high === 0 ? `Alle Werte unter ${w} %` : `${high} ${high === 1 ? "Wert" : "Werte"} hoch`;

  return (
    <section className="home-sys panel" aria-labelledby="sys-h">
      {head(note)}
      <div className="sys-tiles">
        <Tile label="CPU Auslastung" big={cpu ? `${de(cpu.percent, 0)} %` : UNKNOWN} warn={!!cpu && cpu.percent >= w} bar={cpu?.percent} />
        <Tile label="Arbeitsspeicher" big={mem ? `${de(mem.percent, 0)} %` : UNKNOWN} warn={!!mem && mem.percent >= w} bar={mem?.percent}>
          {mem && <span className="sys-data">{de(mem.used_gb)} von {de(mem.total_gb)} GB</span>}
        </Tile>
        <Tile label="GPU Auslastung" big={gpu ? `${de(gpu.percent, 0)} %` : UNKNOWN} warn={gpuHot} bar={gpu?.percent}>
          {gpu && (
            <span className="sys-data">
              VRAM {de(gpu.vram_used_mb / 1024)} von {de(gpu.vram_total_mb / 1024)} GB{gpu.temp_c !== null && ` · ${de(gpu.temp_c, 0)} °C`}
            </span>
          )}
        </Tile>
        <Tile label="Netzwerk" big={net ? de(net.down_mbit) : UNKNOWN}>
          {net && <><span className="sys-data sys-strong">↓ Mbit/s</span><span className="sys-data">↑ {de(net.up_mbit)} Mbit/s</span></>}
        </Tile>
      </div>

      <div className="sys-row">
        <div className="sys-row-head">
          <span className="label">Datenträger</span>
          <span className="sys-data sys-strong">{disk ? <>{de(disk.used_gb, 0)} von {de(disk.total_gb, 0)} GB · {de(disk.percent, 0)} %{disk.percent >= w && <High />}</> : UNKNOWN}</span>
        </div>
        {disk && <Bar value={disk.percent} warn={disk.percent >= w} />}
      </div>
      <div className="sys-row">
        <div className="sys-row-head">
          <span className="label">Akku</span>
          <span className="sys-data sys-strong">
            {!bat ? UNKNOWN : !bat.present ? "kein Akku" : `${bat.percent === null ? UNKNOWN : `${bat.percent} %`}${bat.on_ac === null ? "" : bat.on_ac ? " · Netzbetrieb" : " · Akkubetrieb"}`}
          </span>
        </div>
        {bat?.present && bat.percent !== null && <Bar value={bat.percent} warn={false} />}
      </div>

      <dl className="sys-table">
        <div><dt>System</dt><dd>{data.system.os ?? UNKNOWN}</dd></div>
        <div><dt>Laufzeit</dt><dd>{data.system.uptime_s === null ? UNKNOWN : uptime(data.system.uptime_s)}</dd></div>
      </dl>
    </section>
  );
}
