// S2: what HyperFrames' compiler does to the fonts of a page, offline: calls its own injectDeterministicFontFaces on index.html and prints
// the families it considered, and the @font-face rules it added (family, weight, source kind and size, never the font bytes).
import fs from "node:fs";
const { loadProducer } = await import("/opt/hf/node_modules/hyperframes/dist/producer-PRYLGX6W.js");
const mod = await loadProducer();
const html = fs.readFileSync(process.argv[2], "utf8");
const logs = [];
const logger = { info: (m) => logs.push("info " + m), warn: (m) => logs.push("warn " + m), error: (m) => logs.push("error " + m), debug: () => {} };
const t0 = Date.now();
const out = await mod.injectDeterministicFontFaces(html, { logger, failClosedFontFetch: false, allowSystemFontCapture: false });
const added = out.match(/<style data-hyperframes-deterministic-fonts[^>]*>([\s\S]*?)<\/style>/);
const rules = added ? [...added[1].matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1].replace(/url\(data:[^)]{20,}\)/g, "url(data:…)").replace(/\s+/g, " ").trim().slice(0, 240)) : [];
console.log(JSON.stringify({ ms: Date.now() - t0, injected: !!added, rules, logs: logs.slice(0, 20), changed: out !== html }));
