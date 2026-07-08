/* 可复用数据看板（类 Excel 数据透视表/透视图）。
 * 用法：renderPivotPanel(容器, { stageKey })
 * - 行/列维度任选该页面字段（select/date 字段），值为候选人计数；
 * - 支持一个筛选条件、日期粒度、表格/柱状/堆叠/环形四种视图；
 * - 每个页面有自己的默认维度（PIVOT_DEFAULTS），其余全部可自由调整。 */
"use strict";

const PIVOT_DEFAULTS = {
  registration: { row: "registration_source", col: "education" },
  resume_screening: { row: "resume_screening_status", col: "" },
  qualification: { row: "qualification_status", col: "" },
  written_test: { row: "written_test_status", col: "" },
  personality_test: { row: "personality_test_status", col: "" },
  qualification_interview: { row: "qualification_interview_status", col: "" },
  tech_interview: { row: "tech_interview_status", col: "tech_interview_result" },
  manager_interview: { row: "manager_interview_status", col: "manager_interview_result" },
  approval: { row: "approval_status", col: "" },
  salary: { row: "salary_status", col: "" },
  offer: { row: "offer_status", col: "" },
  contract_signing: { row: "sign_status", col: "" },
  onboarding: { row: "onboard_risk", col: "onboarded" },
};

function pivotDimFields(stageKey) {
  const seen = new Set();
  const out = [];
  for (const f of fieldsForStage(stageKey)) {
    if (seen.has(f.key)) continue;
    if (f.type === "select" || f.type === "date") { seen.add(f.key); out.push(f); }
  }
  // 阶段字段之外补充公共关键维度
  for (const f of allFieldsFlat()) {
    if (seen.has(f.key)) continue;
    if (["education", "work_location", "current_stage"].includes(f.key)) {
      seen.add(f.key); out.push(f);
    }
  }
  return out;
}

function pivotValue(c, key, gran) {
  let v = String(c.data[key] ?? "").trim() || "（空）";
  if (gran && v !== "（空）") {
    if (gran === "ym" && v.length >= 7) v = v.slice(0, 7);
    else if (gran === "m" && v.length >= 7) v = v.slice(5, 7) + "月";
    else if (gran === "ymd" && v.length >= 10) v = v.slice(0, 10);
  }
  return v;
}

async function renderPivotPanel(rootEl, opts = {}) {
  const stageKey = opts.stageKey;
  const dimFields = pivotDimFields(stageKey);
  if (!dimFields.length) {
    rootEl.innerHTML = `<div class="card">该页面暂无可透视的维度字段。</div>`;
    return;
  }
  const defaults = PIVOT_DEFAULTS[stageKey] || {};
  const pick = (want, fallbackIdx) =>
    dimFields.some(f => f.key === want) ? want : (dimFields[fallbackIdx]?.key || "");
  const st = {
    row: pick(defaults.row, 0),
    col: defaults.col && dimFields.some(f => f.key === defaults.col) ? defaults.col : "",
    filterKey: "", filterVal: "",
    view: "bar", gran: "ym", onlyStage: true,
    list: [], chart: null,
  };

  const dimOpts = (selected, withEmpty) =>
    (withEmpty ? `<option value="">（无）</option>` : "") +
    dimFields.map(f =>
      `<option value="${f.key}"${f.key === selected ? " selected" : ""}>${esc(f.label)}</option>`).join("");

  rootEl.innerHTML = `
    <div class="card">
      <div class="toolbar" style="margin-bottom:0;flex-wrap:wrap">
        <div class="chart-ctrl"><label>行维度</label><select data-pv="row">${dimOpts(st.row, false)}</select></div>
        <div class="chart-ctrl"><label>列维度</label><select data-pv="col">${dimOpts(st.col, true)}</select></div>
        <div class="chart-ctrl hidden" data-pv-granwrap><label>日期粒度</label>
          <select data-pv="gran">
            <option value="ym" selected>按年月</option><option value="ymd">按年月日</option><option value="m">按月份</option>
          </select></div>
        <div class="chart-ctrl"><label>筛选字段</label><select data-pv="filterKey">${dimOpts("", true)}</select></div>
        <div class="chart-ctrl"><label>筛选值</label><select data-pv="filterVal"><option value="">全部</option></select></div>
        <div class="chart-ctrl"><label>视图</label>
          <select data-pv="view">
            <option value="bar">柱状图</option><option value="stacked">堆叠柱状图</option>
            <option value="doughnut">环形图</option><option value="table">仅透视表</option>
          </select></div>
        <label class="chk-inline"><input type="checkbox" data-pv-onlystage checked> 仅当前流程</label>
        <div class="spacer"></div>
        <span class="badge badge-blue" data-pv-count></span>
      </div>
    </div>
    <div class="chart-grid">
      <div class="card chart-card" data-pv-chartcard>
        <div class="section-title" data-pv-title></div>
        <div class="chart-canvas-wrap"><canvas data-pv-canvas></canvas></div>
      </div>
      <div class="card">
        <div class="section-title">数据透视表</div>
        <div data-pv-table></div>
      </div>
    </div>`;

  const $$ = sel => rootEl.querySelector(sel);

  async function loadData() {
    const url = st.onlyStage ? `/api/candidates?stage=${stageKey}` : "/api/candidates";
    st.list = await api(url);
    draw();
  }

  function filteredList() {
    if (!st.filterKey || !st.filterVal) return st.list;
    return st.list.filter(c => pivotValue(c, st.filterKey) === st.filterVal);
  }

  function refreshFilterValues() {
    const sel = $$('[data-pv="filterVal"]');
    if (!st.filterKey) { sel.innerHTML = `<option value="">全部</option>`; return; }
    const vals = [...new Set(st.list.map(c => pivotValue(c, st.filterKey)))].sort();
    sel.innerHTML = `<option value="">全部</option>` +
      vals.map(v => `<option value="${esc(v)}"${v === st.filterVal ? " selected" : ""}>${esc(v)}</option>`).join("");
  }

  function orderedVals(list, key, gran) {
    const counts = new Map();
    list.forEach(c => {
      const v = pivotValue(c, key, gran);
      counts.set(v, (counts.get(v) || 0) + 1);
    });
    const f = dimFields.find(x => x.key === key);
    let vals;
    if (f && f.type === "date") {
      vals = [...counts.keys()].filter(v => v !== "（空）").sort();
      if (counts.has("（空）")) vals.push("（空）");
    } else if (f && f.type === "select") {
      vals = (f.options || []).filter(o => counts.has(o));
      [...counts.keys()].forEach(v => { if (!vals.includes(v)) vals.push(v); });
    } else {
      vals = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a)).slice(0, 30);
    }
    return vals;
  }

  function labelOf(key) {
    const f = dimFields.find(x => x.key === key);
    return f ? f.label : key;
  }

  function draw() {
    const list = filteredList();
    $$("[data-pv-count]").textContent = `${list.length} 人`;
    const rowIsDate = (dimFields.find(f => f.key === st.row) || {}).type === "date";
    $$("[data-pv-granwrap]").classList.toggle("hidden", !rowIsDate);
    const gran = rowIsDate ? st.gran : null;

    const rows = orderedVals(list, st.row, gran);
    const cols = st.col ? orderedVals(list, st.col) : null;
    const matrix = (cols || ["数量"]).map(() => rows.map(() => 0));
    list.forEach(c => {
      const ri = rows.indexOf(pivotValue(c, st.row, gran));
      if (ri < 0) return;
      const ci = cols ? cols.indexOf(pivotValue(c, st.col)) : 0;
      if (ci < 0) return;
      matrix[ci][ri] += 1;
    });

    $$("[data-pv-title]").textContent =
      `${labelOf(st.row)} 分布` + (st.col ? ` × ${labelOf(st.col)}` : "") +
      (st.filterKey && st.filterVal ? `（${labelOf(st.filterKey)}=${st.filterVal}）` : "");

    drawPivotChart(rows, cols, matrix);
    drawPivotTable(rows, cols, matrix);
  }

  function drawPivotChart(rows, cols, matrix) {
    const showChart = st.view !== "table";
    $$("[data-pv-chartcard]").classList.toggle("hidden", !showChart);
    if (st.chart) { st.chart.destroy(); st.chart = null; }
    if (!showChart) return;
    const ctx = $$("[data-pv-canvas]").getContext("2d");
    const baseFont = { family: "'Segoe UI','Microsoft YaHei',sans-serif", size: 12 };
    const total = matrix.reduce((a, r) => a + r.reduce((x, y) => x + y, 0), 0);
    const pct = v => total ? `${(v * 100 / total).toFixed(1)}%` : "0%";

    if (st.view === "doughnut") {
      const data = cols ? matrix.map(r => r.reduce((a, b) => a + b, 0)) : matrix[0];
      const labels = cols || rows;
      st.chart = new Chart(ctx, {
        type: "doughnut",
        data: {
          labels,
          datasets: [{ data, backgroundColor: labels.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
                       borderColor: "#fff", borderWidth: 2 }],
        },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: "58%",
          plugins: {
            legend: { position: "right", labels: { font: baseFont, usePointStyle: true } },
            tooltip: { callbacks: { label: c => ` ${c.label}：${c.parsed} 人（${pct(c.parsed)}）` } },
          },
        },
      });
      return;
    }
    const stacked = st.view === "stacked";
    st.chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: rows,
        datasets: (cols || ["数量"]).map((s, i) => ({
          label: s, data: matrix[i],
          backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + "cc",
          borderRadius: 6, borderSkipped: false, maxBarThickness: 46,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { stacked, grid: { display: false }, ticks: { font: baseFont },
               title: { display: true, text: labelOf(st.row), font: baseFont, color: "#64748b" } },
          y: { stacked, beginAtZero: true, grid: { color: "rgba(148,163,184,.18)" },
               ticks: { font: baseFont, precision: 0 },
               title: { display: true, text: "人数", font: baseFont, color: "#64748b" } },
        },
        plugins: {
          legend: { display: !!cols, position: "bottom", labels: { font: baseFont, usePointStyle: true } },
          tooltip: { callbacks: { label: c => ` ${c.dataset.label}：${c.parsed.y} 人（${pct(c.parsed.y)}）` } },
        },
      },
    });
  }

  function drawPivotTable(rows, cols, matrix) {
    const heads = cols || ["数量"];
    const colTotals = heads.map((_, ci) => matrix[ci].reduce((a, b) => a + b, 0));
    const grand = colTotals.reduce((a, b) => a + b, 0);
    const pctOf = v => grand ? `${(v * 100 / grand).toFixed(1)}%` : "—";
    $$("[data-pv-table]").innerHTML = `
      <div class="table-wrap"><table style="min-width:0">
        <thead><tr>
          <th>${esc(labelOf(st.row))}</th>
          ${heads.map(h => `<th>${esc(h)}</th>`).join("")}
          ${cols ? "<th>合计</th>" : ""}<th>占比</th>
        </tr></thead>
        <tbody>
          ${rows.map((r, ri) => {
            const rowTotal = heads.reduce((a, _, ci) => a + matrix[ci][ri], 0);
            return `<tr>
              <td>${esc(r)}</td>
              ${heads.map((_, ci) => `<td>${matrix[ci][ri] || 0}</td>`).join("")}
              ${cols ? `<td><b>${rowTotal}</b></td>` : ""}
              <td class="muted">${pctOf(rowTotal)}</td>
            </tr>`;
          }).join("")}
          <tr style="background:#f8fafc">
            <td><b>合计</b></td>
            ${colTotals.map(t => `<td><b>${t}</b></td>`).join("")}
            ${cols ? `<td><b>${grand}</b></td>` : ""}<td class="muted">100%</td>
          </tr>
        </tbody>
      </table></div>`;
  }

  rootEl.querySelectorAll("[data-pv]").forEach(sel =>
    sel.addEventListener("change", () => {
      st[sel.dataset.pv] = sel.value;
      if (sel.dataset.pv === "filterKey") { st.filterVal = ""; refreshFilterValues(); }
      draw();
    }));
  rootEl.querySelector("[data-pv-onlystage]").addEventListener("change", e => {
    st.onlyStage = e.target.checked;
    loadData().then(refreshFilterValues);
  });

  await loadData();
  refreshFilterValues();
}
