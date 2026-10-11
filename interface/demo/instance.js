// The one world of the page. The transport (the copy of this folder's transport.js that sits in js/ in the built page) and boot.js both import it
// from here, so they share one: a module's instance is per address, and those two files are at two addresses.

import { createWorld } from "./world.js";

export const world = createWorld();
