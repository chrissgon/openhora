// The one place the 3D library is imported from. A page module imports "./three.js" and gets the vendored build, by a
// relative path: the page's policy forbids an inline import map, and nothing is loaded from another host. Nothing
// imports this file in the plumbing package; the scene packages do.
export * from "../vendor/three/three.module.js";
