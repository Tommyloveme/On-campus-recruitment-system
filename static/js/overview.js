"use strict";

/* 全局总览页：KPI 卡片 + 流程漏斗 + SLA 停留时长 + 通过率 + 多条件筛选候选人明细 */

const OV_OPS = [
  ["eq", "等于"], ["ne", "不等于"], ["contains", "包含"],
  ["not_contains", "不包含"], ["empty", "为空"], ["not_empty", "非空"],
];

const ovState = {
  grp: null,
  filters: [],        // {key, op, val}
  stageFilter: "",    // 点击漏斗某流程后过滤
  slaFilter: "",      // ok / warn / overdue
  sortKey: "stay_days",
  sortDir: "desc",
};

function ovFields() {
  const seen = new Set();
  const out = [];
  for (const s of state.stages) {
    for (const f of fieldsForStage(s.key)) {
      if (!seen.has(f.key)) { seen.add(f.key); out.push(f); }
    }
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

async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  ovState.grp = groups[0] || { stats: {}, candidates: [], dashboard: {}, stage_dwell: [] };
  ovState.filters = [];
  ovState.stageFilter = "";
  ovState.slaFilter = "";
  ovRenderShell();
}

function ovRenderShell() {
  const grp = ovState.grp;
  const totals = grp.stats || {};
  const dash = grp.dashboard || {};
  const stageCounts = dash.stage_counts || [];
  const passRates = dash.pass_rates || [];
  const dwell = grp.stage_dwell || [];
  const maxCount = Math.max(1, ...stageCounts.map(s => s.count));

  const kpis = `
    <div class="ov-kpis">
      <div class="ov-kpi" data-ov-kpi=""><div class="ov-kpi-num">${totals.total || 0}</div><div class="ov-kpi-cap">候选人总数</div></div>
      <div class="ov-kpi" data-ov-kpi="signed"><div class="ov-kpi-num" style="color:#16a34a">${totals.signed || 0}</div><div class="ov-kpi-cap">已签约</div></div>
      <div class="ov-kpi" data-ov-kpi="onboarded"><div class="ov-kpi-num" style="color:#2563eb">${totals.onboarded || 0}</div><div class="ov-kpi-cap">已入职</div></div>
      <div class="ov-kpi" data-ov-kpi="high_risk"><div class="ov-kpi-num" style="color:#dc2626">${totals.high_risk || 0}</div><div class="ov-kpi-cap">高风险</div></div>
      <div class="ov-kpi" data-ov-kpi="sla_overdue"><div class="ov-kpi-num" style="color:#d97706">${totals.sla_overdue || 0}</div><div class="ov-kpi-cap">SLA 超期</div></div>
    </div>`;

  const funnel = `
    <div class="card page-section">
      <div class="page-section-head">
        <div class="page-section-title">流程漏斗
          <span class="page-section-sub">点击流程可筛选下方明细</span></div>
      </div>
      <div class="page-section-body">
        <div class="ov-funnel">
          ${stageCounts.map(s => `
            <div class="ov-funnel-row${ovState.stageFilter === s.key ? " active" : ""}" data-ov-stage="${esc(s.key)}" title="点击筛选「${esc(s.label)}」">
              <span class="ov-funnel-label">${esc(s.short_label || s.label)}</span>
              <div class="ov-funnel-track">
                <div class="ov-funnel-bar" style="width:${Math.max(2, s.count * 100 / maxCount)}%"></div>
              </div>
              <span class="ov-funnel-count">${s.count}</span>
            </div>`).join("")}
        </div>
      </div>
    </div>`;

  const slaRows = dwell.map(d => {
    const tone = d.overdue ? "red" : (d.warn ? "yellow" : "green");
    return `
    <tr>
      <td>${esc(d.label)}</td>
      <td>${d.count}</td>
      <td>${d.avg_days}</td>
      <td>${d.max_days}</td>
      <td class="muted">≤${d.sla.warn_days} / ≤${d.sla.max_days} 天</td>
      <td>
        ${d.overdue ? `<span class="badge badge-red" data-ov-sla="overdue" data-ov-slastage="${esc(d.key)}" style="cursor:pointer" title="点击筛选超期候选人">超期 ${d.overdue}</span>` : ""}
        ${d.warn ? `<span class="badge badge-yellow" data-ov-sla="warn" data-ov-slastage="${esc(d.key)}" style="cursor:pointer" title="点击筛选预警候选人">预警 ${d.warn}</span>` : ""}
        ${!d.overdue && !d.warn ? `<span class="badge badge-${d.count ? "green" : "gray"}">${d.count ? "正常" : "—"}</span>` : ""}
      </td>
    </tr>`;
  }).join("");

  const slaSection = `
    <div class="card page-section">
      <div class="page-section-head" title="停留时长 = 候选人进入当前流程至今的天数；SLA 目标见 config/sla.json">
        <div class="page-section-title">各流程停留时长与 SLA
          <span class="page-section-sub">点击「超期 / 预警」徽标可筛选明细</span></div>
      </div>
      <div class="page-section-body">
        <div class="table-wrap">
          <table class="overview-mini-table">
            <thead><tr><th>流程</th><th>人数</th><th>平均停留(天)</th><th>最长停留(天)</th><th>SLA 目标</th><th>状态</th></tr></thead>
            <tbody>${slaRows}</tbody>
          </table>
        </div>
      </div>
    </div>`;

  const passRateRows = passRates.map(p => {
    const rateText = p.rate_pct != null ? `${p.rate_pct}%` : "—";
    return `
    <tr>
      <td>${esc(p.label)}</td>
      <td><strong>${rateText}</strong></td>
      <td class="text-muted">参与 ${p.entered} · 通过 ${p.passed} · 未通过 ${p.failed}${p.pending ? ` · 进行中 ${p.pending}` : ""}</td>
    </tr>`;
  }).join("");

  const passRateSection = `
    <div class="card page-section">
      <div class="page-section-head" title="通过率 = 已通过 ÷（已通过 + 未通过），不含进行中/未开始">
        <div class="page-section-title">各流程通过率
          <span class="page-section-sub">不含进行中 / 未开始</span></div>
      </div>
      <div class="page-section-body">
      ${passRates.length ? `
        <div class="table-wrap">
          <table class="overview-mini-table">
            <thead><tr><th>流程</th><th>通过率</th><th>明细</th></tr></thead>
            <tbody>${passRateRows}</tbody>
          </table>
        </div>` : `<div class="empty">暂无数据</div>`}
      </div>
    </div>`;

  $("#main").innerHTML = `
    <div class="page-wrap">
    <div class="card pagehead">
      <div class="pagehead-text">
        <div class="pagehead-title">全局总览</div>
        <div class="pagehead-sub">跨流程的候选人分布、SLA 停留时长与通过率概览，支持漏斗 / SLA / 多条件组合筛选</div>
      </div>
    </div>
    ${kpis}
    ${funnel}
    <div class="overview-dashboard-grid">${slaSection}${passRateSection}</div>
    <div class="card page-section">
      <div class="page-section-head">
        <div class="page-section-title">候选人明细
          <span class="badge badge-blue" data-ov-listcount></span>
          <span data-ov-activefilters class="page-section-sub"></span></div>
        <button class="btn btn-sm" data-ov-clear>清空筛选</button>
      </div>
      <div class="page-section-body">
        <div class="pv-filters" style="margin:0 0 10px;padding-top:0;border-top:none">
          <span class="pv-cap">筛选</span>
          <div class="pv-filter-list" data-ov-filterlist></div>
          <button class="btn btn-sm" data-ov-addfilter>+ 条件</button>
        </div>
        <div data-ov-table></div>
      </div>
    </div>
    </div>`;

  document.querySelectorAll("[data-ov-stage]").forEach(el =>
    el.addEventListener("click", () => {
      const k = el.dataset.ovStage;
      ovState.stageFilter = ovState.stageFilter === k ? "" : k;
      document.querySelectorAll("[data-ov-stage]").forEach(x =>
        x.classList.toggle("active", x.dataset.ovStage === ovState.stageFilter));
      ovDrawTable();
    }));
  document.querySelectorAll("[data-ov-sla]").forEach(el =>
    el.addEventListener("click", () => {
      ovState.slaFilter = el.dataset.ovSla;
      ovState.stageFilter = el.dataset.ovSlastage || "";
      document.querySelectorAll("[data-ov-stage]").forEach(x =>
        x.classList.toggle("active", x.dataset.ovStage === ovState.stageFilter));
      ovDrawTable();
    }));
  $("[data-ov-addfilter]") && document.querySelector("[data-ov-addfilter]").addEventListener("click", () => {
    const flds = ovFields();
    ovState.filters.push({ key: flds[0]?.key || "候选人", op: "contains", val: "" });
    ovRenderFilters();
  });
  document.querySelector("[data-ov-clear]").addEventListener("click", () => {
    ovState.filters = [];
    ovState.stageFilter = "";
    ovState.slaFilter = "";
    document.querySelectorAll("[data-ov-stage]").forEach(x => x.classList.remove("active"));
    ovRenderFilters();
  });

  ovRenderFilters();
}

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
      else ovDrawTable();
    };
    el.addEventListener("change", handler);
    if (el.tagName === "INPUT") el.addEventListener("input", debounce(handler, 300));
  });
  listEl.querySelectorAll("[data-fdel]").forEach(btn =>
    btn.addEventListener("click", () => {
      ovState.filters.splice(+btn.dataset.fdel, 1);
      ovRenderFilters();
    }));

  ovDrawTable();
}

function ovFilteredCandidates() {
  let list = ovState.grp.candidates || [];
  if (ovState.stageFilter) list = list.filter(c => c.current_stage === ovState.stageFilter);
  if (ovState.slaFilter) list = list.filter(c => c.sla_status === ovState.slaFilter);
  if (ovState.filters.length) list = list.filter(c => ovState.filters.every(f => ovMatch(c, f)));
  return list;
}

function ovDrawTable() {
  const el = document.querySelector("[data-ov-table]");
  if (!el) return;
  let list = ovFilteredCandidates();

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

  const countEl = document.querySelector("[data-ov-listcount]");
  if (countEl) countEl.textContent = `${list.length} / ${(ovState.grp.candidates || []).length} 人`;
  const afEl = document.querySelector("[data-ov-activefilters]");
  if (afEl) {
    const parts = [];
    if (ovState.stageFilter) parts.push(`流程=${ovStageLabel(ovState.stageFilter)}`);
    if (ovState.slaFilter) parts.push(`SLA=${{ warn: "预警", overdue: "超期", ok: "正常" }[ovState.slaFilter]}`);
    afEl.textContent = parts.length ? `（${parts.join("，")}）` : "";
  }

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
      ovDrawTable();
    }));
}
