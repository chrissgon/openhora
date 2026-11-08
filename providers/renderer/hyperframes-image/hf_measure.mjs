// The measure step of the HyperFrames engine (package V3b-2). It runs INSIDE the HyperFrames image, after the render, with no network:
//
//   node /opt/hf-run/hf_measure.mjs <project folder> <boxes.json to write>
//
// It serves the project on 127.0.0.1 itself, loads index.html the way HyperFrames' own renderer does (the runtime script of the pinned package
// is injected and the variables of vars.json are given as window.__hfVariables, the value `hyperframes render --variables-file` supplies),
// reaches every output frame with window.__player.renderSeek(f / fps), the function the renderer calls before it captures a frame, and writes,
// for every frame, the boxes the page itself reports. The encode stage's gate (providers/renderer/_hf_gate.py) judges them; this file judges
// nothing but its own limits and the fonts.
//
//   - every visible descendant of a gsap instance (.hf-inst), its rectangle clipped to the instance's own (the band the block may draw in);
//     the rectangles of the text inside it are NOT clipped (glyph: true), so text that spills out of its band is seen;
//   - every visible renderat page (iframe.hf-ra): each [data-zone] element of its document and the rectangles of its text, offset by the
//     iframe's own position.
//
// Output: {"fonts": [...], "fps": n, "frames": n, "per_frame": [[box, ...], ...], "schema": 1}, keys sorted, numbers rounded to 0.1 px, each box
// {"glyph", "h", "key", "w", "x", "y", "zone"}. Every 30th frame the platform fonts of every text element are read (CDP CSS.getPlatformFontsForNode):
// each must be Inter or JetBrains Mono and a custom font (the three files of /project/fonts), else the refusal `font_not_allowed` (field `drawn`).
//
// A refusal is a row {"ok": false, "code", "field"} written to the output path with exit code 1: boxes_too_many (more than MAX_BOXES_PER_FRAME in
// a frame), boxes_too_large (more than MAX_OUT_BYTES of boxes), font_not_allowed, measure_failed (a page error, a console error, a request
// outside the loopback, a page that never became ready). The page is allowed to request only the loopback server this file starts.
import { createRequire } from "node:module";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const HF_ROOT = "/opt/hf";
const RUNTIME_FILE = "/opt/hf/node_modules/hyperframes/dist/hyperframe.runtime.iife.js";
const LOOPBACK = "127.0.0.1";
const MAX_BOXES_PER_FRAME = 2000;
const MAX_OUT_BYTES = 64 * 1024 * 1024;
const FONT_EVERY = 30;
const ALLOWED_FAMILIES = ["Inter", "JetBrains Mono"];
const READY_TIMEOUT_MS = 30000;
const LOAD_TIMEOUT_MS = 60000;

const [projectArg, outPath] = process.argv.slice(2);
if (!projectArg || !outPath) {
  console.error("usage: hf_measure.mjs <project folder> <boxes.json>");
  process.exit(2);
}

class Refusal extends Error {
  constructor(code, field) {
    super(code + " " + field);
    this.code = code;
    this.field = field;
  }
}

function writeRefusal(code, field) {
  fs.writeFileSync(outPath, JSON.stringify({ ok: false, code, field: String(field).slice(0, 40) }));
}

const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".woff2": "font/woff2", ".mov": "video/quicktime", ".mp4": "video/mp4" };

// What runs inside the page, once per frame: seek, wait one animation frame, collect the boxes.
const IN_PAGE = `window.__hfMeasure = async function (t) {
  window.__player.renderSeek(t);
  await new Promise((r) => requestAnimationFrame(() => r()));
  const out = [];
  const R1 = (x) => Math.round(x * 10) / 10;
  function visible(el, view) {
    // visibility is inherited, so the element's own computed value is the answer; opacity multiplies down the chain
    const cs = view.getComputedStyle(el);
    if (cs.visibility !== "visible" || cs.display === "none") return false;
    let op = 1;
    for (let n = el; n; n = n.parentElement) op *= parseFloat(view.getComputedStyle(n).opacity);
    return op > 0;
  }
  function push(zone, key, glyph, left, top, width, height) {
    out.push({ glyph, h: R1(height), key, w: R1(width), x: R1(left), y: R1(top), zone });
  }
  function glyphs(root, zoneOf, key, ox, oy) {
    const doc = root.ownerDocument, view = doc.defaultView;
    const walker = doc.createTreeWalker(root, 4);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const parent = n.parentElement;
      if (!parent || !n.nodeValue.trim() || /^(script|style|title|noscript)$/i.test(parent.tagName) || !visible(parent, view)) continue;
      const range = doc.createRange();
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 0 && r.height > 0) push(zoneOf(parent), key, true, r.left + ox, r.top + oy, r.width, r.height);
    }
  }
  const view = window;
  for (const inst of document.querySelectorAll(".hf-inst")) {
    const zone = inst.getAttribute("data-hf-zone") || "", key = inst.id;
    const clip = inst.getBoundingClientRect();
    for (const el of inst.querySelectorAll("*")) {
      if (!visible(el, view)) continue;
      const r = el.getBoundingClientRect();
      const x0 = Math.max(r.left, clip.left), y0 = Math.max(r.top, clip.top), x1 = Math.min(r.right, clip.right), y1 = Math.min(r.bottom, clip.bottom);
      if (r.width > 0 && r.height > 0 && x1 > x0 && y1 > y0) push(zone, key, false, x0, y0, x1 - x0, y1 - y0);
    }
    glyphs(inst, () => zone, key, 0, 0);
  }
  for (const frame of document.querySelectorAll("iframe.hf-ra")) {
    if (!visible(frame, view)) continue;
    const doc = frame.contentDocument;
    if (!doc || !doc.body) continue;
    const zone = frame.getAttribute("data-hf-zone") || "", key = frame.getAttribute("data-hf-key") || "", box = frame.getBoundingClientRect();
    for (const el of doc.querySelectorAll("[data-zone]")) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) push(el.getAttribute("data-zone") || "", key, false, r.left + box.left, r.top + box.top, r.width, r.height);
    }
    glyphs(doc.body, (el) => { const z = el.closest("[data-zone]"); return z ? z.getAttribute("data-zone") || "" : zone; }, key, box.left, box.top);
  }
  return out;
};`;

async function main() {
  const root = fs.realpathSync(projectArg);
  const require = createRequire(HF_ROOT + "/package.json");
  const puppeteer = require("puppeteer-core");
  const chrome = process.env.PUPPETEER_EXECUTABLE_PATH;
  if (!chrome) throw new Refusal("measure_failed", "browser");
  const runtimeJs = fs.readFileSync(RUNTIME_FILE, "utf8");
  const vars = JSON.parse(fs.readFileSync(path.join(root, "vars.json"), "utf8"));
  const fps = vars.fps;
  const frames = Math.round(vars.duration * fps);
  if (!Number.isInteger(fps) || fps < 1 || !Number.isInteger(frames) || frames < 1) throw new Refusal("measure_failed", "vars");

  // The page's own @font-face rules are replaced by FontFace objects built from the files of fonts/ (HyperFrames' compiler does the equivalent:
  // it embeds each local font file). Only the files of fonts/ can be registered: nothing else can supply a glyph.
  const b64 = new Map();
  function faceOf(body) {
    const family = /font-family\s*:\s*"([^"]+)"/.exec(body), weight = /font-weight\s*:\s*(\d+)/.exec(body);
    const src = /url\("(?:\.\.\/)?fonts\/([a-z0-9-]+\.woff2)"\)/.exec(body);
    if (!family || !weight || !src) return null;
    const file = path.join(root, "fonts", src[1]);
    if (!fs.existsSync(file)) return null;
    if (!b64.has(file)) b64.set(file, fs.readFileSync(file).toString("base64"));
    return { family: family[1], weight: weight[1], b64: b64.get(file) };
  }
  function withFonts(text) {
    const faces = [...text.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => faceOf(m[1])).filter(Boolean);
    const stripped = text.replace(/@font-face\s*\{[^}]*\}/g, "");
    const script = "<script>(function(){var F=" + JSON.stringify(faces) + ";window.__hfFaceLoads=F.map(function(f){var b=Uint8Array.from(atob(f.b64),function(c){return c.charCodeAt(0)});" +
      "var ff=new FontFace(f.family,b.buffer,{weight:f.weight});document.fonts.add(ff);return ff.load();});})();</script>";
    return { stripped, script };
  }

  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, "http://" + LOOPBACK).pathname);
    if (p === "/__runtime.js") { res.writeHead(200, { "content-type": "text/javascript" }); return res.end(runtimeJs); }
    if (p === "/favicon.ico") { res.writeHead(204); return res.end(); }
    if (p === "/") p = "/index.html";
    const file = path.resolve(root, "." + path.normalize(p));
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end(); }
    const size = fs.statSync(file).size;
    const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
    if (range && !p.endsWith(".html")) {
      const start = range[1] ? parseInt(range[1], 10) : 0, end = range[2] ? Math.min(parseInt(range[2], 10), size - 1) : size - 1;
      res.writeHead(206, { "content-type": MIME[path.extname(file)] || "application/octet-stream", "accept-ranges": "bytes", "content-range": "bytes " + start + "-" + end + "/" + size, "content-length": end - start + 1 });
      return fs.createReadStream(file, { start, end }).pipe(res);
    }
    let body = fs.readFileSync(file);
    if (p.endsWith(".html")) {
      const { stripped, script } = withFonts(body.toString("utf8"));
      let inject = script;
      if (p === "/index.html") inject += "<script>window.__hfVariables = " + JSON.stringify(vars).replace(/</g, "\\u003c") + ";</script><script src=\"/__runtime.js\"></script>";
      body = Buffer.from(stripped.replace("<head>", "<head>" + inject), "utf8");
    }
    res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream", "accept-ranges": "bytes" });
    res.end(body);
  });
  await new Promise((r) => server.listen(0, LOOPBACK, r));
  const origin = "http://" + LOOPBACK + ":" + server.address().port + "/";

  let browser = null;
  try {
    browser = await puppeteer.launch({
      executablePath: chrome, headless: "shell",
      args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--font-render-hinting=none", "--hide-scrollbars"],
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1080, height: 1920, deviceScaleFactor: 1 });
    const problems = [];
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      const url = req.url();
      if (url.startsWith(origin) || url.startsWith("data:") || url.startsWith("blob:")) req.continue();
      else { problems.push("request outside the loopback"); req.abort(); }
    });
    page.on("console", (m) => { if (m.type() === "error") problems.push("console error"); });
    page.on("pageerror", () => problems.push("page error"));
    page.on("requestfailed", (r) => { if (r.url().startsWith(origin)) problems.push("request failed"); });
    await page.goto(origin + "index.html", { waitUntil: "load", timeout: LOAD_TIMEOUT_MS });
    await page.waitForFunction(() => window.__player && window.__player.renderSeek && window.__timelines && window.__timelines.main, { timeout: READY_TIMEOUT_MS, polling: 100 })
      .catch(() => { throw new Refusal("measure_failed", "player"); });
    for (const frame of page.frames()) await frame.evaluate(() => Promise.all(window.__hfFaceLoads || []));
    await new Promise((r) => setTimeout(r, 500));
    await page.evaluate(IN_PAGE);

    const cdp = await page.createCDPSession();
    await cdp.send("DOM.enable");
    await cdp.send("CSS.enable");
    const fonts = new Map();
    async function checkFonts() {
      const { root: doc } = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
      const ids = [];
      (function walk(node) {
        if (node.nodeType === 1 && !/^(SCRIPT|STYLE|TITLE|NOSCRIPT)$/.test(node.nodeName) && (node.children || []).some((c) => c.nodeType === 3 && c.nodeValue.trim())) ids.push(node.nodeId);
        for (const c of node.children || []) walk(c);
        if (node.contentDocument) walk(node.contentDocument);
        for (const s of node.shadowRoots || []) walk(s);
      })(doc);
      for (const nodeId of ids) {
        const { fonts: used } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
        for (const f of used) {
          if (!ALLOWED_FAMILIES.includes(f.familyName) || f.isCustomFont !== true) throw new Refusal("font_not_allowed", "drawn");
          fonts.set(f.familyName, { custom: true, family: f.familyName });
        }
      }
    }

    const rows = [];
    let bytes = 0;
    for (let f = 0; f < frames; f++) {
      const boxes = await page.evaluate((t) => window.__hfMeasure(t), f / fps);
      if (boxes.length > MAX_BOXES_PER_FRAME) throw new Refusal("boxes_too_many", "frame " + f);
      const text = JSON.stringify(boxes);
      bytes += text.length + 1;
      if (bytes > MAX_OUT_BYTES) throw new Refusal("boxes_too_large", "frame " + f);
      rows.push(text);
      if (f % FONT_EVERY === 0) await checkFonts();
      if (problems.length) throw new Refusal("measure_failed", problems[0] + " at frame " + f);
    }
    if (problems.length) throw new Refusal("measure_failed", problems[0]);
    const list = [...fonts.values()].sort((a, b) => (a.family < b.family ? -1 : 1));
    fs.writeFileSync(outPath, '{"fonts":' + JSON.stringify(list) + ',"fps":' + fps + ',"frames":' + frames + ',"per_frame":[' + rows.join(",") + '],"schema":1}');
  } finally {
    if (browser) await browser.close().catch(() => {});
    server.close();
  }
}

try {
  await main();
  process.exit(0);
} catch (err) {
  if (err instanceof Refusal) writeRefusal(err.code, err.field);
  else writeRefusal("measure_failed", "measure");
  console.error(String(err && err.message ? err.message : err).slice(0, 300));
  process.exit(1);
}
