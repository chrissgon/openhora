// The one place the page reaches the network: api.js sends every request through `transport(url, init)`, which returns a Response.
// In the interface the service serves, this is the browser's own request function and nothing else. There is no flag, query string or
// stored value that changes it: the copy built for the demo (scripts/build_demo.py) has this file replaced by one that answers from memory,
// and only that copy does.

export function transport(url, init) {
  return fetch(url, init);
}

/**
 * The one other way out of the page: an upload that reports its progress. A request body that is a file (a recording) is sent with a request
 * object that tells how many bytes have gone (`onProgress(sent, total)`), which `fetch` cannot do over plain HTTP. It takes the same `init` as
 * `transport` and returns the same kind of Response; api.js calls it for the media route alone. A request that could not be made rejects, as
 * `fetch` does; an aborted one rejects with an AbortError.
 */
export function transportUpload(url, init, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(init.method || "POST", url);
    request.responseType = "text";
    for (const [name, value] of Object.entries(init.headers || {})) request.setRequestHeader(name, value);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === "function") onProgress(event.loaded, event.total);
    };
    request.onload = () => resolve(new Response(request.responseText, { status: request.status, headers: { "Content-Type": request.getResponseHeader("Content-Type") || "application/json" } }));
    request.onerror = () => reject(new TypeError("network error"));
    request.ontimeout = () => reject(new TypeError("network error"));
    request.onabort = () => reject(new DOMException("aborted", "AbortError"));
    if (init.signal) {
      if (init.signal.aborted) {
        reject(new DOMException("aborted", "AbortError"));
        return;
      }
      init.signal.addEventListener("abort", () => request.abort());
    }
    request.send(init.body);
  });
}
