/* Sleep Tracker UI — vanilla JS, no dependencies.
   All user-supplied content is inserted via textContent (never innerHTML). */
"use strict";

(function () {
  var doc = document;
  var SVGNS = "http://www.w3.org/2000/svg";
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var state = {
    records: Array.isArray(window.__INITIAL_RECORDS__) ? window.__INITIAL_RECORDS__ : [],
    stats: window.__INITIAL_STATS__ || {
      total: 0, avg_hours: 0, avg_quality: 0,
      current_streak: 0, best_streak: 0, series: []
    },
    range: "30d",       // chart range: 30d | 90d | 1y | all
    nights: null,       // /api/series nights for the current range (sparse, asc)
    nightsMap: null,    // date -> night (stages/source enrichment)
    seriesMeta: null    // {start, end, range} from /api/series
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
