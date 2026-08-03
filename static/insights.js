/* Sleep Insights page renderer.
 *
 * Fetches /api/analytics and draws every chart as inline SVG — no libraries,
 * no CDNs. All data-derived strings go through textContent (or SVG <title>
 * text nodes); nothing user-controlled is ever assigned to innerHTML,
 * matching the project's XSS convention.
 */
(function () {
  "use strict";

  var SVGNS = "http://www.w3.org/2000/svg";

  var COLOR = {
    ink: "#141413",
    muted: "#6E6B64",
    grid: "#F2EFE9",
    axis: "#E8E4DC",
    accent: "#D97757",
    slate: "#6A7B8A",
    sage: "#7D8B6F",
    gold: "#C2A36B",
    plum: "#8A6E7B",
  };

  // Stage series order chosen for color separation (validated):
  // terracotta / slate / gold / plum are mutually distinguishable; the
  // muted trio never sits adjacent.
  var STAGE_SERIES = [
    { key: "deep", label: "Deep", color: COLOR.accent },
    { key: "rem", label: "REM", color: COLOR.slate },
    { key: "light", label: "Light", color: COLOR.gold },
    { key: "awake", label: "Awake", color: COLOR.plum },
  ];

  // ── DOM helpers (textContent only for data) ────────────────

  function h(tag, className, textStr) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (textStr !== undefined && textStr !== null) node.textContent = textStr;
    return node;
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS(SVGNS, tag);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          node.setAttribute(key, String(attrs[key]));
        }
      }
    }
    return node;
  }

  function svgText(x, y, str, opts) {
    opts = opts || {};
    var node = svgEl("text", {
      x: x,
      y: y,
      fill: opts.fill || COLOR.muted,
      "font-size": opts.size || 13,
      "text-anchor": opts.anchor || "start",
      "font-family": opts.serif
        ? "Georgia, 'Times New Roman', serif"
        : "system-ui, -apple-system, sans-serif",
    });
    if (opts.weight) node.setAttribute("font-weight", opts.weight);
    node.textContent = str;
    return node;
  }

  function chartSvg(width, height, label) {
    var node = svgEl("svg", {
      viewBox: "0 0 " + width + " " + height,
      class: "chart",
      role: "img",
      "aria-label": label,
    });
    var title = svgEl("title");
    title.textContent = label;
    node.appendChild(title);
    return node;
  }

  function markTitle(mark, str) {
    var title = svgEl("title");
    title.textContent = str;
    mark.appendChild(title);
  }

  function emptyState(container, section, fallbackMin) {
    var min = (section && section.min_nights) || fallbackMin || 7;
    container.appendChild(
      h(
        "div",
        "empty-state",
        "Not enough nights yet — log " + min + "+ nights to unlock this."
      )
    );
  }

  function legend(entries) {
    var box = h("div", "legend");
    entries.forEach(function (entry) {
      var chip = h("span", "chip");
      var swatch = h("span", "swatch" + (entry.hollow ? " hollow" : ""));
      if (!entry.hollow) swatch.style.background = entry.color;
      chip.appendChild(swatch);
      chip.appendChild(document.createTextNode(entry.label));
      box.appendChild(chip);
    });
    return box;
  }

  function linScale(d0, d1, r0, r1) {
    var span = d1 - d0 === 0 ? 1 : d1 - d0;
    return function (v) {
      return r0 + ((v - d0) / span) * (r1 - r0);
    };
  }

  function dayNumber(dateStr) {
    return Date.parse(dateStr + "T00:00:00Z") / 86400000;
  }

  function shortDate(dateStr) {
    var d = new Date(dateStr + "T00:00:00Z");
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return months[d.getUTCMonth()] + " " + d.getUTCDate();
  }

  function fmt1(v) {
    return (Math.round(v * 10) / 10).toFixed(1);
  }

  // ── Headline stat tiles ────────────────────────────────────

  function tile(label, value, note) {
    var box = h("div", "stat-tile");
    box.appendChild(h("div", "stat-label", label));
    box.appendChild(h("div", "stat-value", value));
    if (note) box.appendChild(h("div", "stat-note", note));
    return box;
  }

  function renderHeadline(data) {
    var row = document.getElementById("headline");
    row.appendChild(tile("Nights logged", String(data.n_nights), "all time"));

    var report = data.weekly_report;
    if (report.available) {
      var delta = report.headline.delta_hours_vs_prev_week;
      var note = "last 7 days";
      if (delta !== null && delta !== undefined) {
        note = (delta >= 0 ? "+" : "−") + fmt1(Math.abs(delta)) + "h vs prior week";
      }
      row.appendChild(tile("Avg sleep", fmt1(report.headline.avg_hours) + "h", note));
      row.appendChild(
        tile("Avg quality", fmt1(report.headline.avg_quality) + "/5",
          report.headline.nights_logged + " nights this week")
      );
    }
    if (data.bedtime_consistency.available) {
      row.appendChild(
        tile("Consistency", Math.round(data.bedtime_consistency.consistency_score) + "/100",
          "typical bedtime " + data.bedtime_consistency.bedtime.mean)
      );
    }
    if (data.sleep_debt.available) {
      row.appendChild(
        tile("Sleep debt", fmt1(data.sleep_debt.current_debt_hours) + "h",
          "vs " + fmt1(data.sleep_debt.need_hours) + "h goal, decayed")
      );
    }
  }

  // ── What stands out ────────────────────────────────────────

  function renderStandout(data) {
    var body = document.getElementById("standout-body");
    var report = data.weekly_report;
    if (!report.available || !report.insights.length) {
      emptyState(body, report, 5);
      return;
    }
    var list = h("ul", "insight-list");
    report.insights.forEach(function (sentence) {
      list.appendChild(h("li", null, sentence));
    });
    body.appendChild(list);
  }

  // ── Duration trend chart ───────────────────────────────────

  function renderTrend(data) {
    var body = document.getElementById("trend-body");
    var section = data.duration_trend;
    if (!section.available) {
      emptyState(body, section, 7);
      return;
    }

    var W = 680, H = 280;
    var m = { l: 46, r: 14, t: 14, b: 36 };
    var points = section.points;
    var xs = points.map(function (p) { return dayNumber(p.date); });
    var hoursVals = points.map(function (p) { return p.hours; });
    var lo = Math.max(0, Math.min.apply(null, hoursVals) - 0.75);
    var hi = Math.max.apply(null, hoursVals) + 0.75;
    var x = linScale(xs[0], xs[xs.length - 1], m.l, W - m.r);
    var y = linScale(lo, hi, H - m.b, m.t);

    var chart = chartSvg(W, H,
      "Line chart of nightly sleep hours over time with a rolling 7-night mean and variability band.");

    // Grid + y ticks (whole hours).
    for (var t = Math.ceil(lo); t <= Math.floor(hi); t++) {
      chart.appendChild(svgEl("line", {
        x1: m.l, x2: W - m.r, y1: y(t), y2: y(t),
        stroke: COLOR.grid, "stroke-width": 1,
      }));
      chart.appendChild(svgText(m.l - 8, y(t) + 4, t + "h", { anchor: "end" }));
    }
    // X ticks: ~5 dates.
    var step = Math.max(1, Math.floor(points.length / 5));
    for (var i = 0; i < points.length; i += step) {
      chart.appendChild(svgText(x(xs[i]), H - m.b + 20, shortDate(points[i].date),
        { anchor: "middle" }));
    }
    chart.appendChild(svgEl("line", {
      x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b,
      stroke: COLOR.axis, "stroke-width": 1,
    }));

    // Rolling-std band around the rolling mean.
    var band = points.filter(function (p) { return p.rolling_mean !== null; });
    if (band.length > 1) {
      var upper = band.map(function (p) {
        return x(dayNumber(p.date)) + "," + y(p.rolling_mean + p.rolling_std);
      });
      var lower = band.slice().reverse().map(function (p) {
        return x(dayNumber(p.date)) + "," + y(p.rolling_mean - p.rolling_std);
      });
      chart.appendChild(svgEl("polygon", {
        points: upper.concat(lower).join(" "),
        fill: COLOR.accent, "fill-opacity": 0.10, stroke: "none",
      }));
    }

    // Nightly line (thin, slate) + dots with tooltips.
    chart.appendChild(svgEl("polyline", {
      points: points.map(function (p) {
        return x(dayNumber(p.date)) + "," + y(p.hours);
      }).join(" "),
      fill: "none", stroke: COLOR.slate, "stroke-width": 1.25,
      "stroke-opacity": 0.7,
    }));
    points.forEach(function (p) {
      var dot = svgEl("circle", {
        cx: x(dayNumber(p.date)), cy: y(p.hours), r: 2.6,
        fill: COLOR.slate, stroke: "#fff", "stroke-width": 1,
      });
      markTitle(dot, p.date + " — " + fmt1(p.hours) + "h");
      chart.appendChild(dot);
    });

    // Rolling mean (accent, 2px).
    if (band.length > 1) {
      chart.appendChild(svgEl("polyline", {
        points: band.map(function (p) {
          return x(dayNumber(p.date)) + "," + y(p.rolling_mean);
        }).join(" "),
        fill: "none", stroke: COLOR.accent, "stroke-width": 2,
        "stroke-linejoin": "round",
      }));
    }

    var scroll = h("div", "chart-scroll");
    scroll.appendChild(chart);
    body.appendChild(scroll);
    body.appendChild(legend([
      { color: COLOR.slate, label: "Nightly hours" },
      { color: COLOR.accent, label: "7-night rolling mean (band = ±1 SD)" },
    ]));

    if (section.trend) {
      var slope = section.trend.slope_hours_per_week;
      var sentence = "Trend: " + (slope >= 0 ? "+" : "−")
        + Math.abs(Math.round(slope * 60)) + " min/week";
      if (section.trend.ci95) {
        sentence += " (95% CI " + fmt1(section.trend.ci95[0]) + " to "
          + fmt1(section.trend.ci95[1]) + " h/week"
          + (section.trend.significant ? ", statistically significant" : ", not significant")
          + ")";
      }
      body.appendChild(h("p", "fineprint", sentence + "."));
    }
  }

  // ── Bedtime consistency clock ──────────────────────────────

  function clockAngle(minutes) {
    return (minutes / 1440) * 2 * Math.PI - Math.PI / 2; // midnight at top
  }

  function polar(cx, cy, r, angle) {
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  }

  function renderClock(data) {
    var body = document.getElementById("clock-body");
    var section = data.bedtime_consistency;
    if (!section.available) {
      emptyState(body, section, 5);
      return;
    }

    var W = 340, H = 340, cx = W / 2, cy = H / 2;
    var rBed = 128, rWake = 96;
    var chart = chartSvg(W, H,
      "Clock chart of bedtimes (outer ring) and wake times (inner ring) around a 24-hour circle.");

    [rBed, rWake].forEach(function (radius) {
      chart.appendChild(svgEl("circle", {
        cx: cx, cy: cy, r: radius, fill: "none",
        stroke: COLOR.grid, "stroke-width": 1,
      }));
    });
    // Hour ticks + the four cardinal labels.
    for (var hr = 0; hr < 24; hr++) {
      var a = clockAngle(hr * 60);
      var p1 = polar(cx, cy, rBed + 4, a);
      var p2 = polar(cx, cy, rBed + (hr % 6 === 0 ? 12 : 8), a);
      chart.appendChild(svgEl("line", {
        x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1],
        stroke: COLOR.axis, "stroke-width": hr % 6 === 0 ? 1.5 : 1,
      }));
    }
    [["Midnight", 0], ["06:00", 360], ["Noon", 720], ["18:00", 1080]]
      .forEach(function (pair) {
        var a = clockAngle(pair[1]);
        var p = polar(cx, cy, rBed + 24, a);
        chart.appendChild(svgText(p[0], p[1] + 4, pair[0], { anchor: "middle" }));
      });

    // Mean spokes.
    function spoke(timeStr, radius, color) {
      var mins = parseInt(timeStr.slice(0, 2), 10) * 60
        + parseInt(timeStr.slice(3), 10);
      var p = polar(cx, cy, radius, clockAngle(mins));
      var line = svgEl("line", {
        x1: cx, y1: cy, x2: p[0], y2: p[1],
        stroke: color, "stroke-width": 2, "stroke-opacity": 0.55,
        "stroke-dasharray": "3 3",
      });
      markTitle(line, "Typical " + (radius === rBed ? "bedtime" : "wake") + ": " + timeStr);
      chart.appendChild(line);
    }
    spoke(section.bedtime.mean, rBed, COLOR.accent);
    spoke(section.wake.mean, rWake, COLOR.slate);

    // Night points: bedtime outer / wake inner; weekends hollow.
    section.points.forEach(function (p) {
      [[p.bed_minutes, rBed, COLOR.accent, "bedtime"],
       [p.wake_minutes, rWake, COLOR.slate, "wake"]].forEach(function (spec) {
        var pos = polar(cx, cy, spec[1], clockAngle(spec[0]));
        var attrs = {
          cx: pos[0], cy: pos[1], r: 4.5,
          fill: p.weekend ? "#fff" : spec[2],
          stroke: spec[2], "stroke-width": p.weekend ? 2 : 1,
          "fill-opacity": p.weekend ? 1 : 0.8,
        };
        var dot = svgEl("circle", attrs);
        var mins = spec[0];
        markTitle(dot, p.date + " " + spec[3] + " "
          + String(Math.floor(mins / 60)).padStart(2, "0") + ":"
          + String(mins % 60).padStart(2, "0")
          + (p.weekend ? " (weekend)" : ""));
        chart.appendChild(dot);
      });
    });

    // Center score.
    chart.appendChild(svgText(cx, cy - 4, Math.round(section.consistency_score) + "",
      { anchor: "middle", size: 30, fill: COLOR.ink, serif: true }));
    chart.appendChild(svgText(cx, cy + 16, "consistency / 100", { anchor: "middle", size: 12 }));

    body.appendChild(chart);
    body.appendChild(legend([
      { color: COLOR.accent, label: "Bedtime (outer)" },
      { color: COLOR.slate, label: "Wake (inner)" },
      { color: COLOR.slate, label: "Weekend night", hollow: true },
    ]));

    var jetlag = section.social_jetlag;
    if (jetlag.available) {
      var mins = jetlag.shift_minutes;
      body.appendChild(h("p", "fineprint",
        "Social jetlag: your sleep midpoint runs " + Math.abs(Math.round(mins))
        + " min " + (mins >= 0 ? "later" : "earlier")
        + " on weekends (" + jetlag.weekend_midpoint + " vs "
        + jetlag.weekday_midpoint + " on weekdays)."));
    } else {
      body.appendChild(h("p", "fineprint",
        "Social jetlag needs a few weekday and weekend nights to compare."));
    }
  }

  // ── Sweet spot bars ────────────────────────────────────────

  function roundedTopBar(x0, y0, w, hgt, r) {
    if (hgt <= 0) return null;
    r = Math.min(r, w / 2, hgt);
    var d = "M" + x0 + "," + (y0 + hgt)
      + " L" + x0 + "," + (y0 + r)
      + " Q" + x0 + "," + y0 + " " + (x0 + r) + "," + y0
      + " L" + (x0 + w - r) + "," + y0
      + " Q" + (x0 + w) + "," + y0 + " " + (x0 + w) + "," + (y0 + r)
      + " L" + (x0 + w) + "," + (y0 + hgt) + " Z";
    return svgEl("path", { d: d });
  }

  function renderSweetSpot(data) {
    var body = document.getElementById("sweet-body");
    var section = data.duration_quality_curve;
    if (!section.available) {
      emptyState(body, section, 5);
      return;
    }

    var W = 340, H = 250;
    var m = { l: 34, r: 8, t: 18, b: 52 };
    var y = linScale(0, 5, H - m.b, m.t);
    var slot = (W - m.l - m.r) / section.bins.length;
    var barW = Math.min(44, slot - 14);

    var chart = chartSvg(W, H,
      "Bar chart of average quality rating for each sleep-duration range; the highest-rated range is highlighted.");

    for (var t = 1; t <= 5; t++) {
      chart.appendChild(svgEl("line", {
        x1: m.l, x2: W - m.r, y1: y(t), y2: y(t),
        stroke: COLOR.grid, "stroke-width": 1,
      }));
      chart.appendChild(svgText(m.l - 6, y(t) + 4, String(t), { anchor: "end" }));
    }
    chart.appendChild(svgEl("line", {
      x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b,
      stroke: COLOR.axis, "stroke-width": 1,
    }));

    section.bins.forEach(function (bin, i) {
      var x0 = m.l + i * slot + (slot - barW) / 2;
      var isSpot = bin.label === section.sweet_spot;
      if (bin.mean_quality !== null) {
        var bar = roundedTopBar(x0, y(bin.mean_quality), barW,
          (H - m.b) - y(bin.mean_quality), 4);
        bar.setAttribute("fill", isSpot ? COLOR.accent : COLOR.slate);
        if (!isSpot) bar.setAttribute("fill-opacity", "0.55");
        markTitle(bar, bin.label + ": avg quality " + fmt1(bin.mean_quality)
          + "/5 over " + bin.count + " night" + (bin.count === 1 ? "" : "s"));
        chart.appendChild(bar);
        chart.appendChild(svgText(x0 + barW / 2, y(bin.mean_quality) - 6,
          fmt1(bin.mean_quality),
          { anchor: "middle", size: 12, fill: isSpot ? COLOR.accent : COLOR.muted,
            weight: isSpot ? 600 : 400 }));
      }
      chart.appendChild(svgText(x0 + barW / 2, H - m.b + 18, bin.label,
        { anchor: "middle", size: 12.5, fill: COLOR.ink }));
      chart.appendChild(svgText(x0 + barW / 2, H - m.b + 34,
        "n=" + bin.count, { anchor: "middle", size: 11.5 }));
    });

    body.appendChild(chart);
    if (section.sweet_spot) {
      body.appendChild(h("p", "fineprint",
        "Highest average quality: " + section.sweet_spot
        + " (only ranges with " + section.sweet_spot_min_count + "+ nights qualify)."));
    } else {
      body.appendChild(h("p", "fineprint",
        "No duration range has " + section.sweet_spot_min_count
        + "+ nights yet, so no sweet spot is called."));
    }
  }

  // ── Stage composition ──────────────────────────────────────

  function renderStages(data) {
    var body = document.getElementById("stages-body");
    var section = data.stage_composition;
    if (!section.available) {
      var wrap = h("div");
      wrap.appendChild(h("div", "empty-state",
        "No wearable stage data yet — import an Apple Health or Fitbit export "
        + "to unlock this (needs " + ((section && section.min_nights) || 5)
        + "+ nights with stages)."));
      body.appendChild(wrap);
      return;
    }

    var points = section.points;
    var W = Math.max(680, points.length * 16 + 60), H = 260;
    var m = { l: 44, r: 10, t: 12, b: 32 };
    var y = linScale(0, 100, H - m.b, m.t);
    var slot = (W - m.l - m.r) / points.length;
    var barW = Math.max(4, Math.min(12, slot - 3));

    var chart = chartSvg(W, H,
      "Stacked bar chart of nightly sleep-stage composition: deep, REM, light and awake percentages.");

    [0, 25, 50, 75, 100].forEach(function (t) {
      chart.appendChild(svgEl("line", {
        x1: m.l, x2: W - m.r, y1: y(t), y2: y(t),
        stroke: COLOR.grid, "stroke-width": 1,
      }));
      chart.appendChild(svgText(m.l - 8, y(t) + 4, t + "%", { anchor: "end" }));
    });

    points.forEach(function (p, i) {
      var x0 = m.l + i * slot + (slot - barW) / 2;
      var acc = 0;
      var tooltip = p.date + " — " + STAGE_SERIES.map(function (s) {
        return s.label + " " + Math.round(p[s.key + "_pct"]) + "%";
      }).join(" · ");
      STAGE_SERIES.forEach(function (s) {
        var value = p[s.key + "_pct"];
        var yTop = y(acc + value);
        var height = y(acc) - yTop;
        acc += value;
        if (height <= 0) return;
        // 2px surface gap between stacked segments.
        var rect = svgEl("rect", {
          x: x0, y: yTop + 1, width: barW, height: Math.max(0.5, height - 2),
          fill: s.color, rx: 1.5,
        });
        markTitle(rect, tooltip);
        chart.appendChild(rect);
      });
      var step = Math.max(1, Math.floor(points.length / 8));
      if (i % step === 0) {
        chart.appendChild(svgText(x0 + barW / 2, H - m.b + 20, shortDate(p.date),
          { anchor: "middle", size: 12 }));
      }
    });

    var scroll = h("div", "chart-scroll");
    scroll.appendChild(chart);
    body.appendChild(scroll);
    body.appendChild(legend(STAGE_SERIES.map(function (s) {
      return { color: s.color, label: s.label };
    })));

    if (section.reference) {
      var chips = h("div", "ref-chips");
      [["Deep", section.reference.deep], ["REM", section.reference.rem]]
        .forEach(function (pair) {
          var ref = pair[1];
          var chip = h("div", "ref-chip");
          var strong = h("strong", null, pair[0] + " " + fmt1(ref.your_pct) + "%");
          chip.appendChild(strong);
          chip.appendChild(document.createTextNode(
            " of time asleep — " + ref.status + " the ~"
            + Math.round(ref.reference_low) + "–"
            + Math.round(ref.reference_high) + "% typical adult range"));
          chips.appendChild(chip);
        });
      body.appendChild(chips);
      body.appendChild(h("p", "fineprint", section.reference.note));
    }
  }

  // ── Sleep debt ─────────────────────────────────────────────

  function renderDebt(data) {
    var body = document.getElementById("debt-body");
    var section = data.sleep_debt;
    if (!section.available) {
      emptyState(body, section, 7);
      return;
    }

    var series = section.series;
    var W = 680, H = 240;
    var m = { l: 46, r: 14, t: 14, b: 34 };
    var xs = series.map(function (p) { return dayNumber(p.date); });
    var maxDebt = Math.max(1, Math.max.apply(null, series.map(function (p) {
      return p.cumulative_debt;
    })));
    var x = linScale(xs[0], xs[xs.length - 1], m.l, W - m.r);
    var y = linScale(0, maxDebt * 1.15, H - m.b, m.t);

    var chart = chartSvg(W, H,
      "Area chart of cumulative sleep debt in hours over time, with exponential decay.");

    var tickStep = maxDebt > 8 ? 4 : maxDebt > 4 ? 2 : 1;
    for (var t = 0; t <= maxDebt * 1.15; t += tickStep) {
      chart.appendChild(svgEl("line", {
        x1: m.l, x2: W - m.r, y1: y(t), y2: y(t),
        stroke: COLOR.grid, "stroke-width": 1,
      }));
      chart.appendChild(svgText(m.l - 8, y(t) + 4, t + "h", { anchor: "end" }));
    }
    var stepX = Math.max(1, Math.floor(series.length / 5));
    for (var i = 0; i < series.length; i += stepX) {
      chart.appendChild(svgText(x(xs[i]), H - m.b + 20, shortDate(series[i].date),
        { anchor: "middle" }));
    }

    var linePoints = series.map(function (p) {
      return x(dayNumber(p.date)) + "," + y(p.cumulative_debt);
    });
    chart.appendChild(svgEl("polygon", {
      points: linePoints.concat([
        x(xs[xs.length - 1]) + "," + y(0), x(xs[0]) + "," + y(0),
      ]).join(" "),
      fill: COLOR.accent, "fill-opacity": 0.12, stroke: "none",
    }));
    chart.appendChild(svgEl("polyline", {
      points: linePoints.join(" "),
      fill: "none", stroke: COLOR.accent, "stroke-width": 2,
      "stroke-linejoin": "round",
    }));
    series.forEach(function (p) {
      var dot = svgEl("circle", {
        cx: x(dayNumber(p.date)), cy: y(p.cumulative_debt), r: 2.4,
        fill: COLOR.accent, stroke: "#fff", "stroke-width": 1,
      });
      markTitle(dot, p.date + " — debt " + fmt1(p.cumulative_debt) + "h (night was "
        + (p.nightly_deficit >= 0 ? fmt1(p.nightly_deficit) + "h short" :
          fmt1(-p.nightly_deficit) + "h over goal") + ")");
      chart.appendChild(dot);
    });
    chart.appendChild(svgEl("line", {
      x1: m.l, x2: W - m.r, y1: y(0), y2: y(0),
      stroke: COLOR.axis, "stroke-width": 1,
    }));

    var scroll = h("div", "chart-scroll");
    scroll.appendChild(chart);
    body.appendChild(scroll);

    var summary = "Current debt: " + fmt1(section.current_debt_hours)
      + "h against a " + fmt1(section.need_hours) + "h/night goal. "
      + section.recovery.message;
    body.appendChild(h("p", "fineprint", summary));
  }

  // ── Quality drivers ────────────────────────────────────────

  function driverBar(r) {
    var W = 150, H = 18, mid = W / 2;
    var chartNode = svgEl("svg", {
      viewBox: "0 0 " + W + " " + H, width: W, height: H,
      role: "img",
      "aria-label": "Correlation " + fmt1(r),
    });
    chartNode.appendChild(svgEl("line", {
      x1: mid, x2: mid, y1: 1, y2: H - 1, stroke: COLOR.axis, "stroke-width": 1,
    }));
    var span = Math.max(1.5, Math.abs(r) * (mid - 4));
    chartNode.appendChild(svgEl("rect", {
      x: r >= 0 ? mid : mid - span, y: 4,
      width: span, height: H - 8, rx: 3,
      fill: r >= 0 ? COLOR.accent : COLOR.slate,
    }));
    return chartNode;
  }

  function renderDrivers(data) {
    var body = document.getElementById("drivers-body");
    var section = data.quality_drivers;
    if (!section.available) {
      emptyState(body, section, 5);
      return;
    }

    var table = h("table", "drivers-table");
    var shown = 0;
    section.drivers.forEach(function (driver) {
      if (!driver.available) return;
      shown++;
      var row = h("tr");
      var labelCell = h("td", "driver-label");
      labelCell.appendChild(document.createTextNode(driver.label));
      if (driver.unreliable) {
        labelCell.appendChild(h("span", "badge", "low data (n=" + driver.n + ")"));
      }
      row.appendChild(labelCell);

      var barCell = h("td");
      barCell.appendChild(driverBar(driver.pearson_r));
      row.appendChild(barCell);

      var metaCell = h("td", "driver-meta");
      metaCell.appendChild(document.createTextNode(
        "r=" + fmt1(driver.pearson_r) + " · ρ=" + fmt1(driver.spearman_rho)
        + " · " + driver.strength + " " + driver.direction));
      row.appendChild(metaCell);
      table.appendChild(row);
    });

    if (!shown) {
      emptyState(body, section, 5);
      return;
    }
    body.appendChild(table);
    body.appendChild(legend([
      { color: COLOR.accent, label: "Higher → better quality" },
      { color: COLOR.slate, label: "Higher → worse quality" },
    ]));
    body.appendChild(h("p", "fineprint",
      "Correlations under 10 nights are flagged — treat them as hints, not findings."));
  }

  // ── Anomalies ──────────────────────────────────────────────

  function renderAnomalies(data) {
    var body = document.getElementById("anomalies-body");
    var section = data.anomalies;
    if (!section.available) {
      emptyState(body, section, 10);
      return;
    }
    if (!section.outliers.length) {
      body.appendChild(h("div", "empty-state",
        "No unusual nights detected across " + section.nights_scored
        + " scored nights — your sleep stayed within its own pattern."));
      return;
    }

    var list = h("ul", "anomaly-list");
    section.outliers.slice(-8).reverse().forEach(function (o) {
      var item = h("li");
      item.appendChild(h("span", "anomaly-date", o.date));
      var sentence;
      if (o.metric === "duration") {
        sentence = "Unusually " + o.direction + " night: " + fmt1(o.value)
          + "h vs your ~" + fmt1(o.baseline_mean) + "h baseline (z="
          + fmt1(o.z) + ").";
      } else {
        sentence = "Sleep timing shifted " + o.direction + ": midpoint "
          + o.value + " vs usual ~" + o.baseline_mean + " (z=" + fmt1(o.z) + ").";
      }
      item.appendChild(h("span", null, sentence));
      list.appendChild(item);
    });
    body.appendChild(list);
    body.appendChild(h("p", "fineprint",
      "Showing the most recent " + Math.min(8, section.outliers.length)
      + " of " + section.outliers.length + " flagged night"
      + (section.outliers.length === 1 ? "" : "s") + "."));
  }

  // ── Claude weekly summary ──────────────────────────────────

  function hideAiSummary() {
    var card = document.getElementById("card-ai-summary");
    if (card) card.style.display = "none";
  }

  function renderAiSummary() {
    var body = document.getElementById("ai-summary-body");
    if (!body) return;
    fetch("/api/summary", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        if (!data.available || !data.summary) {
          // No key or an API hiccup — hide the card entirely, no error noise.
          hideAiSummary();
          return;
        }
        body.textContent = "";
        String(data.summary).split(/\n+/).forEach(function (paragraph) {
          paragraph = paragraph.trim();
          if (paragraph) body.appendChild(h("p", "ai-summary-text", paragraph));
        });
      })
      .catch(hideAiSummary);
  }

  // ── Boot ───────────────────────────────────────────────────

  function renderAll(data) {
    renderHeadline(data);
    renderStandout(data);
    renderTrend(data);
    renderClock(data);
    renderSweetSpot(data);
    renderStages(data);
    renderDebt(data);
    renderDrivers(data);
    renderAnomalies(data);
  }

  function showLoadError() {
    var body = document.getElementById("standout-body");
    body.appendChild(h("div", "empty-state",
      "Couldn't load analytics. Refresh to try again."));
  }

  fetch("/api/analytics", { headers: { Accept: "application/json" } })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    })
    .then(function (data) {
      renderAll(data);
      renderAiSummary();
    })
    .catch(function () {
      showLoadError();
      hideAiSummary();
    });
})();
