/* AI Learning Tube — static front end. No dependencies; data comes from data/catalog.json. */
(function () {
  "use strict";

  const PAGE = 36;
  const LEVEL_LABEL = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" };
  const LEVEL_HINT = {
    beginner: "Short explainers and intro courses to build intuition.",
    intermediate: "Full university courses and hands-on tutorials.",
    advanced: "Research-level courses, seminars and frontier topics.",
  };
  const SORTS = { quality: "Top quality", newest: "Newest", views: "Most viewed", short: "Shortest first" };
  const DURS = { "": "Any length", s: "Under 10 min", m: "10–30 min", l: "30–60 min", xl: "Over 1 hour" };

  let DB = null; // catalog
  const IDX = {}; // lookups
  const $main = document.getElementById("main");
  const $nav = document.getElementById("sidebar");
  const $search = document.getElementById("search");
  let observer = null;

  // ------------------------------------------------------------ utils
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;
  // lowercase, accents stripped, punctuation -> spaces, padded so " token" matches word starts
  const norm = (s) => " " + String(s || "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ").trim() + " ";

  function fmtDur(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  }
  function fmtHours(sec) {
    const h = sec / 3600;
    return h >= 1 ? (Math.round(h * 10) / 10) + " h" : Math.round(sec / 60) + " min";
  }
  function fmtNum(n) {
    n = n || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "K";
    return String(n);
  }
  function ago(dateStr) {
    if (!dateStr) return "";
    const d = new Date(dateStr + "T00:00:00Z");
    const days = Math.max(0, (Date.now() - d.getTime()) / 864e5);
    const units = [[365, "year"], [30, "month"], [7, "week"], [1, "day"]];
    for (const [n, u] of units) {
      if (days >= n) { const k = Math.floor(days / n); return k + " " + u + (k > 1 ? "s" : "") + " ago"; }
    }
    return "today";
  }
  const thumbUrl = (id, size) => "https://i.ytimg.com/vi/" + enc(id) + "/" + (size || "mqdefault") + ".jpg";
  const ytUrl = (id) => "https://www.youtube.com/watch?v=" + enc(id);
  const plUrl = (id) => "https://www.youtube.com/playlist?list=" + enc(id);

  function parseHash() {
    const h = location.hash.replace(/^#/, "").split("#")[0] || "/";
    const [path, qs] = h.split("?");
    const params = new URLSearchParams(qs || "");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    return { parts, params };
  }
  function browseHref(over) {
    const { params } = parseHash();
    const p = new URLSearchParams();
    const merged = Object.assign({ q: params.get("q") || "", topic: params.get("topic") || "", lv: params.get("lv") || "",
      f: params.get("f") || "", ch: params.get("ch") || "", sort: params.get("sort") || "", dur: params.get("dur") || "" }, over || {});
    for (const k in merged) if (merged[k]) p.set(k, merged[k]);
    const s = p.toString();
    return "#/" + (s ? "?" + s : "");
  }

  // ------------------------------------------------------------ load
  fetch("data/catalog.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then((data) => { DB = data; index(); renderNav(); route(); })
    .catch((err) => {
      $main.innerHTML = '<p class="empty">Could not load the catalog (' + esc(err.message) + ").</p>";
    });

  function index() {
    IDX.video = new Map(DB.videos.map((v) => [v.id, v]));
    IDX.series = new Map(DB.series.map((s) => [s.id, s]));
    IDX.topic = new Map(DB.topics.map((t) => [t.id, t]));
    IDX.channel = new Map(DB.channels.map((c) => [c.key, c]));
    for (const v of DB.videos) {
      const tnames = v.tp.map((t) => (IDX.topic.get(t) || {}).name || t).join(" ");
      const ch = (IDX.channel.get(v.c) || {}).name || v.c;
      v._h = norm(v.t + " " + ch + " " + tnames + " " + v.lv + " " + v.f + " " + (v.why.kw || []).join(" ") + " " + v.tp.join(" "));
    }
    // position of each item within each topic's path (for "next step")
    IDX.pathPos = new Map();
    for (const tid in DB.paths) {
      const flat = [];
      for (const lv of DB.levels) for (const it of DB.paths[tid][lv] || []) flat.push(Object.assign({ lv }, it));
      IDX.pathPos.set(tid, flat);
    }
  }

  // ------------------------------------------------------------ nav
  function renderNav() {
    const link = (href, label, extra) => '<a class="nav-link" href="' + href + '">' + label + (extra || "") + "</a>";
    let h = link("#/", "🏠&nbsp; Home") + link("#/paths", "🧭&nbsp; Learning paths") + link("#/courses", "🎓&nbsp; Courses") +
      link("#/about", "ℹ️&nbsp; How ranking works");
    h += "<h4>Topics</h4>";
    for (const t of DB.topics) {
      if (!t.n) continue;
      h += link("#/topic/" + enc(t.id), '<span class="nav-dot"></span>' + esc(t.name), '<span class="count">' + t.n + "</span>");
    }
    h += "<h4>Channels</h4>";
    for (const c of DB.channels) {
      h += link("#/?ch=" + enc(c.key), esc(c.name), '<span class="count">' + c.n + "</span>");
    }
    $nav.innerHTML = h;
  }
  function markNav() {
    const cur = (location.hash || "#/").replace(/^(#[^#]*)#.*$/, "$1");
    for (const a of $nav.querySelectorAll(".nav-link")) {
      const href = a.getAttribute("href");
      const on = href === "#/" ? cur === "#/" || cur === "#" || cur === "" : cur === href || cur.startsWith(href + "?") || cur.startsWith(href + "/");
      a.classList.toggle("active", on);
    }
  }

  // ------------------------------------------------------------ routing
  window.addEventListener("hashchange", route);
  function route() {
    if (!DB) return;
    if (observer) { observer.disconnect(); observer = null; }
    document.body.classList.remove("nav-open");
    const { parts, params } = parseHash();
    $search.value = parts.length === 0 ? params.get("q") || "" : $search.value;
    const view = parts[0] || "";
    if (view === "watch" && parts[1]) renderWatch(parts[1]);
    else if (view === "topic" && parts[1]) renderTopic(parts[1]);
    else if (view === "course" && parts[1]) renderCourse(parts[1]);
    else if (view === "courses") renderCourses();
    else if (view === "paths") renderPaths();
    else if (view === "about") renderAbout();
    else renderBrowse(params);
    markNav();
    if (!(view === "paths" && location.hash.split("#")[2])) window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ pieces
  function avatar(chKey) {
    const c = IDX.channel.get(chKey) || { name: chKey };
    const initials = esc((c.name || "?").split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase());
    return '<span class="avatar">' + (c.thumb ? '<img src="' + esc(c.thumb) + '" alt="" loading="lazy">' : initials) + "</span>";
  }
  function chName(key) { return esc((IDX.channel.get(key) || {}).name || key); }
  function topicName(id) { return esc((IDX.topic.get(id) || {}).name || id); }
  function lvTag(lv) { return '<span class="tag lv-' + esc(lv) + '">' + esc(LEVEL_LABEL[lv] || lv) + "</span>"; }

  function thumb(id, label, badges) {
    return '<div class="thumb"><img src="' + thumbUrl(id) + '" alt="" loading="lazy"><span class="ph">' + esc(label) + "</span>" + (badges || "") + "</div>";
  }

  function videoCard(v, opts) {
    opts = opts || {};
    const step = opts.step ? '<span class="step-num">' + opts.step + "</span>" : "";
    return '<article class="card">' +
      '<a href="#/watch/' + enc(v.id) + '" aria-label="' + esc(v.t) + '">' + thumb(v.id, v.t, step + '<span class="badge-dur">' + fmtDur(v.d) + "</span>") + "</a>" +
      '<div class="meta">' + avatar(v.c) + '<div class="meta-text">' +
      '<h3 class="title"><a href="#/watch/' + enc(v.id) + '" title="' + esc(v.t) + '">' + esc(v.t) + "</a></h3>" +
      '<div class="sub"><a href="#/?ch=' + enc(v.c) + '">' + chName(v.c) + "</a> · " + fmtNum(v.v) + " views · " + ago(v.p) + "</div>" +
      '<div class="tags"><span class="q" title="Quality score (0–100)">★ ' + Math.round(v.q) + "</span>" + lvTag(v.lv) +
      '<a class="tag" href="#/topic/' + enc(v.tp[0]) + '">' + topicName(v.tp[0]) + "</a>" +
      '<span class="tag">' + esc(v.f) + "</span></div>" +
      "</div></div></article>";
  }

  function seriesCard(s, opts) {
    opts = opts || {};
    const first = s.v[0];
    const total = s.v.reduce((a, id) => a + ((IDX.video.get(id) || {}).d || 0), 0);
    const step = opts.step ? '<span class="step-num">' + opts.step + "</span>" : "";
    const label = s.course ? "Course" : "Playlist";
    return '<article class="card">' +
      '<a class="stack" href="#/course/' + enc(s.id) + '" aria-label="' + esc(s.t) + '">' +
      thumb(first, s.t, step + '<span class="badge-course"><b>' + s.v.length + "</b>lectures</span>") + "</a>" +
      '<div class="meta">' + avatar(s.c) + '<div class="meta-text">' +
      '<h3 class="title"><a href="#/course/' + enc(s.id) + '" title="' + esc(s.t) + '">' + esc(s.t) + "</a></h3>" +
      '<div class="sub">' + chName(s.c) + " · " + label + " · " + fmtHours(total) + "</div>" +
      '<div class="tags"><span class="q" title="Course quality (average of its lectures)">★ ' + Math.round(s.q) + "</span>" + lvTag(s.lv) +
      '<a class="tag" href="#/topic/' + enc(s.tp[0]) + '">' + topicName(s.tp[0]) + "</a></div>" +
      "</div></div></article>";
  }

  function sampleBanner() {
    return DB.meta.sample_data ? '<div class="banner">Demo build with sample data — video IDs are placeholders, so thumbnails and the player won\'t load. The nightly GitHub Action builds the real catalog.</div>' : "";
  }

  // ------------------------------------------------------------ browse
  function filterVideos(params) {
    const toks = norm(params.get("q") || "").trim().split(" ").filter(Boolean);
    const topic = params.get("topic"), lv = params.get("lv"), f = params.get("f"), ch = params.get("ch"), dur = params.get("dur");
    let out = DB.videos.filter((v) => {
      if (topic && !v.tp.includes(topic)) return false;
      if (lv && v.lv !== lv) return false;
      if (f && v.f !== f) return false;
      if (ch && v.c !== ch) return false;
      if (dur) {
        const m = v.d / 60;
        if (dur === "s" && !(m < 10)) return false;
        if (dur === "m" && !(m >= 10 && m < 30)) return false;
        if (dur === "l" && !(m >= 30 && m < 60)) return false;
        if (dur === "xl" && !(m >= 60)) return false;
      }
      for (const t of toks) if (!v._h.includes(" " + t)) return false;
      return true;
    });
    const sort = params.get("sort") || "quality";
    const cmp = {
      quality: (a, b) => b.q - a.q,
      newest: (a, b) => (b.p > a.p ? 1 : b.p < a.p ? -1 : b.q - a.q),
      views: (a, b) => b.v - a.v,
      short: (a, b) => a.d - b.d,
    }[sort] || ((a, b) => b.q - a.q);
    if (toks.length && sort === "quality") {
      // title matches first, then quality
      const inTitle = (v) => { const nt = norm(v.t); return toks.every((t) => nt.includes(" " + t)) ? 1 : 0; };
      out.sort((a, b) => inTitle(b) - inTitle(a) || b.q - a.q);
    } else out.sort(cmp);
    return out;
  }

  function select(name, value, options, allLabel) {
    let h = '<select data-k="' + name + '" aria-label="' + esc(allLabel) + '">';
    if (allLabel) h += '<option value="">' + esc(allLabel) + "</option>";
    for (const [k, label] of options) h += '<option value="' + esc(k) + '"' + (k === value ? " selected" : "") + ">" + esc(label) + "</option>";
    return h + "</select>";
  }

  function renderBrowse(params) {
    const list = filterVideos(params);
    const topic = params.get("topic") || "";
    const anyFilter = ["q", "topic", "lv", "f", "ch", "dur"].some((k) => params.get(k));
    let h = sampleBanner();
    if (!anyFilter) h += hero();
    h += '<div class="chips" role="list">';
    h += '<a class="chip' + (topic ? "" : " on") + '" href="' + browseHref({ topic: "" }) + '">All</a>';
    for (const t of DB.topics) if (t.n) h += '<a class="chip' + (topic === t.id ? " on" : "") + '" href="' + browseHref({ topic: t.id }) + '">' + esc(t.name) + "</a>";
    h += "</div>";
    h += '<div class="toolbar">' +
      select("lv", params.get("lv") || "", DB.levels.map((l) => [l, LEVEL_LABEL[l]]), "All levels") +
      select("f", params.get("f") || "", DB.formats.map((f) => [f, f]), "All formats") +
      select("ch", params.get("ch") || "", DB.channels.map((c) => [c.key, c.name]), "All channels") +
      select("dur", params.get("dur") || "", Object.entries(DURS).filter(([k]) => k), "Any length") +
      select("sort", params.get("sort") || "quality", Object.entries(SORTS), "") +
      (anyFilter ? '<a class="clear-btn" href="#/">Clear filters</a>' : "") +
      '<span class="result-count">' + list.length.toLocaleString() + " videos</span></div>";
    if (topic) {
      h += '<p class="sub">Want a guided order? <a class="tag lv-beginner" href="#/topic/' + enc(topic) + '">Open the ' + topicName(topic) + " learning path →</a></p><br>";
    }
    h += list.length ? '<div class="grid" id="grid"></div><div class="sentinel" id="sentinel"></div>'
      : '<p class="empty">No videos match these filters.</p>';
    $main.innerHTML = h;
    for (const sel of $main.querySelectorAll(".toolbar select")) {
      sel.addEventListener("change", () => { location.hash = browseHref({ [sel.dataset.k]: sel.value }); });
    }
    if (!list.length) return;
    const grid = document.getElementById("grid");
    let shown = 0;
    const more = () => {
      const chunk = list.slice(shown, shown + PAGE);
      grid.insertAdjacentHTML("beforeend", chunk.map((v) => videoCard(v)).join(""));
      shown += chunk.length;
      if (shown >= list.length && observer) observer.disconnect();
    };
    more();
    observer = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) more(); }, { rootMargin: "800px" });
    observer.observe(document.getElementById("sentinel"));
  }

  function hero() {
    const totalSec = DB.videos.reduce((a, v) => a + v.d, 0);
    let roads = "";
    for (const r of DB.roadmaps) {
      roads += '<a class="road-mini" href="#/paths#' + enc(r.id) + '"><b>' + esc(r.name) + "</b><span>" +
        r.topics.map(topicName).join(" → ") + "</span></a>";
    }
    return '<section class="hero"><div><h1>' + esc(DB.site.title) + "</h1><p>" + esc(DB.site.tagline) + "</p>" +
      '<div class="stats"><div><b>' + DB.videos.length.toLocaleString() + "</b>videos</div><div><b>" + DB.series.length +
      "</b>courses &amp; playlists</div><div><b>" + Math.round(totalSec / 3600).toLocaleString() + "</b>hours</div><div><b>" +
      DB.channels.length + "</b>channels</div></div></div>" +
      '<div class="hero-roads">' + roads + '<a class="btn primary" href="#/paths">See all learning paths →</a></div></section>';
  }

  // ------------------------------------------------------------ paths
  function renderPaths() {
    let h = sampleBanner() + '<div class="page-head"><h1>Learning paths</h1><p>Each topic is ordered beginner → intermediate → advanced. Roadmaps chain topics into a full track.</p></div>';
    h += '<h2 class="section-title">Roadmaps</h2>';
    for (const r of DB.roadmaps) {
      h += '<section class="roadmap" id="' + esc(r.id) + '"><h3>' + esc(r.name) + "</h3><p>" + esc(r.description || "") + '</p><div class="road">' +
        r.topics.map((t, i) => (i ? '<span class="arrow">→</span>' : "") + '<a href="#/topic/' + enc(t) + '">' + (i + 1) + ". " + topicName(t) + "</a>").join("") +
        "</div></section>";
    }
    h += '<h2 class="section-title">All topics</h2><div class="topic-grid">';
    for (const t of DB.topics) {
      const p = DB.paths[t.id] || {};
      const steps = DB.levels.reduce((a, l) => a + (p[l] || []).length, 0);
      h += '<a class="topic-card" href="#/topic/' + enc(t.id) + '"><h3>' + esc(t.name) + "</h3><p>" + esc(t.desc) + '</p><div class="sub">' +
        t.n + " videos · " + steps + " path steps</div></a>";
    }
    $main.innerHTML = h + "</div>";
    const anchor = location.hash.split("#")[2];
    if (anchor) { const el = document.getElementById(anchor); if (el) el.scrollIntoView(); }
  }

  function renderTopic(tid) {
    const t = IDX.topic.get(tid);
    if (!t) return notFound();
    const path = DB.paths[tid] || {};
    let h = sampleBanner() + '<div class="page-head"><h1>' + esc(t.name) + "</h1><p>" + esc(t.desc) + "</p>";
    if (t.pre && t.pre.length) {
      h += '<div class="prereq">Helpful before you start: ' + t.pre.map((p) => '<a href="#/topic/' + enc(p) + '">' + topicName(p) + "</a>").join(", ") + "</div>";
    }
    h += '<div class="prereq"><a href="' + browseHref({ topic: tid, q: "", lv: "", f: "", ch: "", dur: "", sort: "" }) + '">Browse all ' + t.n + " videos in this topic →</a></div></div>";
    let step = 0, any = false;
    for (const lv of DB.levels) {
      const items = path[lv] || [];
      h += '<section class="stage ' + lv + '"><div class="stage-head"><h2>' + LEVEL_LABEL[lv] + '</h2><span class="hint">' + LEVEL_HINT[lv] + "</span></div>";
      if (!items.length) {
        h += '<p class="sub">Nothing at this level yet from the selected channels.</p>';
      } else {
        any = true;
        h += '<div class="grid">';
        for (const it of items) {
          step++;
          if (it.k === "s") { const s = IDX.series.get(it.id); if (s) h += seriesCard(s, { step }); }
          else { const v = IDX.video.get(it.id); if (v) h += videoCard(v, { step }); }
        }
        h += "</div>";
      }
      h += "</section>";
    }
    if (!any) h += '<p class="empty">No videos found for this topic yet.</p>';
    $main.innerHTML = h;
  }

  // ------------------------------------------------------------ courses
  function renderCourses() {
    const list = DB.series.slice().sort((a, b) => (b.course - a.course) || b.q - a.q);
    let h = sampleBanner() + '<div class="page-head"><h1>Courses &amp; playlists</h1><p>Full lecture series from the selected channels, ranked by the average quality of their lectures.</p></div>';
    for (const lv of DB.levels) {
      const group = list.filter((s) => s.lv === lv);
      if (!group.length) continue;
      h += '<h2 class="section-title">' + LEVEL_LABEL[lv] + '</h2><div class="grid">' + group.map((s) => seriesCard(s)).join("") + "</div>";
    }
    $main.innerHTML = list.length ? h : h + '<p class="empty">No courses yet.</p>';
  }

  function renderCourse(id) {
    const s = IDX.series.get(id);
    if (!s) return notFound();
    const total = s.v.reduce((a, vid) => a + ((IDX.video.get(vid) || {}).d || 0), 0);
    let h = sampleBanner() + '<div class="page-head"><h1>' + esc(s.t) + '</h1><div class="watch-sub">' + avatar(s.c) + "<span>" + chName(s.c) + "</span>" +
      lvTag(s.lv) + s.tp.map((t) => '<a class="tag" href="#/topic/' + enc(t) + '">' + topicName(t) + "</a>").join("") +
      "<span>" + s.v.length + " lectures · " + fmtHours(total) + '</span><span class="q">★ ' + Math.round(s.q) + "</span>" +
      '<a class="btn primary" href="#/watch/' + enc(s.v[0]) + '">▶ Start course</a>' +
      '<a class="btn" href="' + plUrl(s.id) + '" target="_blank" rel="noopener">Open on YouTube ↗</a></div></div><div class="course-list">';
    s.v.forEach((vid, i) => {
      const v = IDX.video.get(vid);
      if (!v) return;
      h += '<div class="course-row"><span class="n">' + (i + 1) + '</span><a href="#/watch/' + enc(v.id) + '">' + thumb(v.id, v.t, '<span class="badge-dur">' + fmtDur(v.d) + "</span>") +
        '</a><div><h3 class="title"><a href="#/watch/' + enc(v.id) + '">' + esc(v.t) + '</a></h3><div class="sub">' + fmtNum(v.v) + " views · " + ago(v.p) + "</div>" +
        '<div class="tags"><span class="q">★ ' + Math.round(v.q) + "</span>" + lvTag(v.lv) + '<span class="tag">' + esc(v.f) + "</span></div></div></div>";
    });
    $main.innerHTML = h + "</div>";
  }

  // ------------------------------------------------------------ watch
  function nextInPath(v) {
    const tid = v.tp[0];
    const flat = IDX.pathPos.get(tid) || [];
    const i = flat.findIndex((it) => (it.k === "v" && it.id === v.id) || (it.k === "s" && it.id === v.s));
    if (i < 0 || i + 1 >= flat.length) return null;
    return flat[i + 1];
  }

  function sideItem(v, current) {
    return '<a class="side-item' + (current ? " current" : "") + '" href="#/watch/' + enc(v.id) + '">' +
      thumb(v.id, v.t, '<span class="badge-dur">' + fmtDur(v.d) + "</span>") +
      '<div><h4 class="title">' + esc(v.t) + '</h4><div class="sub">' + chName(v.c) + "</div>" +
      '<div class="sub">' + fmtNum(v.v) + " views · ★ " + Math.round(v.q) + "</div></div></a>";
  }

  function renderWatch(id) {
    const v = IDX.video.get(id);
    if (!v) return notFound("This video isn't in the catalog (it may have been removed or filtered).");
    const s = v.s ? IDX.series.get(v.s) : null;
    const comps = ["Approval (likes/view)", "Popularity", "Engagement (comments)", "Freshness", "Completeness", "Course structure"];
    let player;
    if (v.ne) {
      player = '<a class="player" href="' + ytUrl(v.id) + '" target="_blank" rel="noopener"><img src="' + thumbUrl(v.id, "hqdefault") + '" alt=""></a>';
    } else {
      player = '<div class="player" id="player"><button class="play-cover" aria-label="Play video"><img src="' + thumbUrl(v.id, "hqdefault") + '" alt=""><span></span></button></div>';
    }
    let main = player + "<h1>" + esc(v.t) + '</h1><div class="watch-sub">' + avatar(v.c) +
      '<a href="#/?ch=' + enc(v.c) + '"><b>' + chName(v.c) + "</b></a><span>" + fmtNum(v.v) + " views</span><span>" + esc(v.p) + "</span>" +
      '<span class="q">★ ' + Math.round(v.q) + " quality</span>" +
      '<a class="btn" href="' + ytUrl(v.id) + '" target="_blank" rel="noopener">Watch on YouTube ↗</a></div>';
    main += '<div class="tags">' + lvTag(v.lv) + '<span class="tag">' + esc(v.f) + "</span>" +
      v.tp.map((t) => '<a class="tag" href="#/topic/' + enc(t) + '">' + topicName(t) + "</a>").join("") +
      (v.cc ? '<span class="tag">CC captions</span>' : "") + "</div>";
    const nxt = nextInPath(v);
    if (nxt) {
      const tgt = nxt.k === "s" ? IDX.series.get(nxt.id) : IDX.video.get(nxt.id);
      if (tgt) {
        main += '<div class="box next-step"><h3>Next step in the ' + topicName(v.tp[0]) + " path (" + LEVEL_LABEL[nxt.lv] + ")</h3>" +
          '<a href="' + (nxt.k === "s" ? "#/course/" : "#/watch/") + enc(nxt.id) + '"><b>' + esc(tgt.t) + "</b></a></div>";
      }
    }
    const kw = (v.why.kw || []).map((k) => "“" + esc(k) + "”").join(", ");
    main += '<div class="box why"><h3>Why it’s here and how it’s tagged</h3><ul>' +
      "<li><b>Topic:</b> " + topicName(v.tp[0]) + (kw ? " — matched " + kw : "") + (v.why.pl ? " (also from its course playlist)" : "") + "</li>" +
      "<li><b>Level:</b> " + esc(LEVEL_LABEL[v.lv]) + (v.why.lv && v.why.lv.length ? " — " + v.why.lv.map(esc).join("; ") : "") + "</li>" +
      "<li><b>Format:</b> " + esc(v.f) + (v.why.f ? " — " + esc(v.why.f) : "") + "</li></ul></div>";
    main += '<div class="box"><h3>Quality score: ' + Math.round(v.q) + ' / 100</h3><div class="bars">';
    v.qb.forEach((val, i) => {
      main += "<span>" + comps[i] + '</span><span class="bar"><i style="width:' + Math.max(0, Math.min(100, val)) + '%"></i></span><span>' + val + "</span>";
    });
    main += '</div><p class="sub"><a href="#/about">How the score works →</a></p></div>';
    if (v.ds) main += '<div class="box"><h3>Description</h3><p class="desc">' + esc(v.ds) + "</p></div>";

    let side = "";
    if (s) {
      side += '<div class="box"><h3><a href="#/course/' + enc(s.id) + '">' + esc(s.t) + "</a></h3><p class=\"sub\">" + (s.v.indexOf(v.id) + 1) + " / " + s.v.length + '</p><div class="side-list">';
      const at = Math.max(0, s.v.indexOf(v.id));
      const windowIds = s.v.slice(Math.max(0, at - 2), at + 8);
      for (const vid of windowIds) { const x = IDX.video.get(vid); if (x) side += sideItem(x, vid === v.id); }
      side += "</div></div>";
    }
    const related = DB.videos.filter((x) => x.id !== v.id && x.tp[0] === v.tp[0] && (!s || x.s !== s.id))
      .sort((a, b) => (a.lv === v.lv ? 0 : 1) - (b.lv === v.lv ? 0 : 1) || b.q - a.q).slice(0, 12);
    if (related.length) {
      side += '<h3 class="section-title">More on ' + topicName(v.tp[0]) + '</h3><div class="side-list">' + related.map((x) => sideItem(x)).join("") + "</div>";
    }
    $main.innerHTML = sampleBanner() + '<div class="watch"><div>' + main + "</div><aside>" + side + "</aside></div>";
    const cover = $main.querySelector(".play-cover");
    if (cover) {
      cover.addEventListener("click", () => {
        const f = document.createElement("iframe");
        f.src = "https://www.youtube-nocookie.com/embed/" + enc(v.id) + "?autoplay=1&rel=0";
        f.title = v.t;
        f.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
        f.allowFullscreen = true;
        f.referrerPolicy = "strict-origin-when-cross-origin";
        document.getElementById("player").replaceChildren(f);
      });
    }
  }

  // ------------------------------------------------------------ about
  function renderAbout() {
    const m = DB.meta;
    let rows = DB.channels.map((c) => '<tr><td><a href="' + esc(c.url) + '" target="_blank" rel="noopener">' + esc(c.name) + "</a></td><td>" +
      c.n.toLocaleString() + "</td><td>" + fmtNum(c.subs) + "</td></tr>").join("");
    $main.innerHTML = sampleBanner() + '<div class="about page-head"><h1>How this catalog works</h1>' +
      "<p>Last rebuilt <b>" + esc(m.generated) + "</b> · " + m.videos_listed.toLocaleString() + " videos listed out of " +
      m.videos_scanned.toLocaleString() + " scanned · " + m.courses + " courses/playlists.</p>" +
      "<h2>What gets in</h2><p>Only videos uploaded by the channels below. Each video's title, tags, description (with link lines and " +
      "repeated channel boilerplate removed) and course-playlist title are matched against a topic dictionary. Ambiguous words such as " +
      "“transformer”, “agent” or “diffusion” only count when the video is clearly about AI, so electrical transformers and chemical " +
      "diffusion stay out. Promotional videos, Shorts and anything under two minutes are dropped.</p>" +
      "<h2>Level and format</h2><p>Level comes from known course numbers (e.g. CS229 is intermediate, CS336 advanced), wording in the " +
      "title and playlist (“what is”, “introduction”, “seminar”, “theory”…), length, and a gentle per-channel default. Format is Lecture, " +
      "Explainer, Tutorial, Talk, Deep dive or News &amp; Podcast. Every video page shows the signals behind its tags.</p>" +
      "<h2>Quality score (0–100)</h2><p>A weighted mix of audience and content signals:</p><ul>" +
      "<li><b>Approval</b> — likes per view, smoothed so a video with few views isn't judged on noise.</li>" +
      "<li><b>Popularity</b> — total views and views per day.</li>" +
      "<li><b>Engagement</b> — comments per view, smoothed.</li>" +
      "<li><b>Freshness</b> — decays with age at a topic-specific rate (agents and LLMs age fast; math barely ages).</li>" +
      "<li><b>Completeness</b> — captions, chapter markers and a real description.</li>" +
      "<li><b>Course structure</b> — being part of a full lecture series.</li></ul>" +
      "<p>Audience signals are compared within each channel, so a smaller channel isn't buried by a bigger one. These are proxies for " +
      "quality, not a review of the teaching itself; the site's curator can boost, pin, retag or hide any video.</p>" +
      "<h2>Channels</h2><table><thead><tr><th>Channel</th><th>Videos listed</th><th>Subscribers</th></tr></thead><tbody>" + rows + "</tbody></table>" +
      '<footer class="site">Video data from the YouTube Data API. Videos and thumbnails belong to their creators. Builder ' + esc(m.builder) + ".</footer></div>";
  }

  function notFound(msg) {
    $main.innerHTML = '<p class="empty">' + esc(msg || "Page not found.") + ' <a href="#/">Go home</a></p>';
  }

  // ------------------------------------------------------------ chrome
  document.getElementById("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $search.value.trim();
    const { parts } = parseHash();
    location.hash = parts.length ? "#/" + (q ? "?q=" + enc(q) : "") : browseHref({ q });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== $search && !/input|select|textarea/i.test(document.activeElement.tagName)) {
      e.preventDefault(); $search.focus();
    }
  });
  document.getElementById("menu-btn").addEventListener("click", (e) => {
    const mobile = window.matchMedia("(max-width: 960px)").matches;
    const cls = mobile ? "nav-open" : "nav-collapsed";
    document.body.classList.toggle(cls);
    e.currentTarget.setAttribute("aria-expanded", String(mobile ? document.body.classList.contains("nav-open") : !document.body.classList.contains("nav-collapsed")));
  });
  document.getElementById("scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
  document.getElementById("theme-btn").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });
  // Thumbnails that fail to load (removed videos, demo IDs) show a text placeholder.
  document.addEventListener("error", (e) => {
    const t = e.target;
    if (t.tagName === "IMG" && t.parentElement && t.parentElement.classList.contains("thumb")) t.parentElement.classList.add("noimg");
    else if (t.tagName === "IMG" && t.parentElement && t.parentElement.classList.contains("avatar")) t.remove();
    else if (t.tagName === "IMG" && t.closest && t.closest(".player")) t.style.visibility = "hidden";
  }, true);
})();
