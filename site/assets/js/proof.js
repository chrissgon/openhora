/* Proof page: "Which model runs this skill?" and "The gate, by hand". Static: assets/data/proof.json, no network
   beyond this site's own file. Without script, the page shows mkt-social-copy's result and the gate's starting values. */
(function () {
  var BAND = { "reliable": "ok", "watch": "warn", "needs a test": "err" };
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };

  /* ---------- which model runs this skill: the rule of runtime/proof.py, route() ---------- */
  var box = document.querySelector("[data-model-route]");
  if (box) {
    var q = box.querySelector("input"), list = box.querySelector("ul"), out = box.querySelector("[data-result]");
    var data = null, picked = "mkt-social-copy";
    var render = function (name) {
      var s = data.skills.filter(function (x) { return x.skill === name; })[0];
      if (!s) return;
      picked = name;
      var rows = data.lab_models.map(function (l) { return { model: l.model, adapter: l.adapter, m: s.models[l.model] || { band: "needs a test", cause: "no evidence on this model", score: "n/a", mean: "n/a", runs: "0", gate: "-" } }; });
      var reliable = rows.filter(function (r) { return r.m.band === "reliable"; });
      var row = function (model, adapter, m) {
        return '<tr><th scope="row"><b>' + esc(model) + "</b><small>" + esc(adapter) + "</small></th><td>" +
          '<span class="band-word ' + BAND[m.band] + '">' + esc(m.band) + "</span>" + (m.cause ? '<small class="mr-cause">' + esc(m.cause) + "</small>" : "") +
          "</td><td>" + esc(m.score) + "</td><td>" + esc(m.mean) + "</td><td>" + esc(m.runs) + "</td><td>" + esc(m.gate) + "</td></tr>";
      };
      var why = reliable.length
        ? "its band is reliable on " + reliable.length + " of " + rows.length + " lab models: the runtime may release a run on them without review, when the measurement and the image match the recorded ones, and auto picks the cheapest of them by price and measured usage; a model you name runs whatever its band, and then waits for you"
        : "no lab model has a reliable band for it: a run waits for your review, whichever model you name";
      out.innerHTML =
        '<div class="mr-head"><h4 class="mr-name">' + esc(s.skill) + '</h4><span class="mr-ver">v' + esc(s.version) + " · last full test " + esc(s.last_full_test) + "</span></div>" +
        '<table class="mr-table"><thead><tr><th scope="col">Model</th><th scope="col">Band</th><th scope="col">Score</th><th scope="col">Mean</th><th scope="col">Runs</th><th scope="col">Gate</th></tr></thead><tbody>' +
        rows.map(function (r) { return row(r.model, r.adapter, r.m); }).join("") + "</tbody></table>" +
        '<div class="mr-route ' + (reliable.length ? "is-floor" : "is-ref") + '"><p class="mr-k">Released without review on</p><p class="mr-model">' +
        (reliable.length ? reliable.map(function (r) { return esc(r.model); }).join(", ") : "no lab model") + ' <span class="pui-badge pui-soft ' + (reliable.length ? "pui-success" : "pui-theme") + '">' +
        (reliable.length ? "reliable" : "supervised") + '</span></p><p class="mr-why"><span>Why:</span> ' + esc(why) + ".</p></div>";
      list.querySelectorAll("button").forEach(function (b) {
        if (b.getAttribute("data-skill") === name) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
      });
    };
    var filter = function () {
      var v = q.value.trim().toLowerCase();
      list.querySelectorAll("li").forEach(function (li) { li.hidden = v && li.textContent.toLowerCase().indexOf(v) < 0; });
    };
    list.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-skill]");
      if (b && data) render(b.getAttribute("data-skill"));
    });
    list.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      var items = Array.prototype.filter.call(list.querySelectorAll("button"), function (b) { return !b.closest("li").hidden; });
      var i = items.indexOf(document.activeElement);
      var n = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (n) { n.focus(); e.preventDefault(); }
    });
    q.addEventListener("input", filter);
    q.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === "ArrowDown") {
        var first = Array.prototype.filter.call(list.querySelectorAll("button"), function (b) { return !b.closest("li").hidden; })[0];
        if (first) { if (e.key === "Enter" && data) render(first.getAttribute("data-skill")); else first.focus(); e.preventDefault(); }
      }
    });
    /* the data is the committed file assets/data/proof.json, from this site's own folder */
    fetch("/assets/data/proof.json").then(function (r) { return r.json(); }).then(function (d) {
      data = d;
      render(picked);
    }).catch(function () { data = null; });
  }

  /* ---------- the gate, by hand: measure.py gate_passes, eval_status.py pessimistic_score ---------- */
  var gate = document.querySelector("[data-gate]");
  if (gate) {
    var THRESHOLD = 0.8, TOLERANCE = 0.05, Z = 1.2816, RELIABLE_AT = 0.70, SLACK = 1e-9;
    var pess = function (s, n) {
      if (n <= 0) return 0;
      var p = s / n, z2 = Z * Z;
      var margin = Z * Math.sqrt(Math.max(0, p * (1 - p) / n + z2 / (4 * n * n)));
      return Math.max(0, (p + z2 / (2 * n) - margin) / (1 + z2 / n));
    };
    var f2 = function (x) { return x.toFixed(2); };
    var $ = function (s) { return gate.querySelector(s); };
    var update = function () {
      var cases = {}, bases = {};
      gate.querySelectorAll("input[type=range]").forEach(function (r) {
        var c = r.getAttribute("data-case"), v = parseFloat(r.value);
        r.nextElementSibling.textContent = f2(v);
        if (r.hasAttribute("data-base")) bases[c] = v; else (cases[c] = cases[c] || []).push(v);
      });
      var keys = Object.keys(cases), S = 0, N = 0, withMeans = [], baseMeans = [];
      keys.forEach(function (c) {
        var m = cases[c].reduce(function (a, b) { return a + b; }, 0) / cases[c].length;
        S += cases[c].reduce(function (a, b) { return a + b; }, 0); N += cases[c].length;
        withMeans.push(m); baseMeans.push(bases[c]);
        $("[data-case-mean='" + c + "']").textContent = f2(m);
      });
      var mean = function (a) { return a.reduce(function (x, y) { return x + y; }, 0) / a.length; };
      var w = mean(withMeans), b = mean(baseMeans);
      var atThr = w >= THRESHOLD - SLACK, inTol = w >= b - TOLERANCE - SLACK, pass = atThr && inTol;
      $("[data-with]").textContent = f2(w); $("[data-base]").textContent = f2(b);
      $("[data-with-bar]").style.width = (w * 100) + "%"; $("[data-base-bar]").style.width = (b * 100) + "%";
      var v = $("[data-verdict]");
      v.classList.toggle("is-pass", pass); v.classList.toggle("is-fail", !pass);
      $("[data-verdict-word]").textContent = pass ? "The gate passes" : "The gate fails";
      $("[data-verdict-why]").textContent = pass
        ? f2(w) + " ≥ 0.8, and " + f2(w) + " is not below " + f2(b) + " − 0.05"
        : (!atThr ? f2(w) + " is under the threshold 0.8" : f2(w) + " is below " + f2(b) + " − 0.05, the baseline minus the tolerance");
      var score = pess(S, N), band, why;
      if (!pass) { band = "needs a test"; why = "the newest full test fails the gate"; }
      else if (score < RELIABLE_AT) { band = "watch"; why = "pessimistic score " + f2(score) + " is under 0.70 (mean " + f2(S / N) + ", " + N + " runs)"; }
      else { band = "reliable"; why = "pessimistic score " + f2(score) + " (mean " + f2(S / N) + ", " + N + " runs)"; }
      var bw = $("[data-band]");
      bw.className = "band-word " + BAND[band]; bw.textContent = band;
      $("[data-band-why]").textContent = why;
    };
    gate.addEventListener("input", update);
    update();
  }
})();
