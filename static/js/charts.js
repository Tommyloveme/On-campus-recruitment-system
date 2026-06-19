"use strict";

/* 数据图表页 */
const charts = { list: [], instance: null };
const CHART_COLORS = [
  "#2563eb", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#84cc16", "#0ea5e9", "#f97316", "#14b8a6", "#64748b",
];

async function renderCharts() {
  const fields = allFieldsFlat().filter(f => f.type === "select" || f.type === "date");
  const fieldOpts = (selected) =>
    fields.map(f =>
      `<option value="${f.key}"${f.key === selected ? " selected" : ""}>${esc(f.label)}</option>`).join("");
  const dimOpts = fieldOpts("offer_status");
  const serOpts = `<option value="">（无）</option>` + fieldOpts("");

  $("#main").innerHTML = `
    <div class="card">
      <div class="toolbar" style="margin-bottom:0">
        <div class="chart-ctrl"><label>维度（横轴）</label><select id="ch-dim">${dimOpts}</select></div>
        <div class="chart-ctrl hidden" id="ch-gran-wrap"><label>日期粒度</label>
          <select id="ch-gran">
            <option value="ym" selected>按年月</option>
            <option value="ymd">按年月日</option>
            <option value="m">按月份</option>
          </select></div>
        <div class="chart-ctrl"><label>系列（图例）</label><select id="ch-ser">${serOpts}</select></div>
        <div class="chart-ctrl"><label>图表类型</label>
          <select id="ch-type">
            <option value="bar">柱状图</option>
            <option value="stacked">堆叠柱状图</option>
            <option value="hbar">条形图</option>
            <option value="doughnut">环形图</option>
            <option value="pie">饼图</option>
          </select></div>
        <div class="spacer"></div>
        <span id="ch-count" class="badge badge-blue"></span>
      </div>
    </div>
    <div class="chart-grid">
      <div class="card chart-card">
        <div class="section-title" id="ch-title"></div>
        <div class="chart-canvas-wrap"><canvas id="ch-canvas"></canvas></div>
      </div>
      <div class="card">
        <div class="section-title">数据透视表</div>
        <div id="ch-pivot"></div>
      </div>
    </div>`;

  charts.list = await api("/api/candidates");
  ["ch-dim", "ch-ser", "ch-type", "ch-gran"].forEach(id =>
    $("#" + id).addEventListener("change", drawChart));
  drawChart();
}

function isDateField(key) {
  const f = allFieldsFlat().find(f => f.key === key);
  return !!f && f.type === "date";
}

function chartValue(c, key, gran) {
  let v = c.data[key] || "（空）";
  if (gran && v !== "（空）" && isDateField(key)) {
    if (gran === "ym" && v.length >= 7) v = v.slice(0, 7);
    else if (gran === "m" && v.length >= 7) v = v.slice(5, 7) + "月";
  }
  return v;
}

function chartLabelOf(key) {
  const f = allFieldsFlat().find(f => f.key === key);
  return f ? f.label : key;
}

function orderedValues(list, key, gran) {
  const counts = new Map();
  list.forEach(c => {
    const v = chartValue(c, key, gran);
    counts.set(v, (counts.get(v) || 0) + 1);
  });
  const f = allFieldsFlat().find(f => f.key === key);
  let values;
  if (f && f.type === "date") {
    values = [...counts.keys()].filter(v => v !== "（空）").sort();
    if (counts.has("（空）")) values.push("（空）");
  } else if (f && f.type === "select") {
    values = (f.options || []).filter(o => counts.has(o));
    if (counts.has("（空）")) values.push("（空）");
  } else {
    values = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a)).slice(0, 30);
  }
  return values;
}

function drawChart() {
  const dimKey = $("#ch-dim").value;
  let serKey = $("#ch-ser").value;
  const type = $("#ch-type").value;
  if (["pie", "doughnut"].includes(type)) serKey = "";

  const dimIsDate = isDateField(dimKey);
  $("#ch-gran-wrap").classList.toggle("hidden", !dimIsDate);
  const gran = dimIsDate ? $("#ch-gran").value : null;

  let list = charts.list;
  $("#ch-count").textContent = `共 ${list.length} 名候选人`;

  const dims = orderedValues(list, dimKey, gran);
  const sers = serKey ? orderedValues(list, serKey) : null;
  const matrix = (sers || ["数量"]).map(() => dims.map(() => 0));
  list.forEach(c => {
    const di = dims.indexOf(chartValue(c, dimKey, gran));
    if (di < 0) return;
    const si = sers ? sers.indexOf(chartValue(c, serKey)) : 0;
    if (si < 0) return;
    matrix[si][di] += 1;
  });

  const granName = { ymd: "按年月日", ym: "按年月", m: "按月份" }[gran] || "";
  $("#ch-title").textContent =
    `${chartLabelOf(dimKey)}${granName ? "·" + granName : ""} 分布` +
    (serKey ? ` × ${chartLabelOf(serKey)}` : "");

  if (charts.instance) { charts.instance.destroy(); charts.instance = null; }
  const ctx = $("#ch-canvas").getContext("2d");
  const baseFont = { family: "'Segoe UI','Microsoft YaHei',sans-serif", size: 12 };

  if (["pie", "doughnut"].includes(type)) {
    charts.instance = new Chart(ctx, {
      type,
      data: {
        labels: dims,
        datasets: [{
          data: matrix[0],
          backgroundColor: dims.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
          borderColor: "#fff", borderWidth: 2, hoverOffset: 8,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        cutout: type === "doughnut" ? "58%" : 0,
        plugins: {
          legend: { position: "right", labels: { font: baseFont, usePointStyle: true, padding: 14 } },
          tooltip: { padding: 10, cornerRadius: 8 },
        },
      },
    });
  } else {
    const horizontal = type === "hbar";
    const stacked = type === "stacked";
    charts.instance = new Chart(ctx, {
      type: "bar",
      data: {
        labels: dims,
        datasets: (sers || ["数量"]).map((s, i) => ({
          label: s,
          data: matrix[i],
          backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + "cc",
          hoverBackgroundColor: CHART_COLORS[i % CHART_COLORS.length],
          borderRadius: 6, borderSkipped: false,
          maxBarThickness: 46,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        scales: {
          x: { stacked, grid: { display: horizontal }, ticks: { font: baseFont }, border: { display: false } },
          y: { stacked, beginAtZero: true, ticks: { font: baseFont, precision: 0 }, border: { display: false } },
        },
        plugins: {
          legend: { display: !!sers, position: "bottom", labels: { font: baseFont, usePointStyle: true, padding: 14 } },
          tooltip: { padding: 10, cornerRadius: 8 },
        },
      },
    });
  }
  renderPivotTable(dims, sers, matrix, dimKey, serKey);
}

function renderPivotTable(dims, sers, matrix, dimKey, serKey) {
  const colHeads = sers || ["数量"];
  const colTotals = colHeads.map((_, si) => matrix[si].reduce((a, b) => a + b, 0));
  const grand = colTotals.reduce((a, b) => a + b, 0);
  $("#ch-pivot").innerHTML = `
    <div class="table-wrap"><table style="min-width:0">
      <thead><tr>
        <th>${esc(chartLabelOf(dimKey))}</th>
        ${colHeads.map(h => `<th>${esc(h)}</th>`).join("")}
        ${sers ? "<th>合计</th>" : ""}
      </tr></thead>
      <tbody>
        ${dims.map((d, di) => {
          const rowTotal = colHeads.reduce((acc, _, si) => acc + matrix[si][di], 0);
          return `<tr>
            <td>${esc(d)}</td>
            ${colHeads.map((_, si) => `<td>${matrix[si][di] || 0}</td>`).join("")}
            ${sers ? `<td><b>${rowTotal}</b></td>` : ""}
          </tr>`;
        }).join("")}
        <tr style="background:#f8fafc">
          <td><b>合计</b></td>
          ${colTotals.map(t => `<td><b>${t}</b></td>`).join("")}
          ${sers ? `<td><b>${grand}</b></td>` : ""}
        </tr>
      </tbody>
    </table></div>`;
}
