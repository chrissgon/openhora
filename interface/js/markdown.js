// Markdown, rendered safely (WP-9.17). The one place the page turns Markdown into elements. It reads a small subset and builds
// DOM nodes with createElement and text nodes, so a text from a model, a document or a comment can never become markup:
//   - blocks: headings 1 to 4, paragraphs, fenced and indented code, bullet and numbered lists (nested), quotes, tables
//     (GitHub style), rules; inline: bold, italic, code, links, line breaks, backslash escapes;
//   - everything else is text: a raw tag, a comment, an entity and a footnote show as typed; an image is its alt text and its
//     address as text (nothing is fetched); a link is its text followed by its address in parentheses, unless the address is a
//     route of this page (it starts with `#/`), which becomes a plain anchor, so that a click never leaves the page;
//   - the only attributes ever set are `class` (a fixed name, or `language-` and a name cleaned to letters, digits, `_`, `+`, `-`)
//     and the `href` of such an anchor. Nothing here reads or writes a style, an event handler, a source or a title.
// Bounded work: a document over RENDER_LIMIT characters renders its first part and shows the rest as one plain block; quotes
// and lists nest MAX_DEPTH levels, a paragraph over MAX_INLINE characters stays text, a paragraph keeps at most MAX_DELIMS
// emphasis marks, at most MAX_LINKS bracket pairs are tried in a paragraph, and an address, a title and the spaces between are
// searched only within a fixed span, so no input costs more than a few passes over its text.

/** The most characters of a document rendered as Markdown; the rest is shown as one plain block. */
export const RENDER_LIMIT = 200000;
const MAX_DEPTH = 8;
const MAX_INLINE = 50000;
const MAX_DELIMS = 200;
const MAX_BRACKET = 1000;
const MAX_URL = 2000;
const MAX_LINKS = 500;      // bracket pairs tried in one paragraph; the next ones stay text
const MAX_SPACE = 100;      // spaces skipped between the parts of a link
const ALIGN_CLASS = Object.freeze({ left: "wb-md-left", center: "wb-md-center", right: "wb-md-right" });
const ESCAPABLE = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~";

function el(tag, cls) {
  const node = document.createElement(tag);
  if (cls) node.setAttribute("class", cls);
  return node;
}

function appendAll(parent, list) {
  for (const item of list) parent.append(item);
  return parent;
}

// --- the page's own routes ----------------------------------------------------------------------------------------------------

/**
 * The hash of an address that is a route of this page (`#/...`), else null. Only such an address becomes an anchor: a click on it
 * stays in the page (a typed answer and the open card stay where they are). Every other address, of this origin or not, is shown as
 * text, so a click never leaves the single page.
 */
function routeHref(dest) {
  const text = dest.trim();
  return text.length <= MAX_URL && /^#\/\S*$/.test(text) ? text : null;
}

// --- inline -------------------------------------------------------------------------------------------------------------------

const BREAK = Object.freeze({ lineBreak: true });

class Delim {
  constructor(ch, count, open, close) {
    this.ch = ch;
    this.n = count;
    this.orig = count;
    this.open = open;
    this.close = close;
  }
}

const isSpace = (ch) => ch === undefined || /\s/.test(ch);
const isPunct = (ch) => ch !== undefined && /[\p{P}\p{S}]/u.test(ch);

/** Strings, nodes and line breaks of a list, with the leftover delimiters as text and neighbouring strings joined. */
function finish(list) {
  const out = [];
  const push = (text) => {
    if (!text) return;
    if (typeof out[out.length - 1] === "string") out[out.length - 1] += text;
    else out.push(text);
  };
  for (const item of list) {
    if (typeof item === "string") push(item);
    else if (item instanceof Delim) push(item.ch.repeat(item.n));
    else if (item === BREAK) out.push(el("br"));
    else out.push(item);
  }
  return out;
}

/** Turn pairs of emphasis marks into strong and em nodes (the CommonMark rules for runs, in a bounded form). */
function resolveEmphasis(list) {
  for (let ci = 0; ci < list.length; ci++) {
    const closer = list[ci];
    if (!(closer instanceof Delim) || !closer.close) continue;
    while (closer.n > 0) {
      let found = -1;
      for (let k = ci - 1; k >= 0; k--) {
        const opener = list[k];
        if (!(opener instanceof Delim) || opener.ch !== closer.ch || !opener.open || opener.n === 0) continue;
        if ((opener.close || closer.open) && (opener.orig + closer.orig) % 3 === 0 && !(opener.orig % 3 === 0 && closer.orig % 3 === 0)) continue;
        found = k;
        break;
      }
      if (found < 0) break;
      const opener = list[found];
      const use = opener.n >= 2 && closer.n >= 2 ? 2 : 1;
      const node = appendAll(el(use === 2 ? "strong" : "em"), finish(list.slice(found + 1, ci)));
      opener.n -= use;
      closer.n -= use;
      list.splice(found + 1, ci - found - 1, node);
      ci = found + 2;
    }
  }
  return finish(list);
}

function plainText(list) {
  return list.map((item) => (typeof item === "string" ? item : item.textContent)).join("");
}

/** Where the runs of backticks are, by length, so that a code span finds its closing run without a search from each opener. */
function backtickRuns(src) {
  const runs = new Map();
  for (let i = 0; i < src.length; i++) {
    if (src[i] !== "`") continue;
    let j = i;
    while (src[j] === "`") j++;
    const length = j - i;
    if (!runs.has(length)) runs.set(length, { starts: [], at: 0 });
    runs.get(length).starts.push(i);
    i = j - 1;
  }
  return runs;
}

function closingRun(runs, length, from) {
  const held = runs.get(length);
  if (!held) return -1;
  while (held.at < held.starts.length && held.starts[held.at] < from) held.at++;
  return held.at < held.starts.length ? held.starts[held.at] : -1;
}

function skipSpace(src, at) {
  let k = at;
  while ((src[k] === " " || src[k] === "\n" || src[k] === "\t") && k - at < MAX_SPACE) k++;
  return k;
}

/** `[label](destination "title")` at `at` (the position of the bracket): {label, dest, end} or null. */
function linkAt(src, at) {
  const limit = Math.min(src.length, at + MAX_BRACKET);
  let depth = 0;
  let j = at + 1;
  for (; j < limit; j++) {
    const ch = src[j];
    if (ch === "\\") j++;
    else if (ch === "[") depth++;
    else if (ch === "]") {
      if (depth === 0) break;
      depth--;
    }
  }
  if (j >= limit || src[j] !== "]" || src[j + 1] !== "(") return null;
  let k = skipSpace(src, j + 2);
  let dest;
  if (src[k] === "<") {
    const close = src.slice(k + 1, k + 2 + MAX_URL).indexOf(">");
    if (close < 0 || src.slice(k, k + 1 + close).includes("\n")) return null;
    dest = src.slice(k + 1, k + 1 + close);
    k = k + 1 + close + 1;
  } else {
    const start = k;
    let parens = 0;
    for (; k < src.length && k - start < MAX_URL; k++) {
      const ch = src[k];
      if (ch === "\\") k++;
      else if (ch === " " || ch === "\n" || ch === "\t") break;
      else if (ch === "(") parens++;
      else if (ch === ")") {
        if (parens === 0) break;
        parens--;
      }
    }
    if (k - start >= MAX_URL) return null;
    dest = src.slice(start, k).replace(/\\([!-/:-@[-`{-~])/g, "$1");
  }
  k = skipSpace(src, k);
  const quote = src[k];
  if (quote === "\"" || quote === "'" || quote === "(") {
    const end = quote === "(" ? ")" : quote;
    let m = k + 1;
    for (; m < src.length && m - k < MAX_URL; m++) {
      if (src[m] === "\\") m++;
      else if (src[m] === end) break;
    }
    if (src[m] !== end) return null;
    k = skipSpace(src, m + 1);
  }
  if (src[k] !== ")") return null;
  return { label: src.slice(at + 1, j), dest, end: k + 1 };
}

/** The strings and nodes of an inline text: the paragraph, a heading, a table cell, a link's label. */
function inlineNodes(src, inLink, budget = { links: MAX_LINKS }) {
  if (src.length > MAX_INLINE) return [src];
  const out = [];
  let buf = "";
  let delims = 0;
  const flush = () => {
    if (buf) out.push(buf);
    buf = "";
  };
  const runs = backtickRuns(src);
  const n = src.length;
  let i = 0;
  while (i < n) {
    const c = src[i];
    if (c === "\\") {
      const next = src[i + 1];
      if (next === "\n") {
        flush();
        out.push(BREAK);
        i += 2;
        while (src[i] === " ") i++;
      } else if (next !== undefined && ESCAPABLE.includes(next)) {
        buf += next;
        i += 2;
      } else {
        buf += c;
        i++;
      }
    } else if (c === "`") {
      let j = i;
      while (src[j] === "`") j++;
      const length = j - i;
      const close = closingRun(runs, length, j);
      if (close < 0) {
        buf += src.slice(i, j);
        i = j;
      } else {
        let code = src.slice(j, close).replace(/\n/g, " ");
        if (code.length > 2 && code[0] === " " && code[code.length - 1] === " " && code.trim() !== "") code = code.slice(1, -1);
        flush();
        out.push(appendAll(el("code"), [code]));
        i = close + length;
      }
    } else if (c === "!" && src[i + 1] === "[") {
      const link = budget.links-- > 0 ? linkAt(src, i + 1) : null;
      if (!link) {
        buf += c;
        i++;
      } else {
        const alt = plainText(inlineNodes(link.label, true, budget));
        buf += alt ? `${alt} (${link.dest})` : link.dest;
        i = link.end;
      }
    } else if (c === "[") {
      const link = budget.links-- > 0 ? linkAt(src, i) : null;
      if (!link) {
        buf += c;
        i++;
      } else {
        const label = inlineNodes(link.label, true, budget);
        const href = inLink ? null : routeHref(link.dest);
        flush();
        if (href) {
          const anchor = appendAll(el("a", "pui-link pui-theme"), label);
          anchor.setAttribute("href", href);
          out.push(anchor);
        } else {
          out.push(...label);
          if (link.dest.trim() && plainText(label) !== link.dest) buf += ` (${link.dest})`;
        }
        i = link.end;
      }
    } else if (c === "*" || c === "_") {
      let j = i;
      while (src[j] === c) j++;
      const before = i > 0 ? src[i - 1] : undefined;
      const after = j < n ? src[j] : undefined;
      const left = !isSpace(after) && (!isPunct(after) || isSpace(before) || isPunct(before));
      const right = !isSpace(before) && (!isPunct(before) || isSpace(after) || isPunct(after));
      const open = c === "*" ? left : left && (!right || isPunct(before));
      const close = c === "*" ? right : right && (!left || isPunct(after));
      if ((open || close) && delims < MAX_DELIMS) {
        flush();
        out.push(new Delim(c, j - i, open, close));
        delims++;
      } else {
        buf += src.slice(i, j);
      }
      i = j;
    } else if (c === "\n") {
      let end = buf.length;
      while (end > 0 && buf[end - 1] === " ") end--;
      const hard = buf.length - end >= 2;
      buf = buf.slice(0, end);
      if (hard) {
        flush();
        out.push(BREAK);
      } else {
        buf += "\n";
      }
      i++;
      while (src[i] === " ") i++;
    } else {
      buf += c;
      i++;
    }
  }
  flush();
  return resolveEmphasis(out);
}

// --- blocks -------------------------------------------------------------------------------------------------------------------

const FENCE = /^( {0,3})(`{3,}|~{3,})(.*)$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}>/;
const MARKER = /^( {0,3})([-*+]|(\d{1,9})([.)]))( +|$)/;

const isBlank = (line) => line.trim() === "";

function indentOf(line) {
  let n = 0;
  while (line[n] === " ") n++;
  return n;
}

function headingOf(line) {
  const m = /^ {0,3}(#{1,4})(?=[ \t]|$)/.exec(line);
  if (!m) return null;
  let text = line.slice(m[0].length).trim();
  let end = text.length;
  while (end > 0 && text[end - 1] === "#") end--;
  if (end < text.length && (end === 0 || text[end - 1] === " " || text[end - 1] === "\t")) text = text.slice(0, end).trimEnd();
  return { level: m[1].length, text };
}

/** {sym, ordered, number, content, offset} of a list item's first line, or null. */
function markerOf(line) {
  const m = MARKER.exec(line);
  if (!m) return null;
  const indent = m[1].length;
  const spaces = m[5].length;
  const width = indent + m[2].length;
  const bare = line.length === width + spaces;
  const offset = bare || spaces >= 5 ? width + 1 : width + spaces;
  return { sym: m[4] === undefined ? m[2] : m[4], ordered: m[3] !== undefined, number: m[3] === undefined ? 0 : Number(m[3]), content: bare ? "" : line.slice(offset), offset };
}

function splitRow(line) {
  const s = line.trim();
  const cells = [];
  let cur = "";
  for (let k = 0; k < s.length; k++) {
    const ch = s[k];
    if (ch === "\\" && s[k + 1] === "|") {
      cur += "|";
      k++;
    } else if (ch === "|") {
      cells.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  if (s.startsWith("|")) cells.shift();
  if (s.endsWith("|") && !s.endsWith("\\|")) cells.pop();
  return cells.map((cell) => cell.trim());
}

/** The alignment names of a delimiter row (`""`, `left`, `center`, `right` per column), or null when the line is not one. */
function alignments(line) {
  if (!line.includes("-") || line.length > MAX_INLINE) return null;
  const cells = splitRow(line);
  if (!cells.length) return null;
  const out = [];
  for (const cell of cells) {
    if (!/^:?-+:?$/.test(cell)) return null;
    out.push(cell.startsWith(":") ? (cell.endsWith(":") ? "center" : "left") : (cell.endsWith(":") ? "right" : ""));
  }
  return out;
}

function tableAt(lines, i) {
  if (i + 1 >= lines.length || indentOf(lines[i]) > 3) return null;
  const head = lines[i];
  const rule = lines[i + 1];
  if (!head.includes("|") && !rule.includes("|")) return null;
  const aligns = alignments(rule);
  if (!aligns || head.length > MAX_INLINE || splitRow(head).length !== aligns.length) return null;
  return aligns;
}

/** True when the line at `i` begins a block that can interrupt a paragraph. */
function interrupts(lines, i) {
  const line = lines[i];
  const fence = FENCE.exec(line);
  if (fence && !(fence[2][0] === "`" && fence[3].includes("`"))) return true;
  if (headingOf(line) || HR.test(line) || QUOTE.test(line)) return true;
  const item = markerOf(line);
  if (item && item.content !== "" && (!item.ordered || item.number === 1)) return true;
  return tableAt(lines, i) !== null;
}

function codeBlock(parent, text, lang) {
  const code = appendAll(el("code", lang ? `language-${lang}` : ""), [text]);
  parent.append(appendAll(el("pre"), [code]));
}

function languageOf(info) {
  const word = info.trim().split(/\s+/)[0] || "";
  return word.toLowerCase().replace(/[^a-z0-9_+-]/g, "").slice(0, 30);
}

function paragraph(parent, lines, bare) {
  const kids = inlineNodes(lines.map((l) => l.trimStart()).join("\n").trimEnd(), false);
  if (bare) appendAll(parent, kids);
  else parent.append(appendAll(el("p"), kids));
}

/**
 * Append the blocks of `lines` to `parent`. With `bare`, the first block, when it is a paragraph, goes into `parent` without its
 * own element (the text of a tight list item). `depth` counts the quotes and lists around this text.
 */
function blocks(lines, parent, depth, bare) {
  const n = lines.length;
  let i = 0;
  let emitted = 0;
  while (i < n) {
    const line = lines[i];
    if (isBlank(line)) {
      i++;
      continue;
    }
    const first = bare && emitted === 0;
    emitted++;
    if (depth >= MAX_DEPTH) {
      const start = i;
      while (i < n && !isBlank(lines[i])) i++;
      paragraph(parent, lines.slice(start, i), first);
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence && !(fence[2][0] === "`" && fence[3].includes("`"))) {
      const body = [];
      const mark = fence[2];
      const close = new RegExp(`^ {0,3}${mark[0] === "`" ? "`" : "~"}{${mark.length},}[ \\t]*$`);
      i++;
      while (i < n && !close.test(lines[i])) {
        const lead = Math.min(fence[1].length, indentOf(lines[i]));
        body.push(lines[i].slice(lead));
        i++;
      }
      i++;
      codeBlock(parent, body.join("\n"), languageOf(fence[3]));
      continue;
    }
    const heading = headingOf(line);
    if (heading) {
      parent.append(appendAll(el(`h${heading.level}`), inlineNodes(heading.text, false)));
      i++;
      continue;
    }
    if (HR.test(line)) {
      parent.append(el("hr"));
      i++;
      continue;
    }
    if (QUOTE.test(line)) {
      const body = [];
      while (i < n) {
        const l = lines[i];
        if (QUOTE.test(l)) {
          body.push(l.replace(/^ {0,3}> ?/, ""));
        } else if (!isBlank(l) && body.length && !isBlank(body[body.length - 1]) && !interrupts(lines, i)) {
          body.push(l);
        } else {
          break;
        }
        i++;
      }
      const quote = el("blockquote");
      blocks(body, quote, depth + 1, false);
      parent.append(quote);
      continue;
    }
    const item = markerOf(line);
    if (item) {
      i = list(lines, i, parent, depth, item);
      continue;
    }
    const aligns = tableAt(lines, i);
    if (aligns) {
      i = table(lines, i, parent, aligns);
      continue;
    }
    if (indentOf(line) >= 4) {
      const body = [];
      while (i < n && (isBlank(lines[i]) || indentOf(lines[i]) >= 4)) {
        body.push(lines[i].slice(Math.min(4, indentOf(lines[i]))));
        i++;
      }
      while (body.length && body[body.length - 1].trim() === "") body.pop();
      codeBlock(parent, body.join("\n"), "");
      continue;
    }
    const start = i;
    i++;
    while (i < n && !isBlank(lines[i]) && !interrupts(lines, i)) i++;
    paragraph(parent, lines.slice(start, i), first);
  }
}

/** True when the line is the next item of the list that `firstItem` began (the same bullet, or the same number delimiter). */
function sibling(line, firstItem) {
  const item = markerOf(line);
  return item !== null && item.ordered === firstItem.ordered && item.sym === firstItem.sym;
}

/** A list starting at `i`; returns the index after it. */
function list(lines, start, parent, depth, firstItem) {
  const n = lines.length;
  const node = el(firstItem.ordered ? "ol" : "ul");
  let i = start;
  while (i < n) {
    const item = markerOf(lines[i]);
    if (!item || item.ordered !== firstItem.ordered || item.sym !== firstItem.sym || HR.test(lines[i])) break;
    const body = [item.content];
    i++;
    let gap = 0;
    while (i < n) {
      const l = lines[i];
      if (isBlank(l)) {
        gap++;
        body.push("");
      } else if (indentOf(l) >= item.offset) {
        gap = 0;
        body.push(l.slice(item.offset));
      } else if (gap === 0 && !interrupts(lines, i) && !sibling(l, firstItem)) {
        body.push(l);
      } else {
        break;
      }
      i++;
    }
    while (body.length && body[body.length - 1] === "") body.pop();
    const li = el("li");
    blocks(body, li, depth + 1, true);
    node.append(li);
  }
  parent.append(node);
  return i;
}

/** A table whose header is at `start`; returns the index after its last row. */
function table(lines, start, parent, aligns) {
  const n = lines.length;
  const cell = (tag, text, k) => {
    const node = el(tag, ALIGN_CLASS[aligns[k]] || "");
    return appendAll(node, inlineNodes(text, false));
  };
  const row = (tag, text) => {
    const cells = splitRow(text);
    const tr = el("tr");
    for (let k = 0; k < aligns.length; k++) tr.append(cell(tag, cells[k] || "", k));
    return tr;
  };
  const head = el("thead");
  head.append(row("th", lines[start]));
  const body = el("tbody");
  let i = start + 2;
  while (i < n && !isBlank(lines[i]) && !interrupts(lines, i)) {
    body.append(row("td", lines[i]));
    i++;
  }
  parent.append(appendAll(el("table"), [head, body]));
  return i;
}

// --- the entry ----------------------------------------------------------------------------------------------------------------

function normal(text) {
  return text.replace(/\r\n?/g, "\n").split("\n").map((line) => {
    if (line[0] !== " " && line[0] !== "\t") return line;
    let k = 0;
    let lead = "";
    while (line[k] === " " || line[k] === "\t") {
      lead += line[k] === "\t" ? "    " : " ";
      k++;
    }
    return lead + line.slice(k);
  });
}

/**
 * The Markdown text as a `div.wb-md` of elements. A text over RENDER_LIMIT characters is cut at a line end: the first part is
 * rendered, a sentence says so, and the rest follows as one plain block.
 */
export function renderMarkdown(source) {
  const root = el("div", "wb-md");
  let text = typeof source === "string" ? source : (source === undefined || source === null ? "" : String(source));
  let rest = "";
  if (text.length > RENDER_LIMIT) {
    let cut = text.lastIndexOf("\n", RENDER_LIMIT) + 1;
    if (cut <= 0) {
      cut = RENDER_LIMIT;
      const unit = text.charCodeAt(cut - 1);
      if (unit >= 0xd800 && unit <= 0xdbff) cut--;
    }
    rest = text.slice(cut);
    text = text.slice(0, cut);
  }
  blocks(normal(text), root, 0, false);
  if (rest) {
    root.append(appendAll(el("p", "wb-md-note"), [`The rest of this document (${rest.length} more characters) is shown as plain text.`]));
    root.append(appendAll(el("pre", "wb-md-rest"), [rest]));
  }
  return root;
}
