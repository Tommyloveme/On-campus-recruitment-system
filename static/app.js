/* 校招候选人管理系统 - 前端逻辑（原生JS，无构建依赖） */
"use strict";

const state = {
  me: null,
  fields: [],
  groups: [],
  tab: "candidates",
  logPage: 1,
};

/* ---------------- 基础工具 ---------------- */
async function api(url, options = {}) {
  if (options.json !== undefined) {
    options.body = JSON.stringify(options.json);
    options.headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    delete options.json;
  }
  const res = await fetch(url, options);
  let body = null;
  try { body = await res.json(); } catch (_) { /* 文件下载等场景 */ }
  if (!res.ok) {
    const msg = (body && body.error) || `请求失败 (${res.status})`;
    if (res.status === 401 && state.me) { showLogin(); }
    throw new Error(msg);
  }
  return body;
}

function $(sel) { return document.querySelector(sel); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let toastTimer = null;
function toast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
}

function openModal(title, bodyHtml, footHtml) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = bodyHtml;
  $("#modal-foot").innerHTML = footHtml || "";
  $("#modal-mask").classList.remove("hidden");
}
function closeModal() { $("#modal-mask").classList.add("hidden"); }
$("#modal-mask").addEventListener("click", e => { if (e.target.id === "modal-mask") closeModal(); });

const isAdmin = () => state.me && state.me.role === "admin";
const canEdit = gid => isAdmin() || (state.me.role === "editor" && state.me.group_id === gid);
const visibleFields = () => state.fields.filter(f => f.visible);

/* ---------------- 登录 ---------------- */
function showLogin() {
  state.me = null;
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

async function doLogin() {
  const username = $("#login-username").value.trim();
  const password = $("#login-password").value;
  const errEl = $("#login-error");
  errEl.classList.add("hidden");
  try {
    state.me = await api("/api/login", { method: "POST", json: { username, password } });
    await boot();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  }
}

$("#login-btn").addEventListener("click", doLogin);
$("#login-password").addEventListener("keydown", e => { if (e.key === "Enter") doLogin(); });
$("#logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  showLogin();
});

/* ---------------- 主框架 ---------------- */
async function boot() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  const roleName = { admin: "管理员", editor: "编辑", viewer: "只读" }[state.me.role];
  $("#user-info").textContent =
    `${state.me.display_name}（${roleName}${state.me.group_name ? " · " + state.me.group_name : ""}）`;

  const [cfg, groups] = await Promise.all([api("/api/config"), api("/api/groups")]);
  state.fields = cfg.fields;
  state.groups = groups;

  const tabs = [["candidates", "候选人"]];
  if (isAdmin()) tabs.push(["overview", "全局总览"]);
  tabs.push(["logs", "操作日志"]);
  if (isAdmin()) tabs.push(["admin", "系统管理"]);
  $("#nav-tabs").innerHTML = tabs.map(([id, name]) =>
    `<button class="tab" data-tab="${id}">${name}</button>`).join("");
  $("#nav-tabs").querySelectorAll(".tab").forEach(btn =>
    btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
  switchTab("candidates");
}

function switchTab(tab) {
  state.tab = tab;
  $("#nav-tabs").querySelectorAll(".tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === tab));
  ({ candidates: renderCandidates, overview: renderOverview, logs: renderLogs, admin: renderAdmin }[tab])();
}

/* ---------------- 候选人页 ---------------- */
const BADGE_RULES = {
  offer_status: { "已接受": "green", "已发放": "blue", "未发放": "gray", "已拒绝": "red" },
  sign_status: { "已签约": "green", "未签约": "yellow", "已违约": "red" },
  physical_exam_done: { "是": "green", "否": "gray" },
  onboard_booked: { "是": "green", "否": "gray" },
  onboarded: { "是": "green", "否": "gray" },
  onboard_risk: { "无": "green", "低": "blue", "中": "yellow", "高": "red" },
};

function cellHtml(field, value) {
  const v = value ?? "";
  if (v === "") return `<span style="color:#cbd5e1">—</span>`;
  const rule = BADGE_RULES[field.key];
  if (rule) return `<span class="badge badge-${rule[v] || "gray"}">${esc(v)}</span>`;
  return esc(v);
}

async function renderCandidates() {
  const groupOpts = state.groups.map(g =>
    `<option value="${g.id}">${esc(g.name)}（${g.candidate_count}）</option>`).join("");
  $("#main").innerHTML = `
    <div class="toolbar">
      <input type="text" id="cand-search" placeholder="搜索姓名 / 电话 / 部门 / 任意字段…">
      ${isAdmin() ? `<select id="cand-group"><option value="">全部分组</option>${groupOpts}</select>` : ""}
      <div class="spacer"></div>
      <button class="btn" id="btn-template">下载导入模板</button>
      <button class="btn" id="btn-import">Excel 导入</button>
      <button class="btn btn-primary" id="btn-add">+ 新增候选人</button>
    </div>
    <div id="cand-table" class="table-wrap"><div class="empty">加载中…</div></div>`;

  $("#btn-template").addEventListener("click", () => { location.href = "/api/import/template"; });
  $("#btn-import").addEventListener("click", openImportModal);
  $("#btn-add").addEventListener("click", () => openCandidateModal(null));
  $("#cand-search").addEventListener("input", debounce(loadCandidateTable, 300));
  const sel = $("#cand-group");
  if (sel) sel.addEventListener("change", loadCandidateTable);
  await loadCandidateTable();
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function loadCandidateTable() {
  const q = $("#cand-search")?.value.trim() || "";
  const gid = $("#cand-group")?.value || "";
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (gid) params.set("group_id", gid);
  const list = await api("/api/candidates?" + params);
  const fields = visibleFields();
  const showGroupCol = isAdmin();
  if (!list.length) {
    $("#cand-table").innerHTML = `<div class="empty">暂无候选人数据，可通过「Excel 导入」或「新增候选人」添加</div>`;
    return;
  }
  const head = `<tr>${showGroupCol ? "<th>分组</th>" : ""}${fields.map(f => `<th>${esc(f.label)}</th>`).join("")}<th>操作</th></tr>`;
  const rows = list.map(c => `
    <tr>
      ${showGroupCol ? `<td><span class="badge badge-gray">${esc(c.group_name)}</span></td>` : ""}
      ${fields.map(f => `<td>${cellHtml(f, c.data[f.key])}</td>`).join("")}
      <td>
        ${canEdit(c.group_id)
          ? `<button class="btn btn-sm" data-edit="${c.id}">编辑</button>
             <button class="btn btn-sm btn-danger" data-del="${c.id}">删除</button>`
          : `<span style="color:#94a3b8;font-size:12px">只读</span>`}
      </td>
    </tr>`).join("");
  $("#cand-table").innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  $("#cand-table").querySelectorAll("[data-edit]").forEach(b =>
    b.addEventListener("click", () => openCandidateModal(list.find(c => c.id === +b.dataset.edit))));
  $("#cand-table").querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () => deleteCandidate(list.find(c => c.id === +b.dataset.del))));
}

function fieldInput(f, value) {
  const v = esc(value ?? "");
  if (f.type === "select") {
    const opts = ["", ...(f.options || [])].map(o =>
      `<option value="${esc(o)}" ${o === (value ?? "") ? "selected" : ""}>${o === "" ? "（未填写）" : esc(o)}</option>`).join("");
    return `<select data-field="${f.key}">${opts}</select>`;
  }
  const type = f.type === "date" ? "date" : "text";
  return `<input type="${type}" data-field="${f.key}" value="${v}">`;
}

function openCandidateModal(cand) {
  const editable = state.fields.filter(f => f.editable);
  const isNew = !cand;
  const editableGroups = state.groups.filter(g => canEdit(g.id));
  const groupSelect = isNew ? `
    <div class="form-item">
      <label>所属分组 *</label>
      <select id="cand-modal-group">
        ${editableGroups.map(g => `<option value="${g.id}" ${state.me.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}
      </select>
    </div>` : `
    <div class="form-item"><label>所属分组</label><input value="${esc(cand.group_name)}" disabled></div>`;

  openModal(isNew ? "新增候选人" : `编辑候选人 - ${esc(cand.data.name || "")}`, `
    ${groupSelect}
    <div class="form-grid">
      ${editable.map(f => `
        <div class="form-item">
          <label>${esc(f.label)}${f.required ? " *" : ""}</label>
          ${fieldInput(f, cand ? cand.data[f.key] : "")}
        </div>`).join("")}
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="cand-save">保存</button>`);

  $("#cand-save").addEventListener("click", async () => {
    const data = {};
    $("#modal-body").querySelectorAll("[data-field]").forEach(el => { data[el.dataset.field] = el.value; });
    try {
      if (isNew) {
        const gid = +$("#cand-modal-group").value;
        await api("/api/candidates", { method: "POST", json: { group_id: gid, data } });
        toast("候选人已新增");
      } else {
        const r = await api(`/api/candidates/${cand.id}`, { method: "PUT", json: { data } });
        toast(r.changed ? `已保存，更新了 ${r.changed} 项信息` : "内容无变化");
      }
      closeModal();
      state.groups = await api("/api/groups");
      loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

function deleteCandidate(cand) {
  openModal("删除确认",
    `<p>确定删除候选人「<b>${esc(cand.data.name || "")}</b>」吗？该操作会记录到日志，但数据不可恢复。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="del-confirm">确认删除</button>`);
  $("#del-confirm").addEventListener("click", async () => {
    try {
      await api(`/api/candidates/${cand.id}`, { method: "DELETE" });
      toast("已删除");
      closeModal();
      state.groups = await api("/api/groups");
      loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- Excel 导入 ---------------- */
function openImportModal() {
  const editableGroups = state.groups.filter(g => canEdit(g.id));
  if (!editableGroups.length) { toast("您没有任何分组的编辑权限", true); return; }
  const importCols = state.fields.filter(f => f.importable).map(f => f.excel_column).join("、");
  openModal("Excel 导入候选人", `
    <div class="form-item">
      <label>导入到分组</label>
      <select id="import-group">
        ${editableGroups.map(g => `<option value="${g.id}" ${state.me.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}
      </select>
    </div>
    <div class="form-item">
      <label>选择 .xlsx 文件（第一行为表头）</label>
      <input type="file" id="import-file" accept=".xlsx">
    </div>
    <p style="font-size:12px;color:#64748b;line-height:1.8">
      当前配置可导入的列（在 config/fields.json 中可调整）：<br>${esc(importCols)}<br>
      已存在的候选人（按电话或姓名匹配）将被更新，其余新增。
    </p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="import-go">开始导入</button>`);

  $("#import-go").addEventListener("click", async () => {
    const file = $("#import-file").files[0];
    if (!file) { toast("请先选择文件", true); return; }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("group_id", $("#import-group").value);
    try {
      const r = await api("/api/import", { method: "POST", body: fd });
      toast(`导入完成：新增 ${r.created} 人，更新 ${r.updated} 人${r.skipped ? "，跳过 " + r.skipped + " 行" : ""}`);
      closeModal();
      state.groups = await api("/api/groups");
      loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- 管理员总览 ---------------- */
async function renderOverview() {
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  const groups = await api("/api/overview");
  const fields = visibleFields();
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

/* ---------------- 操作日志 ---------------- */
const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], user: ["用户", "gray"], group: ["分组", "gray"], config: ["配置", "gray"],
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

/* ---------------- 系统管理（管理员） ---------------- */
async function renderAdmin() {
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
          <div class="section-title">网页字段显示配置</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">勾选 = 在候选人列表/总览中显示该列（同步写入 config/fields.json）</p>
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
  await Promise.all([loadGroupList(), loadUserList()]);
  renderFieldConfig();

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

async function loadGroupList() {
  state.groups = await api("/api/groups");
  $("#group-list").innerHTML = state.groups.map(g => `
    <div class="tag-row">
      <span>${esc(g.name)} <span class="badge badge-gray">${g.candidate_count} 人</span></span>
      <button class="btn btn-sm btn-danger" data-gdel="${g.id}">删除</button>
    </div>`).join("") || `<div class="empty" style="padding:16px">暂无分组，请先创建</div>`;
  $("#group-list").querySelectorAll("[data-gdel]").forEach(b =>
    b.addEventListener("click", async () => {
      try {
        await api(`/api/groups/${b.dataset.gdel}`, { method: "DELETE" });
        toast("分组已删除");
        loadGroupList();
      } catch (e) { toast(e.message, true); }
    }));
}

async function loadUserList() {
  const users = await api("/api/users");
  const roleName = { admin: "管理员", editor: "编辑", viewer: "只读" };
  $("#user-list").innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>账号</th><th>姓名</th><th>角色</th><th>所属分组</th><th>操作</th></tr></thead>
      <tbody>
        ${users.map(u => `
          <tr>
            <td>${esc(u.username)}</td>
            <td>${esc(u.display_name)}</td>
            <td><span class="badge badge-${u.role === "admin" ? "red" : u.role === "editor" ? "blue" : "gray"}">${roleName[u.role]}</span></td>
            <td>${esc(u.group_name || "—")}</td>
            <td>
              <button class="btn btn-sm" data-uedit="${u.id}">编辑</button>
              ${u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}
            </td>
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
  const groupOpts = [`<option value="">（无分组）</option>`,
    ...state.groups.map(g =>
      `<option value="${g.id}" ${user && user.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`)].join("");
  openModal(isNew ? "新增用户" : `编辑用户 - ${esc(user.username)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>登录账号 *</label>
        <input id="u-username" value="${user ? esc(user.username) : ""}" ${isNew ? "" : "disabled"}></div>
      <div class="form-item"><label>显示姓名</label>
        <input id="u-display" value="${user ? esc(user.display_name) : ""}"></div>
      <div class="form-item"><label>密码 ${isNew ? "*" : "（留空则不修改）"}</label>
        <input id="u-password" type="password" autocomplete="new-password"></div>
      <div class="form-item"><label>角色</label>
        <select id="u-role">
          <option value="editor" ${user?.role === "editor" ? "selected" : ""}>编辑（可改本组数据）</option>
          <option value="viewer" ${user?.role === "viewer" ? "selected" : ""}>只读（仅查看本组）</option>
          <option value="admin" ${user?.role === "admin" ? "selected" : ""}>管理员（全部权限）</option>
        </select></div>
      <div class="form-item"><label>所属权限分组</label>
        <select id="u-group">${groupOpts}</select></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="u-save">保存</button>`);

  $("#u-save").addEventListener("click", async () => {
    const payload = {
      username: $("#u-username").value.trim(),
      display_name: $("#u-display").value.trim(),
      password: $("#u-password").value,
      role: $("#u-role").value,
      group_id: $("#u-group").value ? +$("#u-group").value : null,
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

function renderFieldConfig() {
  $("#field-config").innerHTML = state.fields.map(f => `
    <label><input type="checkbox" data-fkey="${f.key}" ${f.visible ? "checked" : ""}> ${esc(f.label)}</label>`).join("");
}

async function saveFieldConfig() {
  const updates = [...$("#field-config").querySelectorAll("[data-fkey]")].map(el =>
    ({ key: el.dataset.fkey, visible: el.checked }));
  try {
    const r = await api("/api/config", { method: "PUT", json: { fields: updates } });
    state.fields = r.fields;
    toast("字段显示配置已保存");
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 启动 ---------------- */
(async function init() {
  try {
    state.me = await api("/api/me");
    await boot();
  } catch (_) {
    showLogin();
  }
})();
