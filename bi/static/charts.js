/* ============================================================================
   Transfer & Conversion Intelligence Platform :: chart primitives.

   Hand-built SVG, no charting library. That is a deliberate trade: the whole
   dependency set for this dashboard is a static file server, so there is no
   build step, no bundle, and nothing to keep on a version treadmill for a demo
   that has to still run in a year.

   The specs below are fixed and shared by every chart, because consistency is
   what makes a set of panels read as one system:

     bars     <= 24px thick, 4px rounded data-end, square at the baseline,
              growing from a single baseline, >= 2px of surface between neighbours
     lines    2px, round join and cap
     markers  >= 8px diameter, 2px ring in the surface colour so they stay
              legible where they overlap
     grid     hairline, solid, one step off the surface -- never dashed, because
              a dashed rule reads as "threshold" when it is only a grid
     labels   selective: the extreme, the endpoint, or the one series the panel
              is about. A number on every mark goes unread.

   Colour is never written here as hex. Every mark reads a CSS custom property,
   so a theme swap is a token change and no chart can hold a private palette.
   ========================================================================= */
(function (global) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const BAR_MAX = 24;     // mark spec: cap thickness, let the band keep its air
  const BAR_R = 4;        // rounded data-end
  const GAP = 2;          // surface gap between touching marks

  function cssVar(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }

  function el(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) {
      n.setAttribute(k, attrs[k]);
    }
    if (parent) parent.appendChild(n);
    return n;
  }

  /* Text is inserted as a text node, never as markup: category and series names
     arrive from the API and are untrusted input. */
  function text(parent, str, attrs) {
    const t = el("text", attrs, parent);
    t.appendChild(document.createTextNode(str));
    return t;
  }

  /* ---- scales & ticks ---------------------------------------------------- */
  function linear(d0, d1, r0, r1) {
    const span = (d1 - d0) || 1;
    const f = v => r0 + (v - d0) / span * (r1 - r0);
    f.invert = p => d0 + (p - r0) / (r1 - r0) * span;
    return f;
  }

  /* Clean tick values (0 / 50 / 100), never raw data extents. */
  function ticks(min, max, count) {
    if (min === max) { min = Math.min(0, min); max = max || 1; }
    const raw = (max - min) / (count || 5);
    const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
    const norm = raw / mag;
    const step = (norm >= 7.5 ? 10 : norm >= 3.5 ? 5 : norm >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) {
      out.push(Math.round(v * 1e6) / 1e6);
    }
    return out;
  }

  const fmt = n => n === null || n === undefined || isNaN(n) ? "—"
    : Math.abs(n) >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 0 })
      : String(Math.round(n * 10) / 10);

  /* ---- mark geometry ----------------------------------------------------- */
  /* Rounded on the data-end only; square where it meets the baseline. */
  function barPath(x, y, w, h, side) {
    const r = Math.max(0, Math.min(BAR_R, side === "top" ? h : w, side === "top" ? w / 2 : h / 2));
    if (h <= 0 || w <= 0) return "";
    if (side === "top") {
      return `M${x},${y + h}V${y + r}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}V${y + h}Z`;
    }
    if (side === "right") {
      return `M${x},${y}h${w - r}a${r},${r} 0 0 1 ${r},${r}v${h - 2 * r}a${r},${r} 0 0 1 ${-r},${r}H${x}Z`;
    }
    return `M${x + w},${y}H${x + r}a${r},${r} 0 0 0 ${-r},${r}v${h - 2 * r}a${r},${r} 0 0 0 ${r},${r}h${w - r}Z`;
  }

  /* ---- tooltip ----------------------------------------------------------- */
  const tip = () => document.getElementById("tip");

  function showTip(evt, category, rows) {
    const t = tip();
    t.textContent = "";
    if (category) {
      const c = document.createElement("div");
      c.className = "t-cat";
      c.textContent = category;             // untrusted: text node only
      t.appendChild(c);
    }
    rows.forEach(r => {
      const row = document.createElement("div");
      row.className = "t-row";
      if (r.color) {
        const k = document.createElement("span");
        k.className = "t-key";
        k.style.background = r.color;
        row.appendChild(k);
      }
      const v = document.createElement("span");
      v.className = "t-val";
      v.textContent = r.value;              // value leads
      row.appendChild(v);
      if (r.name) {
        const n = document.createElement("span");
        n.className = "t-name";
        n.textContent = r.name;             // label follows
        row.appendChild(n);
      }
      t.appendChild(row);
    });
    t.classList.add("on");
    moveTip(evt);
  }

  function moveTip(evt) {
    const t = tip(), pad = 14;
    const w = t.offsetWidth, h = t.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
    t.style.left = Math.max(8, x) + "px";
    t.style.top = Math.max(8, y) + "px";
  }

  function hideTip() { tip().classList.remove("on"); }

  /* Hit targets are bigger than the mark and answer keyboard focus too, so a
     value is never reachable by precise pointing alone. */
  function hit(g, box, category, rows) {
    const h = el("rect", {
      x: box.x, y: box.y, width: Math.max(box.width, 1),
      height: Math.max(box.height, 1), class: "hit", tabindex: "0",
      role: "img", "aria-label": category + ": " + rows.map(r => r.value + " " + (r.name || "")).join(", ")
    }, g);
    h.addEventListener("pointerenter", e => showTip(e, category, rows));
    h.addEventListener("pointermove", moveTip);
    h.addEventListener("pointerleave", hideTip);
    h.addEventListener("focus", e => {
      const r = h.getBoundingClientRect();
      showTip({ clientX: r.left + r.width / 2, clientY: r.top }, category, rows);
    });
    h.addEventListener("blur", hideTip);
    return h;
  }

  /* ---- frame ------------------------------------------------------------- */
  /* Height always includes the axis band, so a card never grows an inner
     scrollbar just to show its own tick labels. */
  function frame(host, opts) {
    host.textContent = "";
    const m = Object.assign({ top: 14, right: 16, bottom: 30, left: 46 }, opts.margin);
    const w = Math.max(host.clientWidth || 560, 260);
    const h = (opts.plot || 210) + m.top + m.bottom;
    const svg = el("svg", {
      class: "chart", width: w, height: h, viewBox: `0 0 ${w} ${h}`,
      role: "img", "aria-label": opts.label || ""
    }, host);
    return { svg, m, w, h, iw: w - m.left - m.right, ih: h - m.top - m.bottom };
  }

  function yAxis(f, y, tickVals, unitFmt) {
    tickVals.forEach(v => {
      const py = Math.round(y(v)) + .5;
      el("line", { x1: f.m.left, x2: f.w - f.m.right, y1: py, y2: py, class: "gridline" }, f.svg);
      text(f.svg, (unitFmt || fmt)(v), {
        x: f.m.left - 9, y: py + 4, "text-anchor": "end", class: "tick"
      });
    });
  }

  /* ======================================================================== */
  /* Columns -- one categorical series, or an ordinal ramp across the band.    */
  /* ======================================================================== */
  function columns(host, o) {
    const rows = o.rows || [];
    if (!rows.length) { host.innerHTML = '<p class="empty">No data in this scope.</p>'; return; }
    const f = frame(host, o);
    const vals = rows.map(o.value);
    const max = Math.max(0, ...vals), min = Math.min(0, ...vals);
    const tv = ticks(min, max, 4);
    const y = linear(Math.min(min, tv[0]), Math.max(max, tv[tv.length - 1]),
      f.m.top + f.ih, f.m.top);
    yAxis(f, y, tv, o.tickFmt);

    const band = f.iw / rows.length;
    const bw = Math.min(BAR_MAX, Math.max(6, band - GAP * 2));
    const base = y(0);
    const surface = cssVar("--surface");

    rows.forEach((r, i) => {
      const v = o.value(r) || 0;
      const cx = f.m.left + band * i + band / 2;
      const top = Math.min(y(v), base), hgt = Math.abs(base - y(v));
      const colour = o.color ? o.color(r, i) : cssVar("--series-1");
      el("path", {
        d: barPath(cx - bw / 2, top, bw, hgt, "top"),
        fill: colour, class: "mark"
      }, f.svg);
      // Selective labelling: the panel's own extreme, not every column.
      if (o.labelAll || (o.labelIndex !== undefined && o.labelIndex === i)) {
        text(f.svg, (o.tickFmt || fmt)(v), {
          x: cx, y: top - 7, "text-anchor": "middle", class: "val"
        });
      }
      text(f.svg, o.label(r), {
        x: cx, y: f.m.top + f.ih + 18, "text-anchor": "middle", class: "cat"
      });
      hit(f.svg, { x: cx - band / 2, y: f.m.top, width: band, height: f.ih },
        o.label(r), o.tip ? o.tip(r) : [{ value: fmt(v), name: o.unit || "", color: colour }]);
    });

    el("line", {
      x1: f.m.left, x2: f.w - f.m.right, y1: base + .5, y2: base + .5, class: "axisline"
    }, f.svg);

    // A second series on the SAME unit and the same axis -- never a second scale.
    if (o.line) {
      const pts = rows.map((r, i) => [f.m.left + band * i + band / 2, y(o.line(r) || 0)]);
      el("path", {
        d: pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join(""),
        fill: "none", stroke: cssVar("--series-2"), "stroke-width": 2,
        "stroke-linejoin": "round", "stroke-linecap": "round"
      }, f.svg);
      pts.forEach(p => {
        el("circle", { cx: p[0], cy: p[1], r: 4.5, fill: cssVar("--series-2"),
          stroke: surface, "stroke-width": 2 }, f.svg);
      });
    }
  }

  /* ======================================================================== */
  /* Horizontal bars -- long category names, with optional emphasis.          */
  /* ======================================================================== */
  function barsH(host, o) {
    const rows = o.rows || [];
    if (!rows.length) { host.innerHTML = '<p class="empty">No data in this scope.</p>'; return; }
    const m = { top: 8, right: 54, bottom: 26, left: o.labelWidth || 150 };
    const f = frame(host, { plot: rows.length * 34, margin: m, label: o.label_ });
    const max = Math.max(0, ...rows.map(o.value));
    const tv = ticks(0, max, 4);
    // Domain covers the data even when the last clean tick falls short of it,
    // otherwise the longest bar renders past the plot edge.
    const x = linear(0, Math.max(max, tv[tv.length - 1]), f.m.left, f.w - f.m.right);

    tv.forEach(v => {
      const px = Math.round(x(v)) + .5;
      el("line", { x1: px, x2: px, y1: f.m.top, y2: f.m.top + f.ih, class: "gridline" }, f.svg);
      text(f.svg, fmt(v), { x: px, y: f.m.top + f.ih + 17, "text-anchor": "middle", class: "tick" });
    });

    const band = f.ih / rows.length;
    const bh = Math.min(BAR_MAX, Math.max(6, band - GAP * 3));
    rows.forEach((r, i) => {
      const v = o.value(r) || 0;
      const cy = f.m.top + band * i + band / 2;
      const colour = o.color ? o.color(r, i) : cssVar("--series-1");
      el("path", {
        d: barPath(f.m.left, cy - bh / 2, Math.max(x(v) - f.m.left, 1), bh, "right"),
        fill: colour, class: "mark"
      }, f.svg);
      text(f.svg, o.label(r), {
        x: f.m.left - 10, y: cy + 4, "text-anchor": "end", class: "cat"
      });
      // Bars label at the tip -- outside the mark, so nothing is ever clipped.
      text(f.svg, (o.tickFmt || fmt)(v), { x: x(v) + 8, y: cy + 4, class: "val" });
      hit(f.svg, { x: f.m.left, y: cy - band / 2, width: f.iw, height: band },
        o.label(r), o.tip ? o.tip(r) : [{ value: fmt(v), name: o.unit || "", color: colour }]);
    });
    el("line", { x1: f.m.left + .5, x2: f.m.left + .5, y1: f.m.top,
      y2: f.m.top + f.ih, class: "axisline" }, f.svg);
  }

  /* ======================================================================== */
  /* Diverging bars -- polarity around a baseline (drift ahead of / behind).  */
  /* ======================================================================== */
  function diverging(host, o) {
    const rows = o.rows || [];
    if (!rows.length) { host.innerHTML = '<p class="empty">No data in this scope.</p>'; return; }
    const m = { top: 8, right: 52, bottom: 26, left: o.labelWidth || 150 };
    const f = frame(host, { plot: rows.length * 34, margin: m });
    const vals = rows.map(o.value);
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const tv = ticks(lo, hi, 4);
    const x = linear(Math.min(lo, tv[0]), Math.max(hi, tv[tv.length - 1]),
      f.m.left, f.w - f.m.right);
    const zero = x(0);

    tv.forEach(v => {
      const px = Math.round(x(v)) + .5;
      el("line", { x1: px, x2: px, y1: f.m.top, y2: f.m.top + f.ih, class: "gridline" }, f.svg);
      text(f.svg, fmt(v), { x: px, y: f.m.top + f.ih + 17, "text-anchor": "middle", class: "tick" });
    });

    const band = f.ih / rows.length;
    const bh = Math.min(BAR_MAX, Math.max(6, band - GAP * 3));
    rows.forEach((r, i) => {
      const v = o.value(r) || 0;
      const cy = f.m.top + band * i + band / 2;
      const pos = v >= 0;
      const colour = pos ? cssVar("--div-pos") : cssVar("--div-neg");
      const w = Math.max(Math.abs(x(v) - zero), 1);
      el("path", {
        d: barPath(pos ? zero : zero - w, cy - bh / 2, w, bh, pos ? "right" : "left"),
        fill: colour, class: "mark"
      }, f.svg);
      text(f.svg, o.label(r), { x: f.m.left - 10, y: cy + 4, "text-anchor": "end", class: "cat" });
      text(f.svg, (v > 0 ? "+" : "") + fmt(v), {
        x: pos ? zero + w + 8 : zero - w - 8, y: cy + 4,
        "text-anchor": pos ? "start" : "end", class: "val"
      });
      hit(f.svg, { x: f.m.left, y: cy - band / 2, width: f.iw, height: band },
        o.label(r), o.tip ? o.tip(r) : [{ value: (v > 0 ? "+" : "") + fmt(v),
          name: o.unit || "", color: colour }]);
    });
    // The frozen baseline itself.
    el("line", { x1: zero + .5, x2: zero + .5, y1: f.m.top, y2: f.m.top + f.ih,
      class: "axisline" }, f.svg);
  }

  /* ======================================================================== */
  /* Box plot -- distribution, because the spread is the point, not the mean. */
  /* ======================================================================== */
  function boxes(host, o) {
    const rows = o.rows || [];
    if (!rows.length) { host.innerHTML = '<p class="empty">No data in this scope.</p>'; return; }
    const f = frame(host, { plot: o.plot || 250, margin: { top: 14, right: 16, bottom: 34, left: 48 } });
    const hi = Math.max(...rows.map(r => r.p90 ?? r.p75 ?? 0));
    const lo = Math.min(...rows.map(r => r.min_days ?? r.p25 ?? 0));
    const tv = ticks(Math.min(0, lo), hi, 5);
    const y = linear(Math.min(lo, tv[0]), Math.max(hi, tv[tv.length - 1]),
      f.m.top + f.ih, f.m.top);
    yAxis(f, y, tv);

    const band = f.iw / rows.length;
    const bw = Math.min(38, Math.max(10, band - GAP * 6));
    const colour = cssVar("--series-1");
    const surface = cssVar("--surface");

    rows.forEach((r, i) => {
      const cx = f.m.left + band * i + band / 2;
      const g = el("g", { class: "mark" }, f.svg);
      // whisker: min to P90 -- the upper fence is a percentile, because the
      // long tail is the thing worth seeing, not a lone outlier.
      el("line", { x1: cx, x2: cx, y1: y(r.min_days), y2: y(r.p90),
        stroke: colour, "stroke-width": 2, "stroke-linecap": "round", opacity: .45 }, g);
      el("rect", { x: cx - bw / 2, y: y(r.p75), width: bw,
        height: Math.max(y(r.p25) - y(r.p75), 2), rx: 3, fill: colour, opacity: .28 }, g);
      el("line", { x1: cx - bw / 2, x2: cx + bw / 2, y1: y(r.median), y2: y(r.median),
        stroke: colour, "stroke-width": 2.5, "stroke-linecap": "round" }, g);
      text(f.svg, o.label(r), { x: cx, y: f.m.top + f.ih + 18,
        "text-anchor": "middle", class: "cat" });
      hit(f.svg, { x: cx - band / 2, y: f.m.top, width: band, height: f.ih },
        o.label(r), [
          { value: fmt(r.median), name: "median", color: colour },
          { value: fmt(r.p25) + " – " + fmt(r.p75), name: "P25–P75" },
          { value: fmt(r.p90), name: "P90" },
          { value: fmt(r.n), name: "projects" }
        ]);
    });
    el("line", { x1: f.m.left, x2: f.w - f.m.right, y1: f.m.top + f.ih + .5,
      y2: f.m.top + f.ih + .5, class: "axisline" }, f.svg);
  }

  /* ======================================================================== */
  /* Part-to-whole -- a stacked bar, not a pie: these values sit close.       */
  /* ======================================================================== */
  function stack(host, o) {
    const segs = (o.rows || []).filter(r => o.value(r) > 0);
    host.textContent = "";
    if (!segs.length) { host.innerHTML = '<p class="empty">No open projects in this scope.</p>'; return; }
    const total = segs.reduce((a, r) => a + o.value(r), 0);
    const w = Math.max(host.clientWidth || 480, 240), h = 44;
    const svg = el("svg", { class: "chart", width: w, height: h,
      viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": o.label_ || "" }, host);
    const surface = cssVar("--surface");
    let x = 0;
    segs.forEach(r => {
      const v = o.value(r);
      const sw = Math.max((v / total) * w - GAP, 2);   // 2px surface gap, not a stroke
      el("rect", { x, y: 8, width: sw, height: 22, rx: 4,
        fill: o.color(r), class: "mark" }, svg);
      if (sw > 34) {
        text(svg, String(v), { x: x + sw / 2, y: 24, "text-anchor": "middle",
          fill: "#fff", "font-weight": "620", "font-size": "12" });
      }
      hit(svg, { x, y: 0, width: sw + GAP, height: h }, o.label(r),
        [{ value: v + " projects", name: Math.round(v / total * 100) + "% of open",
          color: o.color(r) }]);
      x += sw + GAP;
    });
  }

  /* ======================================================================== */
  /* Lines over time -- every preserved replan against the frozen baseline.   */
  /* ======================================================================== */
  function lines(host, o) {
    const series = (o.series || []).filter(s => s.points.length);
    if (!series.length) { host.innerHTML = '<p class="empty">No revision history.</p>'; return; }
    const f = frame(host, { plot: o.plot || 240, margin: { top: 16, right: 18, bottom: 34, left: 62 } });
    const all = series.flatMap(s => s.points);
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (o.rule !== undefined && o.rule !== null) { lo = Math.min(lo, o.rule); hi = Math.max(hi, o.rule); }
    const pad = (hi - lo) * .12 || 86400000;
    const x = linear(Math.min(...xs), Math.max(...xs), f.m.left, f.w - f.m.right);
    const y = linear(lo - pad, hi + pad, f.m.top + f.ih, f.m.top);

    // Dates on both axes: tick labels are dates, so they get date formatting.
    const yt = ticks(lo - pad, hi + pad, 4);
    yt.forEach(v => {
      const py = Math.round(y(v)) + .5;
      el("line", { x1: f.m.left, x2: f.w - f.m.right, y1: py, y2: py, class: "gridline" }, f.svg);
      text(f.svg, o.fmtY(v), { x: f.m.left - 9, y: py + 4, "text-anchor": "end", class: "tick" });
    });

    // The immutable baseline, drawn as an explicit threshold rule. Dashed here
    // is meaningful -- it is a commitment line, not a gridline.
    if (o.rule !== undefined && o.rule !== null) {
      const ry = Math.round(y(o.rule)) + .5;
      el("line", { x1: f.m.left, x2: f.w - f.m.right, y1: ry, y2: ry,
        stroke: cssVar("--status-crit"), "stroke-width": 1.5, "stroke-dasharray": "5 4" }, f.svg);
      text(f.svg, "frozen baseline", { x: f.w - f.m.right, y: ry - 7,
        "text-anchor": "end", class: "cat", fill: cssVar("--status-crit") });
    }

    const surface = cssVar("--surface");
    series.forEach(s => {
      const colour = cssVar(s.token);
      el("path", {
        d: s.points.map((p, i) => (i ? "L" : "M") + x(p[0]) + "," + y(p[1])).join(""),
        fill: "none", stroke: colour, "stroke-width": 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
        "stroke-dasharray": s.dashed ? "5 4" : null
      }, f.svg);
      s.points.forEach(p => {
        el("circle", { cx: x(p[0]), cy: y(p[1]), r: 4.5, fill: colour,
          stroke: surface, "stroke-width": 2 }, f.svg);
      });
    });

    // One tooltip per revision, listing every series at that x.
    series[0].points.forEach((p, i) => {
      const px = x(p[0]);
      const bw = f.iw / series[0].points.length;
      hit(f.svg, { x: px - bw / 2, y: f.m.top, width: bw, height: f.ih },
        o.fmtX(p[0]), series.map(s => ({
          value: s.points[i] ? o.fmtY(s.points[i][1]) : "—",
          name: s.name, color: cssVar(s.token)
        })));
    });

    const xt = [series[0].points[0][0], series[0].points[series[0].points.length - 1][0]];
    xt.forEach((v, i) => text(f.svg, o.fmtX(v), {
      x: x(v), y: f.m.top + f.ih + 19,
      "text-anchor": i ? "end" : "start", class: "tick"
    }));
    el("line", { x1: f.m.left, x2: f.w - f.m.right, y1: f.m.top + f.ih + .5,
      y2: f.m.top + f.ih + .5, class: "axisline" }, f.svg);
  }

  global.Charts = { columns, barsH, diverging, boxes, stack, lines,
    cssVar, fmt, hideTip };
})(window);
