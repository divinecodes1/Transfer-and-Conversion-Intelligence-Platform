(function () {
  "use strict";

  const C = window.Charts;
  const state = {
    view: "overview",
    analyticsTab: "cycle",
    operationsTab: "import",
    identity: null,
    boot: null,
    project: null,
    projectSearch: "",
    projectSort: "schedule_deviation_days",
    filters: { fiscal_year: null, transfer_type: null, portfolio: null,
      site: null, complexity: null }
  };

  const HEALTH = {
    ON_TRACK: { label: "On track", tone: "good" },
    AT_RISK: { label: "At risk", tone: "warn" },
    LATE: { label: "Late", tone: "crit" },
    UNKNOWN: { label: "Unknown", tone: "none" }
  };
  const DEMO_USERS = ["admin.demo", "analyst.demo", "manager.auto", "manager.power", "viewer.demo"];
  const fmt = C.fmt;
  const days = value => value === null || value === undefined ? "-" : fmt(value) + " d";
  const signedDays = value => value === null || value === undefined ? "-" : (value > 0 ? "+" : "") + fmt(value) + " d";
  const pct = value => value === null || value === undefined ? "-" : (value * 100).toFixed(1) + "%";

  function h(tag, attrs, kids) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined) node.setAttribute(key, value);
    });
    (kids || []).forEach(child => child && node.appendChild(child));
    return node;
  }

  async function request(path, options) {
    const opts = options || {};
    const headers = { ...(opts.headers || {}) };
    if (state.identity) headers["X-Demo-User"] = state.identity;
    if (opts.body) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { ...opts, headers });
    if (!response.ok) throw new Error(path + " returned " + response.status);
    return response.json();
  }

  function get(path, params) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "") query.set(key, value);
    });
    return request(path + (query.toString() ? "?" + query : ""));
  }

  function post(path, body) {
    return request(path, { method: "POST", body: JSON.stringify(body) });
  }

  function currentFilters() {
    return { ...state.filters };
  }

  function projectFilters() {
    return { portfolio: state.filters.portfolio,
      transfer_type: state.filters.transfer_type, site: state.filters.site,
      complexity: state.filters.complexity };
  }

  function pageHead(title, subtitle, actions) {
    return h("div", { class: "page-head" }, [
      h("div", {}, [h("h1", { text: title }), h("p", { text: subtitle })]),
      actions ? h("div", { class: "page-actions" }, actions) : null
    ]);
  }

  function card(title, subtitle, span, action) {
    const body = h("div", { class: "cardbody" });
    const header = h("header", {}, [
      h("div", {}, [h("h2", { text: title }), subtitle ? h("p", { class: "sub", text: subtitle }) : null]),
      action || null
    ]);
    return { body, el: h("section", { class: "card " + (span || "col-6") }, [header, body]) };
  }

  function statusBadge(health) {
    const item = HEALTH[health] || HEALTH.UNKNOWN;
    return h("span", { class: "status-badge " + item.tone }, [
      h("span", { class: "dot " + item.tone }), h("span", { text: item.label })
    ]);
  }

  function riskBadge(risk) {
    if (!risk) return h("span", { class: "risk-badge none", text: "Not scored" });
    return h("span", { class: "risk-badge " + risk.risk_band, text: risk.risk_band + " " + risk.risk_score });
  }

  function metricTile(label, value, detail, tone) {
    return h("div", { class: "metric-tile " + (tone || "") }, [
      h("span", { class: "metric-label", text: label }),
      h("strong", { text: String(value) }),
      detail ? h("small", { text: detail }) : null
    ]);
  }

  function provenance(env) {
    const metrics = env.metrics || [];
    const applied = env.filters_applied || {};
    const scope = Object.entries(applied).map(([key, value]) => key.split(".").pop().replace(/_/g, " ") + " = " + value).join(" / ") || "whole visible portfolio";
    const summary = [
      metrics.map(metric => metric.business_name + " v" + metric.version).join(", "),
      scope,
      "data as of " + (env.data_as_of || "-")
    ].filter(Boolean).join(" / ");
    const details = h("dl");
    metrics.forEach(metric => {
      details.appendChild(h("dt", { text: metric.business_name }));
      details.appendChild(h("dd", { text:
        metric.definition +
        " Population: " + metric.population + "." +
        " Exclusions: " + (metric.exclusions || "None") + "." +
        " Owner: " + metric.owner + "."
      }));
    });
    return h("details", { class: "provenance" }, [h("summary", { text: summary }), details]);
  }

  function dataTable(columns, rows, className) {
    return h("div", { class: "tablewrap " + (className || "") }, [
      h("table", {}, [
        h("thead", {}, [h("tr", {}, columns.map(column => h("th", { text: column.label })))]),
        h("tbody", {}, rows.map(row => h("tr", {}, columns.map(column => {
          const value = column.render ? column.render(row) : String(row[column.key] ?? "-");
          return h("td", column.class ? { class: column.class } : {}, [value instanceof Node ? value : document.createTextNode(value)]);
        }))))
      ])
    ]);
  }

  function segmented(items, active, onChange) {
    return h("div", { class: "segmented", role: "tablist" }, items.map(item => {
      const button = h("button", { type: "button", text: item.label, role: "tab" });
      button.setAttribute("aria-selected", String(item.value === active));
      button.onclick = () => onChange(item.value);
      return button;
    }));
  }

  function empty(text) {
    return h("div", { class: "empty-state" }, [h("strong", { text: "No data in this scope" }), h("p", { text })]);
  }

  function legend(items) {
    return h("div", { class: "legend" }, items.map(item => h("span", { class: "item" }, [
      h("span", { class: item.line ? "linekey" : "swatch", style: "background:" + item.color }),
      h("span", { text: item.label })
    ])));
  }

  async function overview(root) {
    const filters = currentFilters();
    const [projects, kpis, forecast, insight, risks] = await Promise.all([
      get("/api/register", { ...filters, limit: 1000 }),
      get("/api/kpis", filters),
      get("/api/accuracy", projectFilters()),
      post("/api/insight", { filters }),
      post("/api/project-risks", { filters: projectFilters() })
    ]);
    const active = (projects.projects || []).filter(project => ["ACTIVE", "PLANNED"].includes(project.status));
    const counts = active.reduce((out, project) => ({ ...out, [project.health]: (out[project.health] || 0) + 1 }), {});
    const completed = (kpis.kpis || {}).throughput || 0;
    const onTime = (kpis.kpis || {}).on_time_rate;
    const riskById = new Map(risks.risks.map(risk => [risk.project_id, risk]));
    const attention = [...active].sort((a, b) => (b.schedule_deviation_days || 0) - (a.schedule_deviation_days || 0)).slice(0, 6);

    root.appendChild(pageHead("Transfer Project Overview", "Performance, predictability, and the transfers that need attention."));
    const grid = h("div", { class: "grid" });
    root.appendChild(grid);

    const modelInsight = insight.mode === "model";
    const briefing = card(modelInsight ? "AI portfolio briefing" : "Governed portfolio briefing",
      modelInsight ? "Model narrative grounded only in governed metric responses." : "Deterministic decision brief available without a model provider.", "col-8",
      h("span", { class: "ai-label", text: modelInsight ? "AI" : "RULES" }));
    briefing.body.appendChild(h("h3", { class: "insight-headline", text: insight.headline }));
    briefing.body.appendChild(h("p", { class: "insight-copy", text: insight.content }));
    briefing.body.appendChild(h("div", { class: "highlight-row" }, insight.highlights.map(item =>
      h("span", { class: "highlight " + item.tone }, [h("small", { text: item.label }), h("strong", { text: String(item.value) })]))));
    briefing.body.appendChild(h("p", { class: "ai-provenance", text: insight.model + " / " + insight.provenance.join(" / ") }));
    grid.appendChild(briefing.el);

    const headline = card("On-time completion", "Completed on or before the frozen baseline.", "col-4");
    headline.body.appendChild(h("div", { class: "hero-value" }, [document.createTextNode(onTime === null || onTime === undefined ? "-" : Number(onTime).toFixed(1)), h("span", { text: "%" })]));
    headline.body.appendChild(h("p", { class: "hero-note", text: fmt(completed) + " completed transfers in scope" }));
    headline.el.appendChild(provenance(kpis));
    grid.appendChild(headline.el);

    const healthCard = card("Open portfolio", "Current schedule health against baseline.", "col-5");
    healthCard.body.appendChild(h("div", { class: "metric-grid" }, [
      metricTile("Open", active.length, "active and planned"),
      metricTile("On track", counts.ON_TRACK || 0, "within baseline", "good"),
      metricTile("At risk", counts.AT_RISK || 0, "1-30 days", "warning"),
      metricTile("Late", counts.LATE || 0, "over 30 days", "critical")
    ]));
    grid.appendChild(healthCard.el);

    const attentionCard = card("Attention queue", "Highest current movement away from baseline.", "col-7",
      h("button", { class: "text-btn", text: "Open register", onclick: () => navigate("projects") }));
    attentionCard.body.appendChild(dataTable([
      { label: "Project", render: row => h("button", { class: "table-link", text: row.project_id, onclick: () => openProject(row.project_id) }) },
      { label: "Health", render: row => statusBadge(row.health) },
      { label: "AI risk", render: row => riskBadge(riskById.get(row.project_id)) },
      { label: "Drift", render: row => signedDays(row.schedule_deviation_days), class: "numeric" }
    ], attention));
    grid.appendChild(attentionCard.el);

    const horizonOrder = ["0-29", "30-59", "60-89", "90+"];
    const rows = horizonOrder.map(bucket => forecast.series.find(row => row.horizon_bucket === bucket)).filter(Boolean);
    const reliability = card("Forecast reliability", "Median absolute error by forecast horizon.", "col-12");
    const chart = h("div");
    reliability.body.appendChild(chart);
    reliability.body.appendChild(legend(rows.map((row, index) => ({ label: row.horizon_bucket + " days out", color: C.cssVar("--ord-" + (index + 1)) }))));
    reliability.el.appendChild(provenance(forecast));
    grid.appendChild(reliability.el);
    queueDraw(() => C.columns(chart, { rows, plot: 210, label: row => row.horizon_bucket, value: row => row.median_abs_error, unit: "days median error", color: (row, index) => C.cssVar("--ord-" + (index + 1)), labelAll: true, tickFmt: value => fmt(value) + "d" }));
  }

  async function projectsView(root) {
    const [payload, riskPayload] = await Promise.all([
      get("/api/register", { ...currentFilters(), limit: 1000 }),
      post("/api/project-risks", { filters: projectFilters() })
    ]);
    const riskById = new Map(riskPayload.risks.map(risk => [risk.project_id, risk]));
    let rows = payload.projects.filter(project => !state.projectSearch || JSON.stringify(project).toLowerCase().includes(state.projectSearch.toLowerCase()));
    rows.sort((a, b) => {
      if (state.projectSort === "project_id") return String(a.project_id).localeCompare(String(b.project_id));
      return (b[state.projectSort] || -Infinity) - (a[state.projectSort] || -Infinity);
    });
    const search = h("input", { type: "search", placeholder: "Search projects", value: state.projectSearch, "aria-label": "Search projects" });
    search.oninput = event => { state.projectSearch = event.target.value; render(); };
    const sort = h("select", { "aria-label": "Sort projects" });
    [["schedule_deviation_days", "Largest schedule drift"], ["project_id", "Project ID"]].forEach(([value, label]) => {
      const option = h("option", { value, text: label });
      if (state.projectSort === value) option.selected = true;
      sort.appendChild(option);
    });
    sort.onchange = event => { state.projectSort = event.target.value; render(); };
    root.appendChild(pageHead("Project register", "Every visible transfer with governed delivery metrics and explainable delay risk.", [search, sort, h("button", { class: "secondary-btn", text: "Export CSV", onclick: () => exportCsv(rows) })]));
    const shell = h("section", { class: "data-surface" });
    shell.appendChild(h("div", { class: "result-summary", text: rows.length + " of " + payload.total_matching + " projects" }));
    shell.appendChild(dataTable([
      { label: "Project", render: row => h("button", { class: "table-link", text: row.project_id, onclick: () => openProject(row.project_id) }) },
      { label: "Type", key: "transfer_type" }, { label: "Portfolio", key: "portfolio" },
      { label: "Route", render: row => (row.source_site || "-") + " to " + (row.target_site || "-") },
      { label: "Status", key: "status" }, { label: "Health", render: row => statusBadge(row.health) },
      { label: "Delay risk", render: row => riskBadge(riskById.get(row.project_id)) },
      { label: "Baseline", key: "baseline_finish" }, { label: "Latest", key: "latest_finish" },
      { label: "Drift", render: row => signedDays(row.schedule_deviation_days), class: "numeric" }
    ], rows, "register"));
    root.appendChild(shell);
  }

  async function projectDetail(root, projectId) {
    const [detail, risks] = await Promise.all([
      get("/api/projects/" + encodeURIComponent(projectId)),
      post("/api/project-risks", { filters: projectFilters() })
    ]);
    const project = detail.project;
    const risk = risks.risks.find(row => row.project_id === projectId);
    root.appendChild(pageHead(project.project_id, (project.transfer_type || "Transfer") + " / " + (project.portfolio || "Unassigned portfolio"), [
      h("button", { class: "secondary-btn", text: "Back to projects", onclick: () => navigate("projects") })
    ]));
    const grid = h("div", { class: "grid" });
    grid.appendChild(h("section", { class: "summary-band col-12" }, [
      metricTile("Status", project.status), metricTile("Cycle time", days(project.actual_cycle_time_days)),
      metricTile("Schedule drift", signedDays(project.schedule_deviation_days), "latest vs baseline", project.schedule_deviation_days > 30 ? "critical" : ""),
      metricTile("Completion variance", signedDays(project.completion_variance_days)),
      metricTile("AI delay risk", risk ? risk.risk_band + " " + risk.risk_score : "Not scored", risk ? risk.drivers.join("; ") : "", risk ? risk.risk_band : "")
    ]));
    const history = card("Schedule revision history", "Every plan change is preserved against the immutable baseline.", "col-8");
    const chart = h("div");
    history.body.appendChild(chart);
    history.body.appendChild(dataTable([
      { label: "Revision", render: row => String(row.revision_id) + (row.is_baseline ? " (baseline)" : "") },
      { label: "Recorded", render: row => String(row.revision_timestamp).slice(0, 10) },
      { label: "Reason", render: row => row.revision_reason || "-" },
      { label: "Planned finish", key: "planned_finish" }, { label: "Forecast finish", key: "forecast_finish" }
    ], detail.schedule_revisions));
    grid.appendChild(history.el);
    const facts = card("Delivery context", "Current governed project attributes.", "col-4");
    facts.body.appendChild(h("dl", { class: "facts" }, Object.entries({ "Transfer type": project.transfer_type, "Portfolio": project.portfolio, "Complexity": project.complexity_class, "Source site": project.source_site, "Target site": project.target_site, "Baseline finish": project.baseline_finish, "Latest finish": project.latest_finish, "Milestones": detail.milestones.length }).flatMap(([key, value]) => [h("dt", { text: key }), h("dd", { text: String(value ?? "-") })])));
    grid.appendChild(facts.el);
    root.appendChild(grid);
    const revisions = detail.schedule_revisions;
    const baseline = revisions.find(row => row.is_baseline);
    queueDraw(() => C.lines(chart, { plot: 250, rule: baseline ? new Date(baseline.planned_finish).getTime() : null, fmtX: value => new Date(value).toISOString().slice(0, 10), fmtY: value => new Date(value).toISOString().slice(0, 10), series: [
      { name: "Planned finish", token: "--series-1", points: revisions.map(row => [new Date(row.revision_timestamp).getTime(), new Date(row.planned_finish).getTime()]) },
      { name: "Forecast finish", token: "--series-2", dashed: true, points: revisions.map(row => [new Date(row.revision_timestamp).getTime(), new Date(row.forecast_finish).getTime()]) }
    ] }));
  }

  async function analytics(root) {
    root.appendChild(pageHead("Transfer analytics", "Distributions, schedule movement, forecast accuracy, bottlenecks, and project history."));
    root.appendChild(segmented([
      { value: "cycle", label: "Cycle time" }, { value: "schedule", label: "Schedule performance" },
      { value: "forecast", label: "Forecast accuracy" }, { value: "bottlenecks", label: "Bottlenecks" },
      { value: "history", label: "Project history" }
    ], state.analyticsTab, value => { state.analyticsTab = value; render(); }));
    const grid = h("div", { class: "grid analytics-grid" });
    root.appendChild(grid);
    if (state.analyticsTab === "cycle") await cyclePanel(grid);
    if (state.analyticsTab === "schedule") await schedulePanel(grid);
    if (state.analyticsTab === "forecast") await forecastPanel(grid);
    if (state.analyticsTab === "bottlenecks") await bottleneckPanel(grid);
    if (state.analyticsTab === "history") await historyPicker(grid);
  }

  async function cyclePanel(grid) {
    const payload = await get("/api/distribution", { group_by: "transfer_type", ...currentFilters() });
    const rows = payload.series.filter(row => row.cohort !== null).map(row => ({ ...row, group_value: row.cohort, median: row.p50 }));
    const panel = card("Cycle-time distribution", "P25 to P75 box, median line, and P90 whisker by transfer type.", "col-12");
    const chart = h("div"); panel.body.appendChild(chart);
    panel.body.appendChild(dataTable([{ label: "Transfer type", key: "group_value" }, { label: "n", key: "n" }, { label: "P25", render: row => days(row.p25) }, { label: "Median", render: row => days(row.median) }, { label: "P75", render: row => days(row.p75) }, { label: "P90", render: row => days(row.p90) }], rows));
    panel.el.appendChild(provenance(payload)); grid.appendChild(panel.el);
    queueDraw(() => C.boxes(chart, { rows, label: row => String(row.group_value) }));
  }

  async function schedulePanel(grid) {
    const [payload, projects] = await Promise.all([get("/api/schedule-drift", { group_by: "transfer_type", ...currentFilters() }), get("/api/projects", { ...projectFilters(), limit: 12 })]);
    const rows = payload.series.filter(row => row.group_value !== null).sort((a, b) => b.median - a.median);
    const panel = card("Original vs latest schedule", "Median movement away from frozen baseline.", "col-7");
    const chart = h("div"); panel.body.appendChild(chart); panel.el.appendChild(provenance(payload)); grid.appendChild(panel.el);
    const queue = card("Largest open slip", "Projects ranked by current schedule drift.", "col-5");
    queue.body.appendChild(dataTable([{ label: "Project", render: row => h("button", { class: "table-link", text: row.project_id, onclick: () => openProject(row.project_id) }) }, { label: "Health", render: row => statusBadge(row.health) }, { label: "Drift", render: row => signedDays(row.schedule_deviation_days) }], projects.projects.slice(0, 10))); grid.appendChild(queue.el);
    queueDraw(() => C.diverging(chart, { rows, label: row => String(row.group_value), value: row => row.median, unit: "days median drift", labelWidth: 150 }));
  }

  async function forecastPanel(grid) {
    const payload = await get("/api/accuracy", projectFilters());
    const order = ["0-29", "30-59", "60-89", "90+"];
    const rows = order.map(bucket => payload.series.find(row => row.horizon_bucket === bucket)).filter(Boolean);
    const panel = card("Forecast error by horizon", "Absolute error and directional bias on the same day scale.", "col-12");
    const chart = h("div"); panel.body.appendChild(chart);
    panel.body.appendChild(dataTable([{ label: "Days out", key: "horizon_bucket" }, { label: "Forecasts", key: "n" }, { label: "Median abs error", render: row => days(row.median_abs_error) }, { label: "P90 abs error", render: row => days(row.p90_abs_error) }, { label: "Bias", render: row => signedDays(row.bias) }], rows));
    panel.el.appendChild(provenance(payload)); grid.appendChild(panel.el);
    queueDraw(() => C.columns(chart, { rows, plot: 240, label: row => row.horizon_bucket, value: row => row.median_abs_error, line: row => row.bias, color: (row, index) => C.cssVar("--ord-" + (index + 1)), labelAll: true, tickFmt: value => fmt(value) + "d" }));
  }

  async function bottleneckPanel(grid) {
    const payload = await get("/api/stage-cycle-time");
    const rows = payload.series.slice();
    const slowest = rows.reduce((index, row, i) => row.median > rows[index].median ? i : index, 0);
    const panel = card("Where the time goes", "Milestone-to-milestone duration in process order.", "col-12");
    const chart = h("div"); panel.body.appendChild(chart); panel.el.appendChild(provenance(payload)); grid.appendChild(panel.el);
    queueDraw(() => C.barsH(chart, { rows, label: row => row.from_stage + " to " + row.to_stage, value: row => row.median, unit: "days median", labelWidth: 210, tickFmt: value => fmt(value) + "d", color: (row, index) => index === slowest ? C.cssVar("--series-1") : C.cssVar("--axis") }));
  }

  async function historyPicker(grid) {
    const payload = await get("/api/register", { ...currentFilters(), limit: 1000 });
    const panel = card("Project history", "Choose a transfer to inspect every preserved plan revision.", "col-12");
    const picker = h("select", { class: "wide-select", "aria-label": "Choose project" });
    payload.projects.forEach(project => picker.appendChild(h("option", { value: project.project_id, text: project.project_id + " / " + project.transfer_type })));
    picker.onchange = () => openProject(picker.value);
    panel.body.appendChild(picker);
    panel.body.appendChild(h("button", { class: "primary-btn", text: "Open project history", onclick: () => picker.value && openProject(picker.value) }));
    grid.appendChild(panel.el);
  }

  async function reports(root) {
    const filters = currentFilters();
    const [portfolio, insight] = await Promise.all([get("/api/trend", projectFilters()), post("/api/insight", { filters })]);
    root.appendChild(pageHead("Reports", "Print-ready portfolio reporting, governed exports, and audience-aware AI email drafts.", [
      h("button", { class: "secondary-btn", text: "Print report", onclick: () => window.print() }),
      h("button", { class: "secondary-btn", text: "Export trend CSV", onclick: () => exportCsv(portfolio.series) })
    ]));
    const grid = h("div", { class: "grid" }); root.appendChild(grid);
    const report = card("Portfolio performance report", "Current filters apply to every figure and narrative.", "col-8 report-sheet");
    report.body.appendChild(h("h3", { class: "insight-headline", text: insight.headline }));
    report.body.appendChild(h("p", { class: "insight-copy", text: insight.content }));
    report.body.appendChild(dataTable([{ label: "Fiscal year", render: row => "FY" + row.fiscal_year }, { label: "Throughput", key: "throughput" }, { label: "Median cycle", render: row => days(row.median_cycle_time) }, { label: "On time", render: row => row.on_time_rate === null ? "-" : Number(row.on_time_rate).toFixed(1) + "%" }, { label: "Replan rate", render: row => row.replan_rate === null ? "-" : Number(row.replan_rate).toFixed(1) + "%" }], portfolio.series));
    report.el.appendChild(provenance(portfolio)); grid.appendChild(report.el);
    const draft = card("AI email draft", "Tailor the same governed snapshot to its audience.", "col-4", h("span", { class: "ai-label", text: "AI" }));
    const audience = h("select", { "aria-label": "Report audience" });
    [["steering_committee", "Steering committee"], ["site_leads", "Site leads"], ["project_managers", "Project managers"]].forEach(([value, label]) => audience.appendChild(h("option", { value, text: label })));
    const cadence = h("select", { "aria-label": "Report cadence" });
    ["weekly", "monthly", "quarterly"].forEach(value => cadence.appendChild(h("option", { value, text: value[0].toUpperCase() + value.slice(1) })));
    const output = h("div", { class: "draft-output" }, [h("p", { text: "Generate a draft to create an executive-ready email from this report." })]);
    const generate = h("button", { class: "primary-btn", text: "Generate email draft" });
    generate.onclick = async () => {
      generate.disabled = true; generate.textContent = "Generating...";
      try {
        const result = await post("/api/report-draft", { filters, audience: audience.value, cadence: cadence.value });
        output.textContent = "";
        output.appendChild(h("strong", { text: result.subject }));
        output.appendChild(h("pre", { text: result.body }));
        output.appendChild(h("button", { class: "secondary-btn", text: "Copy", onclick: () => navigator.clipboard && navigator.clipboard.writeText(result.subject + "\n\n" + result.body) }));
      } catch (error) { output.textContent = error.message; }
      generate.disabled = false; generate.textContent = "Generate email draft";
    };
    draft.body.appendChild(h("div", { class: "form-row" }, [audience, cadence])); draft.body.appendChild(generate); draft.body.appendChild(output); grid.appendChild(draft.el);
  }

  function askResult(container, result) {
    container.textContent = "";
    container.appendChild(h("div", { class: "answer-copy", text: result.answer || "No answer returned." }));
    if (result.interpretation) container.appendChild(h("p", { class: "interpretation", text: "Interpreted as: " + result.interpretation }));
    if (result.rows && result.rows.length) {
      const keys = Object.keys(result.rows[0]).slice(0, 6);
      container.appendChild(dataTable(keys.map(key => ({ label: key.replace(/_/g, " "), key })), result.rows.slice(0, 25)));
    }
    container.appendChild(h("div", { class: "trace-row" }, [
      h("span", { text: result.metric ? result.metric.business_name + " v" + result.metric.version : result.intent }),
      h("code", { text: result.tool_called || "No data tool called" }),
      h("span", { text: "Data as of " + (result.data_as_of || "-") }),
      h("span", { text: result.provenance_complete ? "Provenance complete" : "Provenance incomplete" })
    ]));
  }

  async function askView(root) {
    root.appendChild(pageHead("Ask AI", "Natural-language answers bounded by the governed metric catalogue, with the tool trace shown."));
    const layout = h("div", { class: "ask-layout" }); root.appendChild(layout);
    const form = h("form", { class: "ask-workbench" });
    const input = h("textarea", { rows: "4", maxlength: "500", placeholder: "Which transfer type has the highest median cycle time?", "aria-label": "Ask a metric question" });
    const examples = h("div", { class: "prompt-chips" });
    ["How accurate are our forecasts?", "Which transfer type has the highest cycle time?", "Which projects are more than 30 days behind baseline?", "What does schedule drift mean?"].forEach(question => examples.appendChild(h("button", { type: "button", text: question, onclick: () => { input.value = question; input.focus(); } })));
    const submit = h("button", { class: "primary-btn", type: "submit", text: "Ask Transfer & Conversion Intelligence Platform" });
    form.appendChild(input); form.appendChild(examples); form.appendChild(submit); layout.appendChild(form);
    const result = h("section", { class: "answer-panel" }, [h("strong", { text: "Answer and evidence" }), h("p", { text: "The assistant will show its interpretation, governed source, data vintage, and execution trace here." })]); layout.appendChild(result);
    form.onsubmit = async event => {
      event.preventDefault(); if (input.value.trim().length < 3) return;
      submit.disabled = true; submit.textContent = "Working..."; result.textContent = "Resolving against the metric catalogue...";
      try { askResult(result, await post("/api/ask", { question: input.value.trim(), filters: currentFilters() })); }
      catch (error) { result.textContent = error.message; }
      submit.disabled = false; submit.textContent = "Ask Transfer & Conversion Intelligence Platform";
    };
  }

  async function operations(root) {
    if (!(state.boot.whoami.roles || []).includes("PLATFORM_ADMIN")) {
      root.appendChild(pageHead("Operations", "Administrative access is required for this workspace."));
      root.appendChild(h("div", { class: "error-state" }, [
        h("strong", { text: "Platform administrator required" }),
        h("p", { text: "Your effective identity does not include the PLATFORM_ADMIN role." }),
        h("button", { class: "secondary-btn", text: "Return to portfolio", onclick: () => navigate("overview") })
      ]));
      return;
    }
    root.appendChild(pageHead("Operations", "Data onboarding, service connections, AI activity, and access visibility."));
    root.appendChild(segmented([{ value: "import", label: "Data import" }, { value: "connections", label: "Connections" }, { value: "automation", label: "AI automation" }, { value: "access", label: "Access control" }], state.operationsTab, value => { state.operationsTab = value; render(); }));
    const panel = h("div", { class: "operations-panel" }); root.appendChild(panel);
    if (state.operationsTab === "import") importPanel(panel);
    if (state.operationsTab === "connections") connectionPanel(panel);
    if (state.operationsTab === "automation") await automationPanel(panel);
    if (state.operationsTab === "access") accessPanel(panel);
  }

  function importPanel(root) {
    const input = h("input", { type: "file", accept: ".csv,text/csv", "aria-label": "Choose CSV file" });
    const result = h("div", { class: "import-result" }, [h("p", { text: "Choose a project or schedule-revision CSV to validate it locally before controlled ingestion." })]);
    input.onchange = async () => {
      const file = input.files[0]; if (!file) return;
      const text = await file.text(); const lines = text.trim().split(/\r?\n/); const headers = (lines[0] || "").split(",").map(value => value.trim());
      result.textContent = "";
      result.appendChild(metricTile("Rows detected", Math.max(0, lines.length - 1), file.name));
      result.appendChild(metricTile("Columns", headers.length, headers.slice(0, 5).join(", ") + (headers.length > 5 ? "..." : "")));
      result.appendChild(h("div", { class: "callout", text: "Validation complete. Production ingestion remains controlled by the Transfer & Conversion Intelligence Platform ETL pipeline so data-quality quarantine and audit history cannot be bypassed." }));
    };
    root.appendChild(h("section", { class: "data-surface" }, [h("h2", { text: "Validated CSV onboarding" }), h("p", { text: "Preview file shape in the browser, then use the governed ingestion pipeline for loading, quarantine, and rollback." }), h("label", { class: "file-drop" }, [h("strong", { text: "Select a CSV file" }), h("span", { text: "Projects or schedule revisions" }), input]), result]));
  }

  function connectionPanel(root) {
    const services = [
      { name: "Analytics API", detail: "Read-only governed metric contract", status: state.boot.health.status },
      { name: "PostgreSQL warehouse", detail: "CORE, METRIC, MART, governance and RLS", status: state.boot.health.status },
      { name: "Assistant service", detail: "Catalogue-bound answers, RAG, audit trail", status: "available" },
      { name: "Tableau feeds", detail: "Governed outbound data products", status: "not configured" },
      { name: "Offline snapshot", detail: "Last successful browser response cache", status: "browser managed" }
    ];
    root.appendChild(h("section", { class: "data-surface" }, [h("h2", { text: "Connection registry" }), h("p", { text: "Operational status for the services behind this Transfer & Conversion Intelligence Platform environment." }), h("div", { class: "connection-list" }, services.map(service => h("div", { class: "connection-row" }, [h("span", { class: "connection-icon", text: service.name[0] }), h("div", {}, [h("strong", { text: service.name }), h("small", { text: service.detail })]), h("span", { class: "connection-state", text: service.status })])))]));
  }

  async function automationPanel(root) {
    const payload = await get("/api/assistant-audit", { limit: 100 });
    const answered = payload.calls.filter(call => !call.abstained).length;
    root.appendChild(h("div", { class: "summary-band" }, [metricTile("Calls this session", payload.in_memory), metricTile("Answered", answered), metricTile("Abstained safely", payload.calls.length - answered), metricTile("Persisted", payload.persisted, payload.degraded ? "Audit store degraded" : "Audit store healthy", payload.degraded ? "warning" : "good") ]));
    const surface = h("section", { class: "data-surface" }, [h("h2", { text: "AI execution history" }), h("p", { text: "Every question records its resolution, tool, duration, and provenance state." })]);
    surface.appendChild(payload.calls.length ? dataTable([{ label: "Asked at", render: row => String(row.asked_at).slice(0, 19).replace("T", " ") }, { label: "Identity", render: row => row.identity || "anonymous" }, { label: "Question", key: "question" }, { label: "Intent", key: "intent" }, { label: "Metric", render: row => row.resolved_metric || "-" }, { label: "Duration", render: row => row.duration_ms + " ms" }, { label: "Result", render: row => row.abstained ? "Abstained" : "Answered" }], [...payload.calls].reverse()) : empty("Ask the assistant a question to create the first audited run."));
    root.appendChild(surface);
    if (payload.runs && payload.runs.length) {
      root.appendChild(h("section", { class: "data-surface automation-runs" }, [
        h("h2", { text: "Model refresh runs" }),
        h("p", { text: "Scheduled briefing and risk-cache activity from the provider-backed AI layer." }),
        dataTable([
          { label: "Started", render: row => String(row.started_at).slice(0, 19).replace("T", " ") },
          { label: "Job", key: "job" }, { label: "Trigger", key: "trigger" },
          { label: "Status", key: "status" }, { label: "Items", key: "item_count" },
          { label: "Model", render: row => row.model || "-" },
          { label: "Duration", render: row => row.duration_ms === null ? "-" : row.duration_ms + " ms" }
        ], payload.runs)
      ]));
    }
  }

  function accessPanel(root) {
    const who = state.boot.whoami;
    root.appendChild(h("section", { class: "data-surface" }, [h("h2", { text: "Current identity and entitlements" }), h("p", { text: "Visibility is enforced by the API and PostgreSQL row-level policy. Switching identity demonstrates the effective scope; this screen does not grant access." }), h("div", { class: "summary-band" }, [metricTile("Username", who.username), metricTile("Role", who.role || (who.unrestricted ? "administrator" : "viewer")), metricTile("Access", who.unrestricted ? "All portfolios" : "Entitled scope"), metricTile("Mode", who.auth_mode || "enforced")]), h("div", { class: "callout", text: "Administrative role and site assignment changes belong in the identity provider and governance tables, where they are auditable." })]));
  }

  function exportCsv(rows) {
    if (!rows.length) return;
    const keys = Object.keys(rows[0]);
    const escape = value => '"' + String(value ?? "").replace(/"/g, '""') + '"';
    const csv = [keys.map(escape).join(","), ...rows.map(row => keys.map(key => escape(row[key])).join(","))].join("\r\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = "transfer-conversion-intelligence-platform-" + new Date().toISOString().slice(0, 10) + ".csv";
    link.click(); URL.revokeObjectURL(link.href);
  }

  let pendingDraws = [];
  function queueDraw(callback) { pendingDraws.push(callback); }
  function flushDraws() { const queued = pendingDraws; pendingDraws = []; queued.forEach(callback => callback()); }

  function navigate(view) {
    state.view = view; state.project = null;
    history.replaceState(null, "", view === "overview" ? "#/" : "#/" + view);
    document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-current", button.dataset.view === view ? "page" : "false"));
    render();
  }

  function openProject(projectId) {
    state.project = projectId; state.view = "project-detail";
    history.replaceState(null, "", "#/projects/" + encodeURIComponent(projectId));
    document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-current", button.dataset.view === "projects" ? "page" : "false"));
    render();
  }

  async function render() {
    const app = document.getElementById("app");
    app.classList.add("stale");
    const root = h("div", { class: "view-shell" });
    pendingDraws = [];
    try {
      if (state.view === "overview") await overview(root);
      else if (state.view === "projects") await projectsView(root);
      else if (state.view === "project-detail") await projectDetail(root, state.project);
      else if (state.view === "analytics") await analytics(root);
      else if (state.view === "reports") await reports(root);
      else if (state.view === "ask") await askView(root);
      else if (state.view === "operations") await operations(root);
      app.replaceChildren(root); flushDraws();
    } catch (error) {
      app.replaceChildren(h("div", { class: "error-state" }, [h("strong", { text: "Transfer & Conversion Intelligence Platform could not load this view" }), h("p", { text: String(error.message || error) }), h("button", { class: "primary-btn", text: "Try again", onclick: render })]));
    }
    app.classList.remove("stale"); C.hideTip();
  }

  function option(select, value, label, current) {
    const item = h("option", { value: value === null ? "" : value, text: label });
    if (String(value) === String(current)) item.selected = true;
    select.appendChild(item);
  }

  function fillFilters(boot) {
    const year = document.getElementById("f-year");
    const type = document.getElementById("f-type");
    const portfolio = document.getElementById("f-portfolio");
    const site = document.getElementById("f-site");
    const complexity = document.getElementById("f-complexity");
    [year, type, portfolio, site, complexity].forEach(select => { select.textContent = ""; });
    option(year, null, "All years", state.filters.fiscal_year); boot.fiscal_years.forEach(value => option(year, value, "FY" + value, state.filters.fiscal_year));
    option(type, null, "All types", state.filters.transfer_type); boot.transfer_types.forEach(value => option(type, value, value, state.filters.transfer_type));
    option(portfolio, null, "All portfolios", state.filters.portfolio); boot.portfolios.forEach(value => option(portfolio, value, value, state.filters.portfolio));
    option(site, null, "All sites", state.filters.site); (boot.sites || []).forEach(value => option(site, value, value, state.filters.site));
    option(complexity, null, "All complexity", state.filters.complexity); (boot.complexities || []).forEach(value => option(complexity, value, value, state.filters.complexity));
    year.onchange = () => { state.filters.fiscal_year = year.value || null; render(); };
    type.onchange = () => { state.filters.transfer_type = type.value || null; render(); };
    portfolio.onchange = () => { state.filters.portfolio = portfolio.value || null; render(); };
    site.onchange = () => { state.filters.site = site.value || null; render(); };
    complexity.onchange = () => { state.filters.complexity = complexity.value || null; render(); };
    document.getElementById("vintage").textContent = boot.health.projects + " projects visible / data as of " + boot.health.data_as_of;
  }

  function setupAssistant() {
    const panel = document.getElementById("assistant-panel"); const launcher = document.getElementById("assistant-launcher");
    const close = open => { panel.setAttribute("aria-hidden", String(!open)); launcher.setAttribute("aria-expanded", String(open)); };
    launcher.onclick = () => close(panel.getAttribute("aria-hidden") === "true"); document.getElementById("assistant-close").onclick = () => close(false);
    document.getElementById("assistant-form").onsubmit = async event => {
      event.preventDefault(); const input = document.getElementById("assistant-input"); const question = input.value.trim(); if (question.length < 3) return;
      const messages = document.getElementById("assistant-messages"); messages.appendChild(h("div", { class: "message user", text: question })); input.value = "";
      const waiting = h("div", { class: "message assistant", text: "Checking the governed metric layer..." }); messages.appendChild(waiting); messages.scrollTop = messages.scrollHeight;
      try { const result = await post("/api/ask", { question, filters: currentFilters() }); waiting.textContent = result.answer; waiting.appendChild(h("small", { text: (result.tool_called || result.intent) + " / " + (result.data_as_of || "current scope") })); }
      catch (error) { waiting.textContent = error.message; }
    };
  }

  async function boot() {
    document.querySelectorAll("[data-view]").forEach(button => button.onclick = () => navigate(button.dataset.view));
    document.getElementById("clear-filters").onclick = () => { state.filters = { fiscal_year: null, transfer_type: null, portfolio: null, site: null, complexity: null }; fillFilters(state.boot); render(); };
    const user = document.getElementById("f-user"); DEMO_USERS.forEach(value => option(user, value, value, state.identity));
    user.onchange = async () => {
      state.identity = user.value;
      state.project = null;
      state.boot = await get("/api/bootstrap");
      fillFilters(state.boot);
      document.getElementById("operations-nav").hidden =
        !(state.boot.whoami.roles || []).includes("PLATFORM_ADMIN");
      render();
    };
    const theme = document.getElementById("theme");
    theme.onclick = () => { const current = document.documentElement.getAttribute("data-theme"); const next = current === "dark" ? "light" : "dark"; document.documentElement.setAttribute("data-theme", next); localStorage.setItem("transferops-theme", next); render(); };
    const savedTheme = localStorage.getItem("transferops-theme"); if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);
    setupAssistant();
    try {
      state.boot = await get("/api/bootstrap"); state.identity = state.boot.whoami.username; user.value = state.identity; fillFilters(state.boot);
      document.getElementById("operations-nav").hidden = !(state.boot.whoami.roles || []).includes("PLATFORM_ADMIN");
      document.getElementById("connection-status").replaceChildren(
        h("span", { class: "dot good" }),
        document.createTextNode(state.boot.ai && state.boot.ai.ai && state.boot.ai.ai.configured ? " Live + AI" : " Live")
      );
    } catch (error) {
      document.getElementById("connection-status").textContent = "Unavailable";
    }
    const hash = location.hash.replace(/^#\//, "");
    if (hash.startsWith("projects/")) { state.project = decodeURIComponent(hash.slice(9)); state.view = "project-detail"; }
    else if (["projects", "analytics", "reports", "ask", "operations"].includes(hash)) state.view = hash;
    document.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-current", button.dataset.view === (state.view === "project-detail" ? "projects" : state.view) ? "page" : "false"));
    render();
    let resizeTimer; addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 180); });
  }

  boot();
})();
