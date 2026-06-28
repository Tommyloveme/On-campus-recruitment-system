"use strict";

/* 操作日志与系统管理 */
const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], export: ["导出", "yellow"], backup: ["备份", "gray"],
  user: ["用户", "gray"], config: ["配置", "gray"],
};

let adminUsersCache = [];

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

async function renderAdmin() {
  const title = isGroupAdmin() ? "成员管理" : "用户管理";
  const hint = isGroupAdmin()
    ? "添加「组成员」或「只读」账号（默认密码 123456）。"
    : "管理系统用户账号与角色。";

  $("#main").innerHTML = `
    <div class="admin-grid">
      <div class="card">
        <div class="section-title">${title}</div>
        <p style="font-size:12px;color:#64748b;margin-bottom:10px">${hint}</p>
        <div id="user-list"></div>
        <button class="btn btn-primary" id="btn-add-user" style="margin-top:12px">+ ${isGroupAdmin() ? "添加成员" : "新增用户"}</button>
      </div>
      ${isAdmin() ? `
      <div class="card">
        <div class="section-title">数据备份与恢复</div>
        <div id="backup-list" style="max-height:260px;overflow-y:auto"></div>
        <button class="btn btn-primary btn-sm" id="btn-backup-now" style="margin-top:12px">立即备份</button>
      </div>
      <div class="card">
        <div class="section-title">字段配置说明</div>
        <p style="font-size:12px;color:#64748b;line-height:1.8">
          各阶段列表列与导入字段请在 <code>config/stages/</code> 目录下的 JSON 文件中维护。
        </p>
      </div>` : ""}
    </div>`;

  await loadUserList();
  $("#btn-add-user").addEventListener("click", () => openUserModal(null));
  if (isAdmin()) {
    await loadBackupList();
    $("#btn-backup-now").addEventListener("click", async () => {
      try {
        const r = await api("/api/backups", { method: "POST" });
        toast(`备份完成：${r.name}`);
        loadBackupList();
      } catch (e) { toast(e.message, true); }
    });
  }
}

async function loadBackupList() {
  const backups = await api("/api/backups");
  $("#backup-list").innerHTML = backups.length
    ? backups.map(b => `
      <div class="backup-row">
        <span>${esc(b.name)}</span>
        <span class="muted">${esc(b.created_at)} · ${b.size_kb} KB</span>
        <button class="btn btn-sm btn-danger" data-restore="${esc(b.name)}">恢复</button>
      </div>`).join("")
    : `<div class="empty" style="padding:12px">暂无备份</div>`;
  $("#backup-list").querySelectorAll("[data-restore]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm(`确定恢复到备份「${b.dataset.restore}」？当前数据将被覆盖。`)) return;
      try {
        await api("/api/backups/restore", { method: "POST", json: { name: b.dataset.restore } });
        toast("备份已恢复，请刷新页面");
      } catch (e) { toast(e.message, true); }
    }));
}

function adminJobRoleOptions() {
  return (window.accountOptions && window.accountOptions.job_roles) ||
    ["拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA"];
}

function readUserTableFilters() {
  const root = $("#user-list");
  if (!root) return {};
  const jobRoles = [...root.querySelectorAll(".uf-job-role:checked")].map(cb => cb.value);
  return {
    username: (root.querySelector(".uf-username")?.value || "").trim().toLowerCase(),
    display_name: (root.querySelector(".uf-display")?.value || "").trim().toLowerCase(),
    supervisor: (root.querySelector(".uf-supervisor")?.value || "").trim().toLowerCase(),
    department: (root.querySelector(".uf-department")?.value || "").trim().toLowerCase(),
    role: root.querySelector(".uf-role")?.value || "",
    job_roles: jobRoles,
  };
}

function userMatchesFilters(u, f) {
  if (f.username && !u.username.toLowerCase().includes(f.username)) return false;
  if (f.display_name && !(u.display_name || "").toLowerCase().includes(f.display_name)) return false;
  if (f.supervisor && !(u.supervisor || "").toLowerCase().includes(f.supervisor)) return false;
  if (f.department && !(u.department || "").toLowerCase().includes(f.department)) return false;
  if (f.role && u.role !== f.role) return false;
  if (f.job_roles.length) {
    const roles = u.job_roles || [];
    if (!f.job_roles.some(r => roles.includes(r))) return false;
  }
  return true;
}

function renderUserTableBody(users, showOps) {
  const roleBadge = { admin: "red", global_viewer: "blue", group_admin: "yellow", editor: "blue", viewer: "gray" };
  const f = readUserTableFilters();
  const filtered = users.filter(u => userMatchesFilters(u, f));
  const tbody = $("#user-list tbody");
  if (!tbody) return;
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="${showOps ? 7 : 6}" class="empty" style="padding:16px">没有符合条件的用户</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(u => `
    <tr>
      <td>${esc(u.username)}</td>
      <td>${esc(u.display_name)}</td>
      <td>${esc(u.supervisor || "—")}</td>
      <td>${esc(u.department || "—")}</td>
      <td>${esc((u.job_roles || []).join("、") || "—")}</td>
      <td><span class="badge badge-${roleBadge[u.role] || "gray"}">${ROLE_NAMES[u.role] || u.role}</span></td>
      ${showOps ? `<td>
        <button class="btn btn-sm" data-uedit="${u.id}">编辑</button>
        ${isAdmin() && u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}
      </td>` : ""}
    </tr>`).join("");
  tbody.querySelectorAll("[data-uedit]").forEach(b =>
    b.addEventListener("click", () => openUserModal(adminUsersCache.find(u => u.id === +b.dataset.uedit))));
  tbody.querySelectorAll("[data-udel]").forEach(b =>
    b.addEventListener("click", async () => {
      try {
        await api(`/api/users/${b.dataset.udel}`, { method: "DELETE" });
        toast("用户已删除");
        loadUserList();
      } catch (e) { toast(e.message, true); }
    }));
}

async function loadUserList() {
  adminUsersCache = await api("/api/users");
  const roleBadge = { admin: "red", global_viewer: "blue", group_admin: "yellow", editor: "blue", viewer: "gray" };
  const showOps = isAdmin() || isGroupAdmin();
  const roleList = adminJobRoleOptions();
  const sysRoleOpts = isGroupAdmin()
    ? [["editor", "组成员"], ["viewer", "只读"]]
    : [["editor", "组成员"], ["group_admin", "组管理员"], ["viewer", "只读"],
       ["global_viewer", "全局查看员"], ["admin", "系统管理员"]];
  const jobRoleFilter = roleList.map(role =>
    `<label class="checkbox-item uf-job-item"><input type="checkbox" class="uf-job-role" value="${esc(role)}"><span>${esc(role)}</span></label>`
  ).join("");
  $("#user-list").innerHTML = `
    <div class="table-wrap"><table>
      <thead>
        <tr><th>账号</th><th>姓名</th><th>主管</th><th>部门</th><th>业务角色</th><th>系统角色</th>${showOps ? "<th>操作</th>" : ""}</tr>
        <tr class="filter-row">
          <th><input type="text" class="uf-username" placeholder="筛选"></th>
          <th><input type="text" class="uf-display" placeholder="筛选"></th>
          <th><input type="text" class="uf-supervisor" placeholder="筛选"></th>
          <th><input type="text" class="uf-department" placeholder="筛选"></th>
          <th><div class="uf-job-wrap checkbox-group">${jobRoleFilter}</div></th>
          <th><select class="uf-role"><option value="">全部</option>
            ${sysRoleOpts.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("")}</select></th>
          ${showOps ? "<th></th>" : ""}
        </tr>
      </thead>
      <tbody></tbody>
    </table></div>`;
  const onFilter = () => renderUserTableBody(adminUsersCache, showOps);
  $("#user-list").querySelectorAll(".uf-username, .uf-display, .uf-supervisor, .uf-department, .uf-role").forEach(el =>
    el.addEventListener("input", onFilter));
  $("#user-list").querySelector(".uf-role")?.addEventListener("change", onFilter);
  $("#user-list").querySelectorAll(".uf-job-role").forEach(cb =>
    cb.addEventListener("change", onFilter));
  renderUserTableBody(adminUsersCache, showOps);
}

function openUserModal(user) {
  const isNew = !user;
  const groupAdminMode = isGroupAdmin();
  const roleOptions = (groupAdminMode
    ? [["editor", "组成员"], ["viewer", "只读"]]
    : [["editor", "组成员"], ["group_admin", "组管理员"], ["viewer", "只读"],
       ["global_viewer", "全局查看员"], ["admin", "系统管理员"]])
    .map(([v, t]) => `<option value="${v}" ${user?.role === v ? "selected" : ""}>${t}</option>`).join("");
  const roleList = adminJobRoleOptions();
  const jobRoleHtml = roleList.map(role => {
    const checked = (user?.job_roles || (isNew ? ["拓源人", "接口人"] : [])).includes(role) ? "checked" : "";
    return `<label class="checkbox-item"><input type="checkbox" class="u-job-role" value="${esc(role)}" ${checked}><span>${esc(role)}</span></label>`;
  }).join("");
  openModal(isNew ? (groupAdminMode ? "添加成员" : "新增用户") : `编辑用户 - ${esc(user.username)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>登录账号（工号） *</label>
        <input id="u-username" value="${user ? esc(user.username) : ""}" ${isNew ? "" : "disabled"}></div>
      <div class="form-item"><label>姓名</label>
        <input id="u-display" value="${user ? esc(user.display_name) : ""}"></div>
      <div class="form-item"><label>主管</label>
        <input id="u-supervisor" value="${user ? esc(user.supervisor || "") : ""}"></div>
      <div class="form-item"><label>二层部门 *</label>
        <select id="u-dept-level2"></select></div>
      <div class="form-item"><label>三层部门</label>
        <select id="u-dept-level3"></select></div>
      <div class="form-item"><label>密码 ${isNew ? "（默认 123456）" : "（留空则不修改）"}</label>
        <input id="u-password" type="${isNew ? "text" : "password"}" ${isNew ? `value="123456"` : ""}></div>
      <div class="form-item"><label>系统角色</label><select id="u-role">${roleOptions}</select></div>
      <div class="form-item" style="grid-column:1/-1"><label>业务角色</label>
        <div class="checkbox-group">${jobRoleHtml}</div></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="u-save">保存</button>`);
  renderDeptLevelSelects(
    $("#u-dept-level2"), $("#u-dept-level3"),
    user?.dept_level2 || "", user?.dept_level3 || "",
  );
  $("#u-save").addEventListener("click", async () => {
    const payload = {
      username: $("#u-username").value.trim(),
      display_name: $("#u-display").value.trim(),
      supervisor: $("#u-supervisor").value.trim(),
      dept_level2: $("#u-dept-level2").value,
      dept_level3: $("#u-dept-level3").value.trim(),
      password: $("#u-password").value,
      role: $("#u-role").value,
      job_roles: [...$("#modal-body").querySelectorAll(".u-job-role:checked")].map(cb => cb.value),
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
