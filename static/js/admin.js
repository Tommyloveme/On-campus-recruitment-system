"use strict";

/* 操作日志与系统管理 */
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
