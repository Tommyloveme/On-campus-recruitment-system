/* 可复用数据看板（Excel 式数据透视图）。
 * 用法：renderPivotPanel(容器, { stageKey })
 *
 * 能力对标 Excel 透视图：
 * - 行（类别轴）与列（图例/系列）均支持多字段叠加（组合维度，如 学历 / 性别）；
 * - 字段可选页面内任意字段（含文本/下拉/日期），日期支持粒度切换；
 * - 值汇总：计数 / 去重计数 / 数值字段求和、平均、最大、最小；
 * - 多条件筛选（等于/不等于/包含/为空/非空，可叠加任意多条，AND 关系）；
 * - 排序（按名称/按数值升降序）、Top N 截断、行列小计与占比；
 * - 视图：透视表 / 柱状 / 堆叠 / 折线 / 环形；表格支持一键导出 CSV。 */
"use strict";

const PIVOT_DEFAULTS = {
  registration: { rows: ["来源渠道"], cols: ["学历"] },
  resume_screening: { rows: ["简历筛选状态"] },
  qualification: { rows: ["资审状态"] },
  written_test: { rows: ["笔试状态"] },
  personality_test: { rows: ["性格测评状态"] },
  qualification_interview: { rows: ["资格面试状态"] },
  tech_interview: { rows: ["技术面状态"], cols: ["技术面结果"] },
  manager_interview: { rows: ["主管面状态"], cols: ["主管面结果"] },
  approval: { rows: ["报批状态"] },
  salary: { rows: ["谈薪状态"] },
  offer: { rows: ["Offer状态"] },
  contract_signing: { rows: ["签约状态"] },
  onboarding: { rows: ["入职风险"], cols: ["是否入职"] },
};

const PIVOT_OPS = [
  ["eq", "等于"], ["ne", "不等于"], ["contains", "包含"],
  ["not_contains", "不包含"], ["empty", "为空"], ["not_empty", "非空"],
];

const PIVOT_MAX_ZONE_FIELDS = 3;

function pivotAllFields(stageKey) {
  // 仅当前流程 UI 可见列（与列表表头一致），可作行维度 / 筛选
  if (!stageKey) return [];
  if (typeof stageListFields === "function") return stageListFields(stageKey);
  return visibleFields(stageKey);
}

function pivotRawValue(c, key) {
  // 拓源人/接口人：看板维度与筛选用已存姓名（与列表一致）
  if (key === "拓源人" || key === "sourcer") {
    const n = c.data?.["拓源人姓名"] || c.data?.sourcer_name || c.data?.["拓源人"] || c.data?.sourcer;
    return n != null && String(n).trim() !== "" ? String(n).trim() : "";
  }
  if (key === "接口人" || key === "interface_person") {
    const n = c.data?.["接口人姓名"] || c.data?.interface_person_name || c.data?.["接口人"] || c.data?.interface_person;
    return n != null && String(n).trim() !== "" ? String(n).trim() : "";
  }
  const v = c.data?.[key];
  if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  if (key === "当前流程" || key === "current_stage") return String(c.current_stage || "").trim();
  return "";
}

function pivotBucket(c, key, gran) {
  let v = pivotRawValue(c, key) || "（空）";
  if (gran && v !== "（空）") {
    if (gran === "y" && v.length >= 4) v = v.slice(0, 4) + "年";
    else if (gran === "ym" && v.length >= 7) v = v.slice(0, 7);
    else if (gran === "m" && v.length >= 7) v = v.slice(5, 7) + "月";
    else if (gran === "ymd" && v.length >= 10) v = v.slice(0, 10);
  }
  return v;
}

function pivotMatchFilter(c, flt) {
  const v = pivotRawValue(c, flt.key);
  switch (flt.op) {
    case "eq": return v === flt.val;
    case "ne": return v !== flt.val;
    case "contains": return flt.val === "" || v.includes(flt.val);
    case "not_contains": return flt.val === "" || !v.includes(flt.val);
    case "empty": return v === "";
    case "not_empty": return v !== "";
    default: return true;
  }
}

async function renderPivotPanel(rootEl, opts = {}) {
  const stageKey = opts.stageKey;
  const dimFields = pivotAllFields(stageKey);
  if (!dimFields.length) {
    rootEl.innerHTML = `<div class="card">该页面暂无可透视的字段。</div>`;
    return;
  }
  const defaults = PIVOT_DEFAULTS[stageKey] || {};
  const hasField = k => dimFields.some(f => f.key === k);
  const st = {
    rows: (defaults.rows || []).filter(hasField),
    cols: (defaults.cols || []).filter(hasField),
    agg: "count", aggField: "",
    view: "bar", gran: "ym", colGran: "ym",
    sort: "value_desc", topN: 20,
    pct: "none",
    filters: [],
    list: [], chart: null,
  };
  if (!st.rows.length) st.rows = [dimFields[0].key];

  const fieldOpts = (selected, withEmpty) =>
    (withEmpty ? `<option value="">（无）</option>` : "") +
    dimFields.map(f =>
      `<option value="${esc(f.key)}"${f.key === selected ? " selected" : ""}>${esc(f.label)}</option>`).join("");

  rootEl.innerHTML = `
    <div class="card pv-panel">
      <div class="pv-toolbar">
        <div class="pv-group pv-zone-wrap">
          <span class="pv-cap">行（类别轴）</span>
          <span class="pv-zone" data-pv-zone="rows"></span>
          <select data-pv="gran" class="pv-gran hidden">
            <option value="ymd">按日</option><option value="ym" selected>按月</option>
            <option value="y">按年</option><option value="m">仅月份</option>
          </select>
        </div>
        <div class="pv-group pv-zone-wrap">
          <span class="pv-cap">列（图例/系列）</span>
          <span class="pv-zone" data-pv-zone="cols"></span>
        </div>
        <div class="pv-group">
          <span class="pv-cap">值</span>
          <select data-pv="agg">
            <option value="count">人数</option>
            <option value="distinct">去重计数</option>
            <option value="sum">求和</option>
            <option value="avg">平均</option>
            <option value="max">最大</option>
            <option value="min">最小</option>
          </select>
          <select data-pv="aggField" class="hidden">${fieldOpts("", false)}</select>
        </div>
        <div class="pv-group">
          <span class="pv-cap">排序</span>
          <select data-pv="sort">
            <option value="value_desc">数值 ↓</option><option value="value_asc">数值 ↑</option>
            <option value="label_asc">名称 A→Z</option><option value="label_desc">名称 Z→A</option>
          </select>
          <span class="pv-cap">Top</span>
          <select data-pv="topN">
            <option value="10">10</option><option value="20" selected>20</option>
            <option value="50">50</option><option value="0">全部</option>
          </select>
        </div>
        <div class="pv-group">
          <span class="pv-cap">占比</span>
          <select data-pv="pct">
            <option value="none">不显示</option><option value="grand">总计占比</option>
            <option value="row">行内占比</option><option value="col">列内占比</option>
          </select>
        </div>
        <div class="pv-group">
          <span class="pv-cap">视图</span>
          <select data-pv="view">
            <option value="bar">柱状图</option><option value="stacked">堆叠柱状</option>
            <option value="line">折线图</option><option value="doughnut">环形图</option>
            <option value="table">仅透视表</option>
          </select>
        </div>
        <div class="spacer"></div>
        <button class="btn btn-sm" data-pv-refresh title="强制从服务器同步最新数据">刷新</button>
        <span class="cache-status" data-pv-cache-status></span>
        <button class="btn btn-sm" data-pv-export>导出 CSV</button>
        <span class="badge badge-blue" data-pv-count></span>
      </div>
      <div class="pv-filters">
        <span class="pv-cap">筛选</span>
        <div class="pv-filter-list" data-pv-filterlist></div>
        <button class="btn btn-sm" data-pv-addfilter>+ 条件</button>
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
  let lastGrid = null;   // 导出 CSV 用
  const cacheKey = stageKey || "registration";

  function updatePivotCacheStatus() {
    const el = $$("[data-pv-cache-status]");
    if (!el) return;
    const entry = dashCache.pivot.get(cacheKey);
    if (!entry || !entry.loadedAt) {
      el.textContent = "尚未加载";
      el.className = "cache-status";
      return;
    }
    el.textContent = `上次刷新：${formatRefreshTime(entry.loadedAt)}`;
    el.className = "cache-status" + (entry.stale ? " stale" : "");
  }

  async function fetchPivotList() {
    const url = !stageKey || stageKey === "registration"
      ? "/api/candidates"
      : `/api/candidates?stage=${encodeURIComponent(stageKey)}&mode=reached`;
    const list = await api(url);
    dashCache.pivot.set(cacheKey, { list, loadedAt: Date.now(), stale: false });
    return list;
  }

  async function loadData(opts = {}) {
    const force = !!(opts && opts.force);
    const entry = dashCache.pivot.get(cacheKey);
    if (!force && dashCacheFresh(entry)) {
      st.list = entry.list;
      updatePivotCacheStatus();
      draw();
      return;
    }
    if (!force && entry && entry.list) {
      st.list = entry.list;
      updatePivotCacheStatus();
      draw();
      fetchPivotList().then(list => {
        st.list = list;
        updatePivotCacheStatus();
        draw();
      }).catch(() => {});
      return;
    }
    updatePivotCacheStatus();
    st.list = await fetchPivotList();
    updatePivotCacheStatus();
    draw();
  }

  $$("[data-pv-refresh]")?.addEventListener("click", async () => {
    const btn = $$("[data-pv-refresh]");
    if (btn) { btn.disabled = true; btn.textContent = "同步中…"; }
    try {
      await loadData({ force: true });
      toast("看板数据已同步");
    } catch (e) {
      toast(e.message || "刷新失败", true);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "刷新"; }
    }
  });

  /* ---------- 行/列多字段区（Excel 式叠加） ---------- */

  function renderZones() {
    for (const zone of ["rows", "cols"]) {
      const el = $$(`[data-pv-zone="${zone}"]`);
      const keys = st[zone];
      const canRemove = zone === "cols" || keys.length > 1;
      el.innerHTML = keys.map((k, i) => `
        <span class="pv-zone-item">
          <select data-zone="${zone}" data-zi="${i}">${fieldOpts(k, false)}</select>
          ${canRemove ? `<button class="pv-filter-del" data-zone-del="${zone}" data-zi="${i}" title="移除该字段">×</button>` : ""}
        </span>`).join("")
        + (keys.length < PIVOT_MAX_ZONE_FIELDS
          ? `<button class="btn btn-sm pv-zone-add" data-zone-add="${zone}" title="叠加一个字段（组合维度）">+</button>` : "");

      el.querySelectorAll("select[data-zone]").forEach(sel =>
        sel.addEventListener("change", () => {
          st[zone][+sel.dataset.zi] = sel.value;
          draw();
        }));
      el.querySelectorAll("[data-zone-del]").forEach(btn =>
        btn.addEventListener("click", () => {
          st[zone].splice(+btn.dataset.zi, 1);
          renderZones();
          draw();
        }));
      const addBtn = el.querySelector("[data-zone-add]");
      if (addBtn) addBtn.addEventListener("click", () => {
        const used = new Set([...st.rows, ...st.cols]);
        const next = dimFields.find(f => !used.has(f.key)) || dimFields[0];
        st[zone].push(next.key);
        renderZones();
        draw();
      });
    }
  }

  /* ---------- 多条件筛选 ---------- */

  function renderFilters() {
    const listEl = $$("[data-pv-filterlist]");
    listEl.innerHTML = st.filters.map((flt, i) => {
      const valDisabled = flt.op === "empty" || flt.op === "not_empty";
      const vals = [...new Set(st.list.map(c => pivotRawValue(c, flt.key)).filter(Boolean))].sort();
      return `
      <span class="pv-filter" data-fi="${i}">
        <select data-fpart="key">${fieldOpts(flt.key, false)}</select>
        <select data-fpart="op">${PIVOT_OPS.map(([v, l]) =>
          `<option value="${v}"${flt.op === v ? " selected" : ""}>${l}</option>`).join("")}</select>
        ${valDisabled ? "" : `
        <input list="pv-vals-${i}" data-fpart="val" value="${esc(flt.val)}" placeholder="值">
        <datalist id="pv-vals-${i}">${vals.slice(0, 60).map(v =>
          `<option value="${esc(v)}">`).join("")}</datalist>`}
        <button class="pv-filter-del" data-fdel="${i}" title="删除条件">×</button>
      </span>`;
    }).join("");

    listEl.querySelectorAll("[data-fpart]").forEach(el => {
      const idx = +el.closest("[data-fi]").dataset.fi;
      const part = el.dataset.fpart;
      const handler = () => {
        st.filters[idx][part] = el.value;
        if (part === "op" || part === "key") renderFilters();
        draw();
      };
      el.addEventListener("change", handler);
      if (el.tagName === "INPUT") el.addEventListener("input", debounce(handler, 300));
    });
    listEl.querySelectorAll("[data-fdel]").forEach(btn =>
      btn.addEventListener("click", () => {
        st.filters.splice(+btn.dataset.fdel, 1);
        renderFilters();
        draw();
      }));
  }

  function filteredList() {
    if (!st.filters.length) return st.list;
    return st.list.filter(c => st.filters.every(f => pivotMatchFilter(c, f)));
  }

  /* ---------- 汇总 ---------- */

  function isDateField(key) {
    return (dimFields.find(x => x.key === key) || {}).type === "date";
  }

  function labelOf(key) {
    const f = dimFields.find(x => x.key === key);
    return f ? f.label : key;
  }

  function zoneLabel(keys) {
    return keys.map(labelOf).join(" / ");
  }

  function zoneBucket(c, keys, gran) {
    return keys.map(k => pivotBucket(c, k, isDateField(k) ? gran : null)).join(" / ");
  }

  function aggName() {
    const names = { count: "人数", distinct: "去重计数", sum: "求和", avg: "平均", max: "最大", min: "最小" };
    let n = names[st.agg] || "人数";
    if (st.agg !== "count" && st.aggField) n += `（${labelOf(st.aggField)}）`;
    return n;
  }

  function aggregate(items) {
    if (st.agg === "count") return items.length;
    if (st.agg === "distinct") {
      return new Set(items.map(c => pivotRawValue(c, st.aggField || st.rows[0])).filter(Boolean)).size;
    }
    const nums = items.map(c => parseFloat(pivotRawValue(c, st.aggField))).filter(n => !isNaN(n));
    if (!nums.length) return 0;
    if (st.agg === "sum") return +nums.reduce((a, b) => a + b, 0).toFixed(2);
    if (st.agg === "avg") return +(nums.reduce((a, b) => a + b, 0) / nums.length).toFixed(2);
    if (st.agg === "max") return Math.max(...nums);
    if (st.agg === "min") return Math.min(...nums);
    return 0;
  }

  function buildGrid() {
    const list = filteredList();
    const hasCols = st.cols.length > 0;

    const cellItems = new Map();   // `${r}\u0001${c}` -> items[]
    const rowItems = new Map();
    const colItems = new Map();
    for (const c of list) {
      const r = zoneBucket(c, st.rows, st.gran);
      const cl = hasCols ? zoneBucket(c, st.cols, st.colGran) : "值";
      const ck = r + "\u0001" + cl;
      (cellItems.get(ck) || cellItems.set(ck, []).get(ck)).push(c);
      (rowItems.get(r) || rowItems.set(r, []).get(r)).push(c);
      (colItems.get(cl) || colItems.set(cl, []).get(cl)).push(c);
    }

    let rows = [...rowItems.keys()];
    let cols = hasCols ? [...colItems.keys()] : ["值"];

    const rowVal = r => aggregate(rowItems.get(r) || []);
    const sorters = {
      value_desc: (a, b) => rowVal(b) - rowVal(a),
      value_asc: (a, b) => rowVal(a) - rowVal(b),
      label_asc: (a, b) => String(a).localeCompare(String(b), "zh"),
      label_desc: (a, b) => String(b).localeCompare(String(a), "zh"),
    };
    // 首字段为日期时默认按名称（时间）排序更符合直觉
    if (isDateField(st.rows[0]) && st.sort.startsWith("value") && st.sort === "value_desc" && !st._userSorted) {
      rows.sort(sorters.label_asc);
    } else {
      rows.sort(sorters[st.sort] || sorters.value_desc);
    }
    cols.sort((a, b) => String(a).localeCompare(String(b), "zh"));

    const topN = +st.topN;
    let truncated = 0;
    if (topN > 0 && rows.length > topN) {
      truncated = rows.length - topN;
      rows = rows.slice(0, topN);
    }

    const matrix = cols.map(cl => rows.map(r =>
      aggregate(cellItems.get(r + "\u0001" + cl) || [])));
    const rowTotals = rows.map(r => aggregate(rowItems.get(r) || []));
    const colTotals = cols.map(cl => aggregate(colItems.get(cl) || []));
    const grand = aggregate(list);

    return { rows, cols: hasCols ? cols : null, matrix, rowTotals, colTotals, grand, total: list.length, truncated };
  }

  /* ---------- 绘制 ---------- */

  function draw() {
    $$('[data-pv="gran"]').classList.toggle("hidden", !st.rows.some(isDateField));
    $$('[data-pv="aggField"]').classList.toggle("hidden", st.agg === "count");

    const grid = buildGrid();
    lastGrid = grid;
    $$("[data-pv-count]").textContent = `${grid.total} 人`;
    $$("[data-pv-title]").textContent =
      `${zoneLabel(st.rows)}${st.cols.length ? " × " + zoneLabel(st.cols) : ""} · ${aggName()}` +
      (st.filters.length ? `（已筛 ${st.filters.length} 条件）` : "");
    drawChart(grid);
    drawTable(grid);
  }

  function drawChart(grid) {
    const showChart = st.view !== "table";
    $$("[data-pv-chartcard]").classList.toggle("hidden", !showChart);
    if (st.chart) { st.chart.destroy(); st.chart = null; }
    if (!showChart) return;
    const ctx = $$("[data-pv-canvas]").getContext("2d");
    const baseFont = { family: "'Segoe UI','Microsoft YaHei',sans-serif", size: 12 };

    if (st.view === "doughnut") {
      const data = grid.cols ? grid.colTotals : grid.matrix[0];
      const labels = grid.cols || grid.rows;
      const total = data.reduce((a, b) => a + b, 0) || 1;
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
            tooltip: { callbacks: { label: c =>
              ` ${c.label}：${c.parsed}（${(c.parsed * 100 / total).toFixed(1)}%）` } },
          },
        },
      });
      return;
    }

    const stacked = st.view === "stacked";
    const type = st.view === "line" ? "line" : "bar";
    st.chart = new Chart(ctx, {
      type,
      data: {
        labels: grid.rows,
        datasets: (grid.cols || [aggName()]).map((s, i) => ({
          label: s, data: grid.matrix[i],
          backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + (type === "line" ? "" : "cc"),
          borderColor: CHART_COLORS[i % CHART_COLORS.length],
          borderRadius: type === "bar" ? 6 : 0, borderSkipped: false,
          maxBarThickness: 46, tension: 0.3,
          fill: false,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: {
          x: { stacked, grid: { display: false }, ticks: { font: baseFont },
               title: { display: true, text: zoneLabel(st.rows), font: baseFont, color: "#64748b" } },
          y: { stacked, beginAtZero: true, grid: { color: "rgba(148,163,184,.18)" },
               ticks: { font: baseFont },
               title: { display: true, text: aggName(), font: baseFont, color: "#64748b" } },
        },
        plugins: {
          legend: { display: !!grid.cols, position: "bottom",
                    title: grid.cols ? { display: true, text: zoneLabel(st.cols), font: baseFont } : undefined,
                    labels: { font: baseFont, usePointStyle: true } },
          tooltip: { callbacks: { label: c => ` ${c.dataset.label}：${c.parsed.y ?? c.parsed}` } },
        },
      },
    });
  }

  function pctCell(v, ri, ci, grid) {
    if (st.pct === "none") return "";
    let base = 0;
    if (st.pct === "grand") base = grid.grand;
    else if (st.pct === "row") base = grid.rowTotals[ri];
    else if (st.pct === "col") base = grid.colTotals[ci];
    if (!base) return "";
    return `<span class="pv-pct">${(v * 100 / base).toFixed(1)}%</span>`;
  }

  function drawTable(grid) {
    const heads = grid.cols || [aggName()];
    $$("[data-pv-table]").innerHTML = `
      <div class="table-wrap"><table class="pv-table" style="min-width:0">
        <thead><tr>
          <th>${esc(zoneLabel(st.rows))}</th>
          ${heads.map(h => `<th>${esc(h)}</th>`).join("")}
          ${grid.cols ? `<th>合计</th>` : ""}
        </tr></thead>
        <tbody>
          ${grid.rows.map((r, ri) => `<tr>
            <td>${esc(r)}</td>
            ${heads.map((_, ci) => {
              const v = grid.matrix[ci][ri] || 0;
              return `<td>${v}${pctCell(v, ri, ci, grid)}</td>`;
            }).join("")}
            ${grid.cols ? `<td><b>${grid.rowTotals[ri]}</b></td>` : ""}
          </tr>`).join("")}
          <tr class="pv-total-row">
            <td><b>合计</b></td>
            ${grid.colTotals.slice(0, heads.length).map(t => `<td><b>${t}</b></td>`).join("")}
            ${grid.cols ? `<td><b>${grid.grand}</b></td>` : ""}
          </tr>
        </tbody>
      </table></div>
      ${grid.truncated ? `<p class="muted" style="font-size:12px;margin:6px 0 0">已按 Top ${st.topN} 截断，其余 ${grid.truncated} 项未显示（选择 Top「全部」可展开）。</p>` : ""}`;
  }

  function exportCsv() {
    if (!lastGrid) return;
    const g = lastGrid;
    const heads = g.cols || [aggName()];
    const lines = [[zoneLabel(st.rows), ...heads, g.cols ? "合计" : null].filter(x => x !== null)];
    g.rows.forEach((r, ri) => {
      const row = [r, ...heads.map((_, ci) => g.matrix[ci][ri] || 0)];
      if (g.cols) row.push(g.rowTotals[ri]);
      lines.push(row);
    });
    const totals = ["合计", ...g.colTotals.slice(0, heads.length)];
    if (g.cols) totals.push(g.grand);
    lines.push(totals);
    const csv = "\ufeff" + lines.map(l =>
      l.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `数据看板_${zoneLabel(st.rows)}${st.cols.length ? "_x_" + zoneLabel(st.cols) : ""}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ---------- 事件 ---------- */

  rootEl.querySelectorAll("[data-pv]").forEach(sel =>
    sel.addEventListener("change", () => {
      st[sel.dataset.pv] = sel.value;
      if (sel.dataset.pv === "sort") st._userSorted = true;
      draw();
    }));
  $$("[data-pv-addfilter]").addEventListener("click", () => {
    st.filters.push({ key: dimFields[0].key, op: "eq", val: "" });
    renderFilters();
  });
  $$("[data-pv-export]").addEventListener("click", exportCsv);

  renderZones();
  await loadData();
  renderFilters();
}
