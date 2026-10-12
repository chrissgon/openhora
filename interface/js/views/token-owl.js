// The owl of the token prompt (R-15): the identity's drawing (the mark), inline on this screen only, so that its eyes can move.
// It keeps watch: now and then it blinks slowly and its eyes travel to one side, then the other, and return, in a slow 8 s cycle (css/token.css,
// `.owl-pupil`, `.owl-lid`, `.owl-lidline`); under reduced motion it is still. No shape of the drawing changes.
//
// The palette below is the mark's own and is fixed in every scheme: the one place besides the brand pair of css/base.css that names colours, because the
// owl is the brand's drawing and not the interface's (the same exception the design system makes for the owl in the scene). Nothing here is read
// from the service; the drawing links to nothing and carries no script.

import { svg } from "../dom.js";

const INK = "#1E1B2E";
const BROWN = "#6B4429";
const BODY = "#A47551";
const GOLD = "#FCD34D";
const CREAM = "#E6D2BC";
const WHITE = "#FFFFFF";

let counter = 0;

/** The owl as an SVG of `size` pixels square (168 at the right of the prompt, 64 above the title on a phone: the stylesheet sets the second). */
export function createOwl(size = 168) {
  counter += 1;
  const left = `owl-l${counter}`;
  const right = `owl-r${counter}`;
  const eye = (id, cx, pupilX, glintX, lidX) => svg("g", { "clip-path": `url(#${id})` },
    svg("g", { class: "owl-pupil" },
      svg("circle", { cx: pupilX, cy: 101, r: 11, fill: INK }),
      svg("circle", { cx: glintX, cy: 98, r: 4, fill: WHITE })),
    svg("rect", { class: "owl-lid", x: lidX, y: 70, width: 50, height: 20, fill: BROWN }));
  return svg("svg", { class: "wb-owl", viewBox: "0 0 200 200", width: size, height: size, "aria-hidden": "true" },
    svg("defs", {},
      svg("clipPath", { id: left }, svg("circle", { cx: 74, cy: 98, r: 22 })),
      svg("clipPath", { id: right }, svg("circle", { cx: 126, cy: 98, r: 22 }))),
    svg("g", { stroke: INK, "stroke-width": 7, "stroke-linejoin": "round", "stroke-linecap": "round" },
      svg("path", { d: "M44 70 Q30 40 36 22 Q60 34 74 50Z", fill: BROWN }),
      svg("path", { d: "M156 70 Q170 40 164 22 Q140 34 126 50Z", fill: BROWN }),
      svg("ellipse", { cx: 80, cy: 186, rx: 13, ry: 7, fill: GOLD }),
      svg("ellipse", { cx: 120, cy: 186, rx: 13, ry: 7, fill: GOLD }),
      svg("path", { d: "M100 36 C152 36 180 74 180 120 C180 164 146 186 100 186 C54 186 20 164 20 120 C20 74 48 36 100 36Z", fill: BODY })),
    svg("g", { stroke: INK, "stroke-width": 6, "stroke-linejoin": "round" },
      svg("path", { d: "M30 120 Q28 158 62 174 Q48 148 50 122Z", fill: BROWN }),
      svg("path", { d: "M170 120 Q172 158 138 174 Q152 148 150 122Z", fill: BROWN }),
      svg("path", { d: "M100 72 C84 52 42 54 42 96 C42 128 72 142 100 132 C128 142 158 128 158 96 C158 54 116 52 100 72Z", fill: CREAM }),
      svg("circle", { cx: 74, cy: 98, r: 22, fill: WHITE }),
      svg("circle", { cx: 126, cy: 98, r: 22, fill: WHITE })),
    eye(left, 74, 80, 84, 50),
    eye(right, 126, 132, 136, 102),
    svg("g", { stroke: INK, "stroke-width": 6, fill: "none", "stroke-linecap": "round" },
      svg("circle", { cx: 74, cy: 98, r: 22 }),
      svg("circle", { cx: 126, cy: 98, r: 22 }),
      svg("path", { class: "owl-lidline", d: "M53 90 H95" }),
      svg("path", { class: "owl-lidline", d: "M105 90 H147" })),
    svg("path", { d: "M92 116 Q100 112 108 116 Q103 130 100 132 Q97 130 92 116Z", fill: GOLD, stroke: INK, "stroke-width": 5, "stroke-linejoin": "round" }),
    svg("g", { stroke: BROWN, "stroke-width": 4, fill: "none", "stroke-linecap": "round" },
      svg("path", { d: "M76 156 q6 6 12 0 q6 6 12 0 q6 6 12 0 q6 6 12 0" }),
      svg("path", { d: "M82 168 q6 6 12 0 q6 6 12 0 q6 6 12 0" })));
}
