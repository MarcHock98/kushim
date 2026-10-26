import "@testing-library/jest-dom/vitest";

// jsdom kennt weder matchMedia noch Canvas 2D: schlanke Stubs, die Aufrufe nur entgegennehmen.
if (!window.matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} })) as typeof window.matchMedia;
}
const ctx = new Proxy({}, { get: (_t, k) => (k === "canvas" ? null : () => {}), set: () => true });
HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext;
