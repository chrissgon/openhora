/* Interface page: the tour's frame (it loads the interface in demo mode, /demo/index.html, from this same origin and talks
   to it by postMessage), "Who holds the power", and the owl's states shown once.
   Without script: the poster and the screenshots below are in the page, and Start does nothing. */
(function () {
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- the tour ---------- */
  /* In: play (reduced motion only). Out: ready, step, took-over, ended. The visitor takes over by using the demo itself and restarts it with its
     own "Start over". Only this origin and the frame's own window are heard. */
  document.querySelectorAll("[data-tour]").forEach(function (box) {
    var $ = function (s) { return box.querySelector(s); };
    var frame = $(".tour-frame"), takeLine = $(".tour-takeover");
    var watchdog = null, attempt = 0;
    var LOAD_LIMIT_MS = 15000;

    /* From 900 px up the frame is 1280 by 800 (see .tour-frame) and is scaled to the screen's inner width; the screen's height follows (16:10). */
    var screen = $(".tour-screen");
    var fit = function () {
      var w = screen.getBoundingClientRect().width;
      if (w > 0) box.style.setProperty("--tour-scale", String(w / 1280));
    };
    fit();
    if (window.ResizeObserver) new ResizeObserver(fit).observe(screen);
    window.addEventListener("resize", fit);

    var send = function (type) {
      if (frame.contentWindow) frame.contentWindow.postMessage({ type: type }, location.origin);
    };
    var state = function (name) { box.setAttribute("data-state", name); };
    var fail = function () {
      attempt++; clearTimeout(watchdog);
      frame.removeAttribute("src");
      state("error");
    };
    var playing = function () {
      clearTimeout(watchdog); takeLine.hidden = true;
      state("playing");
    };
    var load = function () {
      var mine = ++attempt, url = frame.getAttribute("data-src");
      state("loading"); takeLine.hidden = true;
      clearTimeout(watchdog);
      watchdog = setTimeout(function () { if (mine === attempt) fail(); }, LOAD_LIMIT_MS);
      fetch(url, { method: "HEAD", cache: "no-store" }).then(function (r) {
        if (mine !== attempt) return;
        if (!r.ok) { fail(); return; }
        frame.src = url;
      }).catch(function () { if (mine === attempt) fail(); });
    };

    window.addEventListener("message", function (e) {
      if (e.origin !== location.origin || e.source !== frame.contentWindow || !e.data || typeof e.data.type !== "string") return;
      var t = e.data.type, now = box.getAttribute("data-state");
      if (t === "ready" && now === "loading") {
        playing();
        if (reduce) send("play");
      } else if (t === "took-over" && (now === "playing")) {
        state("takeover"); takeLine.hidden = false;
      } else if (t === "step" && now === "takeover") {
        playing();
      } else if (t === "ended" && now === "playing") {
        state("ended");
      }
    });

    $("[data-tour-start]").addEventListener("click", load);
    $("[data-tour-retry]").addEventListener("click", load);
  });

/* ---------- who holds the power ---------- */
  document.querySelectorAll("[data-power]").forEach(function (box) {
    var ORDER = ["stopped", "supervised", "milestones", "autonomous", "autonomous-with-policy"];
    var current = "milestones";
    var msg = box.querySelector("[data-pw-msg]"), cmd = box.querySelector("[data-pw-cmd]"), target = box.querySelector("[data-pw-target]");
    var paint = function () {
      box.querySelectorAll(".pw-rung").forEach(function (r) {
        var on = r.getAttribute("data-mode") === current;
        r.classList.toggle("is-now", on);
        r.querySelector(".pw-tag").textContent = on ? "current" : "";
        r.querySelector(".pw-btn").setAttribute("aria-pressed", on ? "true" : "false");
      });
    };
    var say = function (cls, h, p) {
      msg.className = "pw-msg " + cls;
      msg.innerHTML = '<p class="pw-h">' + h + '</p><p class="pw-p">' + p + "</p>";
    };
    var pick = function (m) {
      var from = ORDER.indexOf(current), to = ORDER.indexOf(m);
      box.querySelectorAll(".pw-rung").forEach(function (r) { r.classList.remove("is-refused"); });
      if (to === from) { say("is-idle", "Already " + m, "The same mode changes nothing and writes nothing."); cmd.hidden = true; return; }
      if (to < from) {
        current = m; paint(); cmd.hidden = true;
        say("is-ok", "Accepted at once: " + m, "A move down widens nothing: code accepts the new hash at once and says <code>code:narrowing</code>.");
      } else {
        box.querySelector('.pw-rung[data-mode="' + m + '"]').classList.add("is-refused");
        say("is-no", "Refused on this page: " + m, "A move up never is accepted by code. The mode stays <code>" + current + "</code>.");
        target.textContent = m; cmd.hidden = false;
      }
    };
    box.querySelectorAll("[data-mode-pick]").forEach(function (b) { b.addEventListener("click", function () { pick(b.getAttribute("data-mode-pick")); }); });
    var want = (location.search.match(/[?&]power=([a-z-]+)/) || [])[1];
    if (want) pick(want);
  });
})();
