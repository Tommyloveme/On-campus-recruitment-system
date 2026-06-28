"use strict";

/* 操作日志与系统管理（纯分组授权模型，已取消业务角色） */
const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], export: ["导出", "yellow"], backup: ["备份", "gray"],
  user: ["用户", "gray"], config: ["配置", "gray"], permission: ["权限", "blue"],
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
  $("#main").innerHTML = `
    <div class="admin-grid">
      <div class="card">
        <div class="section-title">用户管理</div>
        <p style="font-size:12px;color:#64748b;margin-bottom:10px">
          以工号、姓名为唯一索引；主管/部门等信息在「更多信息」中维护。
        </p>
        <div id="user-list"></div>
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-primary" id="btn-add-user">+ 新增用户</button>
          <button class="btn" id="btn-batch-edit" disabled>批量修改所选</button>
        </div>
      </div>
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
      </div>
    </div>`;

  await loadUserList();
  $("#btn-add-user").addEventListener("click", () => openUserModal(null));
  $("#btn-batch-edit").addEventListener("click", openBatchEditModal);
  await loadBackupList();
  $("#btn-backup-now").addEventListener("click", async () => {
    try {
      const r = await api("/api/backups", { method: "POST" });
      toast(`备份完成：${r.name}`);
      loadBackupList();
    } catch (e) { toast(e.message, true); }
  });
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

function readUserTableFilters() {
  const root = $("#user-list");
  if (!root) return {};
  return {
    username: (root.querySelector(".uf-username")?.value || "").trim().toLowerCase(),
    display_name: (root.querySelector(".uf-display")?.value || "").trim().toLowerCase(),
    supervisor: (root.querySelector(".uf-supervisor")?.value || "").trim().toLowerCase(),
    department: (root.querySelector(".uf-department")?.value || "").trim().toLowerCase(),
  };
}

function userMatchesFilters(u, f) {
  if (f.username && !(u.username || "").toLowerCase().includes(f.username)) return false;
  if (f.display_name && !(u.display_name || "").toLowerCase().includes(f.display_name)) return false;
  if (f.supervisor && !(u.supervisor || "").toLowerCase().includes(f.supervisor)) return false;
  if (f.department && !(u.department || u.dept_display || "").toLowerCase().includes(f.department)) return false;
  return true;
}

function selectedUserIds() {
  return [...$("#user-list").querySelectorAll(".uf-check:checked")].map(cb => +cb.value);
}

function refreshBatchBtn() {
  const ids = selectedUserIds();
  const btn = $("#btn-batch-edit");
  if (btn) { btn.disabled = ids.length === 0; btn.textContent = ids.length ? `批量修改所选(${ids.length})` : "批量修改所选"; }
}

function renderUserTableBody() {
  const f = readUserTableFilters();
  const filtered = adminUsersCache.filter(u => userMatchesFilters(u, f));
  const tbody = $("#user-list tbody");
  if (!tbody) return;
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty" style="padding:16px">没有符合条件的用户</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(u => `
    <tr>
      <td><input type="checkbox" class="uf-check" value="${u.id}"></td>
      <td>${esc(u.username)}</td>
      <td>${esc(u.display_name)}</td>
      <td>${esc(u.supervisor || "—")}</td>
      <td>${esc(u.department || u.dept_display || "—")}</td>
      <td>
        <button class="btn btn-sm" data-uedit="${u.id}">更多信息/编辑</button>
        ${u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}
      </td>
    </tr>`).join("");
  tbody.querySelectorAll(".uf-check").forEach(cb => cb.addEventListener("change", refreshBatchBtn));
  tbody.querySelectorAll("[data-uedit]").forEach(b =>
    b.addEventListener("click", () => openUserModal(adminUsersCache.find(u => u.id === +b.dataset.uedit))));
  tbody.querySelectorAll("[data-udel]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm("确认删除该用户？")) return;
      try {
        await api(`/api/users/${b.dataset.udel}`, { method: "DELETE" });
        toast("用户已删除");
        loadUserList();
      } catch (e) { toast(e.message, true); }
    }));
  refreshBatchBtn();
}

async function loadUserList() {
  adminUsersCache = await api("/api/users");
  $("#user-list").innerHTML = `
    <div class="table-wrap"><table>
      <thead>
        <tr><th><input type="checkbox" id="uf-check-all"></th><th>工号</th><th>姓名</th><th>主管</th><th>部门</th><th>操作</th></tr>
        <tr class="filter-row">
          <th></th>
          <th><input type="text" class="uf-username" placeholder="筛选工号"></th>
          <th><input type="text" class="uf-display" placeholder="筛选姓名"></th>
          <th><input type="text" class="uf-supervisor" placeholder="筛选主管"></th>
          <th><input type="text" class="uf-department" placeholder="筛选部门"></th>
          <th></th>
        </tr>
      </thead>
      <tbody></tbody>
    </table></div>`;
  const onFilter = () => renderUserTableBody();
  $("#user-list").querySelectorAll(".uf-username, .uf-display, .uf-supervisor, .uf-department").forEach(el =>
    el.addEventListener("input", onFilter));
  $("#uf-check-all").addEventListener("change", e => {
    $("#user-list").querySelectorAll(".uf-check").forEach(cb => cb.checked = e.target.checked);
    refreshBatchBtn();
  });
  renderUserTableBody();
}

function openUserModal(user) {
  const isNew = !user;
  const roleOptions = [["user", "普通用户"], ["admin", "系统管理员"]]
    .map(([v, t]) => `<option value="${v}" ${user?.role === v ? "selected" : ""}>${t}</option>`).join("");
  openModal(isNew ? "新增用户" : `编辑用户 - ${esc(user.username)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>登录账号（工号） *</label>
        <input id="u-username" value="${user ? esc(user.username) : ""}" ${isNew ? "" : "disabled"}></div>
      <div class="form-item"><label>姓名 *</label>
        <input id="u-display" value="${user ? esc(user.display_name) : ""}"></div>
      <div class="form-item"><label>密码 ${isNew ? "（默认 123456）" : "（留空则不修改）"}</label>
        <input id="u-password" type="${isNew ? "text" : "password"}" ${isNew ? `value="123456"` : ""}></div>
      <div class="form-item"><label>系统角色</label><select id="u-role">${roleOptions}</select></div>
      <div class="form-item"><label>主管 *</label>
        <input id="u-supervisor" value="${user ? esc(user.supervisor || "") : ""}"></div>
      <div class="form-item"><label>二层部门 *</label>
        <select id="u-dept-level2"></select></div>
      <div class="form-item"><label>三层部门</label>
        <select id="u-dept-level3"></select></div>
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

function openBatchEditModal() {
  const ids = selectedUserIds();
  if (!ids.length) return;
  openModal(`批量修改 ${ids.length} 个用户`, `
    <p style="font-size:12px;color:#64748b;margin-bottom:10px">仅勾选并填写的字段会被批量更新；留空字段保持不变。</p>
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>主管（留空不变）</label><input id="be-supervisor"></div>
      <div class="form-item"><label>二层部门（留空不变）</label><select id="be-dept-level2"><option value="">（不变）</option></select></div>
      <div class="form-item"><label>三层部门（留空不变）</label><select id="be-dept-level3"><option value="">（不变）</option></select></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="be-save">批量保存</button>`);
  // 复用部门下拉填充
  const l2 = $("#be-dept-level2"), l3 = $("#be-dept-level3");
  (window.accountOptions?.dept_level2_options || []).forEach(o => {
    const opt = document.createElement("option"); opt.value = o; opt.textContent = o; l2.appendChild(opt);
  });
  (window.accountOptions?.dept_level3_options || []).forEach(o => {
    const opt = document.createElement("option"); opt.value = o; opt.textContent = o; l3.appendChild(opt);
  });
  $("#be-save").addEventListener("click", async () => {
    const patch = {};
    const sup = $("#be-supervisor").value.trim();
    const dl2 = $("#be-dept-level2").value;
    const dl3 = $("#be-dept-level3").value;
    if (sup) patch.supervisor = sup;
    if (dl2) patch.dept_level2 = dl2;
    if (dl3) patch.dept_level3 = dl3;
    if (!Object.keys(patch).length) { toast("未填写任何字段"); return; }
    try {
      const r = await api("/api/users/batch", { method: "PUT", json: { ids, patch } });
      toast(`已批量修改 ${r.updated} 个用户`);
      closeModal();
      loadUserList();
    } catch (e) { toast(e.message, true); }
  });
}
