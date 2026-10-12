// The one place the page reaches the network: api.js sends every request through `transport(url, init)`, which returns a Response.
// In the interface the service serves, this is the browser's own request function and nothing else. There is no flag, query string or
// stored value that changes it: the copy built for the demo (scripts/build_demo.py) has this file replaced by one that answers from memory,
// and only that copy does.

export function transport(url, init) {
  return fetch(url, init);
}
