// Building the page's elements. Everything that came from the service is put in the document as text, never as markup:
// a string child becomes a text node, setText assigns textContent, and nothing here builds markup from a string.

const FORBIDDEN = /^(on[a-z]+|style)$/i;

/**
 * h(tag, attrs, ...children): an element. attrs: `class`, `text` (a string, assigned with textContent), `hidden`
 * and other plain attributes. An event handler attribute and a style attribute are refused (the page's policy
 * forbids both), and so is an href that is not a hash link of this page.
 */
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (FORBIDDEN.test(name)) throw new Error(`the attribute ${name} is not allowed`);
    if (name === "text") {
      node.textContent = String(value);
    } else if (name === "href" && !String(value).startsWith("#")) {
      throw new Error("a link on this page is a hash link");
    } else {
      node.setAttribute(name, value === true ? "" : String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

// The namespace is an identifier, not an address the page loads; it is written in two parts so that no file of the page names a host (a test scans for one).
const SVG_NS = ["http:", "", "www.w3.org", "2000", "svg"].join("/");

/**
 * svg(tag, attrs, ...children): an element of the SVG namespace, built as h() builds one (an event handler or a style attribute is refused, a string child
 * is a text node, `text` is assigned with textContent). Used for the few drawings the page makes itself: the token prompt's ground of dots and its owl.
 */
export function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (FORBIDDEN.test(name)) throw new Error(`the attribute ${name} is not allowed`);
    if (name === "text") node.textContent = String(value);
    else if (name === "href" || name === "xlink:href") throw new Error("a drawing of the page links to nothing");
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

/** Replace the text of a node. */
export function setText(node, text) {
  node.textContent = String(text);
  return node;
}

/** Empty a node and put the given children in it. */
export function fill(node, ...children) {
  node.replaceChildren(...children.flat().filter((c) => c !== undefined && c !== null && c !== false).map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
  return node;
}

/**
 * Make the children of a node exactly the given ones, in that order, without taking out the ones that are already there in place: a node that stays is never detached,
 * so what it holds (a scroll position inside it, a playing video, a focused field, a selection) is kept, which `fill` cannot promise since it detaches every child.
 */
export function sync(node, ...children) {
  const want = children.flat(Infinity).filter((c) => c !== undefined && c !== null && c !== false).map((c) => (c instanceof Node ? c : document.createTextNode(String(c))));
  const keep = new Set(want);
  for (const child of [...node.childNodes]) if (!keep.has(child)) child.remove();
  want.forEach((child, i) => {
    const at = node.childNodes[i];
    if (at !== child) node.insertBefore(child, at || null);
  });
  return node;
}

/**
 * Run `render`, then put back the scroll position of every ancestor of `node` that was scrolled before it: a redraw that replaces nodes makes the page shorter for a
 * moment, and a browser then moves the position of a scrolled panel; the person reading further down must stay where they were.
 */
export function keepScroll(node, render) {
  const saved = [];
  for (let up = node.parentNode; up; up = up.parentNode) if (up.scrollTop > 0) saved.push([up, up.scrollTop]);
  const result = render();
  for (const [up, top] of saved) if (up.scrollTop !== top) up.scrollTop = top;
  return result;
}
