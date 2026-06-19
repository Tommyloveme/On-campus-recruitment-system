/* 总览、图表、日志、系统管理页面 */
"use strict";

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

const charts = { list: [], instance: null };
const CHART_COLORS = [
  "#2563eb", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#84cc16", "#0ea5e9", "#f97316", "#14b8a6", "#64748b",
];

async function renderCharts() {
  const fields = allFieldsFlat().filter(f => f.type === "select" || f.type === "date");
  const fieldOpts = (selected) => [
    `<option value="__group"${selected === "__group" ? " selected" : ""}>二层部门</option>`,
    ...fields.map(f =>
      `<option value="${f.key}"${f.key === selected ? " selected" : ""}>${esc(f.label)}</option>`),
  ].join("");
  const dimOpts = fieldOpts("offer_status");
  const serOpts = `<option value="">（无）</option>` + fieldOpts("");
  const groupCtrl = isGroupAdmin()
    ? `<div class="chart-ctrl"><label>分组范围</label>
        <select id="ch-group" disabled><option value="${state.me.group_id}">${esc(state.me.group_name || "")}</option></select></div>`
    : `<div class="chart-ctrl"><label>分组范围</label>
        <select id="ch-group"><option value="">全部分组</option>
          ${state.groups.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}</select></div>`;

  $("#main").innerHTML = `
    <div class="card">
      <div class="toolbar" style="margin-bottom:0">
        ${groupCtrl}
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
  ["ch-group", "ch-dim", "ch-ser", "ch-type", "ch-gran"].forEach(id =>
    $("#" + id).addEventListener("change", drawChart));
  drawChart();
}

function isDateField(key) {
  const f = allFieldsFlat().find(f => f.key === key);
  return !!f && f.type === "date";
}

function chartValue(c, key, gran) {
  if (key === "__group") return c.group_name || "（无分组）";
  let v = c.data[key] || "（空）";
  if (gran && v !== "（空）" && isDateField(key)) {
    if (gran === "ym" && v.length >= 7) v = v.slice(0, 7);
    else if (gran === "m" && v.length >= 7) v = v.slice(5, 7) + "月";
  }
  return v;
}

function chartLabelOf(key) {
  if (key === "__group") return "二层部门";
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
  if (key === "__group") {
    values = state.groups.map(g => g.name).filter(n => counts.has(n));
    if (counts.has("（无分组）")) values.push("（无分组）");
  } else if (f && f.type === "date") {
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
  const gid = $("#ch-group").value;
  const dimKey = $("#ch-dim").value;
  let serKey = $("#ch-ser").value;
  const type = $("#ch-type").value;
  if (["pie", "doughnut"].includes(type)) serKey = "";

  const dimIsDate = isDateField(dimKey);
  $("#ch-gran-wrap").classList.toggle("hidden", !dimIsDate);
  const gran = dimIsDate ? $("#ch-gran").value : null;

  let list = charts.list;
  if (gid) list = list.filter(c => String(c.group_id) === gid);
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
  const groupName = gid ? (state.groups.find(g => String(g.id) === gid)?.name || "") : "全部分组";
  $("#ch-title").textContent =
    `${chartLabelOf(dimKey)}${granName ? "·" + granName : ""} 分布` +
    (serKey ? ` × ${chartLabelOf(serKey)}` : "") + `（${groupName}）`;

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

const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], export: ["导出", "yellow"], backup: ["备份", "gray"],
  user: ["用户", "gray"], group: ["分组", "gray"], config: ["配置", "gray"],
};

async function renderLogs(page = 1) {
  state.logPage = page;
  $("#main").innerHTML = `<div class="card"><div class="section-title">操作日志</div><div id="log-list" class="empty">加载中…</div></div>`;
  const r = await api(`/api/logs?page=${page}`);
  const items = r.items.map(l => {
    const [txt, color] = ACTION_BADGE[l.action] || ["操作", "gray"];
    return `
      <div class="log-item">
        <span class="log-time">${esc(l.created_at)}</span>
        <span class="badge badge-${color}">${txt}</span>
        <span class="log-msg">${esc(l.message)}</span>
      </div>`;
  }).join("");
  const pages = Math.max(1, Math.ceil(r.total / r.size));
  $("#log-list").className = "";
  $("#log-list").innerHTML = (items || `<div class="empty">暂无日志</div>`) + `
    <div class="pager">
      <button class="btn btn-sm" id="log-prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
      <span>第 ${page} / ${pages} 页（共 ${r.total} 条）</span>
      <button class="btn btn-sm" id="log-next" ${page >= pages ? "disabled" : ""}>下一页</button>
    </div>`;
  $("#log-prev").addEventListener("click", () => renderLogs(page - 1));
  $("#log-next").addEventListener("click", () => renderLogs(page + 1));
}

const fieldCfg = { scope: "", stage: "registration", fields: [] };

async function renderAdmin() {
  if (isGroupAdmin()) {
    $("#main").innerHTML = `
      <div class="admin-grid">
        <div class="card">
          <div class="section-title">成员管理 - ${esc(state.me.group_name || "")}</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">向本组添加「组成员」或「只读」账号（默认密码 123456）。</p>
          <div id="user-list"></div>
          <button class="btn btn-primary" id="btn-add-user" style="margin-top:12px">+ 添加本组成员</button>
        </div>
        <div class="card">
          <div class="section-title">本组字段显示配置</div>
          <div class="form-item" style="max-width:260px">
            <label>流程阶段</label>
            <select id="field-stage">
              ${state.stages.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join("")}
            </select>
          </div>
          <div class="check-grid" id="field-config"></div>
          <button class="btn btn-primary btn-sm" id="btn-save-fields" style="margin-top:12px">保存本组配置</button>
        </div>
      </div>`;
    await loadUserList();
    $("#btn-add-user").addEventListener("click", () => openUserModal(null));
    fieldCfg.scope = "self";
    fieldCfg.stage = "registration";
    await loadFieldConfigForAdmin();
    $("#field-stage").addEventListener("change", async e => {
      fieldCfg.stage = e.target.value;
      await loadFieldConfigForAdmin();
    });
    $("#btn-save-fields").addEventListener("click", saveFieldConfig);
    return;
  }

  $("#main").innerHTML = `
    <div class="admin-grid">
      <div>
        <div class="card">
          <div class="section-title">权限分组</div>
          <div id="group-list"></div>
          <div class="toolbar" style="margin:12px 0 0">
            <input type="text" id="new-group-name" placeholder="新分组名称">
            <button class="btn btn-primary" id="btn-add-group">添加</button>
          </div>
        </div>
        <div class="card">
          <div class="section-title">数据备份与恢复</div>
          <div id="backup-list" style="max-height:260px;overflow-y:auto"></div>
          <button class="btn btn-primary btn-sm" id="btn-backup-now" style="margin-top:12px">立即备份</button>
        </div>
        <div class="card">
          <div class="section-title">各阶段字段显示配置</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">字段定义在 config/stages/ 目录；此处仅配置各分组在各阶段的列显示开关。</p>
          <div class="form-item" style="max-width:260px">
            <label>流程阶段</label>
            <select id="field-stage">
              ${state.stages.map(s => `<option value="${s.key}">${esc(s.label)}</option>`).join("")}
            </select>
          </div>
          <div class="form-item" style="max-width:260px">
            <label>配置范围（分组）</label>
            <select id="field-scope">
              ${state.groups.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}
            </select>
          </div>
          <div class="check-grid" id="field-config"></div>
          <button class="btn btn-primary btn-sm" id="btn-save-fields" style="margin-top:12px">保存配置</button>
        </div>
      </div>
      <div class="card">
        <div class="section-title">用户管理</div>
        <div id="user-list"></div>
        <button class="btn btn-primary" id="btn-add-user" style="margin-top:12px">+ 新增用户</button>
      </div>
    </div>`;
  await Promise.all([loadGroupList(), loadUserList(), loadBackupList()]);
  $("#btn-backup-now").addEventListener("click", async () => {
    try {
      const r = await api("/api/backups", { method: "POST" });
      toast(`备份完成：${r.name}`);
      loadBackupList();
    } catch (e) { toast(e.message, true); }
  });
  fieldCfg.scope = state.groups[0]?.id || "";
  fieldCfg.stage = "registration";
  await loadFieldConfigForAdmin();
  $("#field-stage").addEventListener("change", async e => {
    fieldCfg.stage = e.target.value;
    await loadFieldConfigForAdmin();
  });
  $("#field-scope").addEventListener("change", async e => {
    fieldCfg.scope = e.target.value;
    await loadFieldConfigForAdmin();
  });
  $("#btn-add-group").addEventListener("click", async () => {
    const name = $("#new-group-name").value.trim();
    if (!name) { toast("请输入分组名称", true); return; }
    try {
      await api("/api/groups", { method: "POST", json: { name } });
      toast("分组已创建");
      $("#new-group-name").value = "";
      state.groups = await api("/api/groups");
      loadGroupList();
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-add-user").addEventListener("click", () => openUserModal(null));
  $("#btn-save-fields").addEventListener("click", saveFieldConfig);
}

async function loadFieldConfigForAdmin() {
  const gid = fieldCfg.scope === "self" ? state.me.group_id : fieldCfg.scope;
  const r = await api(`/api/config?stage=${fieldCfg.stage}&group_id=${gid}`);
  fieldCfg.fields = r.fields;
  renderFieldConfig();
}

function renderFieldConfig() {
  $("#field-config").innerHTML = fieldCfg.fields.map(f => `
    <label><input type="checkbox" data-fkey="${f.key}" ${f.visible ? "checked" : ""}> ${esc(f.label)}</label>`).join("");
}

async function saveFieldConfig() {
  const updates = [...$("#field-config").querySelectorAll("[data-fkey]")].map(el =>
    ({ key: el.dataset.fkey, visible: el.checked }));
  const gid = fieldCfg.scope === "self" ? state.me.group_id : +fieldCfg.scope;
  const payload = { fields: updates, stage: fieldCfg.stage, group_id: gid };
  try {
    const r = await api("/api/config", { method: "PUT", json: payload });
    fieldCfg.fields = r.fields;
    state.stageFields[fieldCfg.stage] = r.fields;
    toast("字段显示配置已保存");
  } catch (e) { toast(e.message, true); }
}

async function loadGroupList() {
  state.groups = await api("/api/groups");
  $("#group-list").innerHTML = state.groups.map(g => `
    <div class="tag-row">
      <span>${esc(g.name)} <span class="badge badge-gray">${g.candidate_count} 人</span></span>
      <button class="btn btn-sm btn-danger" data-gdel="${g.id}">删除</button>
    </div>`).join("") || `<div class="empty" style="padding:16px">暂无分组</div>`;
  $("#group-list").querySelectorAll("[data-gdel]").forEach(b =>
    b.addEventListener("click", async () => {
      try {
        await api(`/api/groups/${b.dataset.gdel}`, { method: "DELETE" });
        toast("分组已删除");
        loadGroupList();
      } catch (e) { toast(e.message, true); }
    }));
}

async function loadBackupList() {
  const items = await api("/api/backups");
  $("#backup-list").innerHTML = items.length ? items.map(b => `
    <div class="tag-row">
      <span title="${esc(b.name)}">
        ${esc(b.time)}
        <span class="badge badge-${b.manual ? "blue" : "gray"}">${b.manual ? "手动" : "自动"}</span>
        <span style="color:#94a3b8;font-size:12px">${b.size_kb} KB</span>
      </span>
      <button class="btn btn-sm" data-restore="${esc(b.name)}">恢复</button>
    </div>`).join("")
    : `<div class="empty" style="padding:16px">暂无备份</div>`;
  $("#backup-list").querySelectorAll("[data-restore]").forEach(btn =>
    btn.addEventListener("click", () => confirmRestore(btn.dataset.restore)));
}

function confirmRestore(name) {
  openModal("恢复数据确认",
    `<p>确定将系统数据恢复至备份 <b>${esc(name)}</b> 吗？</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="restore-confirm">确认恢复</button>`);
  $("#restore-confirm").addEventListener("click", async () => {
    try {
      const r = await api("/api/backups/restore", { method: "POST", json: { name } });
      toast(`已恢复至 ${r.restored}，正在刷新…`);
      closeModal();
      setTimeout(() => location.reload(), 1200);
    } catch (e) { toast(e.message, true); }
  });
}

async function loadUserList() {
  const users = await api("/api/users");
  const roleBadge = { admin: "red", global_viewer: "blue", group_admin: "yellow", editor: "blue", viewer: "gray" };
  const showOps = isAdmin();
  $("#user-list").innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>账号</th><th>姓名</th><th>角色</th><th>所属分组</th>${showOps ? "<th>操作</th>" : ""}</tr></thead>
      <tbody>
        ${users.map(u => `
          <tr>
            <td>${esc(u.username)}</td>
            <td>${esc(u.display_name)}</td>
            <td><span class="badge badge-${roleBadge[u.role] || "gray"}">${ROLE_NAMES[u.role] || u.role}</span></td>
            <td>${esc(u.group_name || "—")}</td>
            ${showOps ? `<td>
              <button class="btn btn-sm" data-uedit="${u.id}">编辑</button>
              ${u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}
            </td>` : ""}
          </tr>`).join("")}
      </tbody>
    </table></div>`;
  $("#user-list").querySelectorAll("[data-uedit]").forEach(b =>
    b.addEventListener("click", () => openUserModal(users.find(u => u.id === +b.dataset.uedit))));
  $("#user-list").querySelectorAll("[data-udel]").forEach(b =>
    b.addEventListener("click", async () => {
      try {
        await api(`/api/users/${b.dataset.udel}`, { method: "DELETE" });
        toast("用户已删除");
        loadUserList();
      } catch (e) { toast(e.message, true); }
    }));
}

function openUserModal(user) {
  const isNew = !user;
  const groupAdminMode = isGroupAdmin();
  const roleOptions = (groupAdminMode
    ? [["editor", "组成员"], ["viewer", "只读"]]
    : [["editor", "组成员"], ["group_admin", "组管理员"], ["viewer", "只读"],
       ["global_viewer", "全局查看员"], ["admin", "系统管理员"]])
    .map(([v, t]) => `<option value="${v}" ${user?.role === v ? "selected" : ""}>${t}</option>`).join("");
  const groupField = groupAdminMode
    ? `<input value="${esc(state.me.group_name || "")}" disabled>`
    : `<select id="u-group"><option value="">（无分组）</option>
        ${state.groups.map(g =>
          `<option value="${g.id}" ${user && user.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}
       </select>`;
  openModal(isNew ? (groupAdminMode ? "添加本组成员" : "新增用户") : `编辑用户 - ${esc(user.username)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>登录账号 *</label>
        <input id="u-username" value="${user ? esc(user.username) : ""}" ${isNew ? "" : "disabled"}></div>
      <div class="form-item"><label>显示姓名</label>
        <input id="u-display" value="${user ? esc(user.display_name) : ""}"></div>
      <div class="form-item"><label>密码 ${isNew ? "（默认 123456）" : "（留空则不修改）"}</label>
        <input id="u-password" type="${isNew ? "text" : "password"}" ${isNew ? `value="123456"` : ""}></div>
      <div class="form-item"><label>角色</label><select id="u-role">${roleOptions}</select></div>
      <div class="form-item"><label>所属权限分组</label>${groupField}</div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="u-save">保存</button>`);
  $("#u-save").addEventListener("click", async () => {
    const payload = {
      username: $("#u-username").value.trim(),
      display_name: $("#u-display").value.trim(),
      password: $("#u-password").value,
      role: $("#u-role").value,
      group_id: $("#u-group") && $("#u-group").value ? +$("#u-group").value : null,
    };
    try {
      if (isNew) await api("/api/users", { method: "POST", json: payload });
      else await api(`/api/users/${user.id}`, { method: "PUT", json: payload });
      toast("已保存");
      closeModal();
      loadUserList();
    } catch (e) { toast(e.message, true); }
  });
}
