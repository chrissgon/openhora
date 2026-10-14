// The L of a floor's workstations, in the page units of room-frame.js: the numbers of the approved prototype and the transform that puts today's
// workstation (a desk, its chair and its owl, written once in furniture.js) at one of four seats. Pure arithmetic: no library, no page, nothing drawn here.
//
// The workstations stand in an L whose point is the room's open front corner: three seats on the left arm (along the windows' side, running toward the windows) and one on the
// right arm (running toward the bookcase). Seat 0 is the left desk at the point, seat 1 the right desk, seats 2 and 3 the next left desks outward. A square corner top joins the
// two arms when seats 0 and 1 are both drawn. Every workstation is today's, scaled by S: furniture and owl alike, on every floor.

export const S = 0.68;                                         // every workstation's scale
export const C0 = Object.freeze([5.895, 3.78]);                // today's desk top centre (x, z): the point a seat transform is taken about
export const TIP = Object.freeze([6.92, 5.53]);                // the L's outer corner (x, z), inside the floor
export const CORNER = 1.0;                                     // the corner top's side
export const DESK_LEN = 2.21 * S;                              // a desk along its long side
export const DESK_DEP = 1.12 * S;                              // a desk across
/** The L's places: geometry, not a cap. The cap is the runtime's one constant (`MAX_PARALLEL_CEILING`); a test keeps the two equal. */
export const SEAT_COUNT = 4;

/** Where today's working owl sits, and where a waiting owl stands, in today's workstation coordinates (x, z). */
export const WORK_OWL = Object.freeze([4.76, 3.64]);
export const STAND_LEFT = Object.freeze([3.48, 2.623]);        // behind its chair, inside the L
export const STAND_RIGHT = Object.freeze([5.679, 1.428]);      // past its desk's far end, on the bookcase's side, close to the desk

// seat order: 0 the point's left desk, 1 the right desk, 2 and 3 the left desks outward
const ARMS = Object.freeze(["left", "right", "left", "left"]);

/**
 * The four seats: [{index, arm, turn ("swap" for the left arm, "none" for the right), desk: {x0, x1, z0, z1} (the desk top), q: [x, z] (the desk top's centre)}].
 * A left desk spans z TIP.z - DESK_DEP to TIP.z and ends at x TIP.x - CORNER (seat 0), each next one DESK_LEN further toward x = 0; the right desk spans x TIP.x - DESK_DEP to
 * TIP.x and ends at z TIP.z - CORNER.
 */
export function seats() {
  let left = 0;
  return ARMS.map((arm, index) => {
    let desk;
    if (arm === "left") {
      const x1 = TIP[0] - CORNER - left * DESK_LEN;
      desk = { x0: x1 - DESK_LEN, x1, z0: TIP[1] - DESK_DEP, z1: TIP[1] };
      left += 1;
    } else {
      const z1 = TIP[1] - CORNER;
      desk = { x0: TIP[0] - DESK_DEP, x1: TIP[0], z0: z1 - DESK_LEN, z1 };
    }
    return { index, arm, turn: arm === "left" ? "swap" : "none", desk, q: [(desk.x0 + desk.x1) / 2, (desk.z0 + desk.z1) / 2] };
  });
}

/** The square top that joins the two arms at the point: {x0, x1, z0, z1}. */
export function corner() {
  return { x0: TIP[0] - CORNER, x1: TIP[0], z0: TIP[1] - CORNER, z1: TIP[1] };
}

/** What a transform needs of seat `i`: {index, turn, q, s, c0}. The batch of room-frame.js (`seatBatch`) takes exactly this, so that module needs no other. */
export function seat(i) {
  const found = seats()[i];
  if (!found) throw new RangeError(`no seat ${i}`);
  return { index: found.index, turn: found.turn, q: found.q, s: S, c0: C0 };
}

/** A point [x, y, z] of today's workstation, put at seat `seatInfo` (from `seat(i)`). */
export function seatPoint(seatInfo, [x, y, z]) {
  const { q, s, c0, turn } = seatInfo;
  if (turn === "swap") return [q[0] + s * (z - c0[1]), s * y, q[1] + s * (x - c0[0])];
  return [q[0] + s * (x - c0[0]), s * y, q[1] + s * (z - c0[1])];
}

/** Where the owl's foot is drawn (x, z in page units) for a pose at seat `i`: a waiting owl at the seat's standing place, every other one at the seat (asleep: in its chair). */
export function footAt(i, pose) {
  const info = seat(i);
  const there = pose === "waiting" ? (info.turn === "swap" ? STAND_LEFT : STAND_RIGHT) : WORK_OWL;
  const p = seatPoint(info, [there[0], 0, there[1]]);
  return [p[0], p[2]];
}

/** The standing place of seat `i`'s owl, (x, z). */
export const standAt = (i) => footAt(i, "waiting");
