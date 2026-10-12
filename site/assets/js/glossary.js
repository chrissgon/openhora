(function () {
  var q = document.querySelector("[data-gl-filter]"), rows = document.querySelectorAll(".gl-row"), empty = document.querySelector("[data-gl-empty]");
  if (!q) return;
  q.addEventListener("input", function () {
    var v = q.value.trim().toLowerCase(), n = 0;
    rows.forEach(function (r) { var on = !v || r.textContent.toLowerCase().indexOf(v) >= 0; r.hidden = !on; if (on) n++; });
    empty.hidden = n > 0;
  });
})();
