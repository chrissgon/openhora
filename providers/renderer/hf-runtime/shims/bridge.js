(function() {
  var __realSetInterval =
    window.__HF_VIRTUAL_TIME__ && typeof window.__HF_VIRTUAL_TIME__.originalSetInterval === "function"
      ? window.__HF_VIRTUAL_TIME__.originalSetInterval
      : window.setInterval.bind(window);
  var __realClearInterval =
    window.__HF_VIRTUAL_TIME__ && typeof window.__HF_VIRTUAL_TIME__.originalClearInterval === "function"
      ? window.__HF_VIRTUAL_TIME__.originalClearInterval
      : window.clearInterval.bind(window);
  function getDeclaredDuration() {
    var root = document.querySelector('[data-composition-id]');
    if (!root) return 0;
    var d = Number(root.getAttribute('data-duration'));
    if (Number.isFinite(d) && d > 0) return d;
    var comps = document.querySelectorAll('[data-composition-src]');
    var maxEnd = 0;
    for (var i = 0; i < comps.length; i++) {
      var start = Number(comps[i].getAttribute('data-start')) || 0;
      var dur = Number(comps[i].getAttribute('data-duration')) || 0;
      if (dur > 0) maxEnd = Math.max(maxEnd, start + dur);
    }
    if (maxEnd > 0) console.warn('[HF Bridge] No root data-duration; derived ' + maxEnd + 's from sub-compositions');
    return maxEnd;
  }
  function seekSameOriginChildFrames(frameWindow, nextTimeMs) {
    var frames;
    try {
      frames = frameWindow.frames;
    } catch (_error) {
      return;
    }
    if (!frames || typeof frames.length !== "number") return;
    for (var i = 0; i < frames.length; i++) {
      var childWindow = null;
      try {
        childWindow = frames[i];
        if (!childWindow || childWindow === frameWindow) continue;
        if (
          childWindow.__HF_VIRTUAL_TIME__ &&
          typeof childWindow.__HF_VIRTUAL_TIME__.seekToTime === "function"
        ) {
          childWindow.__HF_VIRTUAL_TIME__.seekToTime(nextTimeMs);
        }
      } catch (_error) {
        continue;
      }
      seekSameOriginChildFrames(childWindow, nextTimeMs);
    }
  }
  function bridge() {
    var p = window.__player;
    if (!p || typeof p.renderSeek !== "function" || typeof p.getDuration !== "function") {
      return false;
    }
    var hf = window.__hf || {};
    Object.defineProperty(hf, "duration", {
      configurable: true,
      enumerable: true,
      get: function() {
        // While the GSAP tween-batching interceptor (HF_EARLY_STUB) is draining
        // queued tweens via rAF, the real timelines are still empty. Return 0
        // here so pollHfReady in the engine keeps waiting (its condition is
        // __hf.duration > 0), preventing the capture pipeline from seeking
        // empty timelines and producing blank/incorrect frames.
        if (window.__hfTimelinesBuilding) return 0;
        if (!window.__renderReady) return 0;
        var d = p.getDuration();
        return d > 0 ? d : getDeclaredDuration();
      },
    });
    hf.seek = function(t, options) {
      p.renderSeek(t, options);
      var nextTimeMs = (Math.max(0, Number(t) || 0)) * 1000;
      if (window.__HF_VIRTUAL_TIME__ && typeof window.__HF_VIRTUAL_TIME__.seekToTime === "function") {
        window.__HF_VIRTUAL_TIME__.seekToTime(nextTimeMs);
      }
      seekSameOriginChildFrames(window, nextTimeMs);
    };
    window.__hf = hf;
    return true;
  }
  if (bridge()) return;
  var iv = __realSetInterval(function() {
    if (bridge()) __realClearInterval(iv);
  }, 50);
})();