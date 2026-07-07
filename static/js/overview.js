"use strict";

/* 全局总览页 */
async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  const grp = groups[0] || { stats: {}, candidates: [], dashboard: {} };
  const fields = visibleFields("onboarding").slice(0, 8);
  const totals = grp.stats || {};
  const dash = grp.dashboard || {};
  const stageCounts = dash.stage_counts || [];
  const passRates = dash.pass_rates || [];

  const summary = `
    <div class="card">
      <div class="group-title">候选人汇总</div>
      <div class="stat-row">
        <div class="stat"><b>${totals.total || 0}</b>候选人总数</div>
        <div class="stat"><b>${totals.signed || 0}</b>已签约</div>
        <div class="stat"><b>${totals.onboarded || 0}</b>已入职</div>
        <div class="stat"><b style="color:#dc2626">${totals.high_risk || 0}</b>高风险</div>
      </div>
    </div>`;

  const stageCountRows = stageCounts.map(s => `
    <tr>
      <td>${esc(s.label)}</td>
      <td><span class="badge badge-blue">${s.count}</span></td>
    </tr>`).join("");

  const stageCountSection = `
    <div class="card">
      <div class="group-title">各流程当前人数</div>
      ${stageCounts.length ? `
      <div class="table-wrap">
        <table class="overview-mini-table">
          <thead><tr><th>流程</th><th>人数</th></tr></thead>
          <tbody>${stageCountRows}</tbody>
        </table>
      </div>` : `<div class="empty">暂无数据</div>`}
    </div>`;

  const passRateRows = passRates.map(p => {
    const rateText = p.rate_pct != null ? `${p.rate_pct}%` : "—";
    const sub = `参与 ${p.entered} · 通过 ${p.passed} · 未通过 ${p.failed}${p.pending ? ` · 进行中 ${p.pending}` : ""}`;
    return `
    <tr>
      <td>${esc(p.label)}</td>
      <td><strong>${rateText}</strong></td>
      <td class="text-muted">${esc(sub)}</td>
    </tr>`;
  }).join("");

  const passRateSection = `
    <div class="card">
      <div class="group-title" title="通过率 = 已通过 ÷（已通过 + 未通过），不含进行中/未开始">各流程通过率 <span class="muted" style="font-weight:400;font-size:12px;cursor:help">ⓘ</span></div>
      ${passRates.length ? `
      <div class="table-wrap">
        <table class="overview-mini-table">
          <thead><tr><th>流程</th><th>通过率</th><th>明细</th></tr></thead>
          <tbody>${passRateRows}</tbody>
        </table>
      </div>` : `<div class="empty">暂无数据</div>`}
    </div>`;

  const rows = (grp.candidates || []).map(c => `
    <tr>
      ${fields.map(f => `<td>${cellHtml(f, c.data[f.key])}</td>`).join("")}
      <td class="latest-log" title="${esc(c.latest_log)}">${esc(c.latest_log)}</td>
    </tr>`).join("");

  const section = `
    <div class="card">
      <div class="group-title">全部候选人
        <span class="badge badge-blue">${totals.total || 0} 人</span>
        <span class="badge badge-green">已签约 ${totals.signed || 0}</span>
        <span class="badge badge-gray">已入职 ${totals.onboarded || 0}</span>
        ${totals.high_risk ? `<span class="badge badge-red">高风险 ${totals.high_risk}</span>` : ""}
      </div>
      ${grp.candidates?.length ? `
      <div class="table-wrap">
        <table>
          <thead><tr>${fields.map(f => `<th>${esc(f.label)}</th>`).join("")}<th>最新进展</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>` : `<div class="empty">暂无候选人</div>`}
    </div>`;

  $("#main").innerHTML = summary
    + `<div class="overview-dashboard-grid">${stageCountSection}${passRateSection}</div>`
    + section;
}
