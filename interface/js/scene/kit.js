// The drawing kit of one built scene: cached materials, shared geometry and the helpers that put boxes and cylinders in
// a group. Everything it creates is tracked so `dispose()` frees it (geometries and materials) when the scene is
// rebuilt or left. `box(w, h, d, x, y, z, colour)` puts the box's bottom face at y, as the design tool's code does.

import * as THREE from "../three.js";

export function createKit(palette) {
  const lambert = new Map();
  const basic = new Map();
  const geometries = [];
  const unit = new THREE.BoxGeometry(1, 1, 1);
  const unitEdges = new THREE.EdgesGeometry(unit);
  const edgeMaterial = new THREE.LineBasicMaterial({ color: palette.T.border });
  const themeLine = new THREE.LineBasicMaterial({ color: palette.T.theme });
  const materials = [edgeMaterial, themeLine];

  const lit = (colour) => {
    const key = colour.getHexString();
    if (!lambert.has(key)) lambert.set(key, new THREE.MeshLambertMaterial({ color: colour }));
    return lambert.get(key);
  };
  const flat = (colour) => {
    const key = "f" + colour.getHexString();
    if (!lambert.has(key)) lambert.set(key, new THREE.MeshLambertMaterial({ color: colour, flatShading: true }));
    return lambert.get(key);
  };
  const unlit = (colour) => {
    const key = colour.getHexString();
    if (!basic.has(key)) basic.set(key, new THREE.MeshBasicMaterial({ color: colour }));
    return basic.get(key);
  };
  const track = (geometry) => {
    geometries.push(geometry);
    return geometry;
  };
  // Flat faces in the tone of each (round 4): a material that takes its colour from the vertices and no light, shared by every batch.
  const vertexMaterial = new THREE.MeshBasicMaterial({ vertexColors: true });
  const instances = [];

  const kit = {
    palette, THREE, lit, flat, unlit, track, edgeMaterial, themeLine, unitEdges, unitBox: unit,
    /** A box with its bottom face at y. o: {unlit, cast, edges, shell, parent}; `shell` marks a part of the object's outline (outline.js). */
    box(w, h, d, x, y, z, colour, o = {}) {
      const mesh = new THREE.Mesh(unit, o.unlit ? unlit(colour) : lit(colour));
      mesh.scale.set(w, h, d);
      mesh.position.set(x, y + h / 2, z);
      mesh.castShadow = o.cast !== false;
      mesh.receiveShadow = true;
      if (o.shell) mesh.userData.shell = true;
      (o.parent).add(mesh);
      if (o.edges) {
        const lines = new THREE.LineSegments(unitEdges, edgeMaterial);
        lines.scale.copy(mesh.scale);
        lines.position.copy(mesh.position);
        o.parent.add(lines);
      }
      return mesh;
    },
    /** A mesh of a geometry made by the caller (tracked). o: {unlit, flat, cast, shell, parent}. */
    mesh(geometry, colour, x, y, z, o = {}) {
      const mesh = new THREE.Mesh(track(geometry), o.unlit ? unlit(colour) : o.flat ? flat(colour) : lit(colour));
      mesh.position.set(x, y, z);
      mesh.castShadow = o.cast !== false;
      mesh.receiveShadow = true;
      if (o.shell) mesh.userData.shell = true;
      o.parent.add(mesh);
      return mesh;
    },
    /** A cylinder with its bottom face at y. */
    cyl(rt, rb, h, segments, colour, x, y, z, o = {}) {
      return kit.mesh(new THREE.CylinderGeometry(rt, rb, h, segments), colour, x, y + h / 2, z, o);
    },
    /** A line through points [[x, y, z], ...]. */
    line(points, material, parent) {
      const geometry = track(new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p))));
      const line = new THREE.Line(geometry, material);
      parent.add(line);
      return line;
    },
    /**
     * A batch of static solids and quads, baked into one geometry with a colour on every vertex, drawn in one call (the performance budget: the
     * City holds hundreds of boxes). A solid is given its three visible faces, top, left (+z) and right (+x), each in its own tone; the faces that
     * look away from the camera are not made. `mesh(parent, o)` makes the one mesh (null when the batch is empty); o: {cast, shell}.
     */
    batch() {
      const position = [];
      const colour = [];
      const vertex = (p, c) => {
        position.push(p[0], p[1], p[2]);
        colour.push(c.r, c.g, c.b);
      };
      const quad = (a, b, c, d, tone) => {
        for (const p of [a, b, c, a, c, d]) vertex(p, tone);
      };
      const batch = {
        /** A box with its bottom face at y; `tones` is a Colour or {top, left, right}. */
        box(w, h, d, x, y, z, tones) {
          const t = tones.isColor ? { top: tones, left: tones, right: tones } : tones;
          const x0 = x - w / 2, x1 = x + w / 2, y0 = y, y1 = y + h, z0 = z - d / 2, z1 = z + d / 2;
          quad([x0, y1, z1], [x1, y1, z1], [x1, y1, z0], [x0, y1, z0], t.top);
          quad([x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1], t.left);
          quad([x1, y0, z1], [x1, y0, z0], [x1, y1, z0], [x1, y1, z1], t.right);
          return batch;
        },
        /** A flat rectangle facing up at height y, from (x0, z0) to (x1, z1). */
        flat(x0, z0, x1, z1, y, tone) {
          quad([x0, y, z1], [x1, y, z1], [x1, y, z0], [x0, y, z0], tone);
          return batch;
        },
        /** A rectangle in the front plane (facing +z) at depth z, from (x0, y0) to (x1, y1). */
        front(x0, y0, x1, y1, z, tone) {
          quad([x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z], tone);
          return batch;
        },
        /** A rectangle in the right plane (facing +x) at x, from (z0, y0) to (z1, y1). */
        side(z0, y0, z1, y1, x, tone) {
          quad([x, y0, z1], [x, y0, z0], [x, y1, z0], [x, y1, z1], tone);
          return batch;
        },
        /** A quad of four corners a, b, c, d ([x, y, z] each, counter-clockwise from the camera), in one tone. */
        quad(a, b, c, d, tone) {
          quad(a, b, c, d, tone);
          return batch;
        },
        /** A triangle of three corners, in one tone. */
        tri(a, b, c, tone) {
          for (const p of [a, b, c]) vertex(p, tone);
          return batch;
        },
        count: () => position.length / 9,
        mesh(parent, o = {}) {
          if (!position.length) return null;
          const geometry = track(new THREE.BufferGeometry());
          geometry.setAttribute("position", new THREE.Float32BufferAttribute(position, 3));
          geometry.setAttribute("color", new THREE.Float32BufferAttribute(colour, 3));
          geometry.computeBoundingSphere();
          const mesh = new THREE.Mesh(geometry, vertexMaterial);
          mesh.castShadow = o.cast !== false;
          mesh.receiveShadow = false;
          if (o.shell) mesh.userData.shell = true;
          parent.add(mesh);
          return mesh;
        },
      };
      return batch;
    },
    /** `count` copies of one geometry, one draw call; the caller sets each matrix. The material is the kit's vertex-colour one unless given. */
    instanced(geometry, count, parent, o = {}) {
      const mesh = new THREE.InstancedMesh(track(geometry), o.material || vertexMaterial, count);
      mesh.castShadow = o.cast !== false;
      mesh.receiveShadow = false;
      instances.push(mesh);
      parent.add(mesh);
      return mesh;
    },
    vertexMaterial,
    /** A material the caller made (the beacon's): freed with the kit. */
    adopt(material) {
      materials.push(material);
      return material;
    },
    /** Free a geometry made through `track` or `mesh` now, and forget it (a tower that is made again frees its own; the kit lives as long as the scene). */
    release(geometry) {
      const at = geometries.indexOf(geometry);
      if (at >= 0) geometries.splice(at, 1);
      if (geometry !== unit && geometry !== unitEdges) geometry.dispose();
    },
    /** Free a material made through `adopt` now, and forget it. */
    free(material) {
      const at = materials.indexOf(material);
      if (at >= 0) materials.splice(at, 1);
      material.dispose();
    },
    dispose() {
      for (const g of geometries) g.dispose();
      geometries.length = 0;
      for (const mesh of instances) mesh.dispose();
      instances.length = 0;
      vertexMaterial.dispose();
      for (const m of [...lambert.values(), ...basic.values(), ...materials]) m.dispose();
      lambert.clear();
      basic.clear();
      unit.dispose();
      unitEdges.dispose();
    },
  };
  return kit;
}
