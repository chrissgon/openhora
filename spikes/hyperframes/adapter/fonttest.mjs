// S2 experiment (kept as evidence, cause not found): in headless Chrome 155 with NO system font, an @font-face rule whose data: URI is a woff2 loads for the family
// "Inter" but ends in an error state ("NetworkError") for "Foo" and "JetBrains Mono" in the same kind of page; a FontFace object built from the same bytes always loads.
// The measuring page therefore registers the three fonts as FontFace objects (adapter/measure.mjs). HyperFrames' own render path is unaffected (it embeds the files as data URIs and draws them).
import { createRequire } from "node:module"; import fs from "node:fs";
const require = createRequire("/opt/hf/package.json"); const puppeteer = require("puppeteer-core");
const b64 = (f) => fs.readFileSync("/work/project/fonts/" + f).toString("base64");
const browser = await puppeteer.launch({ executablePath: "/opt/chrome/chrome-headless-shell", headless: "shell", args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"] });
const cases = {
  inter800_only: `@font-face{font-family:Inter;font-weight:800;src:url("data:font/woff2;base64,${b64("inter-800.woff2")}") format("woff2");}`,
  inter800_renamed: `@font-face{font-family:Foo;font-weight:800;src:url("data:font/woff2;base64,${b64("inter-800.woff2")}") format("woff2");}`,
  jb_only: `@font-face{font-family:"JetBrains Mono";font-weight:500;src:url("data:font/woff2;base64,${b64("jetbrains-mono-500.woff2")}") format("woff2");}`,
  inter800_noformat: `@font-face{font-family:Inter;font-weight:800;src:url("data:font/woff2;base64,${b64("inter-800.woff2")}");}`,
};
for (const [name, css] of Object.entries(cases)) {
  const page = await browser.newPage();
  const msgs = []; page.on("console", (m) => msgs.push(m.type() + ":" + m.text().slice(0, 200)));
  await page.setContent(`<html><head><style>${css}</style></head><body><p style="font-family:Inter,Foo,'JetBrains Mono';font-weight:800">Ol\u00e1 \u00e3</p></body></html>`);
  const r = await page.evaluate(async () => { const out = []; for (const f of document.fonts) { try { await f.load(); } catch (e) { out.push("ERR " + e); } out.push(f.family + f.weight + " " + f.status); } return out; });
  console.log(name, JSON.stringify(r), JSON.stringify(msgs));
  await page.close();
}
await browser.close();
