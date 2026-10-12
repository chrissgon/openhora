// Which object the pointer is on: the one thing the tooltip, the click and the outline all read, so they cannot disagree.
//
// The rule (WP-9.10): a ray is tested against the MESHES of the pickable objects and nothing else. A pickable object is a group
// that also holds the edge lines of its boxes (kit.box with `edges`), the lot's theme line and the like; three.js tests a line
// against a ray within a threshold of one world unit, whether the line is visible or not, so a line on the far side of a rack
// "hit" the pointer when it was a unit away from it and, being nearer the camera, won over the mesh the pointer was on. That is
// how the tooltip named the first of three racks while the pointer stood on the third. A line is never pickable; a hidden mesh
// is not either; a mesh belongs to the nearest pickable group above it (the Lobby's door stands inside its floor and wins there).
// A mesh that is not pickable never blocks the pick: a tree, a slab or another object's wall in front of a pickable object is ignored,
// so the pointer on a tree in front of a lot names the lot behind it, by design (the HTML list has the same objects).

/** The visible meshes under `object` (a hidden node hides its subtree, and a group of brackets is no part of what it holds), nearest-owner not decided here. */
export function pickableMeshes(object) {
  const out = [];
  const walk = (node) => {
    if (!node.visible || (node.userData && node.userData.brackets)) return;   // a hidden node hides its subtree; the brackets of a hit (`userData.brackets`) are drawn, never picked
    if (node.isMesh) out.push(node);
    for (const child of node.children) walk(child);
  };
  walk(object);
  return out;
}

/**
 * The pick list of `hits` ({object, id, ...}): every visible mesh with the hit it belongs to. The world matrices are brought up to
 * date first, so a floor that moved since the last frame is picked where it stands.
 */
export function pickList(hits) {
  const byObject = new Map(hits.map((hit) => [hit.object, hit]));
  const meshes = [];
  const owner = new Map();
  for (const hit of hits) {
    hit.object.updateWorldMatrix(true, true);
    for (const mesh of pickableMeshes(hit.object)) {
      let node = mesh;
      let found = null;
      while (node && !found) {
        found = byObject.get(node) || null;
        node = node.parent;
      }
      if (found === hit && !owner.has(mesh)) {
        owner.set(mesh, hit);
        meshes.push(mesh);
      }
    }
  }
  return { meshes, owner };
}

/** The hit under the point `ndc` {x, y} (each from -1 to 1, y up) seen by `camera`, or null. `raycaster` is a three.js Raycaster. */
export function pickHit(raycaster, camera, hits, ndc, list = pickList(hits)) {
  raycaster.setFromCamera(ndc, camera);
  const found = raycaster.intersectObjects(list.meshes, false);
  return found.length ? list.owner.get(found[0].object) || null : null;
}

/**
 * Points on the drawn objects for the page's checks and the offline test: for each hit, the screen position (CSS pixels of a
 * canvas of `size` {w, h}) of the centre of each of its meshes that is the nearest thing under that point, among the meshes of
 * the whole `scene` that are drawn, and of the centre of the object's bounding box when that point is on the object too.
 * Returns [{id, x, y, kind, shell}] with kind "mesh" or "box"; `shell` tells a mesh that makes the object's outline.
 */
export function visibleSamples(THREE, camera, scene, hits, size) {
  scene.updateMatrixWorld(true);
  const raycaster = new THREE.Raycaster();
  const drawn = [];
  scene.traverse((node) => {
    if (!node.isMesh) return;
    for (let p = node; p; p = p.parent) if (!p.visible) return;
    if (node.material && node.material.visible === false) return;
    drawn.push(node);
  });
  const list = pickList(hits);
  const samples = [];
  const project = (point) => {
    const v = point.clone().project(camera);
    return { x: ((v.x + 1) / 2) * size.w, y: ((1 - v.y) / 2) * size.h, ndc: { x: v.x, y: v.y } };
  };
  const nearestOwner = (ndc) => {
    raycaster.setFromCamera(ndc, camera);
    const first = raycaster.intersectObjects(drawn, false)[0];
    return first ? list.owner.get(first.object) || null : null;
  };
  for (const hit of hits) {
    const own = list.meshes.filter((mesh) => list.owner.get(mesh) === hit);
    const centres = own.map((mesh) => ({ kind: "mesh", shell: Boolean(mesh.userData && mesh.userData.shell), point: new THREE.Box3().setFromObject(mesh).getCenter(new THREE.Vector3()) }));
    centres.push({ kind: "box", point: new THREE.Box3().setFromObject(hit.object).getCenter(new THREE.Vector3()) });
    for (const { kind, point, shell } of centres) {
      const at = project(point);
      if (at.ndc.x < -1 || at.ndc.x > 1 || at.ndc.y < -1 || at.ndc.y > 1) continue;
      if (nearestOwner(at.ndc) === hit) samples.push({ id: hit.id, x: at.x, y: at.y, kind, shell: Boolean(shell) });
    }
  }
  return samples;
}
