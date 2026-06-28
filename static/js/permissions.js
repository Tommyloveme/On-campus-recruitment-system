"use strict";

/* 权限管理（合并系统管理）：单一 Excel 式权限矩阵页，仅系统管理员。
 * 行=用户(工号唯一)；列=附属信息(由 config/user_fields.json 配置) + 各模块的 V/R/W/M 四勾选。
 * 支持内联勾选、批量填充、用户 CRUD、附属信息批量修改、操作日志、数据备份、字段配置说明。
 */
let permOptions = { users: [], user_fields: [], modules: [], settings: {} };
let permAclMap = {};        // `${uid}|${moduleKey}` -> {v,r,w,m}
let permModuleCols = [];    // 扁平化的模块列 [{key,label,type}]
let permUsersCache = [];    // 用户列表
let permLogPage = 1;

const PERM_FLAGS = [
  ["v", "perm_visibility", "可见"],
  ["r", "perm_read", "读"],
  ["w", "perm_write", "写"],
  ["m", "perm_manage", "管"],
];

function aclKey(uid, mk) { return `${uid}|${mk}`; }
function aclOf(uid, mk) { return permAclMap[aclKey(uid, mk)] || {v:0,r:0,w:0,m:0}; }

function flattenModuleCols(modules) {
  const out = [];
  for (const m of modules) {
    out.push({ key: m.key, label: m.label, type: m.type });
    for (const it of (m.items || [])) out.push({ key: it.key, label: it.label, type: it.type });
  }
  return out;
}

async function renderPermissions() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可访问「权限管理」。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card">
      <div class="section-title">权限管理 · 用户与模块权限矩阵</div>
      <p style="font-size:12px;color:#64748b;margin-bottom:10px">
        唯一性由工号决定，其余为附属信息（见 <code>config/user_fields.json</code>）。
        勾选即保存；支持多选用户后批量填充某模块的 V/R/W/M。
      </p>
      <div class="perm-toolbar">
        <input type="text" id="perm-search" placeholder="搜索 工号/姓名/主管/部门">
        <button class="btn btn-primary btn-sm" id="perm-add-user">+ 新增用户</button>
        <button class="btn btn-sm" id="perm-batch-edit" disabled>批量修改附属信息</button>
        <span class="perm-sep"></span>
        <span class="perm-batch-group">
          批量授权：模块<select id="perm-batch-module"></select>
          <label class="perm-flag"><input type="checkbox" id="perm-batch-v">可见</label>
          <label class="perm-flag"><input type="checkbox" id="perm-batch-r">读</label>
          <label class="perm-flag"><input type="checkbox" id="perm-batch-w">写</label>
          <label class="perm-flag"><input type="checkbox" id="perm-batch-m">管理</label>
          <button class="btn btn-primary btn-sm" id="perm-batch-apply">应用到所选用户</button>
          <button class="btn btn-sm" id="perm-batch-revoke">清空所选用户该模块</button>
        </span>
        <span class="perm-sep"></span>
        <button class="btn btn-sm" id="perm-export">导出权限矩阵</button>
      </div>
      <div class="table-wrap perm-grid-wrap"><table id="perm-grid" class="perm-grid"></table></div>
    </div>
    <div class="card">
      <div class="section-title">操作日志</div>
      <div id="perm-logs"></div>
    </div>
    <div class="card">
      <div class="section-title">数据备份与恢复</div>
      <div id="perm-backups">
        <div class="backup-list-body" style="max-height:260px;overflow-y:auto"></div>
        <button class="btn btn-primary btn-sm btn-backup-now" style="margin-top:12px">立即备份</button>
      </div>
    </div>
    <div class="card">
      <div class="section-title">附属信息字段配置说明</div>
      <div id="perm-field-config"></div>
    </div>`;

  $("#perm-add-user").addEventListener("click", () => openUserModal(null));
  $("#perm-batch-edit").addEventListener("click", openBatchEditModal);
  $("#perm-search").addEventListener("input", renderPermGridBody);
  $("#perm-batch-apply").addEventListener("click", () => permBatchApply(false));
  $("#perm-batch-revoke").addEventListener("click", () => permBatchApply(true));
  $("#perm-export").addEventListener("click", () => { window.location.href = "/api/module-acl/export"; });

  await loadPermData();
  // 批量模块下拉
  $("#perm-batch-module").innerHTML = permModuleCols
    .map(m => `<option value="${m.key}">${esc(m.label)}${m.type === "section" ? "（板块）" : ""}</option>`).join("");
  renderPermGridBody();
  renderFieldConfigCard();
  renderLogsInto($("#perm-logs"), permLogPage);
  renderBackupsInto($("#perm-backups"));
}

async function loadPermData() {
  const [opts, acls] = await Promise.all([
    api("/api/permissions/options"),
    api("/api/module-acl"),
  ]);
  permOptions = opts;
  permUsersCache = opts.users || [];
  permModuleCols = flattenModuleCols(opts.modules || []);
  permAclMap = {};
  for (const r of (acls || [])) {
    permAclMap[aclKey(r.subject_id, r.module_key)] = {
      v: +r.perm_visibility, r: +r.perm_read, w: +r.perm_write, m: +r.perm_manage,
    };
  }
}

function permSearchFilter() {
  const q = ($("#perm-search")?.value || "").trim().toLowerCase();
  if (!q) return permUsersCache;
  return permUsersCache.filter(u =>
    (u.username || "").toLowerCase().includes(q) ||
    (u.display_name || "").toLowerCase().includes(q) ||
    (u.supervisor || "").toLowerCase().includes(q) ||
    (u.department || u.dept_display || "").toLowerCase().includes(q));
}

function userFieldsForGrid() {
  // 网格附属信息列：除工号(username)/姓名(display_name)单独列外，其余配置字段
  return (permOptions.user_fields || []).filter(f => f.key !== "display_name");
}

function renderPermGridBody() {
  const fields = userFieldsForGrid();
  const users = permSearchFilter();
  const thead = `
    <thead><tr>
      <th class="perm-col-check"><input type="checkbox" id="perm-check-all"></th>
      <th>工号</th>
      <th>姓名</th>
      ${fields.map(f => `<th>${esc(f.label)}</th>`).join("")}
      <th>角色</th>
      <th>操作</th>
      ${permModuleCols.map(m => `<th class="perm-mod-head" title="${esc(m.label)}（${m.type === "section" ? "板块" : "模块"}）">${esc(m.label)}</th>`).join("")}
    </tr></thead>`;
  const tbody = `<tbody>${users.map(u => permUserRow(u, fields)).join("")}</tbody>`;
  $("#perm-grid").innerHTML = thead + tbody;

  $("#perm-check-all").addEventListener("change", e => {
    $("#perm-grid").querySelectorAll(".perm-row-check").forEach(cb => cb.checked = e.target.checked);
    refreshPermBatchBtn();
  });
  $("#perm-grid").querySelectorAll(".perm-row-check").forEach(cb => cb.addEventListener("change", refreshPermBatchBtn));
  $("#perm-grid").querySelectorAll(".perm-flag-cb").forEach(cb =>
    cb.addEventListener("change", () => onPermFlagToggle(+cb.dataset.uid, cb.dataset.mk, cb.dataset.flag, cb.checked)));
  $("#perm-grid").querySelectorAll("[data-uedit]").forEach(b =>
    b.addEventListener("click", () => openUserModal(permUsersCache.find(u => u.id === +b.dataset.uedit))));
  $("#perm-grid").querySelectorAll("[data-udel]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm("确认删除该用户？其模块权限将一并清除。")) return;
      try {
        await api(`/api/users/${b.dataset.udel}`, { method: "DELETE" });
        toast("用户已删除");
        await loadPermData();
        renderPermGridBody();
      } catch (e) { toast(e.message, true); }
    }));
  refreshPermBatchBtn();
}

function permUserRow(u, fields) {
  const infoCells = fields.map(f => `<td class="perm-info-cell">${esc(u[f.key] ?? "—")}</td>`).join("");
  const modCells = permModuleCols.map(m => {
    const a = aclOf(u.id, m.key);
    return `<td class="perm-mod-cell">${PERM_FLAGS.map(([short, , label]) =>
      `<label class="perm-flag" title="${label}"><input type="checkbox" class="perm-flag-cb"
        data-uid="${u.id}" data-mk="${m.key}" data-flag="${short}" ${a[short] ? "checked" : ""}></label>`).join("")}</td>`;
  }).join("");
  return `
    <tr>
      <td><input type="checkbox" class="perm-row-check" value="${u.id}"></td>
      <td class="mono">${esc(u.username)}</td>
      <td>${esc(u.display_name)}</td>
      ${infoCells}
      <td>${esc(ROLE_NAMES[u.role] || u.role)}</td>
      <td class="perm-actions">
        <button class="btn btn-sm" data-uedit="${u.id}">编辑</button>
        ${u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}
      </td>
      ${modCells}
    </tr>`;
}

function refreshPermBatchBtn() {
  const ids = permSelectedUserIds();
  const btn = $("#perm-batch-edit");
  if (btn) { btn.disabled = ids.length === 0; btn.textContent = ids.length ? `批量修改附属信息(${ids.length})` : "批量修改附属信息"; }
}

function permSelectedUserIds() {
  return [...document.querySelectorAll(".perm-row-check:checked")].map(cb => +cb.value);
}

async function onPermFlagToggle(uid, mk, flag, checked) {
  const cur = aclOf(uid, mk);
  cur[flag] = checked ? 1 : 0;
  permAclMap[aclKey(uid, mk)] = cur;
  const body = {
    subject_type: "user", subject_id: uid, module_key: mk,
    perm_visibility: cur.v, perm_read: cur.r, perm_write: cur.w, perm_manage: cur.m,
  };
  if (cur.v === 0 && cur.r === 0 && cur.w === 0 && cur.m === 0) {
    try {
      await api("/api/module-acl", { method: "DELETE", json: { subject_type: "user", subject_id: uid, module_key: mk } });
    } catch (e) { toast(e.message, true); await loadPermData(); renderPermGridBody(); }
    return;
  }
  try {
    await api("/api/module-acl", { method: "PUT", json: body });
  } catch (e) {
    toast(e.message, true);
    await loadPermData();
    renderPermGridBody();
  }
}

async function permBatchApply(revoke) {
  const ids = permSelectedUserIds();
  if (!ids.length) { toast("请先勾选用户"); return; }
  const mk = $("#perm-batch-module").value;
  const flags = {
    perm_visibility: $("#perm-batch-v").checked ? 1 : 0,
    perm_read: $("#perm-batch-r").checked ? 1 : 0,
    perm_write: $("#perm-batch-w").checked ? 1 : 0,
    perm_manage: $("#perm-batch-m").checked ? 1 : 0,
  };
  if (!revoke && !flags.perm_visibility && !flags.perm_read && !flags.perm_write && !flags.perm_manage) {
    toast("请至少勾选一项权限"); return;
  }
  const confirmFlag = revoke ? true : (flags.perm_manage ? confirm("确认批量授予「管理」权限？") : true);
  if (!confirmFlag) return;
  const entries = ids.map(uid => ({ subject_type: "user", subject_id: uid, module_key: mk, ...flags }));
  try {
    const r = await api("/api/module-acl/batch", {
      method: "POST",
      json: { entries, mode: revoke ? "revoke" : "set", confirm: flags.perm_manage && !revoke },
    });
    toast(`${revoke ? "已清空" : "已应用"} ${r.affected} 条权限`);
    await loadPermData();
    renderPermGridBody();
  } catch (e) { toast(e.message, true); }
}

/* ---------- 用户 CRUD（附属信息字段由 user_fields 配置驱动） ---------- */

function fieldInputHtml(f, val) {
  const v = val ?? "";
  if (f.type === "select") {
    const opts = ["", ...(f.options || [])].map(o =>
      `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${o === "" ? "（未填写）" : esc(o)}</option>`).join("");
    return `<select id="uf-${f.key}">${opts}</select>`;
  }
  return `<input id="uf-${f.key}" value="${esc(v)}">`;
}

function openUserModal(user) {
  const isNew = !user;
  const fields = permOptions.user_fields || [];
  const roleOptions = [["user", "普通用户"], ["admin", "系统管理员"]]
    .map(([v, t]) => `<option value="${v}" ${user?.role === v ? "selected" : ""}>${t}</option>`).join("");
  const fieldRows = fields.map(f => `
    <div class="form-item">
      <label>${esc(f.label)} ${f.required ? "*" : ""}${f.readonly ? "（只读/自动）" : ""}</label>
      ${f.readonly ? `<input id="uf-${f.key}" value="${esc(user ? (user[f.key] ?? "") : "")}" disabled>` : fieldInputHtml(f, user ? (user[f.key] ?? "") : "")}
    </div>`).join("");
  openModal(isNew ? "新增用户" : `编辑用户 - ${esc(user.username)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>工号（登录账号） *</label>
        <input id="uf-username" value="${user ? esc(user.username) : ""}" ${isNew ? "" : "disabled"}></div>
      <div class="form-item"><label>系统角色</label><select id="uf-role">${roleOptions}</select></div>
      <div class="form-item"><label>密码 ${isNew ? "（默认 123456）" : "（留空则不修改）"}</label>
        <input id="uf-password" type="text" ${isNew ? `value="123456"` : ""}></div>
      ${fieldRows}
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="uf-save">保存</button>`);
  $("#uf-save").addEventListener("click", async () => {
    const payload = {
      username: $("#uf-username").value.trim(),
      password: $("#uf-password").value,
      role: $("#uf-role").value,
    };
    for (const f of fields) {
      const el = $(`#uf-${f.key}`);
      if (el) payload[f.key] = f.type === "select" ? el.value : el.value.trim();
    }
    try {
      if (isNew) await api("/api/users", { method: "POST", json: payload });
      else await api(`/api/users/${user.id}`, { method: "PUT", json: payload });
      toast("已保存");
      closeModal();
      await loadPermData();
      renderPermGridBody();
    } catch (e) { toast(e.message, true); }
  });
}

function openBatchEditModal() {
  const ids = permSelectedUserIds();
  if (!ids.length) return;
  const fields = (permOptions.user_fields || []).filter(f => !f.readonly && f.key !== "display_name");
  const fieldRows = fields.map(f => `
    <div class="form-item">
      <label>${esc(f.label)}（留空不变）</label>
      ${f.type === "select"
        ? `<select id="be-${f.key}"><option value="">（不变）</option>${(f.options||[]).map(o=>`<option value="${esc(o)}">${esc(o)}</option>`).join("")}</select>`
        : `<input id="be-${f.key}" placeholder="（不变）">`}
    </div>`).join("");
  openModal(`批量修改 ${ids.length} 个用户的附属信息`, `
    <p style="font-size:12px;color:#64748b;margin-bottom:10px">仅填写并保存的字段会被批量更新；留空字段保持不变。</p>
    <div class="form-grid" style="grid-template-columns:1fr 1fr">${fieldRows}</div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="be-save">批量保存</button>`);
  $("#be-save").addEventListener("click", async () => {
    const patch = {};
    for (const f of fields) {
      const el = $(`#be-${f.key}`);
      const val = f.type === "select" ? el.value : el.value.trim();
      if (val) patch[f.key] = val;
    }
    if (!Object.keys(patch).length) { toast("未填写任何字段"); return; }
    try {
      const r = await api("/api/users/batch", { method: "PUT", json: { ids, patch } });
      toast(`已批量修改 ${r.updated} 个用户`);
      closeModal();
      await loadPermData();
      renderPermGridBody();
    } catch (e) { toast(e.message, true); }
  });
}

function renderFieldConfigCard() {
  const fields = permOptions.user_fields || [];
  $("#perm-field-config").innerHTML = `
    <p style="font-size:12px;color:#64748b;margin-bottom:10px">
      在 <code>config/user_fields.json</code> 中新增字段并定义操作模式（text 自由输入 / select 单选下拉，options 为可选项）。<br>
      <b>builtin</b> 字段对应 users 表内置列；非 builtin 字段存入 <code>users.extra</code>(JSON)。
    </p>
    <div class="table-wrap"><table>
      <thead><tr><th>字段key</th><th>标签</th><th>类型</th><th>操作模式/可选项</th><th>必填</th><th>归属</th></tr></thead>
      <tbody>${fields.map(f => `
        <tr>
          <td class="mono">${esc(f.key)}</td>
          <td>${esc(f.label)}</td>
          <td>${esc(f.type)}</td>
          <td>${f.type === "select" ? (f.options || []).map(esc).join("、") : "自由输入"}</td>
          <td>${f.required ? "是" : "否"}</td>
          <td>${f.builtin ? "内置列" : "extra(JSON)"}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}
