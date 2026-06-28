/* 权限管理：用户分组 / 成员 / 模板 / 资源分组 / 权限矩阵 / 批量操作 / 导入导出 */
"use strict";

let permOptions = null;
let aclMatrixCache = [];   // 当前选中资源的 ACL 行
let permSelectedResource = null;

const PERM_COLS = [
  { key: "perm_visibility", label: "可见性", title: "控制该资源是否在列表/搜索中展示" },
  { key: "perm_read", label: "读", title: "可查看资源内容，不可修改" },
  { key: "perm_write", label: "写", title: "可编辑资源内容" },
  { key: "perm_manage", label: "管理", title: "可调整该资源的权限配置本身" },
];

async function renderPermissions() {
  $("#main").innerHTML = `
    <div class="card">
      <div class="section-title">权限管理</div>
      <p style="font-size:12px;color:#64748b;margin-bottom:10px">
        自定义用户分组与资源分组，按「可见性 / 读 / 写 / 管理」四个维度授权。
        支持权限模板、批量授权/撤权、跨资源复制、Excel 导入导出；所有变更记入操作日志。
      </p>
      <div id="perm-tabs" class="perm-tabs"></div>
      <div id="perm-panel"></div>
    </div>`;
  if (!permOptions) await loadPermOptions();
  renderPermTabs();
  renderPermPanel("groups");
}

async function loadPermOptions() {
  try {
    permOptions = await api("/api/permissions/options");
  } catch (e) { toast(e.message, true); permOptions = null; }
}

function renderPermTabs() {
  const tabs = [
    { id: "groups", label: "用户分组" },
    { id: "resources", label: "资源分组" },
    { id: "matrix", label: "权限矩阵" },
    { id: "templates", label: "权限模板" },
    { id: "batch", label: "批量操作" },
  ];
  $("#perm-tabs").innerHTML = tabs.map(t =>
    `<button class="btn btn-sm perm-tab" data-pt="${t.id}">${esc(t.label)}</button>`).join("");
  $("#perm-tabs").querySelectorAll(".perm-tab").forEach(b =>
    b.addEventListener("click", () => renderPermPanel(b.dataset.pt)));
}

function renderPermPanel(tab) {
  $("#perm-tabs").querySelectorAll(".perm-tab").forEach(b =>
    b.classList.toggle("btn-primary", b.dataset.pt === tab));
  if (tab === "groups") renderUserGroupsPanel();
  else if (tab === "resources") renderResourceGroupsPanel();
  else if (tab === "matrix") renderMatrixPanel();
  else if (tab === "templates") renderTemplatesPanel();
  else if (tab === "batch") renderBatchPanel();
}

/* ---------------- 用户分组 ---------------- */

function permUsersById() {
  const m = {};
  (permOptions?.users || []).forEach(u => { m[u.id] = u; });
  return m;
}

function permUGName(id) {
  const g = (permOptions?.user_groups || []).find(x => x.id === id);
  return g ? g.name : `#${id}`;
}

function permUserName(id) {
  const u = permUsersById()[id];
  return u ? `${u.display_name}（${u.username}）` : `#${id}`;
}

function renderUserGroupsPanel() {
  const groups = permOptions?.user_groups || [];
  const members = permOptions?.user_group_members || [];
  const memberCount = {};
  members.forEach(m => { memberCount[m.group_id] = (memberCount[m.group_id] || 0) + 1; });
  const rows = groups.map(g => `
    <tr>
      <td>${esc(g.name)}</td>
      <td>${esc(g.description || "—")}</td>
      <td>${permUGParentLabel(g.parent_id)}</td>
      <td>${memberCount[g.id] || 0}</td>
      <td>
        <button class="btn btn-sm" data-ug-members="${g.id}">成员</button>
        <button class="btn btn-sm" data-ug-edit="${g.id}">编辑</button>
        <button class="btn btn-sm" data-ug-tpl="${g.id}">存为模板</button>
        <button class="btn btn-sm btn-danger" data-ug-del="${g.id}">删除</button>
      </td>
    </tr>`).join("");
  $("#perm-panel").innerHTML = `
    <div class="perm-toolbar">
      <button class="btn btn-primary btn-sm" id="ug-add">+ 新建用户分组</button>
      <button class="btn btn-sm" id="ug-tpl-list">分组模板</button>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>名称</th><th>描述</th><th>父分组</th><th>成员数</th><th>操作</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" class="empty" style="padding:16px">暂无用户分组</td></tr>`}</tbody>
    </table></div>`;
  $("#ug-add").addEventListener("click", () => openUserGroupModal(null));
  $("#ug-tpl-list").addEventListener("click", () => openUGTemplateListModal());
  $("#perm-panel").querySelectorAll("[data-ug-edit]").forEach(b =>
    b.addEventListener("click", () => openUserGroupModal(groups.find(g => g.id === +b.dataset.ugEdit))));
  $("#perm-panel").querySelectorAll("[data-ug-del]").forEach(b =>
    b.addEventListener("click", async () => {
      const g = groups.find(x => x.id === +b.dataset.ugDel);
      if (!confirm(`确定删除用户分组「${g.name}」？关联授权将一并清除。`)) return;
      try { await api(`/api/user-groups/${g.id}`, { method: "DELETE" }); toast("已删除"); await reloadPermOptions(); }
      catch (e) { toast(e.message, true); }
    }));
  $("#perm-panel").querySelectorAll("[data-ug-members]").forEach(b =>
    b.addEventListener("click", () => openUGMembersModal(+b.dataset.ugMembers)));
  $("#perm-panel").querySelectorAll("[data-ug-tpl]").forEach(b =>
    b.addEventListener("click", () => openSaveUGTemplateModal(+b.dataset.ugTpl)));
}

function permUGParentLabel(pid) {
  if (!pid) return "—";
  return esc(permUGName(pid));
}

function openUserGroupModal(group) {
  const isNew = !group;
  const groups = permOptions?.user_groups || [];
  const parentOpts = `<option value="">（顶层）</option>` +
    groups.filter(g => !group || g.id !== group.id).map(g =>
      `<option value="${g.id}" ${group?.parent_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("");
  openModal(isNew ? "新建用户分组" : `编辑用户分组 - ${esc(group.name)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>名称 *</label><input id="ug-name" value="${group ? esc(group.name) : ""}"></div>
      <div class="form-item"><label>父分组</label><select id="ug-parent">${parentOpts}</select></div>
      <div class="form-item" style="grid-column:1/-1"><label>描述</label>
        <textarea id="ug-desc" rows="2">${group ? esc(group.description || "") : ""}</textarea></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ug-save">保存</button>`);
  $("#ug-save").addEventListener("click", async () => {
    const payload = {
      name: $("#ug-name").value.trim(),
      description: $("#ug-desc").value.trim(),
      parent_id: $("#ug-parent").value ? +$("#ug-parent").value : null,
    };
    if (!payload.name) return toast("名称不能为空", true);
    try {
      if (isNew) await api("/api/user-groups", { method: "POST", json: payload });
      else await api(`/api/user-groups/${group.id}`, { method: "PUT", json: payload });
      toast("已保存"); closeModal(); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

async function openUGMembersModal(gid) {
  const group = (permOptions?.user_groups || []).find(g => g.id === gid);
  if (!group) return;
  openModal(`成员管理 - ${esc(group.name)}`, `
    <div style="margin-bottom:10px">
      <button class="btn btn-primary btn-sm" id="ugm-add">+ 添加成员</button>
      <button class="btn btn-sm" id="ugm-add-filter">按部门/角色筛选</button>
    </div>
    <div id="ugm-list" class="perm-member-list">加载中…</div>`,
    `<button class="btn" onclick="closeModal()">关闭</button>`);
  await refreshUGMembers(gid);
  $("#ugm-add").addEventListener("click", () => openUGAddMembersModal(gid));
  $("#ugm-add-filter").addEventListener("click", () => openUGAddByFilterModal(gid));
}

async function refreshUGMembers(gid) {
  const list = $("#ugm-list");
  if (!list) return;
  try {
    const members = await api(`/api/user-groups/${gid}/members`);
    if (!members.length) {
      list.innerHTML = `<div class="empty" style="padding:16px">暂无成员</div>`;
      return;
    }
    list.innerHTML = `<div class="table-wrap"><table>
      <thead><tr><th>工号</th><th>姓名</th><th>系统角色</th><th>部门</th><th></th></tr></thead>
      <tbody>${members.map(m => `
        <tr>
          <td>${esc(m.username)}</td><td>${esc(m.display_name)}</td>
          <td>${esc(ROLE_NAMES[m.role] || m.role)}</td><td>${esc(m.department || "—")}</td>
          <td><button class="btn btn-sm btn-danger" data-ugm-rm="${m.id}">移除</button></td>
        </tr>`).join("")}</tbody></table></div>`;
    list.querySelectorAll("[data-ugm-rm]").forEach(b =>
      b.addEventListener("click", async () => {
        try { await api(`/api/user-groups/${gid}/members/${b.dataset.ugmRm}`, { method: "DELETE" });
          toast("已移除"); refreshUGMembers(gid); await reloadPermOptions();
        } catch (e) { toast(e.message, true); }
      }));
  } catch (e) { list.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

function openUGAddMembersModal(gid) {
  const users = permOptions?.users || [];
  const existing = new Set((permOptions?.user_group_members || [])
    .filter(m => m.group_id === gid).map(m => m.user_id));
  const items = users.map(u => `
    <label class="checkbox-item">
      <input type="checkbox" class="ugm-pick" value="${u.id}" ${existing.has(u.id) ? "disabled" : ""}>
      <span>${esc(u.display_name)}（${esc(u.username)}）<span class="muted">·${esc(ROLE_NAMES[u.role] || u.role)}</span></span>
    </label>`).join("");
  openModal("添加成员", `
    <p class="field-hint">勾选要加入的用户（已加入的已禁用）。批量离职清退请在成员列表中操作。</p>
    <div class="checkbox-group" style="max-height:320px;overflow-y:auto">${items}</div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ugm-save">添加</button>`);
  $("#ugm-save").addEventListener("click", async () => {
    const ids = [...$("#modal-body").querySelectorAll(".ugm-pick:checked")].map(c => +c.value);
    if (!ids.length) return toast("请勾选用户", true);
    try {
      const r = await api(`/api/user-groups/${gid}/members`, { method: "POST", json: { user_ids: ids } });
      toast(`已添加 ${r.added} 名`); closeModal(); await refreshUGMembers(gid); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

function openUGAddByFilterModal(gid) {
  const roleOpts = [["", "全部角色"], ...Object.entries(ROLE_NAMES)];
  openModal("按部门/角色筛选添加", `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>部门（精确匹配）</label>
        <input id="ugf-dept" placeholder="如：存储部"></div>
      <div class="form-item"><label>系统角色</label>
        <select id="ugf-role">${roleOpts.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("")}</select></div>
    </div>
    <p class="field-hint">将同时满足条件的用户加入本分组；与已加入成员自动去重。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ugf-go">添加</button>`);
  $("#ugf-go").addEventListener("click", async () => {
    const filter = {
      department: $("#ugf-dept").value.trim(),
      role: $("#ugf-role").value,
    };
    if (!filter.department && !filter.role) return toast("请至少填一项条件", true);
    try {
      const r = await api(`/api/user-groups/${gid}/members`, { method: "POST", json: { filter } });
      toast(`已添加 ${r.added} 名`); closeModal(); await refreshUGMembers(gid); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

function openSaveUGTemplateModal(gid) {
  const group = (permOptions?.user_groups || []).find(g => g.id === gid);
  openModal("保存为分组模板", `
    <div class="form-item"><label>模板名称 *</label>
      <input id="ugt-name" value="${group ? esc(group.name) + " 模板" : ""}"></div>
    <div class="form-item"><label>描述</label><textarea id="ugt-desc" rows="2"></textarea></div>
    <p class="field-hint">将当前分组的成员工号列表保存为模板，可后续套用创建新分组。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ugt-save">保存</button>`);
  $("#ugt-save").addEventListener("click", async () => {
    const members = await api(`/api/user-groups/${gid}/members`);
    const usernames = members.map(m => m.username);
    const payload = {
      name: $("#ugt-name").value.trim(),
      description: $("#ugt-desc").value.trim(),
      member_usernames: usernames,
    };
    if (!payload.name) return toast("名称不能为空", true);
    try {
      await api("/api/user-group-templates", { method: "POST", json: payload });
      toast("模板已保存"); closeModal(); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

async function openUGTemplateListModal() {
  const tpls = permOptions?.user_group_templates || [];
  openModal("用户分组模板", `
    <div style="margin-bottom:10px"><button class="btn btn-primary btn-sm" id="ugt-add">+ 新建模板</button></div>
    <div class="table-wrap"><table>
      <thead><tr><th>名称</th><th>描述</th><th>成员数</th><th>操作</th></tr></thead>
      <tbody>${tpls.map(t => `
        <tr>
          <td>${esc(t.name)}</td><td>${esc(t.description || "—")}</td>
          <td>${(t.member_usernames || []).length}</td>
          <td>
            <button class="btn btn-sm" data-ugt-apply="${t.id}">套用</button>
            <button class="btn btn-sm btn-danger" data-ugt-del="${t.id}">删除</button>
          </td>
        </tr>`).join("") || `<tr><td colspan="4" class="empty" style="padding:16px">暂无模板</td></tr>`}</tbody>
    </table></div>`,
    `<button class="btn" onclick="closeModal()">关闭</button>`);
  $("#ugt-add")?.addEventListener("click", () => openUGTemplateEditModal(null));
  $("#modal-body").querySelectorAll("[data-ugt-apply]").forEach(b =>
    b.addEventListener("click", () => openUGTemplateApplyModal(+b.dataset.ugtApply)));
  $("#modal-body").querySelectorAll("[data-ugt-del]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm("确定删除该模板？")) return;
      try { await api(`/api/user-group-templates/${b.dataset.ugtDel}`, { method: "DELETE" });
        toast("已删除"); closeModal(); await reloadPermOptions(); openUGTemplateListModal();
      } catch (e) { toast(e.message, true); }
    }));
}

function openUGTemplateEditModal(tpl) {
  const isNew = !tpl;
  openModal(isNew ? "新建分组模板" : `编辑模板 - ${esc(tpl.name)}`, `
    <div class="form-item"><label>名称 *</label><input id="ut-name" value="${tpl ? esc(tpl.name) : ""}"></div>
    <div class="form-item"><label>描述</label><textarea id="ut-desc" rows="2">${tpl ? esc(tpl.description || "") : ""}</textarea></div>
    <div class="form-item"><label>成员工号（逗号或换行分隔）</label>
      <textarea id="ut-members" rows="4" placeholder="hr01, hr02, ...">${tpl ? esc((tpl.member_usernames || []).join(", ")) : ""}</textarea></div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ut-save">保存</button>`);
  $("#ut-save").addEventListener("click", async () => {
    const usernames = $("#ut-members").value.split(/[,，\n\s]+/).map(s => s.trim()).filter(Boolean);
    const payload = {
      name: $("#ut-name").value.trim(),
      description: $("#ut-desc").value.trim(),
      member_usernames: usernames,
    };
    if (!payload.name) return toast("名称不能为空", true);
    try {
      await api("/api/user-group-templates", { method: "POST", json: payload });
      toast("已保存"); closeModal(); await reloadPermOptions(); openUGTemplateListModal();
    } catch (e) { toast(e.message, true); }
  });
}

function openUGTemplateApplyModal(tid) {
  const tpl = (permOptions?.user_group_templates || []).find(t => t.id === tid);
  if (!tpl) return;
  openModal(`套用模板 - ${esc(tpl.name)}`, `
    <div class="form-item"><label>新分组名称 *</label>
      <input id="ut-apply-name" value="${esc(tpl.name)}"></div>
    <p class="field-hint">将创建一个新用户分组并加入模板中的 ${tpl.member_usernames?.length || 0} 个工号（未注册工号自动跳过）。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="ut-apply-go">套用</button>`);
  $("#ut-apply-go").addEventListener("click", async () => {
    const name = $("#ut-apply-name").value.trim();
    if (!name) return toast("名称不能为空", true);
    try {
      const r = await api(`/api/user-group-templates/${tid}/apply`, { method: "POST", json: { name } });
      toast(`已创建分组并加入 ${r.added} 人（跳过 ${r.skipped}）`); closeModal(); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- 资源分组 ---------------- */

function renderResourceGroupsPanel() {
  const groups = permOptions?.resource_groups || [];
  const rows = groups.map(g => `
    <tr>
      <td>${esc(g.name)}</td>
      <td>${esc(g.description || "—")}</td>
      <td>${permRGParentLabel(g.parent_id)}</td>
      <td>${g.candidate_count || 0}</td>
      <td>${g.child_count || 0}</td>
      <td>
        <button class="btn btn-sm" data-rg-edit="${g.id}">编辑</button>
        <button class="btn btn-sm" data-rg-matrix="${g.id}">授权</button>
        <button class="btn btn-sm btn-danger" data-rg-del="${g.id}">删除</button>
      </td>
    </tr>`).join("");
  $("#perm-panel").innerHTML = `
    <div class="perm-toolbar">
      <button class="btn btn-primary btn-sm" id="rg-add">+ 新建资源分组</button>
      <span class="muted" style="margin-left:8px;font-size:12px">资源分组是候选人的逻辑分区，权限按资源分组授予</span>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>名称</th><th>描述</th><th>父分组</th><th>候选人数</th><th>子分组数</th><th>操作</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="6" class="empty" style="padding:16px">暂无资源分组（未分组的候选人沿用角色权限）</td></tr>`}</tbody>
    </table></div>`;
  $("#rg-add").addEventListener("click", () => openResourceGroupModal(null));
  $("#perm-panel").querySelectorAll("[data-rg-edit]").forEach(b =>
    b.addEventListener("click", () => openResourceGroupModal(groups.find(g => g.id === +b.dataset.rgEdit))));
  $("#perm-panel").querySelectorAll("[data-rg-del]").forEach(b =>
    b.addEventListener("click", async () => {
      const g = groups.find(x => x.id === +b.dataset.rgDel);
      if (!confirm(`确定删除资源分组「${g.name}」？`)) return;
      try { await api(`/api/resource-groups/${g.id}`, { method: "DELETE" }); toast("已删除"); await reloadPermOptions(); }
      catch (e) { toast(e.message, true); }
    }));
  $("#perm-panel").querySelectorAll("[data-rg-matrix]").forEach(b =>
    b.addEventListener("click", () => { permSelectedResource = +b.dataset.rgMatrix; renderPermPanel("matrix"); }));
}

function permRGParentLabel(pid) {
  if (!pid) return "—";
  const g = (permOptions?.resource_groups || []).find(x => x.id === pid);
  return g ? esc(g.name) : `#${pid}`;
}

function openResourceGroupModal(group) {
  const isNew = !group;
  const groups = permOptions?.resource_groups || [];
  const parentOpts = `<option value="">（顶层）</option>` +
    groups.filter(g => !group || g.id !== group.id).map(g =>
      `<option value="${g.id}" ${group?.parent_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("");
  openModal(isNew ? "新建资源分组" : `编辑资源分组 - ${esc(group.name)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>名称 *</label><input id="rg-name" value="${group ? esc(group.name) : ""}"></div>
      <div class="form-item"><label>父分组</label><select id="rg-parent">${parentOpts}</select></div>
      <div class="form-item" style="grid-column:1/-1"><label>描述</label>
        <textarea id="rg-desc" rows="2">${group ? esc(group.description || "") : ""}</textarea></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="rg-save">保存</button>`);
  $("#rg-save").addEventListener("click", async () => {
    const payload = {
      name: $("#rg-name").value.trim(),
      description: $("#rg-desc").value.trim(),
      parent_id: $("#rg-parent").value ? +$("#rg-parent").value : null,
    };
    if (!payload.name) return toast("名称不能为空", true);
    try {
      if (isNew) await api("/api/resource-groups", { method: "POST", json: payload });
      else await api(`/api/resource-groups/${group.id}`, { method: "PUT", json: payload });
      toast("已保存"); closeModal(); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- 权限矩阵 ---------------- */

async function renderMatrixPanel() {
  const resources = permOptions?.resource_groups || [];
  if (!resources.length) {
    $("#perm-panel").innerHTML = `<div class="empty" style="padding:24px">请先在「资源分组」中创建分组，再在此授权。</div>`;
    return;
  }
  if (!permSelectedResource || !resources.find(r => r.id === permSelectedResource)) {
    permSelectedResource = resources[0].id;
  }
  const resOpts = resources.map(r =>
    `<option value="${r.id}" ${r.id === permSelectedResource ? "selected" : ""}>${esc(r.name)}</option>`).join("");
  $("#perm-panel").innerHTML = `
    <div class="perm-toolbar">
      <label style="font-size:13px">资源分组：</label>
      <select id="mx-resource" class="perm-select">${resOpts}</select>
      <button class="btn btn-sm" id="mx-refresh">刷新</button>
      <span class="muted" style="margin-left:auto;font-size:12px">勾选后自动保存；行=主体，列=权限维度</span>
    </div>
    <div id="mx-table">加载中…</div>`;
  $("#mx-resource").addEventListener("change", () => { permSelectedResource = +$("#mx-resource").value; renderMatrixPanel(); });
  $("#mx-refresh").addEventListener("click", renderMatrixPanel);
  await loadMatrixTable(permSelectedResource);
}

async function loadMatrixTable(rid) {
  const wrap = $("#mx-table");
  try {
    const [aclRows, members] = await Promise.all([
      api(`/api/acl?resource_type=group&resource_id=${rid}`),
      api("/api/user-groups"),
    ]);
    aclMatrixCache = aclRows;
    const users = permOptions?.users || [];
    const ugs = members;
    const byKey = {};
    aclRows.forEach(r => { byKey[`${r.subject_type}:${r.subject_id}`] = r; });
    const permCell = (subjectType, subjectId, key) => {
      const row = byKey[`${subjectType}:${subjectId}`];
      const checked = row ? row[key] : 0;
      const title = PERM_COLS.find(c => c.key === key).title;
      return `<input type="checkbox" class="mx-perm" title="${esc(title)}"
        data-st="${subjectType}" data-sid="${subjectId}"
        data-key="${key}" ${checked ? "checked" : ""}>`;
    };
    const subjectRows = (type, label, items) => items.map(item => {
      const sid = item.id;
      const name = type === "user"
        ? `${esc(item.display_name)}（${esc(item.username)}）`
        : esc(item.name);
      return `<tr>
        <td>${label}</td><td>${name}</td>
        ${PERM_COLS.map(c => `<td class="perm-cell">${permCell(type, sid, c.key)}</td>`).join("")}
        <td><button class="btn btn-sm btn-danger" data-mx-clear data-st="${type}" data-sid="${sid}">清空</button></td>
      </tr>`;
    }).join("");
    wrap.innerHTML = `<div class="table-wrap"><table class="perm-matrix">
      <thead><tr><th>主体类型</th><th>主体</th>
      ${PERM_COLS.map(c => `<th title="${esc(c.title)}">${esc(c.label)}</th>`).join("")}
      <th>操作</th></tr></thead>
      <tbody>
        ${subjectRows("user", "用户", users)}
        ${ugs.length ? subjectRows("user_group", "用户分组", ugs) : `<tr><td colspan="7" class="empty" style="padding:12px">尚无用户分组</td></tr>`}
      </tbody>
    </table></div>`;
    wrap.querySelectorAll(".mx-perm").forEach(cb =>
      cb.addEventListener("change", () => onMatrixToggle(cb, rid)));
    wrap.querySelectorAll("[data-mx-clear]").forEach(b =>
      b.addEventListener("click", async () => {
        if (!confirm("确定清空该主体在此资源的全部权限？")) return;
        try {
          await api("/api/acl", { method: "DELETE", json: {
            subject_type: b.dataset.st, subject_id: +b.dataset.sid,
            resource_type: "group", resource_id: rid,
          }});
          toast("已清空"); await loadMatrixTable(rid);
        } catch (e) { toast(e.message, true); }
      }));
  } catch (e) { wrap.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

async function onMatrixToggle(cb, rid) {
  const subjectType = cb.dataset.st;
  const subjectId = +cb.dataset.sid;
  const key = cb.dataset.key;
  const row = aclMatrixCache.find(r => r.subject_type === subjectType && r.subject_id === subjectId);
  const perms = row ? {
    perm_visibility: row.perm_visibility, perm_read: row.perm_read,
    perm_write: row.perm_write, perm_manage: row.perm_manage,
  } : { perm_visibility: 0, perm_read: 0, perm_write: 0, perm_manage: 0 };
  perms[key] = cb.checked ? 1 : 0;
  if (key === "perm_manage" && cb.checked) {
    if (!confirm("授予「管理」权限将允许该主体调整此资源的权限配置，确定继续？")) {
      cb.checked = false; return;
    }
  }
  const payload = {
    subject_type: subjectType, subject_id: subjectId,
    resource_type: "group", resource_id: rid, ...perms,
  };
  try {
    await api("/api/acl", { method: "PUT", json: payload });
    toast("已保存");
    await loadMatrixTable(rid);
  } catch (e) { toast(e.message, true); cb.checked = !cb.checked; }
}

/* ---------------- 权限模板 ---------------- */

function renderTemplatesPanel() {
  const tpls = permOptions?.permission_templates || [];
  const rows = tpls.map(t => {
    const flags = PERM_COLS.filter(c => t[c.key]).map(c => c.label).join("、") || "无";
    return `<tr>
      <td>${esc(t.name)}</td><td>${esc(t.description || "—")}</td>
      <td>${esc(flags)}</td>
      <td>
        <button class="btn btn-sm" data-pt-edit="${t.id}">编辑</button>
        <button class="btn btn-sm btn-danger" data-pt-del="${t.id}">删除</button>
      </td>
    </tr>`;
  }).join("");
  $("#perm-panel").innerHTML = `
    <div class="perm-toolbar">
      <button class="btn btn-primary btn-sm" id="pt-add">+ 新建权限模板</button>
      <span class="muted" style="margin-left:8px;font-size:12px">预设常用权限组合，授权时一键套用</span>
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th>名称</th><th>描述</th><th>权限</th><th>操作</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="empty" style="padding:16px">暂无模板</td></tr>`}</tbody>
    </table></div>`;
  $("#pt-add").addEventListener("click", () => openPermTemplateModal(null));
  $("#perm-panel").querySelectorAll("[data-pt-edit]").forEach(b =>
    b.addEventListener("click", () => openPermTemplateModal(tpls.find(t => t.id === +b.dataset.ptEdit))));
  $("#perm-panel").querySelectorAll("[data-pt-del]").forEach(b =>
    b.addEventListener("click", async () => {
      const t = tpls.find(x => x.id === +b.dataset.ptDel);
      if (!confirm(`确定删除权限模板「${t.name}」？`)) return;
      try { await api(`/api/permission-templates/${t.id}`, { method: "DELETE" }); toast("已删除"); await reloadPermOptions(); }
      catch (e) { toast(e.message, true); }
    }));
}

function openPermTemplateModal(tpl) {
  const isNew = !tpl;
  const checks = PERM_COLS.map(c => `
    <label class="checkbox-item">
      <input type="checkbox" id="pt-${c.key}" ${tpl && tpl[c.key] ? "checked" : (isNew && (c.key === "perm_visibility" || c.key === "perm_read") ? "checked" : "")}>
      <span>${esc(c.label)} <span class="muted">·${esc(c.title)}</span></span>
    </label>`).join("");
  openModal(isNew ? "新建权限模板" : `编辑权限模板 - ${esc(tpl.name)}`, `
    <div class="form-item"><label>名称 *</label><input id="pt-name" value="${tpl ? esc(tpl.name) : ""}"></div>
    <div class="form-item"><label>描述</label><textarea id="pt-desc" rows="2">${tpl ? esc(tpl.description || "") : ""}</textarea></div>
    <div class="form-item"><label>权限</label><div class="checkbox-group">${checks}</div></div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="pt-save">保存</button>`);
  $("#pt-save").addEventListener("click", async () => {
    const payload = {
      name: $("#pt-name").value.trim(),
      description: $("#pt-desc").value.trim(),
      perm_visibility: $("#pt-perm_visibility").checked ? 1 : 0,
      perm_read: $("#pt-perm_read").checked ? 1 : 0,
      perm_write: $("#pt-perm_write").checked ? 1 : 0,
      perm_manage: $("#pt-perm_manage").checked ? 1 : 0,
    };
    if (!payload.name) return toast("名称不能为空", true);
    try {
      if (isNew) await api("/api/permission-templates", { method: "POST", json: payload });
      else await api(`/api/permission-templates/${tpl.id}`, { method: "PUT", json: payload });
      toast("已保存"); closeModal(); await reloadPermOptions();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- 批量操作 ---------------- */

function renderBatchPanel() {
  const resources = permOptions?.resource_groups || [];
  const ugs = permOptions?.user_groups || [];
  const users = permOptions?.users || [];
  const resOpts = resources.map(r => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  const ugOpts = ugs.map(g => `<option value="user_group:${g.id}">${esc(g.name)}</option>`).join("");
  const userOpts = users.map(u => `<option value="user:${u.id}">${esc(u.display_name)}（${u.username}）</option>`).join("");
  const permChecks = PERM_COLS.map(c => `
    <label class="checkbox-item"><input type="checkbox" class="bx-perm" data-key="${c.key}"><span>${esc(c.label)}</span></label>`).join("");
  $("#perm-panel").innerHTML = `
    <div class="perm-batch-grid">
      <div class="card">
        <div class="section-title">批量授权 / 撤权</div>
        <div class="form-item"><label>主体（可多选）</label>
          <select id="bx-subjects" multiple style="height:140px">${userOpts}${ugOpts}</select></div>
        <div class="form-item"><label>资源分组（可多选）</label>
          <select id="bx-resources" multiple style="height:140px">${resOpts}</select></div>
        <div class="form-item"><label>权限（授权时勾选；撤权时忽略）</label>
          <div class="checkbox-group">${permChecks}</div></div>
        <div class="form-item"><label><input type="checkbox" id="bx-confirm"> 二次确认（授予管理权限时必勾）</label></div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" id="bx-preview">预览影响</button>
          <button class="btn btn-sm" id="bx-apply">执行授权</button>
          <button class="btn btn-sm btn-danger" id="bx-revoke">执行撤权</button>
        </div>
        <div id="bx-result" style="margin-top:10px;font-size:12px;color:#475569"></div>
      </div>
      <div class="card">
        <div class="section-title">跨资源复制权限</div>
        <div class="form-item"><label>源资源分组</label>
          <select id="cp-source">${resOpts}</select></div>
        <div class="form-item"><label>目标资源分组（可多选）</label>
          <select id="cp-targets" multiple style="height:120px">${resOpts}</select></div>
        <div class="form-item"><label><input type="checkbox" id="cp-confirm"> 二次确认（源含管理权限时必勾）</label></div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-sm" id="cp-preview">预览</button>
          <button class="btn btn-primary btn-sm" id="cp-apply">执行复制</button>
        </div>
        <div id="cp-result" style="margin-top:10px;font-size:12px;color:#475569"></div>
      </div>
      <div class="card">
        <div class="section-title">Excel 导入 / 导出</div>
        <p style="font-size:12px;color:#64748b;line-height:1.7">
          导出当前权限矩阵为 Excel；按相同表头填写后可批量导入（含管理权限需勾选确认）。
        </p>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-sm" id="ex-export">导出权限矩阵</button>
          <input type="file" id="ex-file" accept=".xlsx" style="display:none">
          <button class="btn btn-sm" id="ex-pick">选择 Excel 导入</button>
          <label class="checkbox-item" style="margin-left:8px"><input type="checkbox" id="ex-confirm"> 导入含管理权限时确认</label>
        </div>
        <div id="ex-result" style="margin-top:10px;font-size:12px;color:#475569"></div>
      </div>
    </div>`;
  $("#bx-preview").addEventListener("click", () => batchApply("preview"));
  $("#bx-apply").addEventListener("click", () => batchApply("set"));
  $("#bx-revoke").addEventListener("click", () => batchApply("revoke"));
  $("#cp-preview").addEventListener("click", () => copyApply("preview"));
  $("#cp-apply").addEventListener("click", () => copyApply("apply"));
  $("#ex-export").addEventListener("click", exportAclMatrix);
  $("#ex-pick").addEventListener("click", () => $("#ex-file").click());
  $("#ex-file").addEventListener("change", importAclMatrix);
}

function getBatchPerms() {
  const perms = {};
  $("#perm-panel").querySelectorAll(".bx-perm:checked").forEach(c => { perms[c.dataset.key] = 1; });
  return perms;
}

async function batchApply(mode) {
  const subjects = [...$("#bx-subjects").selectedOptions].map(o => {
    const [st, sid] = o.value.split(":");
    return { subject_type: st, subject_id: +sid };
  });
  const resources = [...$("#bx-resources").selectedOptions].map(o => +o.value);
  if (!subjects.length || !resources.length) return toast("请选择主体与资源", true);
  const perms = getBatchPerms();
  const entries = [];
  for (const s of subjects) {
    for (const r of resources) {
      entries.push({
        subject_type: s.subject_type, subject_id: s.subject_id,
        resource_type: "group", resource_id: r,
        perm_visibility: perms.perm_visibility || 0,
        perm_read: perms.perm_read || 0,
        perm_write: perms.perm_write || 0,
        perm_manage: perms.perm_manage || 0,
      });
    }
  }
  const payload = { entries, mode: mode === "revoke" ? "revoke" : "set" };
  if (mode === "preview") payload.dry_run = true;
  if (mode === "set") payload.confirm = $("#bx-confirm").checked;
  try {
    const r = await api("/api/acl/batch", { method: "POST", json: payload });
    const p = r.preview || {};
    if (r.dry_run) {
      $("#bx-result").innerHTML = `预览：影响 <b>${p.subject_count}</b> 个主体、<b>${p.resource_count}</b> 个资源、<b>${p.entry_count}</b> 条授权。请确认后点击「执行授权」。`;
      toast("预览完成");
    } else {
      $("#bx-result").innerHTML = `已${mode === "revoke" ? "撤销" : "设置"} <b>${r.affected}</b> 条权限。`;
      toast(`已处理 ${r.affected} 条`);
      await loadMatrixTable(permSelectedResource).catch(() => {});
    }
  } catch (e) { toast(e.message, true); $("#bx-result").textContent = e.message; }
}

async function copyApply(mode) {
  const src = +$("#cp-source").value;
  const targets = [...$("#cp-targets").selectedOptions].map(o => +o.value);
  if (!src || !targets.length) return toast("请选择源与目标资源", true);
  const payload = {
    resource_type: "group", source_resource_id: src,
    target_resource_ids: targets,
    confirm: $("#cp-confirm").checked,
  };
  if (mode === "preview") payload.dry_run = true;
  try {
    const r = await api("/api/acl/copy", { method: "POST", json: payload });
    const p = r.preview || {};
    if (r.dry_run) {
      $("#cp-result").innerHTML = `预览：源资源含 <b>${p.acl_rows}</b> 条授权${p.has_manage ? "（含管理权限，执行时需勾选确认）" : ""}，将复制到 <b>${p.target_resource_ids.length}</b> 个目标。`;
      toast("预览完成");
    } else {
      $("#cp-result").innerHTML = `已复制 <b>${r.affected}</b> 条权限到 ${targets.length} 个目标资源。`;
      toast(`已复制 ${r.affected} 条`);
    }
  } catch (e) { toast(e.message, true); $("#cp-result").textContent = e.message; }
}

async function exportAclMatrix() {
  try {
    const res = await fetch("/api/acl/export");
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.error || "导出失败"); }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "权限矩阵.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出");
  } catch (e) { toast(e.message, true); }
}

async function importAclMatrix(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  if ($("#ex-confirm").checked) fd.append("confirm", "1");
  try {
    const res = await fetch("/api/acl/import", { method: "POST", body: fd });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || "导入失败");
    $("#ex-result").innerHTML = `已导入 <b>${body.affected}</b> 条权限。`;
    toast(`已导入 ${body.affected} 条`);
    await reloadPermOptions();
  } catch (e) { toast(e.message, true); $("#ex-result").textContent = e.message; }
  ev.target.value = "";
}

/* ---------------- 公共 ---------------- */

async function reloadPermOptions() {
  await loadPermOptions();
  // 若当前在权限页则就地刷新
  if ($("#perm-panel")) {
    const active = $("#perm-tabs .btn-primary")?.dataset.pt;
    if (active) renderPermPanel(active);
  }
}
