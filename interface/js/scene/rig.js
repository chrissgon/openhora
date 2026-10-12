// The camera rig of the scenes: one isometric orthographic camera (45 degrees round, 35 degrees up) and the bounds of a built
// scene as that camera sees them. The engine and the offline picking test both take them from here, so the test looks through the
// same camera as the page.

export const DISTANCE = 150;
export const AZIMUTH = (45 * Math.PI) / 180;
export const ELEVATION = (35 * Math.PI) / 180;

/** The isometric camera, looking at the origin; its frustum is set by the fit (fit.js). */
export function createCamera(THREE) {
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 1, 500);
  camera.position.set(DISTANCE * Math.cos(ELEVATION) * Math.sin(AZIMUTH), DISTANCE * Math.sin(ELEVATION), DISTANCE * Math.cos(ELEVATION) * Math.cos(AZIMUTH));
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  return camera;
}

/** The bounds of `object` in camera space: {x0, x1, y0, y1}. */
export function contentBounds(THREE, camera, object) {
  return boundsOfBox(THREE, camera, new THREE.Box3().setFromObject(object));
}

/** The bounds of a world-space box (THREE.Box3) in camera space: {x0, x1, y0, y1}. */
export function boundsOfBox(THREE, camera, box) {
  camera.updateMatrixWorld();
  const inverse = camera.matrixWorldInverse;
  const xs = [];
  const ys = [];
  for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
    const p = new THREE.Vector3(x, y, z).applyMatrix4(inverse);
    xs.push(p.x);
    ys.push(p.y);
  }
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
}
