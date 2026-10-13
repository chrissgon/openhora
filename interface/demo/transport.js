// The demo's transport: it replaces js/transport.js in the copy of the interface that scripts/build_demo.py builds. It answers every request
// the page's client makes from the world in memory (world.js), as a Response with the JSON the service would give, and it asks nothing of the
// network. The import below is written so that it resolves the same from this folder and from js/ in the built copy.

import { world } from "../demo/instance.js";

const TOKEN_MIN = 32;

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** The same call the real transport has: a url and an init, and a Response. */
export async function transport(url, init = {}) {
  if (init.signal && init.signal.aborted) throw new DOMException("aborted", "AbortError");
  const method = (init.method || "GET").toUpperCase();
  const [path, text = ""] = String(url).split("?");
  const headers = init.headers || {};
  const auth = headers.Authorization || headers.authorization || "";
  if (path.startsWith("/api/v1") && !(auth.startsWith("Bearer ") && auth.length >= "Bearer ".length + TOKEN_MIN)) {
    return json(401, { error: "token", message: "an API path needs the header Authorization: Bearer <the token in the token file>" });
  }
  if (path === "/token-file") return json(404, { error: "not_found", message: "no such route, project or file" });
  let body = {};
  if (method === "POST" && typeof init.body === "string" && init.body) {
    try {
      body = JSON.parse(init.body);
    } catch (e) {
      return json(400, { error: "usage", message: "the request body is not JSON" });
    }
  }
  const answer = await world.handle(method, path, new URLSearchParams(text), body);
  return json(answer.status, answer.body);
}

/** The upload variant of the real transport: the demo takes no file in, and says so as the service would refuse it. */
export async function transportUpload(url, init = {}, onProgress) {
  if (init.signal && init.signal.aborted) throw new DOMException("aborted", "AbortError");
  return json(409, { error: "refused", message: "This demonstration takes no recording." });
}
