/* Watch history kept in this browser only (localStorage). No account, nothing sent anywhere.
   Entry per video: { s: last position (s), d: duration (s), w: watched?, u: updated (ms epoch) } */
(function () {
  "use strict";
  var KEY = "altube.history.v1";
  var WATCHED_AT = 0.9; // fraction of the video that counts as "watched"
  var ID_RE = /^[\w-]{11}$/;
  var listeners = [];

  function load() {
    try {
      var o = JSON.parse(localStorage.getItem(KEY) || "null");
      if (o && o.v === 1 && o.items && typeof o.items === "object" && !Array.isArray(o.items)) return o.items;
    } catch (e) { /* corrupted or unavailable storage: start empty */ }
    return {};
  }
  var data = load();

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify({ v: 1, items: data })); } catch (e) { /* private mode / quota */ }
    for (var i = 0; i < listeners.length; i++) { try { listeners[i](); } catch (e) {} }
  }
  function num(x) { x = +x; return isFinite(x) && x > 0 ? x : 0; }

  var H = {
    get: function (id) { return data[id] || null; },
    isWatched: function (id) { return !!(data[id] && data[id].w); },
    inProgress: function (id) { var e = data[id]; return !!e && !e.w && e.s >= 10; },
    /** 0..1 for progress bars */
    frac: function (id) {
      var e = data[id];
      if (!e) return 0;
      if (e.w) return 1;
      return e.d > 0 ? Math.min(1, e.s / e.d) : 0;
    },
    /** Record playback position; marks watched once WATCHED_AT is reached (never un-marks). */
    progress: function (id, seconds, duration) {
      if (!ID_RE.test(id)) return null;
      var e = data[id] || { s: 0, d: 0, w: false };
      e.s = Math.round(num(seconds));
      if (num(duration)) e.d = Math.round(num(duration));
      if (e.d && e.s / e.d >= WATCHED_AT) e.w = true;
      e.u = Date.now();
      data[id] = e;
      save();
      return e;
    },
    started: function (id, duration) {
      if (!ID_RE.test(id)) return;
      var e = data[id] || { s: 0, d: 0, w: false };
      if (!e.d && num(duration)) e.d = Math.round(num(duration));
      e.u = Date.now();
      data[id] = e;
      save();
    },
    setWatched: function (id, watched, duration) {
      if (!ID_RE.test(id)) return;
      var e = data[id] || { s: 0, d: Math.round(num(duration)), w: false };
      e.w = !!watched;
      if (!watched) e.s = 0;
      if (!e.d && num(duration)) e.d = Math.round(num(duration));
      e.u = Date.now();
      data[id] = e;
      save();
    },
    remove: function (id) { delete data[id]; save(); },
    clear: function () { data = {}; save(); },
    ids: function () { return Object.keys(data); },
    exportJSON: function () {
      return JSON.stringify({ app: "ai-learning-tube", v: 1, exported: new Date().toISOString(), items: data }, null, 1);
    },
    /** Merge a previously exported file. Newer entries win; "watched" is kept if either copy has it. */
    importJSON: function (text) {
      var o = JSON.parse(text);
      var items = o && o.items;
      if (!items || typeof items !== "object" || Array.isArray(items)) throw new Error("This isn't an AI Learning Tube history file.");
      var n = 0;
      Object.keys(items).forEach(function (id) {
        var e = items[id];
        if (!ID_RE.test(id) || !e || typeof e !== "object") return;
        var inc = { s: Math.round(num(e.s)), d: Math.round(num(e.d)), w: !!e.w, u: num(e.u) };
        var cur = data[id];
        if (!cur) { data[id] = inc; n++; return; }
        var newer = inc.u > (cur.u || 0) ? inc : cur;
        var merged = { s: newer.s, d: newer.d || cur.d || inc.d, w: !!(cur.w || inc.w), u: Math.max(inc.u, cur.u || 0) };
        if (JSON.stringify(merged) !== JSON.stringify(cur)) { data[id] = merged; n++; }
      });
      save();
      return n;
    },
    onChange: function (fn) { listeners.push(fn); },
  };

  // Keep several open tabs in sync.
  window.addEventListener("storage", function (e) {
    if (e.key === KEY) {
      data = load();
      for (var i = 0; i < listeners.length; i++) { try { listeners[i](); } catch (err) {} }
    }
  });
  window.WatchHistory = H;
})();
