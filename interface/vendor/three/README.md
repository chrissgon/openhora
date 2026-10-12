# Vendored: Three.js

The 3D renderer of the interface, copied unchanged from its official npm package. Nothing here is edited: a test
(`runtime/tests/test_interface_files.py`) compares every file listed below with the hash written here.

- Package: `three` on npm (https://www.npmjs.com/package/three), fetched with `npm pack three@latest` into a folder outside the repository
- Version: **0.186.1**
- Licence: MIT, the text is in `LICENSE-three.txt` (copied from the package's `LICENSE`)
- Copied from the package's `build/` folder: `three.module.js` and `three.core.js`. In this version the module imports
  `./three.core.js`, so the two files travel together. No loader, no controls and no addon is vendored.

| File | Bytes | sha256 |
|---|---|---|
| `LICENSE-three.txt` | 1081 | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |
| `three.core.js` | 1458113 | `9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6` |
| `three.module.js` | 662772 | `9052042d676cb0fdc1ddfefe193053f34b7ac0513a616fdac4535d49987812ea` |

A page imports it through `../js/three.js` (a one-line re-export by a relative path), never by an import map, because the
policy the service sends forbids inline scripts. Nothing is loaded from another host.

## To update

1. In a folder outside the repository: `npm pack three@<version>`, unpack the tarball.
2. Replace `three.module.js`, `three.core.js` and `LICENSE-three.txt` with `package/build/three.module.js`,
   `package/build/three.core.js` and `package/LICENSE`. If a new version splits the build in other files, copy exactly those
   that `three.module.js` imports.
3. Rewrite the version and the table above (`shasum -a 256 <file>`), and run `pytest -q runtime/tests/test_interface_files.py`.
