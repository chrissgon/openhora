/* A replay with play and pause (How openhora is built: "An injection, refused").
   Without script every step is shown, in order. Under reduced motion the steps change without animation. */
(function () {
  document.querySelectorAll("[data-replay]").forEach(function (box) {
    var steps = box.querySelectorAll("[data-step]"), dots = box.querySelectorAll("[data-goto]");
    var play = box.querySelector("[data-play]"), word = play.querySelector(".rp-word"), restart = box.querySelector("[data-restart]");
    var ms = parseInt(box.getAttribute("data-ms"), 10) || 2500, at = 0, timer = null;
    box.classList.add("is-live");
    var show = function (i) {
      at = i;
      steps.forEach(function (s, k) { s.classList.toggle("is-on", k <= i); s.classList.toggle("is-now", k === i); s.setAttribute("aria-hidden", k <= i ? "false" : "true"); });
      dots.forEach(function (d, k) { d.classList.toggle("done", k < i); d.classList.toggle("now", k === i); d.setAttribute("aria-current", k === i ? "step" : "false"); });
      box.classList.toggle("is-end", i === steps.length - 1);
    };
    var stop = function () { clearInterval(timer); timer = null; box.classList.remove("is-playing"); word.textContent = "Play"; play.setAttribute("aria-label", "Play"); };
    var start = function () {
      if (at >= steps.length - 1) show(0);
      box.classList.add("is-playing"); word.textContent = "Pause"; play.setAttribute("aria-label", "Pause");
      timer = setInterval(function () {
        if (at >= steps.length - 1) { stop(); return; }
        show(at + 1);
      }, ms);
    };
    play.addEventListener("click", function () { timer ? stop() : start(); });
    restart.addEventListener("click", function () { stop(); show(0); start(); });
    dots.forEach(function (d) { d.addEventListener("click", function () { stop(); show(parseInt(d.getAttribute("data-goto"), 10)); }); });
    show(0);
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (e) {
        if (e[0].isIntersecting) { io.disconnect(); if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) start(); }
      }, { threshold: 0.4 });
      io.observe(box);
    }
  });
})();
