"use strict";

/* 全局总览页：筛选条件置顶，KPI / 流程漏斗 / SLA 停留时长 / 通过率 / 候选人明细
 * 全部基于同一份筛选结果联动刷新。 */

const OV_OPS = [
  ["eq", "等于"], ["ne", "不等于"], ["contains", "包含"],
  ["not_contains", "不包含"], ["empty", "为空"], ["not_empty", "非空"],
];

const ovState = {
  grp: null,
  filters: [],        // {key, op, val}（与数据看板一致的多条件叠加，AND 关系）
  stageFilter: "",    // 流程快捷筛选（漏斗行点击 / 下拉）
  sortKey: "stay_days",
  sortDir: "desc",
};

function ovFields() {
  // 组合筛选字段以「候选人登记」页字段为准
  const seen = new Set();
  const out = [];
  for (const f of fieldsForStage("registration")) {
    if (!seen.has(f.key)) { seen.add(f.key); out.push(f); }
  }
  return out;
}

function ovValue(c, key) {
  const v = c.data?.[key];
  if (v !== undefined && v !== null && String(v).trim() !== "") return String(v).trim();
  if (key === "当前流程") return String(c.current_stage || "").trim();
  return "";
}

function ovMatch(c, flt) {
  const v = ovValue(c, flt.key);
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

function ovStageLabel(key) {
  const s = state.stages.find(x => x.key === key);
  return s ? (s.short_label || s.label) : (key || "—");
}

function ovSlaBadge(c) {
  const days = c.stay_days ?? 0;
  if (c.sla_status === "overdue") return `<span class="badge badge-red" title="超过 SLA 上限">${days} 天 · 超期</span>`;
  if (c.sla_status === "warn") return `<span class="badge badge-yellow" title="接近 SLA 上限">${days} 天 · 预警</span>`;
  return `<span class="badge badge-green">${days} 天</span>`;
}

function ovFilteredCandidates() {
  let list = ovState.grp.candidates || [];
  if (ovState.stageFilter) list = list.filter(c => c.current_stage === ovState.stageFilter);
  if (ovState.filters.length) list = list.filter(c => ovState.filters.every(f => ovMatch(c, f)));
  return list;
}

async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  ovState.grp = groups[0] || { stats: {}, candidates: [], dashboard: {}, stage_dwell: [], sla_config: {} };
  ovState.filters = [];
  ovState.stageFilter = "";
  ovRenderShell();
}

/* ---------- 页面骨架（筛选置顶 + 各联动区块占位） ---------- */

function ovRenderShell() {
  $("#main").innerHTML = `
    <div class="page-wrap">
    <div class="card pagehead">
      <div class="pagehead-text">
        <div class="pagehead-title">全局总览</div>
        <div class="pagehead-sub">跨流程的候选人分布、停留时长与通过率概览；顶部按登记字段组合筛选后所有数据联动刷新</div>
      </div>
      <div class="pagehead-side"><span class="badge badge-blue" data-ov-listcount></span></div>
    </div>

    <div class="card page-section">
      <div class="page-section-head">
        <div class="page-section-title">筛选条件
          <span data-ov-activefilters class="page-section-sub"></span></div>
        <div class="perm-head-actions">
          <button class="btn btn-sm" data-ov-export>导出明细 Excel</button>
          <button class="btn btn-sm" data-ov-clear>清空筛选</button>
        </div>
      </div>
      <div class="page-section-body">
        <div class="pv-filters" style="margin:0;padding-top:0;border-top:none">
          <div class="pv-group">
            <span class="pv-cap">流程</span>
            <select data-ov-stagesel>
              <option value="">全部流程</option>
              ${state.stages.map(s => `<option value="${esc(s.key)}">${esc(s.short_label || s.label)}</option>`).join("")}
            </select>
          </div>
          <span class="pv-cap">筛选</span>
          <div class="pv-filter-list" data-ov-filterlist></div>
          <button class="btn btn-sm" data-ov-addfilter>+ 条件</button>
        </div>
      </div>
    </div>

    <div data-ov-kpis></div>

    <div class="card page-section">
      <div class="page-section-head">
        <div class="page-section-title">流程漏斗
          <span class="page-section-sub">点击流程行可快捷筛选</span></div>
      </div>
      <div class="page-section-body" data-ov-funnel></div>
    </div>

    <div class="overview-dashboard-grid">
      <div class="card page-section">
        <div class="page-section-head" title="停留时长 = 候选人进入当前流程至今的天数">
          <div class="page-section-title">各流程停留时长</div>
        </div>
        <div class="page-section-body" data-ov-sla></div>
      </div>
      <div class="card page-section">
        <div class="page-section-head" title="通过率 = 已通过 ÷（已通过 + 未通过），不含进行中/未开始">
          <div class="page-section-title">各流程通过率
            <span class="page-section-sub">不含进行中 / 未开始</span></div>
        </div>
        <div class="page-section-body" data-ov-passrate></div>
      </div>
    </div>

    <div class="card page-section">
      <div class="page-section-head">
        <div class="page-section-title">候选人明细</div>
      </div>
      <div class="page-section-body"><div data-ov-table></div></div>
    </div>
    </div>`;

  document.querySelector("[data-ov-stagesel]").addEventListener("change", e => {
    ovState.stageFilter = e.target.value;
    ovRefresh();
  });
  document.querySelector("[data-ov-addfilter]").addEventListener("click", () => {
    const flds = ovFields();
    ovState.filters.push({ key: flds[0]?.key || "候选人", op: "contains", val: "" });
    ovRenderFilters();
  });
  document.querySelector("[data-ov-clear]").addEventListener("click", () => {
    ovState.filters = [];
    ovState.stageFilter = "";
    document.querySelector("[data-ov-stagesel]").value = "";
    ovRenderFilters();
  });
  document.querySelector("[data-ov-export]").addEventListener("click", () => {
    const ids = ovFilteredCandidates().map(c => c.id);
    if (!ids.length) { toast("当前筛选结果为空", true); return; }
    exportByProfile("overview", ids);
  });

  ovRenderFilters();
}

/* ---------- 条件筛选 UI ---------- */

function ovRenderFilters() {
  const listEl = document.querySelector("[data-ov-filterlist]");
  if (!listEl) return;
  const flds = ovFields();
  const fieldOpts = selected => flds.map(f =>
    `<option value="${esc(f.key)}"${f.key === selected ? " selected" : ""}>${esc(f.label)}</option>`).join("");
  const cands = ovState.grp.candidates || [];

  listEl.innerHTML = ovState.filters.map((flt, i) => {
    const noVal = flt.op === "empty" || flt.op === "not_empty";
    const vals = [...new Set(cands.map(c => ovValue(c, flt.key)).filter(Boolean))].sort();
    return `
    <span class="pv-filter" data-fi="${i}">
      <select data-fpart="key">${fieldOpts(flt.key)}</select>
      <select data-fpart="op">${OV_OPS.map(([v, l]) =>
        `<option value="${v}"${flt.op === v ? " selected" : ""}>${l}</option>`).join("")}</select>
      ${noVal ? "" : `
      <input list="ov-vals-${i}" data-fpart="val" value="${esc(flt.val)}" placeholder="值">
      <datalist id="ov-vals-${i}">${vals.slice(0, 60).map(v => `<option value="${esc(v)}">`).join("")}</datalist>`}
      <button class="pv-filter-del" data-fdel="${i}" title="删除条件">×</button>
    </span>`;
  }).join("");

  listEl.querySelectorAll("[data-fpart]").forEach(el => {
    const idx = +el.closest("[data-fi]").dataset.fi;
    const part = el.dataset.fpart;
    const handler = () => {
      ovState.filters[idx][part] = el.value;
      if (part === "op" || part === "key") ovRenderFilters();
      else ovRefresh();
    };
    el.addEventListener("change", handler);
    if (el.tagName === "INPUT") el.addEventListener("input", debounce(handler, 300));
  });
  listEl.querySelectorAll("[data-fdel]").forEach(btn =>
    btn.addEventListener("click", () => {
      ovState.filters.splice(+btn.dataset.fdel, 1);
      ovRenderFilters();
    }));

  ovRefresh();
}

/* ---------- 联动刷新：所有区块基于同一筛选结果重算 ---------- */

function ovRefresh() {
  const list = ovFilteredCandidates();
  const all = ovState.grp.candidates || [];

  const countEl = document.querySelector("[data-ov-listcount]");
  if (countEl) countEl.textContent = `${list.length} / ${all.length} 人`;
  const afEl = document.querySelector("[data-ov-activefilters]");
  if (afEl) {
    const parts = [];
    if (ovState.stageFilter) parts.push(`流程=${ovStageLabel(ovState.stageFilter)}`);
    if (ovState.filters.length) parts.push(`${ovState.filters.length} 个条件`);
    afEl.textContent = parts.length ? `（${parts.join("，")}）` : "（未筛选，显示全部）";
  }

  ovDrawKpis(list);
  ovDrawFunnel(list);
  ovDrawSla(list);
  ovDrawPassRate(list);
  ovDrawTable(list);
}

function ovDrawKpis(list) {
  const el = document.querySelector("[data-ov-kpis]");
  if (!el) return;
  const stats = { total: list.length, signed: 0, onboarded: 0, high_risk: 0, sla_overdue: 0 };
  for (const c of list) {
    if (c.flags?.signed) stats.signed++;
    if (c.flags?.onboarded) stats.onboarded++;
    if (c.flags?.high_risk) stats.high_risk++;
    if (c.sla_status === "overdue") stats.sla_overdue++;
  }
  el.innerHTML = `
    <div class="ov-kpis" style="margin-bottom:0">
      <div class="ov-kpi"><div class="ov-kpi-num">${stats.total}</div><div class="ov-kpi-cap">候选人</div></div>
      <div class="ov-kpi"><div class="ov-kpi-num" style="color:#16a34a">${stats.signed}</div><div class="ov-kpi-cap">已签约</div></div>
      <div class="ov-kpi"><div class="ov-kpi-num" style="color:#2563eb">${stats.onboarded}</div><div class="ov-kpi-cap">已入职</div></div>
      <div class="ov-kpi"><div class="ov-kpi-num" style="color:#dc2626">${stats.high_risk}</div><div class="ov-kpi-cap">高风险</div></div>
      <div class="ov-kpi"><div class="ov-kpi-num" style="color:#d97706">${stats.sla_overdue}</div><div class="ov-kpi-cap">SLA 超期</div></div>
    </div>`;
}

function ovDrawFunnel(list) {
  const el = document.querySelector("[data-ov-funnel]");
  if (!el) return;
  const counts = {};
  for (const c of list) counts[c.current_stage || "registration"] = (counts[c.current_stage || "registration"] || 0) + 1;
  const maxCount = Math.max(1, ...Object.values(counts));
  el.innerHTML = `
    <div class="ov-funnel">
      ${state.stages.map(s => {
        const n = counts[s.key] || 0;
        return `
        <div class="ov-funnel-row${ovState.stageFilter === s.key ? " active" : ""}" data-ov-stage="${esc(s.key)}" title="点击筛选「${esc(s.label)}」">
          <span class="ov-funnel-label">${esc(s.short_label || s.label)}</span>
          <div class="ov-funnel-track">
            <div class="ov-funnel-bar" style="width:${Math.max(2, n * 100 / maxCount)}%"></div>
          </div>
          <span class="ov-funnel-count">${n}</span>
        </div>`;
      }).join("")}
    </div>`;
  el.querySelectorAll("[data-ov-stage]").forEach(row =>
    row.addEventListener("click", () => {
      const k = row.dataset.ovStage;
      ovState.stageFilter = ovState.stageFilter === k ? "" : k;
      document.querySelector("[data-ov-stagesel]").value = ovState.stageFilter;
      ovRefresh();
    }));
}

function ovDrawSla(list) {
  const el = document.querySelector("[data-ov-sla]");
  if (!el) return;
  const agg = {};
  for (const c of list) {
    const k = c.current_stage || "registration";
    const a = agg[k] || (agg[k] = { count: 0, total: 0, max: 0 });
    a.count++;
    a.total += c.stay_days || 0;
    a.max = Math.max(a.max, c.stay_days || 0);
  }
  const rows = state.stages.map(s => {
    const a = agg[s.key] || { count: 0, total: 0, max: 0 };
    return `
    <tr>
      <td>${esc(s.short_label || s.label)}</td>
      <td>${a.count}</td>
      <td>${a.count ? (a.total / a.count).toFixed(1) : 0}</td>
      <td>${a.max.toFixed ? a.max.toFixed(1) : a.max}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `
    <div class="table-wrap">
      <table class="overview-mini-table">
        <thead><tr><th>流程</th><th>人数</th><th>平均停留(天)</th><th>最长停留(天)</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function ovDrawPassRate(list) {
  const el = document.querySelector("[data-ov-passrate]");
  if (!el) return;
  const stats = {};
  for (const c of list) {
    for (const [sk, cls] of Object.entries(c.stage_status || {})) {
      const a = stats[sk] || (stats[sk] = { entered: 0, passed: 0, failed: 0, pending: 0 });
      a.entered++;
      if (cls === "pass") a.passed++;
      else if (cls === "fail") a.failed++;
      else if (cls === "pending") a.pending++;
    }
  }
  const rows = state.stages.filter(s => stats[s.key] || (ovState.grp.dashboard?.pass_rates || []).some(p => p.key === s.key)).map(s => {
    const a = stats[s.key] || { entered: 0, passed: 0, failed: 0, pending: 0 };
    const decided = a.passed + a.failed;
    const rate = decided ? (a.passed * 100 / decided).toFixed(1) + "%" : "—";
    return `
    <tr>
      <td>${esc(s.short_label || s.label)}</td>
      <td><strong>${rate}</strong></td>
      <td class="text-muted">参与 ${a.entered} · 通过 ${a.passed} · 未通过 ${a.failed}${a.pending ? ` · 进行中 ${a.pending}` : ""}</td>
    </tr>`;
  }).join("");
  el.innerHTML = rows ? `
    <div class="table-wrap">
      <table class="overview-mini-table">
        <thead><tr><th>流程</th><th>通过率</th><th>明细</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>` : `<div class="empty">暂无数据</div>`;
}

function ovDrawTable(list) {
  const el = document.querySelector("[data-ov-table]");
  if (!el) return;

  const sk = ovState.sortKey;
  const dir = ovState.sortDir === "asc" ? 1 : -1;
  list = [...list].sort((a, b) => {
    let av, bv;
    if (sk === "stay_days") { av = a.stay_days ?? 0; bv = b.stay_days ?? 0; }
    else if (sk === "current_stage") { av = a.current_stage || ""; bv = b.current_stage || ""; }
    else { av = ovValue(a, sk); bv = ovValue(b, sk); }
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "zh") * dir;
  });

  const cols = [
    ["候选人", "候选人"], ["电话", "电话"], ["current_stage", "当前流程"],
    ["stay_days", "停留时长"], ["学历", "学历"], ["毕业院校", "毕业院校"],
    ["拟录取工作地", "工作地"],
  ];
  const arrow = k => ovState.sortKey === k ? (ovState.sortDir === "asc" ? " ↑" : " ↓") : "";

  el.innerHTML = list.length ? `
    <div class="table-wrap">
      <table>
        <thead><tr>
          ${cols.map(([k, l]) =>
            `<th class="sortable" data-ov-sort="${esc(k)}" title="点击排序">${esc(l)}${arrow(k)}</th>`).join("")}
          <th>最新进展</th>
        </tr></thead>
        <tbody>
          ${list.map(c => `
          <tr>
            <td><b>${esc(ovValue(c, "候选人") || "—")}</b></td>
            <td class="mono">${esc(ovValue(c, "电话"))}</td>
            <td><span class="badge badge-blue">${esc(ovStageLabel(c.current_stage))}</span></td>
            <td>${ovSlaBadge(c)}</td>
            <td>${esc(ovValue(c, "学历"))}</td>
            <td>${esc(ovValue(c, "毕业院校"))}</td>
            <td>${esc(ovValue(c, "拟录取工作地"))}</td>
            <td class="latest-log" title="${esc(c.latest_log)}">${esc(c.latest_log)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>` : `<div class="empty">没有符合条件的候选人</div>`;

  el.querySelectorAll("[data-ov-sort]").forEach(th =>
    th.addEventListener("click", () => {
      const k = th.dataset.ovSort;
      if (ovState.sortKey === k) ovState.sortDir = ovState.sortDir === "asc" ? "desc" : "asc";
      else { ovState.sortKey = k; ovState.sortDir = k === "stay_days" ? "desc" : "asc"; }
      ovDrawTable(ovFilteredCandidates());
    }));
}
