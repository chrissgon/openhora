/* openhora website: progressive enhancement only. Without this script every page is complete:
   the colour mode follows the system, the navigation opens through its checkbox, every figure and
   every artifact is shown in its final state. Loaded with `defer`. */
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  /* Colour mode: System -> Light -> Dark. Nothing is stored: a reload starts on System. */
  var NAMES = { system: "System", light: "Light", dark: "Dark" };
  var NEXT = { system: "light", light: "dark", dark: "system" };
  document.querySelectorAll("[data-mode-btn]").forEach(function (btn) {
    var set = function (mode) {
      if (mode === "system") root.removeAttribute("data-pui-mode"); else root.setAttribute("data-pui-mode", mode);
      btn.setAttribute("aria-label", "Colour mode: " + NAMES[mode]);
      btn.setAttribute("data-current", mode);
    };
    btn.addEventListener("click", function () { set(NEXT[btn.getAttribute("data-current") || "system"]); });
  });

  /* A figure settles once, when its region first comes into view. */
  var count = function (el) {
    var end = parseInt(el.getAttribute("data-count"), 10);
    if (reduce.matches || !end) return;
    var start = performance.now(), dur = 900, last = -1;
    var frame = function (now) {
      var t = Math.min(1, (now - start) / dur);
      var v = Math.round(end * (1 - Math.pow(1 - t, 3)));
      if (v !== last) { el.textContent = String(v); last = v; }
      if (t < 1) setTimeout(function () { requestAnimationFrame(frame); }, 33); /* at most 30 fps */
    };
    el.textContent = "0";
    requestAnimationFrame(frame);
  };
  var seen = function (el) {
    if (el.classList.contains("in")) return;
    el.classList.add("in");
    el.querySelectorAll("[data-count]").forEach(count);
  };
  var watched = document.querySelectorAll("[data-observe]");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { seen(e.target); io.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -12% 0px", threshold: 0.15 });
    watched.forEach(function (el) { io.observe(el); });
  } else {
    watched.forEach(seen);
  }

  /* The chain: one continuous line through the stations, in order, turning outside the grid at each row's end. */
  var rounded = function (pts, r) {
    var d = "M" + pts[0][0] + " " + pts[0][1];
    for (var i = 1; i < pts.length - 1; i++) {
      var p = pts[i - 1], q = pts[i], n = pts[i + 1];
      var d1 = Math.hypot(q[0] - p[0], q[1] - p[1]), d2 = Math.hypot(n[0] - q[0], n[1] - q[1]);
      var k1 = Math.min(r, d1 / 2) / d1, k2 = Math.min(r, d2 / 2) / d2;
      d += " L" + (q[0] - (q[0] - p[0]) * k1) + " " + (q[1] - (q[1] - p[1]) * k1);
      d += " Q" + q[0] + " " + q[1] + " " + (q[0] + (n[0] - q[0]) * k2) + " " + (q[1] + (n[1] - q[1]) * k2);
    }
    var z = pts[pts.length - 1];
    return d + " L" + z[0] + " " + z[1];
  };
  document.querySelectorAll("[data-metro]").forEach(function (box) {
    var svg = box.querySelector("svg"), q = function (s) { return svg.querySelector(s); };
    var ties = q(".ml-ties"), base = q(".ml-base"), glow = q(".ml-glow"), lit = q(".ml-lit"), head = q(".ml-head");
    var draw = function () {
      var o = box.getBoundingClientRect(), pts = [], prev = null, litEnd = 0, stns = [];
      box.querySelectorAll("[data-stn], [data-stn-next]").forEach(function (li) {
        var r = li.getBoundingClientRect();
        var c = [r.left + r.width / 2 - o.left, r.top + r.height / 2 - o.top, r, li];
        li.removeAttribute("data-pl"); li.removeAttribute("data-pr"); li.removeAttribute("data-pt"); li.removeAttribute("data-pb");
        if (prev) {
          if (Math.abs(prev[1] - c[1]) > 4) {
            /* a row change: the next station is under the last one (a serpentine), so the line drops straight down between them */
            prev[3].setAttribute("data-pb", ""); li.setAttribute("data-pt", "");
          } else {
            var toRight = c[0] > prev[0];
            prev[3].setAttribute(toRight ? "data-pr" : "data-pl", ""); li.setAttribute(toRight ? "data-pl" : "data-pr", "");
          }
        }
        pts.push([c[0], c[1]]);
        if (li.hasAttribute("data-stn")) { litEnd = pts.length; stns.push({ li: li, k: pts.length - 1 }); }
        prev = c;
      });
      var full = rounded(pts, 22), part = rounded(pts.slice(0, litEnd), 22);
      /* when the line reaches each station: its share of the lit length, so the card lights as the head arrives */
      var probe = document.createElementNS("http://www.w3.org/2000/svg", "path"); svg.appendChild(probe);
      probe.setAttribute("d", part); var total = probe.getTotalLength() || 1;
      stns.forEach(function (s) {
        var at = 0;
        if (s.k > 0) { probe.setAttribute("d", rounded(pts.slice(0, s.k + 1), 22)); at = probe.getTotalLength() / total; }
        s.li.style.setProperty("--at", Math.min(1, at).toFixed(3));
      });
      svg.removeChild(probe);
      ties.setAttribute("d", full); base.setAttribute("d", full);
      glow.setAttribute("d", part); lit.setAttribute("d", part);
      svg.setAttribute("viewBox", "0 0 " + o.width + " " + o.height);
      svg.style.setProperty("--len", Math.ceil(lit.getTotalLength()) + "px");
      head.style.offsetPath = "path('" + part + "')";
    };
    draw();
    window.addEventListener("resize", draw);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
  });

  /* "Approve this exact content": the hash is computed here, in the browser, on every keystroke.
     An approval holds the hash it was given; any other hash is not covered. */
  var sha256 = function (text) {
    var bytes = new TextEncoder().encode(text);
    if (window.crypto && crypto.subtle) {
      return crypto.subtle.digest("SHA-256", bytes).then(function (buf) {
        return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
      });
    }
    return Promise.resolve(sha256js(bytes));
  };
  /* fallback when crypto.subtle is unavailable (a page opened from an insecure origin) */
  var sha256js = function (m) {
    var K = [], H = [], i, j, isP = function (n) { for (var f = 2; f * f <= n; f++) if (n % f === 0) return false; return true; };
    for (i = 2, j = 0; j < 64; i++) if (isP(i)) { if (j < 8) H[j] = (Math.pow(i, 1 / 2) * 4294967296) | 0; K[j++] = (Math.pow(i, 1 / 3) * 4294967296) | 0; }
    var l = m.length, w = new Array(64), n = ((l + 9 + 63) >> 6) << 4, W = new Array(n).fill(0);
    for (i = 0; i < l; i++) W[i >> 2] |= m[i] << (24 - (i % 4) * 8);
    W[l >> 2] |= 0x80 << (24 - (l % 4) * 8); W[n - 1] = l * 8;
    var r = function (x, c) { return (x >>> c) | (x << (32 - c)); };
    for (j = 0; j < n; j += 16) {
      var a = H.slice(0);
      for (i = 0; i < 64; i++) {
        if (i < 16) w[i] = W[j + i] | 0;
        else { var s0 = r(w[i - 15], 7) ^ r(w[i - 15], 18) ^ (w[i - 15] >>> 3), s1 = r(w[i - 2], 17) ^ r(w[i - 2], 19) ^ (w[i - 2] >>> 10); w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0; }
        var t1 = (a[7] + (r(a[4], 6) ^ r(a[4], 11) ^ r(a[4], 25)) + ((a[4] & a[5]) ^ (~a[4] & a[6])) + K[i] + w[i]) | 0;
        var t2 = ((r(a[0], 2) ^ r(a[0], 13) ^ r(a[0], 22)) + ((a[0] & a[1]) ^ (a[0] & a[2]) ^ (a[1] & a[2]))) | 0;
        a = [(t1 + t2) | 0].concat(a.slice(0, 3), [(a[3] + t1) | 0], a.slice(4, 7));
      }
      for (i = 0; i < 8; i++) H[i] = (H[i] + a[i]) | 0;
    }
    return H.map(function (x) { return ("00000000" + (x >>> 0).toString(16)).slice(-8); }).join("");
  };
  document.querySelectorAll("[data-approve]").forEach(function (card) {
    var text = card.querySelector("textarea"), out = card.querySelector("[data-hash]");
    var btn = card.querySelector("[data-approve-btn]"), reset = card.querySelector("[data-reset-btn]");
    var record = card.querySelector("[data-record]"), approvedEl = card.querySelector("[data-approved]"), status = card.querySelector("[data-status]");
    var approved = null, approvedText = null, current = out.textContent, seq = 0;
    var paint = function () {
      if (approved) {
        var html = "";
        for (var i = 0; i < current.length; i++) {
          var c = current[i];
          html += c === approved[i] ? c : '<mark class="hx">' + c + "</mark>";
        }
        out.innerHTML = html;
      } else {
        out.textContent = current;
      }
      var covered = approved && current === approved;
      card.classList.toggle("is-approved", !!covered);
      card.classList.toggle("is-broken", !!approved && !covered);
      btn.textContent = covered ? "Approved" : "Approve this exact content";
      btn.disabled = !!covered;
      reset.hidden = !approved || covered;
      if (approved) {
        record.hidden = false;
        status.textContent = covered ? "This approval covers the content above." : "This approval no longer covers the content.";
      }
    };
    text.addEventListener("input", function () {
      var my = ++seq;
      sha256(text.value).then(function (h) { if (my !== seq) return; current = h; paint(); });
    });
    btn.addEventListener("click", function () {
      approved = current; approvedText = text.value; approvedEl.textContent = approved; paint();
    });
    reset.addEventListener("click", function () {
      text.value = approvedText; current = approved; paint(); text.focus();
    });
    btn.disabled = false;
    sha256(text.value).then(function (h) { current = h; paint(); });
  });

  /* A target heading takes the focus (Proof and Glossary anchors). */
  var focusTarget = function () {
    var id = decodeURIComponent(location.hash.slice(1));
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    var h = el.matches("h1,h2,h3,dt") ? el : el.querySelector("h2,h3,dt");
    if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
  };
  window.addEventListener("hashchange", focusTarget);
  focusTarget();
})();
