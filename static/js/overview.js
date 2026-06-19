"use strict";

/* 全局总览页 */
async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  const grp = groups[0] || { stats: {}, candidates: [] };
  const fields = visibleFields("onboarding").slice(0, 8);
  const totals = grp.stats || {};

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

  $("#main").innerHTML = summary + section;
}
