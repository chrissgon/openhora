// The placeholder figure of slice 1: a plain body and head in the agent's hue, so that the office can be built and tested before any art is chosen
// (decision 10c: the maintainer chooses the art later and nothing here is that choice). These hsl strings are the only colours the office writes.

/** Paint one figure of 16 x 24 art pixels onto `ctx`. */
export function paintPlaceholder(ctx, { look, pose, frame, dir }) {
  const hue = look.hue;
  const walking = pose === "walk";
  ctx.fillStyle = `hsl(${hue} 30% 30%)`;
  ctx.fillRect(5, 22, 2, walking && frame === 1 ? 1 : 2);
  ctx.fillRect(9, 22, 2, walking && frame === 0 ? 1 : 2);
  ctx.fillStyle = `hsl(${hue} 45% 55%)`;
  ctx.fillRect(4, 10, 8, 12);
  if (dir === "up") {
    ctx.fillStyle = `hsl(${hue} 45% 35%)`;
    ctx.fillRect(7, 10, 1, 12);
  }
  ctx.fillStyle = `hsl(${hue} 30% 75%)`;
  ctx.fillRect(5, 2, 6, 7);
}
