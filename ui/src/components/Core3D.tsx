import { useEffect, useRef, useState } from "react";
import { STATE_VIEW, type AvatarState } from "../lib/avatarState";
import { Avatar } from "./Avatar";

// Der 3D-Kern (Plan docs/ui-dynamic-plan.md, P1): eine Hülle, die mit dem Pegel wellt (Noise-Shader, leuchtender Rand),
// eine Teilchenschale, die beim Denken Bänder bildet, und drei gekippte Ringe mit Skalenstrichen. Kein K in der Mitte.
// Alles prozedural mit three.js (lokal gebündelt, kein Netz). Ohne WebGL oder bei Kontextverlust zeichnet der 2D-Orb.
// Last: 30 fps im Ruhezustand und beim Denken (Whisper rechnet), 60 fps nur bei Sprache; nichts, wenn verdeckt;
// Notaus und offline stehen still; bei reduzierter Bewegung ein festes Bild je Zustand.

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Gibt es WebGL? Der Probe-Kontext wird sofort wieder freigegeben, damit viele Ansichten nacheinander nicht die Grenze des
 *  Browsers für gleichzeitige WebGL-Kontexte erreichen (sonst verwirft er einen echten). */
export function hasWebGL(): boolean {
  if (typeof WebGLRenderingContext === "undefined") return false;
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return false;
    try { gl.getExtension?.("WEBGL_lose_context")?.loseContext(); } catch { /* nur Aufräumen */ }
    return true;
  } catch {
    return false;
  }
}

interface Look { color: string; amp: number; band: number; spin: number; ring: number; open: boolean; wire: boolean; still: boolean; glow: number }
function look(state: AvatarState): Look {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => css.getPropertyValue(n).trim() || "#888";
  const base = { amp: 0, band: 0, spin: 0.12, ring: 0.15, open: false, wire: false, still: false, glow: 0.8 };
  switch (state) {
    case "listening": return { ...base, color: v("--amber"), amp: 1, glow: 1 };
    case "thinking": return { ...base, color: v("--arc"), band: 1, spin: 0.35, ring: 0.6, glow: 1 };
    case "speaking": return { ...base, color: v("--arc"), amp: 1, glow: 1.2 };
    case "asking": return { ...base, color: v("--amber"), spin: 0.04, ring: 0 };
    case "alarm": return { ...base, color: v("--alarm"), spin: 0.04, ring: 0 };
    case "halted": return { ...base, color: v("--text-faint"), open: true, still: true, glow: 0.5 };
    case "offline": return { ...base, color: v("--text-faint"), wire: true, still: true, glow: 0.5 };
    default: return { ...base, color: v("--arc"), glow: 0.7 };                                         // idle
  }
}

// 3D-Simplex-Noise (Ashima Arts / Stefan Gustavson, MIT), für die Wellen der Hülle.
const NOISE = `
vec3 m289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}vec4 m289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 perm(vec4 x){return m289(((x*34.0)+1.0)*x);}vec4 tis(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;
vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
i=m289(i);vec4 p=perm(perm(perm(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
float n_=0.142857142857;vec3 ns=n_*D.wyz-D.xzx;vec4 j=p-49.0*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
vec4 nm=tis(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));p0*=nm.x;p1*=nm.y;p2*=nm.z;p3*=nm.w;
vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}`;

const SHELL_VS = `${NOISE}
uniform float uTime; uniform float uAmp; uniform float uBreath;
varying vec3 vN; varying vec3 vV;
void main(){
  float n = snoise(position * 1.7 + vec3(0.0, uTime * 0.35, uTime * 0.2));
  vec3 p = position * (1.0 + uBreath + n * (0.035 + uAmp * 0.2));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;
const SHELL_FS = `
uniform vec3 uColor; uniform float uGlow;
varying vec3 vN; varying vec3 vV;
void main(){
  float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), 2.2);
  gl_FragColor = vec4(uColor * (0.10 + 1.15 * f) * uGlow, 0.18 + 0.82 * f);
}`;
const DOTS_VS = `
uniform float uTime; uniform float uBand; uniform float uAmp; uniform float uPx;
attribute float aSpeed; attribute float aBand; attribute float aSize;
varying float vA;
void main(){
  float a = uTime * aSpeed;
  vec3 p = position;
  p.y = mix(p.y, aBand, uBand);                                  // Denken: Teilchen ordnen sich in Bänder
  float r = length(p.xz); float ang = atan(p.z, p.x) + a;
  p.xz = vec2(cos(ang), sin(ang)) * mix(r, sqrt(max(0.0, 1.9 - aBand * aBand)), uBand);
  p *= 1.0 + uAmp * 0.12 * sin(uTime * 3.0 + aSpeed * 20.0);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = aSize * uPx * (6.0 / -mv.z);
  vA = 0.35 + 0.65 * smoothstep(-1.6, 1.6, p.z);
  gl_Position = projectionMatrix * mv;
}`;
const DOTS_FS = `
uniform vec3 uColor;
varying float vA;
void main(){
  vec2 c = gl_PointCoord - 0.5; float d = dot(c, c);
  if (d > 0.25) discard;
  gl_FragColor = vec4(uColor, vA * (1.0 - d * 4.0));
}`;

export function Core3D({ state, size = 220, level = 0 }: { state: AvatarState; size?: number; level?: number }) {
  const [gl, setGl] = useState(() => hasWebGL());
  const ref = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);
  const levelRef = useRef(level);
  const sizeRef = useRef(size);
  const kick = useRef<() => void>(() => {});
  stateRef.current = state;
  levelRef.current = level;
  sizeRef.current = size;
  const label = STATE_VIEW[state].label;

  useEffect(() => { kick.current(); }, [state, size]);

  useEffect(() => {
    if (!gl) return;
    const canvas = ref.current;
    if (!canvas) return;
    let alive = true, raf = 0;
    let cleanup = () => {};
    void import("three").then((T) => {
      if (!alive) return;
      let renderer: InstanceType<typeof T.WebGLRenderer>;
      try {
        renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
      } catch {
        setGl(false);
        return;
      }
      const onLost = (e: Event) => { e.preventDefault(); setGl(false); };
      canvas.addEventListener("webglcontextlost", onLost);
      const scene = new T.Scene();
      const camera = new T.PerspectiveCamera(35, 1, 0.1, 50);
      camera.position.set(0, 0, 6.4);
      const color = new T.Color();
      const target = new T.Color();

      const shellU = { uTime: { value: 0 }, uAmp: { value: 0 }, uBreath: { value: 0 }, uColor: { value: color }, uGlow: { value: 0.8 } };
      const shellMat = new T.ShaderMaterial({ uniforms: shellU, vertexShader: SHELL_VS, fragmentShader: SHELL_FS,
        transparent: true, depthWrite: false, blending: T.AdditiveBlending });
      const shell = new T.Mesh(new T.IcosahedronGeometry(1, 20), shellMat);
      scene.add(shell);

      const N = 1600;                                                 // Teilchenschale (feste Verteilung, kein Zufall pro Start)
      const pos = new Float32Array(N * 3), speed = new Float32Array(N), band = new Float32Array(N), psize = new Float32Array(N);
      for (let i = 0; i < N; i++) {
        const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
        const R = 1.22 + 0.2 * Math.abs(Math.sin(i * 12.9898));
        pos.set([Math.cos(th) * r * R, y * R, Math.sin(th) * r * R], i * 3);
        speed[i] = 0.15 + 0.35 * Math.abs(Math.sin(i * 78.233));
        band[i] = [-0.75, 0, 0.75][i % 3] + 0.08 * Math.sin(i);
        psize[i] = 1.2 + 1.6 * Math.abs(Math.cos(i * 3.7));
      }
      const dotsGeo = new T.BufferGeometry();
      dotsGeo.setAttribute("position", new T.BufferAttribute(pos, 3));
      dotsGeo.setAttribute("aSpeed", new T.BufferAttribute(speed, 1));
      dotsGeo.setAttribute("aBand", new T.BufferAttribute(band, 1));
      dotsGeo.setAttribute("aSize", new T.BufferAttribute(psize, 1));
      const dotsU = { uTime: { value: 0 }, uBand: { value: 0 }, uAmp: { value: 0 }, uPx: { value: 1 }, uColor: { value: color } };
      const dotsMat = new T.ShaderMaterial({ uniforms: dotsU, vertexShader: DOTS_VS, fragmentShader: DOTS_FS,
        transparent: true, depthWrite: false, blending: T.AdditiveBlending });
      scene.add(new T.Points(dotsGeo, dotsMat));

      const lineMat = new T.LineBasicMaterial({ color, transparent: true, opacity: 0.55 });
      const ringMat = new T.MeshBasicMaterial({ color, transparent: true, opacity: 0.7 });
      const rings: { g: InstanceType<typeof T.Group>; full: InstanceType<typeof T.Mesh>; open: InstanceType<typeof T.Mesh>; dir: number }[] = [];
      const geos: { dispose(): void }[] = [shell.geometry, dotsGeo];
      [[1.55, 1.15, 0.2, 1], [1.7, -0.5, 0.9, -1], [1.85, 0.35, -0.7, 1]].forEach(([r, rx, rz, dir]) => {
        const g = new T.Group();
        const fullGeo = new T.TorusGeometry(r, 0.008, 6, 220), openGeo = new T.TorusGeometry(r, 0.008, 6, 220, Math.PI * 1.45);
        const full = new T.Mesh(fullGeo, ringMat), open = new T.Mesh(openGeo, ringMat);
        const ticks: number[] = [];
        for (let i = 0; i < 72; i++) {
          const a = (i / 72) * Math.PI * 2, l = i % 6 === 0 ? 0.09 : 0.045;
          ticks.push(Math.cos(a) * r, Math.sin(a) * r, 0, Math.cos(a) * (r + l), Math.sin(a) * (r + l), 0);
        }
        const tickGeo = new T.BufferGeometry();
        tickGeo.setAttribute("position", new T.Float32BufferAttribute(ticks, 3));
        g.add(full, open, new T.LineSegments(tickGeo, lineMat));
        g.rotation.set(rx, 0, rz);
        scene.add(g);
        rings.push({ g, full, open, dir });
        geos.push(fullGeo, openGeo, tickGeo);
      });

      const looks = new Map<AvatarState, Look>();                       // Farben einmal je Zustand lesen, nicht pro Frame
      const lookOf = (s: AvatarState) => { let l = looks.get(s); if (!l) { l = look(s); looks.set(s, l); } return l; };
      let last = 0, smooth = 0, t = 0, settle = 0, alarmAt = -1, prev: AvatarState | null = null;
      const cur = { amp: 0, band: 0, spin: 0.12, ring: 0.15, glow: 0.8 };
      const resize = () => {
        const s = sizeRef.current, dpr = Math.min(2, window.devicePixelRatio || 1);
        renderer.setPixelRatio(dpr);
        renderer.setSize(s, s, false);
        dotsU.uPx.value = dpr * (s / 300);
      };
      const step = (dt: number, instant: boolean) => {
        const st = stateRef.current, L = lookOf(st);
        if (st !== prev) { if (st === "alarm") alarmAt = t; prev = st; settle = 0; }
        target.set(L.color);
        const k = instant ? 1 : Math.min(1, dt * 5);                 // weich überblenden (~220 ms)
        color.lerp(target, k);
        const lv = levelRef.current;
        smooth += (lv - smooth) * (lv > smooth ? 0.5 : 0.1);
        for (const key of ["band", "spin", "ring", "glow"] as const) cur[key] += (L[key] - cur[key]) * k;
        cur.amp += (L.amp * smooth - cur.amp) * k;
        if (!L.still) t += dt * (st === "idle" ? 1 : 1.4);
        shellU.uTime.value = t; dotsU.uTime.value = t * 2;
        shellU.uAmp.value = cur.amp; dotsU.uAmp.value = cur.amp; dotsU.uBand.value = cur.band;
        const pulse = alarmAt >= 0 && t - alarmAt < 0.6 ? -0.08 * Math.sin(((t - alarmAt) / 0.6) * Math.PI) : 0;   // Alarm: einmal zusammenziehen
        shellU.uBreath.value = (st === "idle" ? 0.02 * (1 + Math.sin((t / 4) * Math.PI * 2)) : 0) + pulse;
        shellU.uGlow.value = cur.glow;
        shellMat.wireframe = L.wire;
        shell.rotation.y += dt * cur.spin * (L.still ? 0 : 1);
        rings.forEach((r) => {
          r.full.visible = !L.open; r.open.visible = L.open;
          if (!L.still) r.g.rotation.z += dt * cur.ring * r.dir;
        });
      };
      const draw = () => renderer.render(scene, camera);
      const frame = (now: number) => {
        raf = requestAnimationFrame(frame);
        if (document.hidden) return;                                  // verdeckt: nichts zeichnen
        const st = stateRef.current;
        const gap = st === "speaking" || st === "listening" ? 16 : 33;
        if (now - last < gap) return;
        const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
        last = now;
        if (lookOf(st).still && (settle += dt) > 0.6) return;            // Notaus/offline: nach dem Überblenden stillstehen
        step(dt, false);
        draw();
      };
      kick.current = () => {
        resize();
        if (reduced()) { step(0, true); draw(); }                      // festes Bild je Zustand
        settle = 0;
      };
      kick.current();
      if (!reduced()) raf = requestAnimationFrame(frame);
      cleanup = () => {
        cancelAnimationFrame(raf);
        canvas.removeEventListener("webglcontextlost", onLost);
        geos.forEach((g) => g.dispose());
        [shellMat, dotsMat, lineMat, ringMat].forEach((m) => m.dispose());
        renderer.dispose();
        kick.current = () => {};
      };
    }).catch(() => { if (alive) setGl(false); });
    return () => { alive = false; cleanup(); };
  }, [gl]);

  if (!gl) return <Avatar state={state} size={size} level={level} />;
  return <canvas ref={ref} className="core3d" role="img" aria-label={label} style={{ width: size, height: size }} />;
}
