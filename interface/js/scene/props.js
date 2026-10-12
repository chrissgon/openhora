// Props shared by the scenes (handoff scene.md 5.1). Only what the City draws is here; the building, the room and the
// server scenes add theirs in their own packages. Each takes the kit and the group to add to.

export function tree(kit, parent, x, z, s = 1) {
  const { THREE, palette } = kit;
  const group = new THREE.Group();
  group.position.set(x, 0, z);
  parent.add(group);
  kit.cyl(0.07 * s, 0.1 * s, 0.75 * s, 6, palette.trunk, 0, 0, 0, { parent: group });
  const crown = kit.mesh(new THREE.IcosahedronGeometry(0.62 * s, 0), Math.round(x * 3 + z) % 2 ? palette.leafA : palette.leafB,
    0, 1.2 * s, 0, { parent: group, flat: true });
  crown.rotation.set(0.3, x, 0.2);
  return group;
}

/** The waiting marker: a warn exclamation (cube and bar), as one group so it can drop in. */
export function exclamation(kit, parent, x, y, z, cube = 0.3, bar = [0.3, 0.95, 0.3]) {
  const group = new kit.THREE.Group();
  group.position.set(x, y, z);
  parent.add(group);
  kit.box(cube, cube, cube, 0, 0, 0, kit.palette.T.warn, { parent: group });
  kit.box(bar[0], bar[1], bar[2], 0, 0.5, 0, kit.palette.T.warn, { parent: group });
  return group;
}
