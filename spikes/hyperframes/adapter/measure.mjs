// S2 measurement, run INSIDE the image (no network: the page is served on the loopback by this file). Two modes:
//   node measure.mjs boxes /work/project /work/out/boxes.json     per output frame: every drawn caption word, pill, card (check C6)
//   node measure.mjs fonts /work/project /work/out/fonts.json     the fonts the page loaded and drew with (check C5)
//
// It loads the project's index.html the way HyperFrames' own renderer does: the runtime script of the pinned package (dist/hyperframe.runtime.iife.js)
// is injected into the page and the variables of vars.json are given as window.__hfVariables (the value `hyperframes render --variables-file` supplies);
// each frame is then reached through `window.__player.renderSeek(t)`, the function the renderer itself calls before it captures a frame.
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const require = createRequire("/opt/hf/package.json");
const puppeteer = require("puppeteer-core");
const fontkit = require("fontkit");
const [mode, projectDir, outPath] = process.argv.slice(2);
const runtimeJs = fs.readFileSync("/opt/hf/node_modules/hyperframes/dist/hyperframe.runtime.iife.js", "utf8");
const vars = JSON.parse(fs.readFileSync(path.join(projectDir, "vars.json"), "utf8"));
const fps = vars.fps;
const frames = Math.round(vars.duration * fps);

const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".mov": "video/quicktime", ".mp4": "video/mp4" };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (p === "/__runtime.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(runtimeJs); }
  if (p === "/") p = "/index.html";
  const file = path.join(projectDir, path.normalize(p).replace(/^(\.\.[/\\])+/, ""));
  if (!file.startsWith(projectDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
  const size = fs.statSync(file).size;
  const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
  if (range && !p.endsWith(".html")) {
    const start = range[1] ? parseInt(range[1], 10) : 0, end = range[2] ? Math.min(parseInt(range[2], 10), size - 1) : size - 1;
    res.writeHead(206, { "content-type": MIME[path.extname(file)] || "application/octet-stream", "accept-ranges": "bytes", "content-range": `bytes ${start}-${end}/${size}`, "content-length": end - start + 1 });
    return fs.createReadStream(file, { start, end }).pipe(res);
  }
  let body = fs.readFileSync(file);
  if (p === "/index.html") {
    let text = body.toString("utf8");
    const faces = [...fs.readFileSync(path.join(projectDir, "index.html"), "utf8").matchAll(/@font-face \{ font-family: "([^"]+)"; font-weight: (\d+); src: url\("fonts\/([a-z0-9-]+\.woff2)"\)/g)]
      .map((x) => ({ family: x[1], weight: x[2], b64: fs.readFileSync(path.join(projectDir, "fonts", x[3])).toString("base64") }));
    // The page's own @font-face rules are replaced by FontFace objects built from the same three files (HyperFrames' compiler does the equivalent: it
    // embeds each local font file as a data URI). Only the files of fonts/ are registered: nothing else can supply a glyph.
    text = text.replace(/@font-face \{[^}]*\}/g, "");
    const reg = "<script>(function(){var F=" + JSON.stringify(faces) + ";window.__hfFaceLoads=F.map(function(f){var b=Uint8Array.from(atob(f.b64),function(c){return c.charCodeAt(0)});var ff=new FontFace(f.family,b.buffer,{weight:f.weight});document.fonts.add(ff);return ff.load();});})();</script>";
    const inject = reg + "<script>window.__hfVariables = " + JSON.stringify(vars).replace(/</g, "\\u003c") + ";</script><script src=\"/__runtime.js\"></script>";
    body = Buffer.from(text.replace("<head>", "<head>" + inject), "utf8");
  }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream", "accept-ranges": "bytes" });
  res.end(body);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const browser = await puppeteer.launch({
  executablePath: "/opt/chrome/chrome-headless-shell", headless: "shell",
  args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--font-render-hinting=none", "--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
const consoleErrors = [];
page.on("console", (m) => { if (["error", "warning"].includes(m.type())) consoleErrors.push("console " + m.type() + ": " + m.text().slice(0, 300)); });
page.on("pageerror", (e) => consoleErrors.push(String(e).slice(0, 300)));
page.on("requestfailed", (r) => consoleErrors.push("requestfailed " + r.url().slice(0, 90) + " " + (r.failure() && r.failure().errorText)));
page.on("response", (r) => { if (r.url().includes("fonts/")) consoleErrors.push("font response " + r.status() + " " + r.url().slice(-30) + " " + (r.headers()["content-length"] || "")); });
await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: "load", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));
await page.waitForFunction(() => window.__player && window.__player.renderSeek && window.__timelines && window.__timelines.main, { timeout: 5000, polling: 100 }).catch(() => {});
console.error('FONTS', JSON.stringify(await page.evaluate(async () => { let r; try { await window.__hfFonts; r = 'ok'; } catch (e) { r = String(e); } return { r, faces: [...document.fonts].map((f) => f.family + ' ' + f.weight + ' ' + f.status) }; })));
await new Promise((r) => setTimeout(r, 300));

const SEL = {
  caption: [".hl-word", ".caption-pill", ".caption-word", ".kt-word"],
  card: [".cu-stage", ".tc-card", ".card-label", ".sp-badge"],
};

async function measureFrame(f) {
  return page.evaluate(async (t, SEL) => {
    window.__player.renderSeek(t);
    await new Promise((r) => requestAnimationFrame(() => r()));
    const out = [];
    for (const [zone, sels] of Object.entries(SEL)) {
      for (const sel of sels) {
        for (const el of document.querySelectorAll(sel)) {
          let vis = true, op = 1;
          for (let n = el; n && n !== document.body; n = n.parentElement) {
            const cs = getComputedStyle(n);
            op *= parseFloat(cs.opacity);
            if (cs.visibility === "hidden" || cs.display === "none" || parseFloat(cs.opacity) < 0.02) { vis = false; break; }
          }
          if (!vis) continue;
          const r = el.getBoundingClientRect();
          const rg = document.createRange(); rg.selectNodeContents(el); const t = rg.getBoundingClientRect();
          if (r.width > 0 && r.height > 0) out.push({ zone, cls: sel, x: r.x, y: r.y, w: r.width, h: r.height, op: Math.round(op * 100) / 100, tx: t.x, ty: t.y, tw: t.width, th: t.height });
        }
      }
    }
    return out;
  }, f / fps, SEL);
}

if (mode === "boxes") {
  const result = { frames, fps, per_frame: [], console_errors: consoleErrors };
  for (let f = 0; f < frames; f++) result.per_frame.push(await measureFrame(f));
  fs.writeFileSync(outPath, JSON.stringify(result));
} else if (mode === "fonts") {
  const cdp = await page.createCDPSession();
  await cdp.send("DOM.enable"); await cdp.send("CSS.enable");
  const loaded = await page.evaluate(() => [...document.fonts].map((f) => ({ family: f.family.replace(/"/g, ""), weight: f.weight, status: f.status })));
  const seen = new Map();
  const pt = new Set();
  const sample = (vars.words || []).map((w, i) => i);
  // sample the frames where each caption word is on screen, plus the frames of every card
  const times = [];
  for (const w of vars.words) times.push((w.start + w.end) / 2);
  for (const b of vars.beats) { times.push(b.start + 0.3); times.push(b.start + b.dur * 0.6); }
  const root = (await cdp.send("DOM.getDocument", { depth: 0 })).root.nodeId;
  for (const t of times) {
    await page.evaluate(async (t) => { window.__player.renderSeek(t); await new Promise((r) => requestAnimationFrame(() => r())); }, t);
    const { nodeIds } = await cdp.send("DOM.querySelectorAll", { nodeId: root, selector: ".hl-word-text, .caption-word, .kt-word, .cu-value, .cu-affix, .tc-quote, .tc-author, .tc-handle, .card-label, .sp-label" });
    for (const nodeId of nodeIds) {
      const visible = await page.evaluate((id) => true, nodeId);
      const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
      const txt = (await cdp.send("DOM.getOuterHTML", { nodeId })).outerHTML.replace(/<[^>]+>/g, "");
      for (const ch of txt) if ("\u00e3\u00f5\u00e7\u00e9\u00ea\u00e1\u00ed\u00fa\u00c3\u00d5\u00c7\u00c9\u00ca\u00c1\u00cd\u00da".includes(ch)) pt.add(ch);
      for (const f of fonts) {
        const k = `${f.familyName}|${f.postScriptName}|custom=${f.isCustomFont}`;
        const e = seen.get(k) || { family: f.familyName, postScriptName: f.postScriptName, isCustomFont: f.isCustomFont, glyphCount: 0 };
        e.glyphCount += f.glyphCount; seen.set(k, e);
      }
    }
  }
  // glyph coverage of the allow-listed files for the pt-BR set (fontkit reads the file the page was given)
  const coverage = {};
  const dir = path.join(projectDir, "fonts");
  for (const file of fs.readdirSync(dir)) {
    const font = fontkit.openSync(path.join(dir, file));
    coverage[file] = Object.fromEntries([..."\u00e3\u00f5\u00e7\u00e9\u00ea\u00e1\u00ed\u00fa\u00c3\u00d5\u00c7\u00c9\u00ca\u00c1\u00cd\u00da"].map((c) => [c, font.hasGlyphForCodePoint(c.codePointAt(0))]));
  }
  fs.writeFileSync(outPath, JSON.stringify({ loaded_font_faces: loaded, platform_fonts: [...seen.values()], pt_br_chars_on_screen: [...pt].sort().join(""), glyph_coverage: coverage, console_errors: consoleErrors, sampled_times: times.length }));
}
await browser.close();
server.close();
