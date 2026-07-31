/* Sleep Tracker UI — vanilla JS, no dependencies.
   All user-supplied content is inserted via textContent (never innerHTML). */
"use strict";

(function () {
  var doc = document;
  var SVGNS = "http://www.w3.org/2000/svg";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                     "July", "August", "September", "October", "November", "December"];

  var state = {
    records: Array.isArray(window.__INITIAL_RECORDS__) ? window.__INITIAL_RECORDS__ : [],
    stats: window.__INITIAL_STATS__ || {
      total: 0, avg_hours: 0, avg_quality: 0,
      current_streak: 0, best_streak: 0, series: []
    },
    range: "30d",       // chart range: 30d | 90d | 1y | all
    nights: null,       // /api/series nights for the current range (sparse, asc)
    nightsMap: null,    // date -> night (stages/source enrichment)
    seriesMeta: null,   // {start, end, range} from /api/series
    patterns: {
      status: "idle", nights: [], start: null, end: null
    }
  };
  var mutationQueue = Promise.resolve();

  var SOURCE_LABELS = { apple_health: "Apple Health", fitbit: "Fitbit" };

  function sourceLabel(source) {
    if (!source || source === "manual") return null;
    if (SOURCE_LABELS[source]) return SOURCE_LABELS[source];
    var s = String(source).replace(/_/g, " ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  /* ---------------- helpers ---------------- */

  function $(sel, root) { return (root || doc).querySelector(sel); }

  function el(tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function svgEl(tag, attrs) {
    var node = doc.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) {
          node.setAttribute(k, attrs[k]);
        }
      }
    }
    return node;
  }

  function fmt1(v) {
    var n = Number(v);
    if (v === null || v === undefined || isNaN(n)) return "–";
    return (Math.round(n * 10) / 10).toFixed(1);
  }

  function parseISO(iso) {
    var p = String(iso || "").split("-");
    return { y: +p[0], m: +p[1], d: +p[2] };
  }

  function shortDate(iso) {
    var p = parseISO(iso);
    if (!p.m || !p.d) return String(iso || "");
    return MONTHS[p.m - 1] + " " + p.d;
  }

  function fullDate(iso) {
    var p = parseISO(iso);
    if (!p.m || !p.d) return String(iso || "");
    return MONTHS[p.m - 1] + " " + p.d + ", " + p.y;
  }

  function dayNumFromISO(iso) {
    var p = parseISO(iso);
    return Date.UTC(p.y, p.m - 1, p.d) / 86400000;
  }

  function isoFromDayNum(n) {
    return new Date(n * 86400000).toISOString().slice(0, 10);
  }

  function fmtMins(mins) {
    var m = Math.round(Number(mins) || 0);
    var h = Math.floor(m / 60);
    if (!h) return (m % 60) + "m";
    return h + "h " + (m % 60) + "m";
  }

  function stars(q) {
    var n = Math.max(0, Math.min(5, Number(q) || 0));
    return "★★★★★".slice(0, n) +
           "☆☆☆☆☆".slice(0, 5 - n);
  }

  var msgTimers = {};
  function setMsg(node, text, kind) {
    if (!node) return;
    node.textContent = text || "";
    node.className = "msg" + (kind ? " " + kind : "");
    var key = node.id || "m";
    if (msgTimers[key]) { clearTimeout(msgTimers[key]); msgTimers[key] = null; }
    if (text && kind === "ok") {
      msgTimers[key] = setTimeout(function () {
        node.textContent = "";
        node.className = "msg";
      }, 4000);
    }
  }

  /* ---------------- API ---------------- */

  function fetchJson(url, options) {
    return fetch(url, options || {}).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || data.error) {
          throw new Error(data.error || "Request failed (" + res.status + ")");
        }
        return data;
      });
    }, function () {
      throw new Error("Network error — is the server running?");
    });
  }

  function post(url, formData) {
    function run() {
      return fetchJson(url, {
        method: "POST",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" }
      }).then(function (data) {
        if (Array.isArray(data.records)) state.records = data.records;
        if (data.stats) state.stats = data.stats;
        renderStats();
        renderChart();
        renderRecords();
        refreshSeries(); // re-pull the current range so stages/sources stay fresh
        refreshPatterns();
        return data;
      });
    }

    var result = mutationQueue.then(run, run);
    mutationQueue = result.catch(function () {});
    return result;
  }

  /* ---------------- series (trend explorer data) ---------------- */

  var seriesReq = 0;

  function loadSeries(range) {
    var reqId = ++seriesReq;
    var wrap = $("#chart-wrap");
    if (wrap) wrap.classList.add("loading"); // hold the old render, dimmed
    return fetchJson("/api/series?range=" + encodeURIComponent(range))
      .then(function (data) {
        if (reqId !== seriesReq) return;
        state.nights = Array.isArray(data.nights) ? data.nights : [];
        state.seriesMeta = { start: data.start, end: data.end, range: data.range };
        state.nightsMap = {};
        for (var i = 0; i < state.nights.length; i++) {
          state.nightsMap[state.nights[i].date] = state.nights[i];
        }
        if (wrap) wrap.classList.remove("loading");
        renderChart();
      }, function (err) {
        if (reqId !== seriesReq) return;
        if (wrap) wrap.classList.remove("loading");
        throw err;
      });
  }

  function refreshSeries() {
    loadSeries(state.range).catch(function () { /* keep previous render */ });
  }

  function syncRangeButtons() {
    var btns = doc.querySelectorAll(".range-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute("aria-pressed",
        btns[i].dataset.range === state.range ? "true" : "false");
    }
  }

  function initRange() {
    var btns = doc.querySelectorAll(".range-btn");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function () {
        var range = this.dataset.range;
        if (!range || range === state.range) return;
        var prev = state.range;
        state.range = range;
        syncRangeButtons();
        loadSeries(range).catch(function (err) {
          state.range = prev;
          syncRangeButtons();
          renderChart();
          var live = $("#chart-live");
          if (live) live.textContent = err.message;
        });
      });
    }
  }

  /* ---------------- theme ---------------- */

  var mqlDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function currentTheme() {
    var t = doc.documentElement.dataset.theme;
    if (t === "dark" || t === "light") return t;
    return (mqlDark && mqlDark.matches) ? "dark" : "light";
  }

  function syncToggle() {
    var btn = $("#theme-toggle");
    if (!btn) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    btn.setAttribute("aria-label", "Switch to " + next + " theme");
  }

  function initTheme() {
    var btn = $("#theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        doc.documentElement.dataset.theme = next;
        try { localStorage.setItem("sleep-theme", next); } catch (e) { /* ignore */ }
        syncToggle();
        renderChart();
      });
    }
    if (mqlDark && mqlDark.addEventListener) {
      mqlDark.addEventListener("change", function () {
        syncToggle();
        renderChart();
      });
    }
    syncToggle();
  }

  /* ---------------- stats ---------------- */

  function renderStats() {
    var s = state.stats || {};
    $("#stat-total").textContent = (s.total !== undefined && s.total !== null) ? s.total : "–";
    $("#stat-avg-hours").textContent = s.total ? fmt1(s.avg_hours) + "h" : "–";
    $("#stat-avg-quality").textContent = s.total ? fmt1(s.avg_quality) + "/5" : "–";
    var streak = Number(s.current_streak) || 0;
    $("#stat-streak").textContent = streak + (streak === 1 ? " night" : " nights");
    var best = Number(s.best_streak) || 0;
    $("#stat-best-streak").textContent = "Best: " + best + (best === 1 ? " night" : " nights");
    renderDebt();
  }

  /* Sleep debt tile — neutral presentation: it's information, not judgment. */
  function renderDebt() {
    var label = $("#debt-label"), value = $("#stat-debt"), sub = $("#debt-sub");
    if (!label || !value || !sub) return;
    var s = state.stats || {};
    var sd = s.sleep_debt;
    if (!sd || !s.total || !Array.isArray(sd.rolling_14d) || !sd.rolling_14d.length) {
      label.textContent = "Sleep debt";
      value.textContent = "–";
      sub.textContent = "";
      renderDebtSpark(null);
      return;
    }
    var debt = Number(sd.total_debt_hours) || 0;
    var need = fmt1(sd.need);
    if (debt < -0.05) {
      label.textContent = "Rested";
      value.textContent = "+" + fmt1(-debt) + "h";
    } else {
      label.textContent = "Sleep debt";
      value.textContent = fmt1(Math.max(0, debt)) + "h";
    }
    sub.textContent = "14-day window · need " + need + "h";
    renderDebtSpark(sd);
  }

  function renderDebtSpark(sd) {
    var host = $("#debt-spark");
    if (!host) return;
    host.textContent = "";
    var pts = (sd && Array.isArray(sd.rolling_14d)) ? sd.rolling_14d : [];
    if (pts.length < 2) return;

    var W = 120, H = 28, pad = 4;
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, "aria-hidden": "true" });

    var min = 0, max = 0;
    for (var i = 0; i < pts.length; i++) {
      var v = Number(pts[i].cumulative_debt_hours) || 0;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (max - min < 0.5) { max += 0.25; min -= 0.25; }

    function xFor(i) { return pad + (W - 2 * pad) * (pts.length === 1 ? 0 : i / (pts.length - 1)); }
    function yFor(v) { return pad + (H - 2 * pad) * (1 - (v - min) / (max - min)); }

    // zero baseline: the "even" line the trend is read against
    svg.appendChild(svgEl("line", {
      "class": "spark-zero", x1: pad, x2: W - pad, y1: yFor(0), y2: yFor(0)
    }));

    var d = "";
    for (var j = 0; j < pts.length; j++) {
      var val = Number(pts[j].cumulative_debt_hours) || 0;
      d += (j ? " L" : "M") + xFor(j).toFixed(1) + "," + yFor(val).toFixed(1);
    }
    svg.appendChild(svgEl("path", { "class": "spark-line", d: d }));

    var last = Number(pts[pts.length - 1].cumulative_debt_hours) || 0;
    svg.appendChild(svgEl("circle", {
      "class": "spark-dot", cx: xFor(pts.length - 1), cy: yFor(last), r: 2.5
    }));
    host.appendChild(svg);
  }

  /* ---------------- chart ---------------- */

  var tip = null, tipVal = null, tipDate = null, tipQual = null, tipStages = null;

  var STAGE_KEYS = [
    ["deep", "c-seg-deep", "swatch-deep", "Deep"],
    ["rem", "c-seg-rem", "swatch-rem", "REM"],
    ["light", "c-seg-light", "swatch-light", "Light"],
    ["awake", "c-seg-awake", "swatch-awake", "Awake"]
  ];

  var RANGE_COPY = {
    "30d": ["Last 30 days", "Hours per night · reference line at 8h"],
    "90d": ["Last 90 days", "Hours per night · reference line at 8h"],
    "1y": ["Past year", "Nightly hours as dots · 7-night average line · 8h reference"],
    "all": ["All history", "Nightly hours as dots · 7-night average line · 8h reference"]
  };

  function ensureTip() {
    if (!tip) {
      tip = $("#chart-tip");
      tipVal = $("#tip-val");
      tipDate = $("#tip-date");
      tipQual = $("#tip-qual");
      tipStages = $("#tip-stages");
    }
    return tip;
  }

  function stageTotal(stages) {
    if (!stages) return 0;
    var t = 0;
    for (var i = 0; i < STAGE_KEYS.length; i++) {
      t += Math.max(0, Number(stages[STAGE_KEYS[i][0]]) || 0);
    }
    return t;
  }

  function barPath(x, y, w, h) {
    var r = Math.min(4, w / 2, h);
    return "M" + x + "," + (y + h) +
           " L" + x + "," + (y + r) +
           " Q" + x + "," + y + " " + (x + r) + "," + y +
           " L" + (x + w - r) + "," + y +
           " Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
           " L" + (x + w) + "," + (y + h) + " Z";
  }

  function hideLift() {
    var lifted = doc.querySelectorAll(".c-bar.lift, .c-stack.lift");
    for (var i = 0; i < lifted.length; i++) lifted[i].classList.remove("lift");
  }

  function hideTip() {
    if (tip) tip.hidden = true;
    hideLift();
  }

  function showTip(day, markEl, anchorX, anchorY) {
    if (!ensureTip()) return;
    var noData = day.hours === null || day.hours === undefined;
    tipVal.textContent = noData ? "No record" : fmt1(day.hours) + " h";
    tipDate.textContent = fullDate(day.date);
    var qual = (day.quality === null || day.quality === undefined || noData)
      ? "" : "Quality " + day.quality + "/5";
    var src = sourceLabel(day.source);
    tipQual.textContent = qual && src ? qual + " · " + src : (qual || src || "");
    if (tipStages) {
      tipStages.textContent = "";
      if (!noData && day.stages && stageTotal(day.stages) > 0) {
        for (var i = 0; i < STAGE_KEYS.length; i++) {
          var mins = Number(day.stages[STAGE_KEYS[i][0]]);
          if (isNaN(mins) || mins < 0) continue;
          var row = el("div");
          row.appendChild(el("span", "tip-key " + STAGE_KEYS[i][2]));
          row.appendChild(doc.createTextNode(STAGE_KEYS[i][3] + " · " + fmtMins(mins)));
          tipStages.appendChild(row);
        }
      }
    }
    tip.hidden = false;
    var wrap = $("#chart-wrap");
    var ww = wrap.clientWidth;
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var left = Math.max(0, Math.min(ww - tw, anchorX - tw / 2));
    var top = anchorY - th - 8;
    if (top < 0) top = anchorY + 12;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
    hideLift();
    if (markEl) markEl.classList.add("lift");
  }

  /* Dense skeleton (one entry per calendar day) so gaps render honestly. */
  function denseDays(startISO, endISO) {
    var out = [];
    var s = dayNumFromISO(startISO), e = dayNumFromISO(endISO);
    if (!isFinite(s) || !isFinite(e) || e < s || e - s > 4000) return out;
    var map = state.nightsMap || {};
    for (var n = s; n <= e; n++) {
      var iso = isoFromDayNum(n);
      out.push(map[iso] || { date: iso, hours: null, quality: null, stages: null, source: null });
    }
    return out;
  }

  function currentDays() {
    var map = state.nightsMap;
    if (state.range === "30d") {
      // stats.series is already the dense 30-day skeleton; enrich with stages.
      var skel = (state.stats && Array.isArray(state.stats.series)) ? state.stats.series : [];
      var out = [];
      for (var i = 0; i < skel.length; i++) {
        var d = skel[i];
        var extra = (map && map[d.date]) || null;
        out.push({
          date: d.date, hours: d.hours, quality: d.quality,
          stages: extra ? extra.stages : null,
          source: extra ? extra.source : null
        });
      }
      return out;
    }
    var meta = state.seriesMeta;
    if (meta && meta.start && meta.end) return denseDays(meta.start, meta.end);
    return state.nights || [];
  }

  function drawFrame(svg, W, H, pad, plotH, ymax) {
    function yy(v) { return pad.t + plotH * (1 - v / ymax); }
    for (var t = 0; t <= ymax; t += 3) {
      var gy = yy(t);
      if (t > 0) {
        svg.appendChild(svgEl("line", {
          "class": "c-grid", x1: pad.l, x2: W - pad.r, y1: gy, y2: gy
        }));
      }
      var tickText = svgEl("text", {
        "class": "c-tick", x: pad.l - 8, y: gy + 4, "text-anchor": "end"
      });
      tickText.textContent = String(t);
      svg.appendChild(tickText);
    }
    var refY = yy(8);
    svg.appendChild(svgEl("line", {
      "class": "c-ref", x1: pad.l, x2: W - pad.r, y1: refY, y2: refY
    }));
    var refLabel = svgEl("text", {
      "class": "c-reflabel", x: W - pad.r, y: refY - 4, "text-anchor": "end"
    });
    refLabel.textContent = "8h";
    svg.appendChild(refLabel);
    svg.appendChild(svgEl("line", {
      "class": "c-baseline", x1: pad.l, x2: W - pad.r,
      y1: pad.t + plotH, y2: pad.t + plotH
    }));
  }

  function chartEmpty(svg, pad, plotW, plotH, text) {
    var emptyText = svgEl("text", {
      "class": "c-empty", x: pad.l + plotW / 2, y: pad.t + plotH / 2,
      "text-anchor": "middle"
    });
    emptyText.textContent = text;
    svg.appendChild(emptyText);
  }

  function renderChart() {
    var host = $("#chart");
    if (!host) return;
    host.textContent = "";
    hideTip();
    ensureTip();
    var copy = RANGE_COPY[state.range] || RANGE_COPY["30d"];
    var title = $("#chart-title"), sub = $("#chart-sub");
    if (title) title.textContent = copy[0];
    if (sub) sub.textContent = copy[1];
    if (state.range === "1y" || state.range === "all") renderLineChart(host, copy[0]);
    else renderBarChart(host, copy[0]);
  }

  function renderBarChart(host, rangeName) {
    var days = currentDays();
    var legend = $("#stage-legend");
    var W = host.clientWidth || 600;
    var H = 230;
    var pad = { t: 12, r: 10, b: 24, l: 34 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;

    var svg = svgEl("svg", {
      viewBox: "0 0 " + W + " " + H,
      width: W, height: H,
      role: "group",
      "aria-label": "Bar chart: hours slept per night, " + rangeName.toLowerCase()
    });
    host.appendChild(svg);

    var n = days.length;
    var maxHours = 0;
    var hasData = false;
    for (var i = 0; i < n; i++) {
      var h = days[i] && days[i].hours;
      if (h !== null && h !== undefined) {
        hasData = true;
        if (h > maxHours) maxHours = h;
      }
    }

    // Clean y scale: at least 0–9h (keeps the 8h reference inside), 3h ticks.
    var ymax = Math.max(9, Math.ceil(maxHours / 3) * 3);
    function yFor(v) { return pad.t + plotH * (1 - v / ymax); }
    drawFrame(svg, W, H, pad, plotH, ymax);

    if (!n || !hasData) {
      if (legend) legend.hidden = true;
      chartEmpty(svg, pad, plotW, plotH,
        "No sleep recorded in this range");
      return;
    }

    var slot = plotW / n;
    var barW = Math.max(2, Math.min(24, slot - 2)); // <=24px thick, 2px surface gap
    var stack = state.range === "30d";
    var anyStages = false;

    var touchSelection = false;
    for (var j = 0; j < n; j++) {
      var day = days[j];
      var cx = pad.l + slot * j + slot / 2;

      // Sparse x labels: 30d = every 7th day back from the most recent;
      // 90d = month starts.
      if (stack) {
        if ((n - 1 - j) % 7 === 0) {
          var xl = svgEl("text", {
            "class": "c-xlabel", x: cx, y: H - 6, "text-anchor": "middle"
          });
          xl.textContent = shortDate(day.date);
          svg.appendChild(xl);
        }
      } else {
        var pd = parseISO(day.date);
        if (pd.d === 1) {
          var ml = svgEl("text", {
            "class": "c-xlabel", x: cx, y: H - 6, "text-anchor": "middle"
          });
          ml.textContent = MONTHS[pd.m - 1];
          svg.appendChild(ml);
        }
      }

      var hasBar = day.hours !== null && day.hours !== undefined;
      var stTotal = (stack && hasBar && day.stages) ? stageTotal(day.stages) : 0;
      var mark = null;
      if (hasBar) {
        var bh = Math.max(2, plotH * (day.hours / ymax));
        var by = pad.t + plotH - bh;
        if (stTotal > 0 && bh >= 8) {
          // Stacked stage composition: deep (darkest) at the baseline up to
          // awake (lightest), 2px surface gaps between segments.
          anyStages = true;
          mark = svgEl("g", { "class": "c-stack" });
          var segs = [];
          for (var k = 0; k < STAGE_KEYS.length; k++) {
            var mins = Math.max(0, Number(day.stages[STAGE_KEYS[k][0]]) || 0);
            if (mins > 0) segs.push({ cls: STAGE_KEYS[k][1], mins: mins });
          }
          var acc = 0;
          for (var si = 0; si < segs.length; si++) {
            var hRaw = bh * (segs[si].mins / stTotal);
            var segBottomY = pad.t + plotH - acc;
            var isTop = si === segs.length - 1;
            var yTop = segBottomY - hRaw + (isTop ? 0 : 1);
            var yBot = segBottomY - (si === 0 ? 0 : 1);
            var hSeg = Math.max(0.75, yBot - yTop);
            if (isTop) {
              mark.appendChild(svgEl("path", {
                "class": segs[si].cls,
                d: barPath(cx - barW / 2, yBot - hSeg, barW, hSeg)
              }));
            } else {
              mark.appendChild(svgEl("rect", {
                "class": segs[si].cls,
                x: cx - barW / 2, y: yTop, width: barW, height: hSeg
              }));
            }
            acc += hRaw;
          }
          svg.appendChild(mark);
        } else {
          mark = svgEl("path", {
            "class": "c-bar",
            d: barPath(cx - barW / 2, by, barW, bh)
          });
          svg.appendChild(mark);
        }
      }

      // Hit target: full column height, wider than the mark. Focusable if data.
      var hit = svgEl("rect", {
        "class": "c-hit",
        x: pad.l + slot * j, y: pad.t, width: slot, height: plotH,
        rx: 4
      });
      if (hasBar) {
        hit.setAttribute("tabindex", "0");
        hit.setAttribute("role", "img");
        var lab = fullDate(day.date) + ": " + fmt1(day.hours) + " hours";
        if (day.quality !== null && day.quality !== undefined) {
          lab += ", quality " + day.quality + " of 5";
        }
        if (stTotal > 0) {
          for (var sk = 0; sk < STAGE_KEYS.length; sk++) {
            var sm = Number(day.stages[STAGE_KEYS[sk][0]]);
            if (!isNaN(sm) && sm >= 0) {
              lab += ", " + STAGE_KEYS[sk][3].toLowerCase() + " " + fmtMins(sm);
            }
          }
        }
        hit.setAttribute("aria-label", lab);
      }
      (function (d, b, x, y) {
        hit.addEventListener("pointerenter", function () { showTip(d, b, x, y); });
        hit.addEventListener("pointerdown", function (e) {
          if (e.pointerType === "touch") touchSelection = true;
          showTip(d, b, x, y);
        });
        hit.addEventListener("focus", function () { showTip(d, b, x, y); });
        hit.addEventListener("blur", hideTip);
      })(day, mark, cx, hasBar ? yFor(day.hours) : pad.t + plotH - 20);
      svg.appendChild(hit);
    }

    if (legend) legend.hidden = !anyStages;
    svg.addEventListener("pointerleave", function () {
      if (!touchSelection) hideTip();
    });
  }

  /* 1y / all: nightly hours as faint dots + a 7-night rolling average line.
     Gaps are honest — the line breaks across any gap longer than 7 nights. */
  function renderLineChart(host, rangeName) {
    var legend = $("#stage-legend");
    if (legend) legend.hidden = true;
    var nights = state.nights || [];
    var meta = state.seriesMeta || {};
    var W = host.clientWidth || 600;
    var H = 230;
    var pad = { t: 12, r: 10, b: 24, l: 34 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;

    var svg = svgEl("svg", {
      viewBox: "0 0 " + W + " " + H,
      width: W, height: H,
      role: "group",
      "aria-label": "Chart: nightly hours and 7-night average, " + rangeName.toLowerCase()
    });
    host.appendChild(svg);

    var maxHours = 0;
    for (var i = 0; i < nights.length; i++) {
      if (nights[i].hours > maxHours) maxHours = nights[i].hours;
    }
    var ymax = Math.max(9, Math.ceil(maxHours / 3) * 3);
    function yFor(v) { return pad.t + plotH * (1 - v / ymax); }
    drawFrame(svg, W, H, pad, plotH, ymax);

    if (!nights.length) {
      chartEmpty(svg, pad, plotW, plotH, "No sleep recorded in this range");
      return;
    }

    var nums = [];
    for (var d = 0; d < nights.length; d++) nums.push(dayNumFromISO(nights[d].date));
    var startNum = meta.start ? dayNumFromISO(meta.start) : nums[0];
    var endNum = meta.end ? dayNumFromISO(meta.end) : nums[nums.length - 1];
    if (!isFinite(startNum)) startNum = nums[0];
    if (!isFinite(endNum) || endNum <= startNum) endNum = startNum + 1;
    function xFor(num) { return pad.l + plotW * ((num - startNum) / (endNum - startNum)); }

    // Month-start x labels, thinned to ~7.
    var months = [];
    var md = new Date(startNum * 86400000);
    var ty = md.getUTCFullYear(), tm = md.getUTCMonth() + 1;
    if (tm > 11) { tm = 0; ty += 1; }
    var tnum = Date.UTC(ty, tm, 1) / 86400000;
    while (tnum <= endNum) {
      months.push({ num: tnum, m: tm, y: ty });
      tm += 1;
      if (tm > 11) { tm = 0; ty += 1; }
      tnum = Date.UTC(ty, tm, 1) / 86400000;
    }
    var mstep = Math.max(1, Math.ceil(months.length / 7));
    var labeled = 0;
    for (var mi = 0; mi < months.length; mi += mstep) {
      var mk = months[mi];
      var tx = Math.min(xFor(mk.num), W - 24);
      var xlab = svgEl("text", {
        "class": "c-xlabel", x: tx, y: H - 6, "text-anchor": "middle"
      });
      xlab.textContent = MONTHS[mk.m] +
        ((mk.m === 0 || labeled === 0) ? " " + mk.y : "");
      svg.appendChild(xlab);
      labeled++;
    }

    // 7-night rolling average (nights within the previous 7 calendar days).
    var avg = [];
    for (var a = 0; a < nights.length; a++) {
      var sum = 0, cnt = 0;
      for (var w = a; w >= 0 && nums[a] - nums[w] <= 6; w--) {
        sum += nights[w].hours;
        cnt++;
      }
      avg.push(sum / cnt);
    }
    var path = "";
    for (var p = 0; p < nights.length; p++) {
      var breakHere = p === 0 || (nums[p] - nums[p - 1]) > 7;
      path += (breakHere ? " M" : " L") +
        xFor(nums[p]).toFixed(1) + "," + yFor(avg[p]).toFixed(1);
    }

    // Faint nightly dots under the average line.
    var dots = [];
    for (var c = 0; c < nights.length; c++) {
      var dot = svgEl("circle", {
        "class": "c-dot", cx: xFor(nums[c]).toFixed(1),
        cy: yFor(nights[c].hours).toFixed(1), r: 2.5
      });
      dots.push(dot);
      svg.appendChild(dot);
    }
    svg.appendChild(svgEl("path", { "class": "c-avg", d: path.replace(/^ /, "") }));

    // Crosshair + one keyboard-focusable overlay (arrow keys walk the nights).
    var cross = svgEl("line", {
      "class": "c-cross", x1: 0, x2: 0, y1: pad.t, y2: pad.t + plotH,
      visibility: "hidden"
    });
    svg.appendChild(cross);

    var overlay = svgEl("rect", {
      "class": "c-overlay", x: pad.l, y: pad.t, width: plotW, height: plotH,
      rx: 4, tabindex: 0, role: "img"
    });
    overlay.setAttribute("aria-label",
      nights.length + " nights from " + fullDate(nights[0].date) + " to " +
      fullDate(nights[nights.length - 1].date) +
      ". Press the arrow keys to read each night.");
    svg.appendChild(overlay);

    var sel = -1;
    function selectNight(idx, announce) {
      if (idx < 0) idx = 0;
      if (idx >= nights.length) idx = nights.length - 1;
      if (sel >= 0 && dots[sel]) dots[sel].classList.remove("active");
      sel = idx;
      var night = nights[idx];
      var x = xFor(nums[idx]);
      if (dots[idx]) dots[idx].classList.add("active");
      cross.setAttribute("x1", x);
      cross.setAttribute("x2", x);
      cross.setAttribute("visibility", "visible");
      showTip(night, null, x, yFor(night.hours));
      if (announce) {
        var live = $("#chart-live");
        if (live) {
          live.textContent = fullDate(night.date) + ": " + fmt1(night.hours) +
            " hours" + ((night.quality !== null && night.quality !== undefined)
              ? ", quality " + night.quality + " of 5" : "");
        }
      }
    }
    function clearSel() {
      if (sel >= 0 && dots[sel]) dots[sel].classList.remove("active");
      sel = -1;
      cross.setAttribute("visibility", "hidden");
      hideTip();
    }

    var touchSelection = false;
    function selectNearest(e, announce) {
      var rect = svg.getBoundingClientRect();
      var px = (e.clientX - rect.left) * (W / (rect.width || W));
      var best = 0, bd = Infinity;
      for (var q = 0; q < nums.length; q++) {
        var dx = Math.abs(xFor(nums[q]) - px);
        if (dx < bd) { bd = dx; best = q; }
      }
      selectNight(best, announce);
    }
    overlay.addEventListener("pointermove", function (e) {
      selectNearest(e, false);
    });
    overlay.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "touch") touchSelection = true;
      selectNearest(e, true);
    });
    svg.addEventListener("pointerleave", function () {
      if (!touchSelection) clearSel();
    });
    overlay.addEventListener("focus", function () { selectNight(nights.length - 1, true); });
    overlay.addEventListener("blur", clearSel);
    overlay.addEventListener("keydown", function (e) {
      var idx = sel < 0 ? nights.length - 1 : sel;
      if (e.key === "ArrowLeft") idx -= 1;
      else if (e.key === "ArrowRight") idx += 1;
      else if (e.key === "Home") idx = 0;
      else if (e.key === "End") idx = nights.length - 1;
      else return;
      e.preventDefault();
      selectNight(idx, true);
    });
  }

  /* ---------------- all-history patterns ---------------- */

  var patternsReq = 0;
  var patternsPromise = null;
  var heatButtons = [];
  var patternFocusDate = null;

  function normalizePatternNights(raw) {
    var byDate = {};
    if (!Array.isArray(raw)) return [];
    for (var i = 0; i < raw.length; i++) {
      var night = raw[i];
      if (!night || typeof night !== "object") continue;
      var date = String(night.date || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
      var num = dayNumFromISO(date);
      if (!isFinite(num) || isoFromDayNum(num) !== date) continue;
      var hours = Number(night.hours);
      if (!isFinite(hours) || hours < 0 || hours > 24) continue;
      var quality = night.quality;
      if (quality !== null && quality !== undefined) {
        quality = Number(quality);
        if (!isFinite(quality) || quality < 1 || quality > 5) quality = null;
      }
      byDate[date] = {
        date: date,
        hours: hours,
        quality: quality,
        source: typeof night.source === "string" ? night.source : null
      };
    }
    var dates = Object.keys(byDate).sort();
    var nights = [];
    for (var d = 0; d < dates.length; d++) nights.push(byDate[dates[d]]);
    return nights;
  }

  function renderPatternsStatus() {
    var p = state.patterns;
    var loading = $("#patterns-loading");
    var error = $("#patterns-error");
    var empty = $("#patterns-empty");
    var content = $("#patterns-content");
    var card = $("#patterns");
    var hasData = p.nights.length > 0;

    if (loading) {
      loading.hidden = p.status !== "loading";
      loading.textContent = hasData ? "Refreshing patterns…" : "Loading patterns…";
    }
    if (error) error.hidden = p.status !== "error";
    if (empty) empty.hidden = p.status !== "ready" || hasData;
    if (content) content.hidden = !hasData;
    if (card) card.classList.toggle("loading", p.status === "loading");
  }

  function loadPatterns(force) {
    if (!force && patternsPromise) return patternsPromise;
    var reqId = ++patternsReq;
    state.patterns.status = "loading";
    renderPatternsStatus();

    var request = fetchJson("/api/series?range=all")
      .then(function (data) {
        if (reqId !== patternsReq) return null;
        if (!data || !Array.isArray(data.nights)) {
          throw new Error("Invalid patterns response.");
        }
        var nights = normalizePatternNights(data.nights);
        state.patterns = {
          status: "ready",
          nights: nights,
          start: data.start || null,
          end: data.end || null
        };
        renderPatterns();
        return data;
      })
      .catch(function (err) {
        if (reqId !== patternsReq) return null;
        state.patterns.status = "error";
        var errorText = $("#patterns-error-text");
        if (errorText) errorText.textContent = err.message;
        patternsPromise = null;
        renderPatternsStatus();
        throw err;
      });
    patternsPromise = request;
    return request;
  }

  function refreshPatterns() {
    loadPatterns(true).catch(function () { /* the existing view stays available */ });
  }

  function patternYears() {
    var seen = {};
    var years = [];
    for (var i = 0; i < state.patterns.nights.length; i++) {
      var year = parseISO(state.patterns.nights[i].date).y;
      if (!seen[year]) {
        seen[year] = true;
        years.push(year);
      }
    }
    return years.sort(function (a, b) { return a - b; });
  }

  function renderPatternYearSelect(years) {
    var select = $("#pattern-year");
    if (!select) return null;
    var previous = Number(select.value);
    var selected = years.indexOf(previous) >= 0
      ? previous : years[years.length - 1];
    select.textContent = "";
    for (var i = years.length - 1; i >= 0; i--) {
      var option = el("option", null, years[i]);
      option.value = String(years[i]);
      option.selected = years[i] === selected;
      select.appendChild(option);
    }
    select.disabled = years.length < 2;
    return selected;
  }

  function patternThresholds() {
    var debt = state.stats && state.stats.sleep_debt;
    var goal = Number(debt && debt.need);
    if (!isFinite(goal) || goal <= 0 || goal > 24) goal = 8;
    var step = Math.max(0.1, Math.min(1, goal / 3));
    return [goal - step * 2, goal - step, goal];
  }

  function heatLevel(hours, thresholds) {
    if (hours < thresholds[0]) return 1;
    if (hours < thresholds[1]) return 2;
    if (hours < thresholds[2]) return 3;
    return 4;
  }

  function compactHours(value) {
    var rounded = Math.round(value * 10) / 10;
    return String(rounded).replace(/\.0$/, "");
  }

  function updateHeatLegend(thresholds) {
    var labels = [
      "Under " + compactHours(thresholds[0]) + "h",
      compactHours(thresholds[0]) + " to <" + compactHours(thresholds[1]) + "h",
      compactHours(thresholds[1]) + " to <" + compactHours(thresholds[2]) + "h",
      compactHours(thresholds[2]) + "h or more"
    ];
    for (var i = 0; i < labels.length; i++) {
      var node = $("#heat-label-" + (i + 1));
      if (node) node.textContent = labels[i];
    }
  }

  function setHeatDetail(item) {
    if (!item) return;
    var text = fullDate(item.night.date) + " · " + fmt1(item.night.hours) + "h";
    if (item.night.quality !== null && item.night.quality !== undefined) {
      text += " · quality " + item.night.quality + "/5";
    }
    var source = sourceLabel(item.night.source);
    if (source) text += " · " + source;
    var detail = $("#heatmap-detail");
    if (detail) detail.textContent = text;
  }

  function activateHeatCell(item, moveFocus) {
    if (!item) return;
    for (var i = 0; i < heatButtons.length; i++) {
      var active = heatButtons[i] === item;
      heatButtons[i].node.tabIndex = active ? 0 : -1;
      heatButtons[i].node.setAttribute("aria-selected", active ? "true" : "false");
    }
    patternFocusDate = item.night.date;
    setHeatDetail(item);
    if (moveFocus) item.node.focus();
  }

  function heatCellKeydown(e, item) {
    var index = heatButtons.indexOf(item);
    var target = null;
    if (e.key === "ArrowLeft") {
      target = heatButtons[Math.max(0, index - 1)];
    } else if (e.key === "ArrowRight") {
      target = heatButtons[Math.min(heatButtons.length - 1, index + 1)];
    } else if (e.key === "Home") {
      target = heatButtons[0];
    } else if (e.key === "End") {
      target = heatButtons[heatButtons.length - 1];
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      var direction = e.key === "ArrowUp" ? -1 : 1;
      var wanted = item.num + direction * 7;
      var scan = direction < 0 ? heatButtons.length - 1 : 0;
      var stop = direction < 0 ? -1 : heatButtons.length;
      for (; scan !== stop; scan += direction) {
        if ((direction < 0 && heatButtons[scan].num <= wanted) ||
            (direction > 0 && heatButtons[scan].num >= wanted)) {
          target = heatButtons[scan];
          break;
        }
      }
      if (!target) target = direction < 0 ? heatButtons[0] :
        heatButtons[heatButtons.length - 1];
    } else {
      return;
    }
    e.preventDefault();
    activateHeatCell(target, true);
  }

  function renderHeatmap(year) {
    var host = $("#heatmap");
    if (!host || !year) return;
    host.textContent = "";
    heatButtons = [];

    var nights = [];
    var nightsByDate = {};
    for (var i = 0; i < state.patterns.nights.length; i++) {
      var night = state.patterns.nights[i];
      if (parseISO(night.date).y === year) {
        nights.push(night);
        nightsByDate[night.date] = night;
      }
    }

    var yearStart = Date.UTC(year, 0, 1) / 86400000;
    var yearEnd = Date.UTC(year + 1, 0, 1) / 86400000 - 1;
    var startDow = (new Date(yearStart * 86400000).getUTCDay() + 6) % 7;
    var weeks = Math.ceil((startDow + yearEnd - yearStart + 1) / 7);
    host.style.setProperty("--heat-weeks", String(weeks));

    var months = el("div", "heat-months");
    months.setAttribute("aria-hidden", "true");
    months.appendChild(el("span", "heat-corner"));
    for (var m = 0; m < 12; m++) {
      var monthStart = Date.UTC(year, m, 1) / 86400000;
      var week = Math.floor((startDow + monthStart - yearStart) / 7);
      var monthLabel = el("span", "heat-month-label", MONTHS[m]);
      monthLabel.style.gridColumn = String(week + 2);
      months.appendChild(monthLabel);
    }
    host.appendChild(months);

    var weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    var thresholds = patternThresholds();
    updateHeatLegend(thresholds);
    var today = dayNumFromISO(state.patterns.end || window.__TODAY__);

    for (var dow = 0; dow < 7; dow++) {
      var row = el("div", "heat-row");
      row.setAttribute("role", "row");
      var dayLabel = el("span", "heat-weekday", weekdays[dow]);
      dayLabel.setAttribute("role", "rowheader");
      row.appendChild(dayLabel);
      for (var w = 0; w < weeks; w++) {
        var dayNum = yearStart - startDow + w * 7 + dow;
        var date = isoFromDayNum(dayNum);
        var inYear = dayNum >= yearStart && dayNum <= yearEnd;
        var record = inYear ? nightsByDate[date] : null;
        var cell;
        if (record) {
          var level = heatLevel(record.hours, thresholds);
          cell = el("button", "heat-cell heat-level-" + level);
          cell.type = "button";
          cell.setAttribute("role", "gridcell");
          cell.setAttribute("aria-selected", "false");
          var aria = fullDate(date) + ": " + fmt1(record.hours) + " hours";
          if (record.quality !== null && record.quality !== undefined) {
            aria += ", quality " + record.quality + " of 5";
          }
          var src = sourceLabel(record.source);
          if (src) aria += ", " + src;
          cell.setAttribute("aria-label", aria);
          var item = { node: cell, num: dayNum, night: record };
          heatButtons.push(item);
          (function (bound) {
            cell.addEventListener("focus", function () {
              activateHeatCell(bound, false);
            });
            cell.addEventListener("click", function () {
              activateHeatCell(bound, false);
            });
            cell.addEventListener("keydown", function (e) {
              heatCellKeydown(e, bound);
            });
          })(item);
        } else {
          var cls = "heat-cell ";
          if (!inYear) cls += "heat-outside";
          else if (isFinite(today) && dayNum > today) cls += "heat-future";
          else cls += "heat-empty";
          cell = el("span", cls);
          if (inYear) {
            cell.setAttribute("role", "gridcell");
            cell.setAttribute("aria-label",
              fullDate(date) + (dayNum > today ? ": future date" : ": no record"));
            cell.setAttribute("aria-disabled", "true");
          } else {
            cell.setAttribute("aria-hidden", "true");
          }
        }
        row.appendChild(cell);
      }
      host.appendChild(row);
    }

    heatButtons.sort(function (a, b) { return a.num - b.num; });
    var chosen = null;
    for (var b = 0; b < heatButtons.length; b++) {
      if (heatButtons[b].night.date === patternFocusDate) chosen = heatButtons[b];
    }
    if (!chosen && heatButtons.length) chosen = heatButtons[heatButtons.length - 1];
    if (chosen) activateHeatCell(chosen, false);

    var elapsedEnd = Math.min(yearEnd, isFinite(today) ? today : yearEnd);
    var possible = Math.max(0, elapsedEnd - yearStart + 1);
    var sum = 0;
    for (var n = 0; n < nights.length; n++) sum += nights[n].hours;
    var coverage = possible ? Math.round(nights.length / possible * 100) : 0;
    var summary = $("#heatmap-summary");
    if (summary) {
      summary.textContent = nights.length + (nights.length === 1 ? " night" : " nights") +
        " logged · " + (nights.length ? fmt1(sum / nights.length) + "h" : "–") +
        " average · " +
        coverage + "% coverage";
    }
  }

  function monthGroups(nights) {
    var groups = {};
    for (var i = 0; i < nights.length; i++) {
      var p = parseISO(nights[i].date);
      var key = p.y + "-" + String(p.m).padStart(2, "0");
      if (!groups[key]) {
        var start = Date.UTC(p.y, p.m - 1, 1) / 86400000;
        groups[key] = {
          key: key,
          label: MONTH_NAMES[p.m - 1] + " " + p.y,
          start: start,
          end: Date.UTC(p.y, p.m, 1) / 86400000 - 1,
          nights: []
        };
      }
      groups[key].nights.push(nights[i]);
    }
    return groupList(groups);
  }

  function seasonPeriod(date) {
    var p = parseISO(date);
    var startYear, endYear, startMonth, endMonth, name, key;
    if (p.m === 12 || p.m <= 2) {
      endYear = p.m === 12 ? p.y + 1 : p.y;
      startYear = endYear - 1;
      startMonth = 11;
      endMonth = 2;
      name = "Winter";
      key = "winter-" + endYear;
    } else if (p.m <= 5) {
      startYear = endYear = p.y;
      startMonth = 2;
      endMonth = 5;
      name = "Spring";
      key = "spring-" + p.y;
    } else if (p.m <= 8) {
      startYear = endYear = p.y;
      startMonth = 5;
      endMonth = 8;
      name = "Summer";
      key = "summer-" + p.y;
    } else {
      startYear = endYear = p.y;
      startMonth = 8;
      endMonth = 11;
      name = "Autumn";
      key = "autumn-" + p.y;
    }
    return {
      key: key,
      label: name === "Winter"
        ? name + " " + startYear + "-" + String(endYear).slice(-2)
        : name + " " + startYear,
      start: Date.UTC(startYear, startMonth, 1) / 86400000,
      end: Date.UTC(endYear, endMonth, 1) / 86400000 - 1
    };
  }

  function seasonGroups(nights) {
    var groups = {};
    for (var i = 0; i < nights.length; i++) {
      var period = seasonPeriod(nights[i].date);
      if (!groups[period.key]) {
        groups[period.key] = {
          key: period.key,
          label: period.label,
          start: period.start,
          end: period.end,
          nights: []
        };
      }
      groups[period.key].nights.push(nights[i]);
    }
    return groupList(groups);
  }

  function groupList(groups) {
    var list = [];
    for (var key in groups) {
      if (Object.prototype.hasOwnProperty.call(groups, key)) list.push(groups[key]);
    }
    return list.sort(function (a, b) { return a.start - b.start; });
  }

  function fillPeriodSelect(select, groups, selected) {
    select.textContent = "";
    for (var i = groups.length - 1; i >= 0; i--) {
      var group = groups[i];
      var count = group.nights.length;
      var option = el("option", null, group.label + " · " + count +
        (count === 1 ? " night" : " nights"));
      option.value = group.key;
      option.selected = group.key === selected;
      select.appendChild(option);
    }
  }

  function syncComparisonChoices(kind) {
    var a = $("#" + kind + "-a");
    var b = $("#" + kind + "-b");
    if (!a || !b) return;
    for (var i = 0; i < a.options.length; i++) {
      a.options[i].disabled = a.options[i].value === b.value;
    }
    for (var j = 0; j < b.options.length; j++) {
      b.options[j].disabled = b.options[j].value === a.value;
    }
  }

  function populateComparison(kind, groups) {
    var a = $("#" + kind + "-a");
    var b = $("#" + kind + "-b");
    if (!a || !b || !groups.length) return;
    var keys = {};
    for (var i = 0; i < groups.length; i++) keys[groups[i].key] = true;
    var oldA = keys[a.value] ? a.value : groups[groups.length - 1].key;
    var oldB = keys[b.value] && b.value !== oldA
      ? b.value : (groups.length > 1 ? groups[groups.length - 2].key : oldA);
    fillPeriodSelect(a, groups, oldA);
    fillPeriodSelect(b, groups, oldB);
    a.disabled = groups.length < 2;
    b.disabled = groups.length < 2;
    syncComparisonChoices(kind);
    renderComparison(kind, groups);
  }

  function groupMetrics(group) {
    var hours = 0;
    var quality = 0;
    var qualityCount = 0;
    for (var i = 0; i < group.nights.length; i++) {
      hours += group.nights[i].hours;
      if (group.nights[i].quality !== null &&
          group.nights[i].quality !== undefined) {
        quality += group.nights[i].quality;
        qualityCount++;
      }
    }
    var today = dayNumFromISO(state.patterns.end || window.__TODAY__);
    var end = Math.min(group.end, isFinite(today) ? today : group.end);
    var possible = Math.max(1, end - group.start + 1);
    return {
      count: group.nights.length,
      avgHours: hours / group.nights.length,
      avgQuality: qualityCount ? quality / qualityCount : null,
      qualityCount: qualityCount,
      possible: possible,
      coverage: Math.round(group.nights.length / possible * 100)
    };
  }

  function comparisonPeriod(group) {
    var metrics = groupMetrics(group);
    var side = el("div", "compare-period");
    side.appendChild(el("strong", "compare-period-name", group.label));
    var values = el("div", "compare-values");
    values.appendChild(el("span", "compare-hours", fmt1(metrics.avgHours) + "h avg"));
    values.appendChild(el("span", "compare-quality",
      metrics.avgQuality === null
        ? "No quality ratings"
        : fmt1(metrics.avgQuality) + "/5 quality" +
          (metrics.qualityCount < metrics.count
            ? " (" + metrics.qualityCount + " rated)" : "")));
    side.appendChild(values);
    side.appendChild(el("p", "compare-coverage",
      metrics.count + " of " + metrics.possible + " nights logged (" +
      metrics.coverage + "%)"));
    if (metrics.count < 7) {
      side.appendChild(el("p", "compare-caveat",
        "Small sample; averages may shift."));
    } else if (metrics.coverage < 50) {
      side.appendChild(el("p", "compare-caveat",
        "Partial history; averages use logged nights only."));
    }
    return { node: side, metrics: metrics };
  }

  function renderComparison(kind, groups) {
    var host = $("#" + kind + "-results");
    var a = $("#" + kind + "-a");
    var b = $("#" + kind + "-b");
    if (!host || !a || !b) return;
    host.textContent = "";
    var byKey = {};
    for (var i = 0; i < groups.length; i++) byKey[groups[i].key] = groups[i];
    var first = byKey[a.value];
    var second = byKey[b.value];
    if (!first) return;

    var periods = el("div", "compare-periods");
    var firstView = comparisonPeriod(first);
    periods.appendChild(firstView.node);
    if (groups.length < 2 || !second || first.key === second.key) {
      host.appendChild(periods);
      host.appendChild(el("p", "compare-delta",
        "Add nights in another " + (kind === "month" ? "month" : "season") +
        " to compare."));
      return;
    }

    var secondView = comparisonPeriod(second);
    periods.appendChild(secondView.node);
    host.appendChild(periods);
    var difference = firstView.metrics.avgHours - secondView.metrics.avgHours;
    var summary;
    if (Math.abs(difference) < 0.05) {
      summary = "Average sleep was the same.";
    } else {
      summary = first.label + " averaged " + fmt1(Math.abs(difference)) +
        "h " + (difference > 0 ? "more" : "less") + " than " + second.label + ".";
    }
    host.appendChild(el("p", "compare-delta", summary));
  }

  function renderPatterns() {
    renderPatternsStatus();
    if (!state.patterns.nights.length) {
      var select = $("#pattern-year");
      if (select) {
        select.textContent = "";
        select.appendChild(el("option", null, "No data"));
        select.disabled = true;
      }
      return;
    }
    var years = patternYears();
    var selectedYear = renderPatternYearSelect(years);
    renderHeatmap(selectedYear);
    populateComparison("month", monthGroups(state.patterns.nights));
    populateComparison("season", seasonGroups(state.patterns.nights));
  }

  function initPatterns() {
    var year = $("#pattern-year");
    if (year) {
      year.addEventListener("change", function () {
        patternFocusDate = null;
        renderHeatmap(Number(year.value));
      });
    }
    var retry = $("#patterns-retry");
    if (retry) retry.addEventListener("click", function () {
      loadPatterns(true).catch(function () {});
    });
    var kinds = ["month", "season"];
    for (var i = 0; i < kinds.length; i++) {
      (function (kind) {
        var a = $("#" + kind + "-a");
        var b = $("#" + kind + "-b");
        function changed() {
          syncComparisonChoices(kind);
          var groups = kind === "month"
            ? monthGroups(state.patterns.nights)
            : seasonGroups(state.patterns.nights);
          renderComparison(kind, groups);
        }
        if (a) a.addEventListener("change", changed);
        if (b) b.addEventListener("change", changed);
      })(kinds[i]);
    }
    loadPatterns(false).catch(function () {});
  }

  /* ---------------- records table ---------------- */

  function td(cls, text) {
    var cell = el("td", cls);
    if (text !== undefined) cell.textContent = String(text);
    return cell;
  }

  function renderRecords() {
    var body = $("#records-body");
    var table = $("#records-table");
    var empty = $("#empty-msg");
    if (!body) return;
    body.textContent = "";

    var recs = state.records || [];
    var hasAny = recs.length > 0;
    if (table) table.parentElement.hidden = !hasAny; // .table-wrap
    if (empty) empty.hidden = hasAny;
    // Empty state: the import card is the product thesis — feature it.
    var wearCard = $("#wearable-card");
    if (wearCard) wearCard.classList.toggle("import-hero", !hasAny);
    renderLoadMore();
    if (!hasAny) return;

    for (var i = 0; i < recs.length; i++) {
      body.appendChild(displayRow(recs[i]));
    }
  }

  function renderLoadMore() {
    var btn = $("#load-more");
    if (!btn) return;
    var total = Number(state.stats && state.stats.total) || 0;
    btn.hidden = state.records.length >= total || state.records.length >= 10000;
  }

  function focusEditButton(recordId) {
    var row = doc.querySelector('tr[data-id="' + recordId + '"]');
    var button = row && row.querySelector(".c-actions .btn");
    if (!button) return false;
    button.focus();
    return true;
  }

  function focusTableStatus() {
    var msg = $("#table-msg");
    if (!msg) return;
    msg.setAttribute("tabindex", "-1");
    msg.focus();
  }

  function displayRow(r) {
    var tr = el("tr");
    tr.dataset.id = r.id;

    var dateCell = td("c-date", r.date);
    var srcLabel = sourceLabel(r.source);
    if (srcLabel) {
      var chip = el("span", "chip", srcLabel);
      chip.title = "Imported from " + srcLabel;
      dateCell.appendChild(chip);
    }
    tr.appendChild(dateCell);
    tr.appendChild(td("c-time", r.bedtime));
    tr.appendChild(td("c-time", r.wake));
    tr.appendChild(td("num", fmt1(r.hours) + "h"));

    var qCell = el("td");
    var starSpan = el("span", "stars", stars(r.quality));
    starSpan.setAttribute("role", "img");
    starSpan.setAttribute("aria-label", "Quality " + r.quality + " of 5");
    qCell.appendChild(starSpan);
    tr.appendChild(qCell);

    var notesCell = td("c-notes", r.notes || "");
    if (r.notes) notesCell.title = r.notes;
    tr.appendChild(notesCell);

    var actions = el("td", "c-actions");
    var editBtn = el("button", "btn btn-small", "Edit");
    editBtn.type = "button";
    editBtn.setAttribute("aria-label", "Edit record for " + r.date);
    editBtn.addEventListener("click", function () { toEditRow(tr, r); });

    var delBtn = el("button", "btn btn-small btn-danger", "Delete");
    delBtn.type = "button";
    delBtn.setAttribute("aria-label", "Delete record for " + r.date);
    delBtn.addEventListener("click", function () { armDelete(delBtn, r); });

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    tr.appendChild(actions);
    return tr;
  }

  /* Two-step inline delete: first click arms ("Confirm?") for 3s, second commits. */
  function armDelete(btn, r) {
    if (btn.dataset.armed === "1") {
      if (btn._disarmTimer) { clearTimeout(btn._disarmTimer); btn._disarmTimer = null; }
      var index = state.records.indexOf(r);
      var neighbor = state.records[index + 1] || state.records[index - 1];
      btn.disabled = true;
      post("/delete/" + r.id, new FormData()).then(function () {
        setMsg($("#table-msg"), "Deleted " + r.date + ".", "ok");
        if (!neighbor || !focusEditButton(neighbor.id)) focusTableStatus();
      }).catch(function (err) {
        btn.disabled = false;
        disarmDelete(btn, r);
        setMsg($("#table-msg"), err.message, "err");
      });
      return;
    }
    btn.dataset.armed = "1";
    btn.textContent = "Confirm?";
    btn.classList.add("armed");
    btn.setAttribute("aria-label", "Confirm delete for " + r.date);
    btn._disarmTimer = setTimeout(function () { disarmDelete(btn, r); }, 3000);
  }

  function disarmDelete(btn, r) {
    btn.dataset.armed = "";
    btn.textContent = "Delete";
    btn.classList.remove("armed");
    if (r) btn.setAttribute("aria-label", "Delete record for " + r.date);
  }

  function toEditRow(tr, r) {
    tr.textContent = "";
    tr.classList.add("editing");

    function input(type, value, label) {
      var inp = doc.createElement("input");
      inp.type = type;
      inp.value = value;
      inp.setAttribute("aria-label", label);
      return inp;
    }

    var dateIn = input("date", r.date, "Date");
    dateIn.max = window.__TODAY__ || "";
    var bedIn = input("time", r.bedtime, "Bedtime");
    var wakeIn = input("time", r.wake, "Wake time");

    var qualSel = doc.createElement("select");
    qualSel.setAttribute("aria-label", "Quality");
    for (var q = 1; q <= 5; q++) {
      var opt = doc.createElement("option");
      opt.value = String(q);
      opt.textContent = q + "/5";
      if (q === Number(r.quality)) opt.selected = true;
      qualSel.appendChild(opt);
    }

    var notesIn = input("text", r.notes || "", "Notes");
    notesIn.maxLength = 500;

    function cellWith(node, cls) {
      var cell = el("td", cls);
      cell.appendChild(node);
      return cell;
    }

    tr.appendChild(cellWith(dateIn));
    tr.appendChild(cellWith(bedIn));
    tr.appendChild(cellWith(wakeIn));
    tr.appendChild(td("num", "–"));
    tr.appendChild(cellWith(qualSel));
    tr.appendChild(cellWith(notesIn));

    var actions = el("td", "c-actions");
    var saveBtn = el("button", "btn btn-small btn-primary", "Save");
    saveBtn.type = "button";
    saveBtn.addEventListener("click", function () {
      var fd = new FormData();
      fd.append("date", dateIn.value);
      fd.append("bedtime", bedIn.value);
      fd.append("wake", wakeIn.value);
      fd.append("quality", qualSel.value);
      fd.append("notes", notesIn.value);
      saveBtn.disabled = true;
      post("/edit/" + r.id, fd).then(function () {
        setMsg($("#table-msg"), "Updated " + dateIn.value + ".", "ok");
        focusEditButton(r.id);
      }).catch(function (err) {
        saveBtn.disabled = false;
        setMsg($("#table-msg"), err.message, "err");
      });
    });

    var cancelBtn = el("button", "btn btn-small", "Cancel");
    cancelBtn.type = "button";
    cancelBtn.addEventListener("click", function () {
      var fresh = displayRow(r);
      tr.replaceWith(fresh);
      var editButton = fresh.querySelector(".c-actions .btn");
      if (editButton) editButton.focus();
    });

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);
    tr.appendChild(actions);
    dateIn.focus();
  }

  /* ---------------- form ---------------- */

  function initForm() {
    var form = $("#sleep-form");
    if (!form) return;
    var msg = $("#form-msg");
    var saveBtn = $("#save-btn");
    var quality = $("#f-quality");
    var qOut = $("#q-val");

    if (quality && qOut) {
      quality.addEventListener("input", function () {
        qOut.textContent = quality.value;
      });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      setMsg(msg, "", "");
      if (saveBtn) saveBtn.disabled = true;
      var notes = $("#f-notes");
      var submittedNotes = notes ? notes.value : "";
      post("/add", new FormData(form)).then(function () {
        setMsg(msg, "Night saved.", "ok");
        if (notes && notes.value === submittedNotes) {
          notes.value = ""; // Keep anything typed while the request was in flight.
        }
      }).catch(function (err) {
        setMsg(msg, err.message, "err");
      }).then(function () {
        if (saveBtn) saveBtn.disabled = false;
      });
    });
  }

  function initImport() {
    var button = $("#import-btn");
    var input = $("#import-file");
    if (!button || !input) return;

    button.addEventListener("click", function () { input.click(); });
    input.addEventListener("change", function () {
      if (!input.files || !input.files[0]) return;
      var previousTotal = Number(state.stats && state.stats.total) || 0;
      var data = new FormData();
      data.append("file", input.files[0]);
      button.disabled = true;
      post("/import", data).then(function () {
        var imported = Math.max(
          0, (Number(state.stats && state.stats.total) || 0) - previousTotal
        );
        setMsg(
          $("#table-msg"),
          "Imported " + imported + (imported === 1 ? " record." : " records."),
          "ok"
        );
      }).catch(function (err) {
        setMsg($("#table-msg"), err.message, "err");
      }).then(function () {
        input.value = "";
        button.disabled = false;
        button.focus();
      });
    });
  }

  /* ---------------- wearable import ---------------- */

  /* XHR (not fetch) so upload progress is reportable — exports can be 500MB. */
  function uploadWearable(file, onProgress) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", "/import/wearable");
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");

      var mb = Math.max(0.1, file.size / 1048576);
      var mbText = mb >= 100 ? Math.round(mb) + " MB" : (Math.round(mb * 10) / 10) + " MB";
      xhr.upload.addEventListener("progress", function (e) {
        if (!e.lengthComputable) { onProgress(100, "Uploading…"); return; }
        var pct = Math.min(100, (e.loaded / e.total) * 100);
        onProgress(pct, pct >= 100
          ? "Processing…"
          : "Uploading… " + Math.round(pct) + "% of " + mbText);
      });
      xhr.upload.addEventListener("load", function () {
        onProgress(100, "Processing…"); // upload done; server is parsing
      });

      xhr.addEventListener("load", function () {
        var data = {};
        try { data = JSON.parse(xhr.responseText || "{}"); } catch (e) { /* non-JSON */ }
        if (xhr.status >= 200 && xhr.status < 300 && !data.error) {
          if (Array.isArray(data.records)) state.records = data.records;
          if (data.stats) state.stats = data.stats;
          renderStats();
          renderChart();
          renderRecords();
          resolve(data);
        } else {
          reject(new Error(data.error || "Import failed (" + xhr.status + ")"));
        }
      });
      xhr.addEventListener("error", function () {
        reject(new Error("Network error — is the server running?"));
      });

      var fd = new FormData();
      fd.append("file", file);
      xhr.send(fd);
    });
  }

  function initWearable() {
    var zone = $("#dropzone");
    var input = $("#wearable-file");
    if (!zone || !input) return;
    var progWrap = $("#upload-progress");
    var bar = $("#progress-bar");
    var fill = $("#progress-fill");
    var ptext = $("#progress-text");
    var msg = $("#import-msg");
    var busy = false;

    function setProgress(pct, label) {
      if (fill) fill.style.width = pct + "%";
      if (bar) bar.setAttribute("aria-valuenow", String(Math.round(pct)));
      if (ptext) ptext.textContent = label;
    }

    function pick() { if (!busy) input.click(); }

    function start(file) {
      if (busy || !file) return;
      busy = true;
      zone.classList.add("busy");
      zone.setAttribute("aria-disabled", "true");
      setMsg(msg, "", "");
      if (progWrap) progWrap.hidden = false;
      setProgress(0, "Uploading… 0%");

      function run() { return uploadWearable(file, setProgress); }
      var result = mutationQueue.then(run, run);
      mutationQueue = result.catch(function () {});
      result.then(function (data) {
        var i = Number(data.imported) || 0;
        var rep = Number(data.replaced) || 0;
        var sk = Number(data.skipped) || 0;
        // Persistent result summary (not the auto-clearing setMsg path).
        msg.textContent = i + (i === 1 ? " night" : " nights") + " imported (" +
          rep + " replaced, " + sk + " skipped).";
        msg.className = "msg ok";
        refreshSeries();
        refreshPatterns();
      }).catch(function (err) {
        setMsg(msg, err.message, "err");
      }).then(function () {
        busy = false;
        zone.classList.remove("busy");
        zone.removeAttribute("aria-disabled");
        if (progWrap) progWrap.hidden = true;
        input.value = "";
        zone.focus();
      });
    }

    zone.addEventListener("click", pick);
    zone.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
    });
    zone.addEventListener("dragover", function (e) {
      e.preventDefault();
      if (!busy) zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", function () {
      zone.classList.remove("drag-over");
    });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("drag-over");
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      start(f);
    });
    input.addEventListener("change", function () {
      if (input.files && input.files[0]) start(input.files[0]);
    });
  }

  function initLoadMore() {
    var button = $("#load-more");
    if (!button) return;

    button.addEventListener("click", function () {
      var previousCount = 0;
      var total = 0;
      button.disabled = true;
      function run() {
        previousCount = state.records.length;
        total = Number(state.stats && state.stats.total) || 0;
        var target = Math.min(10000, total, Math.max(30, previousCount + 30));
        return fetchJson("/api/records?limit=" + target);
      }
      function applyRecords(records) {
        if (!Array.isArray(records)) throw new Error("Invalid records response.");
        state.records = records;
        renderRecords();
        setMsg(
          $("#table-msg"),
          "Showing " + records.length + " of " + total + " records.",
          "ok"
        );
        if (records[previousCount]) {
          focusEditButton(records[previousCount].id);
        }
      }
      var result = mutationQueue.then(run, run).then(applyRecords);
      mutationQueue = result.catch(function () {});
      result.catch(function (err) {
        setMsg($("#table-msg"), err.message, "err");
      }).then(function () {
        button.disabled = false;
        renderLoadMore();
      });
    });
  }

  /* ---------------- boot ---------------- */

  function init() {
    initTheme();
    initForm();
    initImport();
    initWearable();
    initRange();
    initPatterns();
    initLoadMore();
    renderStats();
    renderChart();
    renderRecords();
    refreshSeries(); // enrich the 30d view with stages/sources

    var resizeTimer = null;
    window.addEventListener("resize", function () {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(renderChart, 150);
    });
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
