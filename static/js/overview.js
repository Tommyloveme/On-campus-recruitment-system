"use strict";

/* 全局总览页 */
async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  const fields = visibleFields("onboarding").slice(0, 8);
  const totals = groups.reduce((acc, g) => {
    acc.total += g.stats.total; acc.signed += g.stats.signed;
    acc.onboarded += g.stats.onboarded; acc.high_risk += g.stats.high_risk;
    return acc;
  }, { total: 0, signed: 0, onboarded: 0, high_risk: 0 });

  const summary = `
    <div class="card">
      <div class="group-title">全部分组汇总</div>
      <div class="stat-row">
        <div class="stat"><b>${totals.total}</b>候选人总数</div>
        <div class="stat"><b>${totals.signed}</b>已签约</div>
        <div class="stat"><b>${totals.onboarded}</b>已入职</div>
        <div class="stat"><b style="color:#dc2626">${totals.high_risk}</b>高风险</div>
        <div class="stat"><b>${groups.length}</b>权限分组数</div>
      </div>
    </div>`;

  const sections = groups.map(grp => {
    const rows = grp.candidates.map(c => `
      <tr>
        ${fields.map(f => `<td>${cellHtml(f, c.data[f.key])}</td>`).join("")}
        <td class="latest-log" title="${esc(c.latest_log)}">${esc(c.latest_log)}</td>
      </tr>`).join("");
    return `
      <div class="card">
        <div class="group-title">${esc(grp.group_name)}
          <span class="badge badge-blue">${grp.stats.total} 人</span>
          <span class="badge badge-green">已签约 ${grp.stats.signed}</span>
          <span class="badge badge-gray">已入职 ${grp.stats.onboarded}</span>
          ${grp.stats.high_risk ? `<span class="badge badge-red">高风险 ${grp.stats.high_risk}</span>` : ""}
        </div>
        ${grp.candidates.length ? `
        <div class="table-wrap">
          <table>
            <thead><tr>${fields.map(f => `<th>${esc(f.label)}</th>`).join("")}<th>最新进展</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>` : `<div class="empty">该分组暂无候选人</div>`}
      </div>`;
  }).join("");

  $("#main").innerHTML = summary + (sections || `<div class="empty">尚未创建任何分组</div>`);
}
