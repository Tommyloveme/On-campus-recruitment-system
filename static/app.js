/* 校招候选人管理系统 - 前端逻辑（原生JS，无构建依赖） */
"use strict";

const state = {
  me: null,
  fields: [],   // 当前用户生效的字段配置（含分组覆盖）
  groups: [],
  app: {},      // 界面运行配置（分页大小等，来自 config/app_config.json 的 ui 部分）
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
  let res;
  try {
    res = await fetch(url, options);
  } catch (_) {
    // 网络层失败（服务未启动/断网）
    toast("网络异常：无法连接服务器，请确认服务是否在线", true);
    throw new Error("网络异常");
  }
  let body = null;
  try { body = await res.json(); } catch (_) { /* 文件下载等场景 */ }
  if (!res.ok) {
    // 会话失效：给出明确提示并回到登录页
    if (res.status === 401 && state.me) {
      toast("登录已失效，请重新登录", true);
      showLogin();
      throw new Error("登录已失效");
    }
    const msg = (body && body.error) ||
      (res.status === 403 ? "无权限执行该操作" : `操作失败 (${res.status})`);
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

const ROLE_NAMES = { admin: "系统管理员", global_viewer: "全局查看员", group_admin: "组管理员", editor: "组成员", viewer: "只读" };
const isAdmin = () => state.me && state.me.role === "admin";
const isGroupAdmin = () => state.me && state.me.role === "group_admin";
/* 可跨分组查看全部数据（界面与管理员一致，但全局查看员只读且无系统管理） */
const canSeeAll = () => state.me && ["admin", "global_viewer"].includes(state.me.role);
/* 可新增/导入候选人 */
const canCreate = () => state.me && ["admin", "group_admin", "editor"].includes(state.me.role);
const canEdit = gid => isAdmin() ||
  (["group_admin", "editor"].includes(state.me.role) && state.me.group_id === gid);
const canDelete = gid => isAdmin() || (isGroupAdmin() && state.me.group_id === gid);
/* 可使用批量删除功能 */
const canBatchDelete = () => isAdmin() || isGroupAdmin();
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
  const roleName = ROLE_NAMES[state.me.role] || state.me.role;
  $("#user-info").textContent =
    `${state.me.display_name}（${roleName}${state.me.group_name ? " · " + state.me.group_name : ""}）`;

  const [cfg, groups] = await Promise.all([api("/api/config"), api("/api/groups")]);
  state.fields = cfg.fields;
  state.app = cfg.app || {};
  state.groups = groups;
  cand.pageSize = state.app.page_size ?? 15;   // 每页默认条数由配置决定
  // 长内容截断的默认宽度由配置决定（app_config.json -> ui.clip_max_width）
  if (state.app.clip_max_width)
    document.documentElement.style.setProperty("--clip-max", state.app.clip_max_width + "px");

  const tabs = [["candidates", "候选人"]];
  if (canSeeAll()) tabs.push(["overview", "全局总览"]);
  if (canSeeAll() || isGroupAdmin()) tabs.push(["charts", "数据图表"]);
  tabs.push(["logs", "操作日志"]);
  if (isAdmin()) tabs.push(["admin", "系统管理"]);   // 全局查看员无系统管理入口
  else if (isGroupAdmin()) tabs.push(["admin", "成员管理"]);
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
  ({ candidates: renderCandidates, overview: renderOverview, charts: renderCharts,
     logs: renderLogs, admin: renderAdmin }[tab])();
}

/* ---------------- 候选人页 ---------------- */
/* 徽章颜色来自字段配置（fields.json 的 colors 属性），无需改代码即可调整 */
function cellHtml(field, value) {
  const v = value ?? "";
  if (v === "") return `<span style="color:#cbd5e1">—</span>`;
  if (field.colors) return `<span class="badge badge-${field.colors[v] || "gray"}">${esc(v)}</span>`;
  // 过长内容：单元格内省略号截断，悬浮显示完整内容
  return `<span class="clip" title="${esc(v)}">${esc(v)}</span>`;
}

/* 今天日期前缀，用于「当前进展」快捷填写，如 0612： */
function todayPrefix() {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}：`;
}

const cand = {
  list: [],           // 服务端返回的完整列表
  sort: null,         // {key, dir: 1|-1}
  selected: new Set(),// 勾选的候选人 id
  uploadTarget: null, // 待上传简历的候选人 id
  page: 1,
  pageSize: 30,       // 默认每页30人，可手动调整
};

async function renderCandidates() {
  const fields = visibleFields();
  const showGroupCol = canSeeAll();

  // 表头第一行：列名（日期列可点击排序）；第二行：每列筛选条件（可多列组合）
  const headCells = fields.map(f => f.type === "date"
    ? `<th class="sortable" data-sortkey="${f.key}" title="点击排序">${esc(f.label)}<span class="sort-arrow" data-arrow="${f.key}"></span></th>`
    : `<th>${esc(f.label)}</th>`).join("");
  const filterCells = fields.map(f => {
    if (f.type === "select") {
      const opts = (f.options || []).map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
      return `<th><select data-filter="${f.key}"><option value="">全部</option>${opts}</select></th>`;
    }
    return `<th><input type="text" data-filter="${f.key}" placeholder="筛选"></th>`;
  }).join("");
  const groupFilter = showGroupCol
    ? `<th><select data-filter="__group"><option value="">全部</option>
        ${state.groups.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}</select></th>`
    : "";

  $("#main").innerHTML = `
    <div class="toolbar">
      <input type="text" id="cand-search" placeholder="全局搜索：姓名 / 电话 / 部门 / 任意字段…">
      <button class="btn btn-sm" id="btn-clear-filter">清空筛选</button>
      <div class="spacer"></div>
      ${canBatchDelete() ? `<button class="btn btn-danger" id="btn-batch-del" disabled>删除选中 (0)</button>` : ""}
      <button class="btn" id="btn-export-excel" disabled>导出选中Excel (0)</button>
      <button class="btn" id="btn-export-resume" disabled>导出选中简历 (0)</button>
      ${canCreate() ? `
        <button class="btn" id="btn-template">下载导入模板</button>
        <button class="btn" id="btn-import">Excel 导入</button>
        <button class="btn btn-primary" id="btn-add">+ 新增候选人</button>` : ""}
    </div>
    <div id="cand-table" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" id="sel-all" title="全选当前筛选结果"></th>
            ${showGroupCol ? "<th>分组</th>" : ""}${headCells}<th>简历</th><th>操作</th>
          </tr>
          <tr class="filter-row">
            <th></th>${groupFilter}${filterCells}<th></th><th></th>
          </tr>
        </thead>
        <tbody id="cand-tbody"></tbody>
      </table>
    </div>
    <div id="cand-pager" class="pager-bar"></div>
    <input type="file" id="resume-input" accept=".pdf,.docx" style="display:none">`;

  if (canCreate()) {
    $("#btn-template").addEventListener("click", () => { location.href = "/api/import/template"; });
    $("#btn-import").addEventListener("click", openImportModal);
    $("#btn-add").addEventListener("click", () => openCandidateModal(null));
  }
  if (canBatchDelete()) $("#btn-batch-del").addEventListener("click", batchDeleteSelected);
  $("#btn-export-resume").addEventListener("click", exportSelectedResumes);
  $("#btn-export-excel").addEventListener("click", exportSelectedExcel);
  enableColumnResize();
  const onFilterChange = () => { cand.page = 1; renderCandidateRows(); };
  $("#cand-search").addEventListener("input", debounce(onFilterChange, 250));
  $("#btn-clear-filter").addEventListener("click", () => {
    $("#cand-search").value = "";
    document.querySelectorAll("[data-filter]").forEach(el => { el.value = ""; });
    cand.sort = null;
    onFilterChange();
  });
  document.querySelectorAll("[data-filter]").forEach(el =>
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", debounce(onFilterChange, 250)));
  document.querySelectorAll(".sortable").forEach(th =>
    th.addEventListener("click", () => toggleSort(th.dataset.sortkey)));
  $("#sel-all").addEventListener("change", e => {
    const ids = filteredCandidates().map(c => c.id);
    if (e.target.checked) ids.forEach(id => cand.selected.add(id));
    else ids.forEach(id => cand.selected.delete(id));
    renderCandidateRows();
  });
  $("#resume-input").addEventListener("change", onResumeFilePicked);

  await loadCandidateTable();
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/* 重新从服务端拉取数据（新增/导入/删除后调用） */
async function loadCandidateTable() {
  cand.list = await api("/api/candidates");
  const ids = new Set(cand.list.map(c => c.id));
  cand.selected.forEach(id => { if (!ids.has(id)) cand.selected.delete(id); });
  renderCandidateRows();
}

/* 组合筛选：全局搜索 + 各列条件（AND 关系），支持单列或多列同时生效 */
function filteredCandidates() {
  let list = cand.list;
  const q = ($("#cand-search")?.value || "").trim().toLowerCase();
  if (q) {
    list = list.filter(c =>
      Object.values(c.data).some(v => String(v).toLowerCase().includes(q)) ||
      c.group_name.toLowerCase().includes(q));
  }
  document.querySelectorAll("[data-filter]").forEach(el => {
    const val = el.value.trim();
    if (!val) return;
    const key = el.dataset.filter;
    if (key === "__group") {
      list = list.filter(c => String(c.group_id) === val);
    } else if (el.tagName === "SELECT") {
      list = list.filter(c => (c.data[key] || "") === val);
    } else {
      const lv = val.toLowerCase();
      list = list.filter(c => String(c.data[key] || "").toLowerCase().includes(lv));
    }
  });
  if (cand.sort) {
    const { key, dir } = cand.sort;
    list = [...list].sort((a, b) => {
      const av = a.data[key] || "", bv = b.data[key] || "";
      if (!av && !bv) return 0;
      if (!av) return 1;          // 空值始终排最后
      if (!bv) return -1;
      return av.localeCompare(bv) * dir;
    });
  }
  return list;
}

function toggleSort(key) {
  if (!cand.sort || cand.sort.key !== key) cand.sort = { key, dir: 1 };
  else if (cand.sort.dir === 1) cand.sort = { key, dir: -1 };
  else cand.sort = null;
  document.querySelectorAll("[data-arrow]").forEach(el => {
    el.textContent = (cand.sort && cand.sort.key === el.dataset.arrow)
      ? (cand.sort.dir === 1 ? " ↑" : " ↓") : "";
  });
  renderCandidateRows();
}

function resumeCellHtml(c) {
  const editable = canEdit(c.group_id);
  if (c.resume_name) {
    return `
      <span class="resume-actions" title="${esc(c.resume_name)}">
        <button class="btn btn-sm" data-resprev="${c.id}">预览</button>
        <button class="btn btn-sm" data-resdl="${c.id}">下载</button>
        ${editable ? `<button class="btn btn-sm" data-resup="${c.id}">更换</button>` : ""}
        ${canDelete(c.group_id) ? `<button class="btn btn-sm btn-danger" data-resdel="${c.id}">删除</button>` : ""}
      </span>`;
  }
  return editable
    ? `<button class="btn btn-sm" data-resup="${c.id}">上传</button>`
    : `<span style="color:#cbd5e1">—</span>`;
}

function renderCandidateRows() {
  const tbody = $("#cand-tbody");
  if (!tbody) return;
  const fields = visibleFields();
  const showGroupCol = isAdmin();
  const list = filteredCandidates();
  const colCount = 3 + fields.length + (showGroupCol ? 1 : 0);

  // 分页
  const total = list.length;
  const pages = cand.pageSize > 0 ? Math.max(1, Math.ceil(total / cand.pageSize)) : 1;
  cand.page = Math.min(Math.max(1, cand.page), pages);
  const pageList = cand.pageSize > 0
    ? list.slice((cand.page - 1) * cand.pageSize, cand.page * cand.pageSize)
    : list;

  if (!pageList.length) {
    tbody.innerHTML = `<tr><td colspan="${colCount}" class="empty">没有符合条件的候选人</td></tr>`;
  } else {
    tbody.innerHTML = pageList.map(c => `
      <tr>
        <td class="col-check"><input type="checkbox" data-sel="${c.id}" ${cand.selected.has(c.id) ? "checked" : ""}></td>
        ${showGroupCol ? `<td><span class="badge badge-gray">${esc(c.group_name)}</span></td>` : ""}
        ${fields.map(f => {
          let inner;
          if (f.key === "progress") {
            // 进展列只显示第一行（最新一条），完整内容悬浮可见
            const full = c.data.progress || "";
            const first = full.split("\n")[0];
            inner = full
              ? `<span class="clip" title="${esc(full)}">${esc(first)}</span>`
              : `<span style="color:#cbd5e1">—</span>`;
            if (canEdit(c.group_id))
              inner += ` <button class="btn btn-sm" data-prog="${c.id}" title="更新进展">更新</button>`;
          } else {
            inner = cellHtml(f, c.data[f.key]);
          }
          return `<td>${inner}</td>`;
        }).join("")}
        <td>${resumeCellHtml(c)}</td>
        <td>
          ${canEdit(c.group_id)
            ? `<button class="btn btn-sm" data-edit="${c.id}">编辑</button>` +
              (canDelete(c.group_id) ? `<button class="btn btn-sm btn-danger" data-del="${c.id}">删除</button>` : "")
            : `<span style="color:#94a3b8;font-size:12px">只读</span>`}
        </td>
      </tr>`).join("");
  }

  tbody.querySelectorAll("[data-sel]").forEach(cb =>
    cb.addEventListener("change", () => {
      const id = +cb.dataset.sel;
      cb.checked ? cand.selected.add(id) : cand.selected.delete(id);
      updateSelectionUI(list);
    }));
  tbody.querySelectorAll("[data-edit]").forEach(b =>
    b.addEventListener("click", () => openCandidateModal(cand.list.find(c => c.id === +b.dataset.edit))));
  tbody.querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () => deleteCandidate(cand.list.find(c => c.id === +b.dataset.del))));
  tbody.querySelectorAll("[data-resdl]").forEach(b =>
    b.addEventListener("click", () => { location.href = `/api/candidates/${b.dataset.resdl}/resume`; }));
  tbody.querySelectorAll("[data-resup]").forEach(b =>
    b.addEventListener("click", () => {
      cand.uploadTarget = +b.dataset.resup;
      $("#resume-input").value = "";
      $("#resume-input").click();
    }));
  tbody.querySelectorAll("[data-resdel]").forEach(b =>
    b.addEventListener("click", () => deleteResume(cand.list.find(c => c.id === +b.dataset.resdel))));
  tbody.querySelectorAll("[data-resprev]").forEach(b =>
    b.addEventListener("click", () => window.open(`/api/candidates/${b.dataset.resprev}/resume/preview`, "_blank")));
  tbody.querySelectorAll("[data-prog]").forEach(b =>
    b.addEventListener("click", () => openProgressModal(cand.list.find(c => c.id === +b.dataset.prog))));

  renderPager(total, pages);
  updateSelectionUI(list);
}

function renderPager(total, pages) {
  // 每页条数选项可在 config/app_config.json 中调整（0 = 全部）
  const sizes = state.app.page_size_options || [15, 30, 50, 100, 0];
  if (!sizes.includes(cand.pageSize)) sizes.unshift(cand.pageSize);
  $("#cand-pager").innerHTML = `
    <span>共 ${total} 人</span>
    <label>每页
      <select id="page-size">
        ${sizes.map(s => `<option value="${s}" ${s === cand.pageSize ? "selected" : ""}>${s === 0 ? "全部" : s}</option>`).join("")}
      </select>
    </label>
    <button class="btn btn-sm" id="page-prev" ${cand.page <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${cand.page} / ${pages} 页</span>
    <button class="btn btn-sm" id="page-next" ${cand.page >= pages ? "disabled" : ""}>下一页</button>`;
  $("#page-size").addEventListener("change", e => {
    cand.pageSize = +e.target.value;
    cand.page = 1;
    renderCandidateRows();
  });
  $("#page-prev").addEventListener("click", () => { cand.page--; renderCandidateRows(); });
  $("#page-next").addEventListener("click", () => { cand.page++; renderCandidateRows(); });
}

function updateSelectionUI(list) {
  const n = cand.selected.size;
  const btnR = $("#btn-export-resume"), btnE = $("#btn-export-excel"), btnD = $("#btn-batch-del");
  btnR.textContent = `导出选中简历 (${n})`;
  btnR.disabled = n === 0;
  btnE.textContent = `导出选中Excel (${n})`;
  btnE.disabled = n === 0;
  if (btnD) {
    btnD.textContent = `删除选中 (${n})`;
    btnD.disabled = n === 0;
  }
  const all = $("#sel-all");
  all.checked = list.length > 0 && list.every(c => cand.selected.has(c.id));
}

/* 批量删除选中候选人（仅系统管理员/组管理员） */
function batchDeleteSelected() {
  const n = cand.selected.size;
  if (!n) return;
  openModal("批量删除确认",
    `<p>确定删除选中的 <b>${n}</b> 名候选人吗？其简历文件将一并删除，操作会记入日志，但数据<b>不可恢复</b>。</p>
     <p style="font-size:12px;color:#64748b">无删除权限的候选人（非本组）将被自动跳过。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="batch-del-confirm">确认删除</button>`);
  $("#batch-del-confirm").addEventListener("click", async () => {
    try {
      const r = await api("/api/candidates/batch_delete", { method: "POST", json: { ids: [...cand.selected] } });
      toast(`已删除 ${r.deleted} 名候选人` + (r.skipped ? `，跳过无权限 ${r.skipped} 名` : ""));
      closeModal();
      cand.selected.clear();
      state.groups = await api("/api/groups");
      await loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------------- 列宽拖拽：所有列可横向拉伸 ---------------- */
function enableColumnResize() {
  const table = $("#cand-table table");
  if (!table) return;
  let styleEl = $("#col-width-style");
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "col-width-style";
    document.head.appendChild(styleEl);
  }
  const colWidths = {};
  const applyWidths = () => {
    styleEl.textContent = Object.entries(colWidths).map(([i, w]) =>
      `#cand-table th:nth-child(${i}), #cand-table td:nth-child(${i}) { width:${w}px; min-width:${w}px; }
       #cand-table td:nth-child(${i}) .clip { max-width:${Math.max(40, w - 24)}px; }`).join("\n");
  };
  table.querySelectorAll("thead tr:first-child th").forEach((th, idx) => {
    const handle = document.createElement("span");
    handle.className = "th-resize";
    handle.title = "拖动调整列宽";
    th.appendChild(handle);
    handle.addEventListener("click", e => e.stopPropagation());  // 不触发排序
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.pageX, startW = th.offsetWidth;
      const onMove = ev => {
        colWidths[idx + 1] = Math.max(48, startW + ev.pageX - startX);
        applyWidths();
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
      };
      document.body.style.cursor = "col-resize";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

/* ---------------- 简历操作 ---------------- */
async function onResumeFilePicked() {
  const file = $("#resume-input").files[0];
  if (!file || !cand.uploadTarget) return;
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (![".pdf", ".docx"].includes(ext)) { toast("仅支持 .pdf 和 .docx 格式", true); return; }
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api(`/api/candidates/${cand.uploadTarget}/resume`, { method: "POST", body: fd });
    toast("简历已保存");
    await loadCandidateTable();
  } catch (e) { toast(e.message, true); }
  cand.uploadTarget = null;
}

function deleteResume(c) {
  openModal("删除简历",
    `<p>确定删除候选人「<b>${esc(c.data.name || "")}</b>」的简历（${esc(c.resume_name)}）吗？</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="resdel-confirm">确认删除</button>`);
  $("#resdel-confirm").addEventListener("click", async () => {
    try {
      await api(`/api/candidates/${c.id}/resume`, { method: "DELETE" });
      toast("简历已删除");
      closeModal();
      await loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

async function exportSelectedResumes() {
  if (!cand.selected.size) return;
  try {
    const res = await fetch("/api/resumes/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...cand.selected] }),
    });
    if (!res.ok) {
      const j = await res.json();
      toast(j.error || "导出失败", true);
      return;
    }
    const count = res.headers.get("X-Export-Count") || cand.selected.size;
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `简历导出_${new Date().toISOString().slice(0, 10)}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${count} 份简历`);
  } catch (e) { toast(e.message, true); }
}

function fieldInput(f, value) {
  const v = esc(value ?? "");
  if (f.type === "select") {
    const opts = ["", ...(f.options || [])].map(o =>
      `<option value="${esc(o)}" ${o === (value ?? "") ? "selected" : ""}>${o === "" ? "（未填写）" : esc(o)}</option>`).join("");
    return `<select data-field="${f.key}">${opts}</select>`;
  }
  if (f.multiline) return `<textarea data-field="${f.key}" rows="3">${v}</textarea>`;
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
          ${fieldInput(f, cand ? cand.data[f.key]
                              : (f.key === "progress" ? todayPrefix() : ""))}
        </div>`).join("")}
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="cand-save">保存</button>`);

  $("#cand-save").addEventListener("click", async () => {
    const data = {};
    $("#modal-body").querySelectorAll("[data-field]").forEach(el => { data[el.dataset.field] = el.value; });
    // 客户端必填校验，立即给出提示
    const missing = editable.filter(f => f.required && !(data[f.key] || "").trim());
    if (missing.length) { toast(`请填写：${missing.map(f => f.label).join("、")}`, true); return; }
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

/* 快捷更新「当前进展」：新内容写在第一行（带今天日期前缀，如 0612：），历史记录顺次后移 */
function openProgressModal(c) {
  const cur = (c.data.progress || "").trim();
  const prefix = todayPrefix();
  const initial = cur ? prefix + "\n" + cur : prefix;
  openModal(`更新进展 - ${esc(c.data.name || "")}`, `
    <div class="form-item">
      <label>当前进展（最新一条写在第一行，列表只显示第一行）</label>
      <textarea id="prog-text" rows="8" style="width:100%">${esc(initial)}</textarea>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="prog-save">保存</button>`);
  const ta = $("#prog-text");
  ta.focus();
  ta.setSelectionRange(prefix.length, prefix.length);   // 光标定位到第一行日期前缀之后
  $("#prog-save").addEventListener("click", async () => {
    try {
      const r = await api(`/api/candidates/${c.id}`, { method: "PUT", json: { data: { progress: ta.value.trim() } } });
      toast(r.changed ? "进展已更新" : "内容无变化");
      closeModal();
      await loadCandidateTable();
    } catch (e) { toast(e.message, true); }
  });
}

/* 导出选中候选人为 Excel */
async function exportSelectedExcel() {
  if (!cand.selected.size) return;
  try {
    const res = await fetch("/api/candidates/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...cand.selected] }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      toast(j.error || "导出失败", true);
      return;
    }
    const count = res.headers.get("X-Export-Count") || cand.selected.size;
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `候选人导出_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${count} 名候选人的Excel`);
  } catch (e) { toast(e.message, true); }
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

/* ---------------- 数据图表（管理员，类Excel数据透视图） ---------------- */
const charts = { list: [], instance: null };
const CHART_COLORS = [
  "#2563eb", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#84cc16", "#0ea5e9", "#f97316", "#14b8a6", "#64748b",
];

async function renderCharts() {
  const fields = visibleFields();
  const dimOpts = [
    `<option value="__group">权限分组</option>`,
    ...fields.map(f =>
      `<option value="${f.key}" ${f.key === "offer_status" ? "selected" : ""}>${esc(f.label)}</option>`),
  ].join("");
  const serOpts = [
    `<option value="">（无）</option>`,
    `<option value="__group">权限分组</option>`,
    ...fields.filter(f => f.type === "select").map(f =>
      `<option value="${f.key}">${esc(f.label)}</option>`),
  ].join("");
  // 组管理员只能看本组数据，分组范围固定为本组
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
  const f = state.fields.find(f => f.key === key);
  return !!f && f.type === "date";
}

/* gran: ymd=按年月日, ym=按年月, m=按月份（跨年聚合） */
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
  if (key === "__group") return "权限分组";
  const f = state.fields.find(f => f.key === key);
  return f ? f.label : key;
}

/* 维度取值的展示顺序：select字段按配置选项顺序，日期按时间升序，其余按数量降序（最多30项） */
function orderedValues(list, key, gran) {
  const counts = new Map();
  list.forEach(c => {
    const v = chartValue(c, key, gran);
    counts.set(v, (counts.get(v) || 0) + 1);
  });
  const f = state.fields.find(f => f.key === key);
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
  if (["pie", "doughnut"].includes(type)) serKey = "";  // 饼图只看单一维度

  // 维度为日期列时显示粒度选择
  const dimIsDate = isDateField(dimKey);
  $("#ch-gran-wrap").classList.toggle("hidden", !dimIsDate);
  const gran = dimIsDate ? $("#ch-gran").value : null;

  let list = charts.list;
  if (gid) list = list.filter(c => String(c.group_id) === gid);
  $("#ch-count").textContent = `共 ${list.length} 名候选人`;

  const dims = orderedValues(list, dimKey, gran);
  const sers = serKey ? orderedValues(list, serKey) : null;

  // 透视计数：matrix[系列][维度]
  const matrix = (sers || ["数量"]).map(() => dims.map(() => 0));
  list.forEach(c => {
    const di = dims.indexOf(chartValue(c, dimKey, gran));
    if (di < 0) return;
    const si = sers ? sers.indexOf(chartValue(c, serKey)) : 0;
    if (si < 0) return;
    matrix[si][di] += 1;
  });

  const granName = { ymd: "按年月日", ym: "按年月", m: "按月份" }[gran] || "";
  const groupName = gid ? (state.groups.find(g => String(g.id) === gid)?.name || state.me.group_name || "") : "全部分组";
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

/* ---------------- 操作日志 ---------------- */
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

/* ---------------- 系统管理（管理员） ---------------- */
async function renderAdmin() {
  if (isGroupAdmin()) {
    // 组管理员：管理本组成员 + 本组的字段显示配置
    $("#main").innerHTML = `
      <div class="admin-grid">
        <div class="card">
          <div class="section-title">成员管理 - ${esc(state.me.group_name || "")}</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">您可以向本组添加「组成员」或「只读」账号（默认密码 123456）；修改与删除用户需联系系统管理员。</p>
          <div id="user-list"></div>
          <button class="btn btn-primary" id="btn-add-user" style="margin-top:12px">+ 添加本组成员</button>
        </div>
        <div class="card">
          <div class="section-title">本组字段显示配置</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">勾选 = 本组成员的候选人列表中显示该列（仅影响本组，保存为本组独立配置文件）</p>
          <div class="check-grid" id="field-config"></div>
          <button class="btn btn-primary btn-sm" id="btn-save-fields" style="margin-top:12px">保存本组配置</button>
        </div>
      </div>`;
    await loadUserList();
    $("#btn-add-user").addEventListener("click", () => openUserModal(null));
    fieldCfg.scope = "self";
    fieldCfg.fields = state.fields;
    renderFieldConfig();
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
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">系统每小时自动备份一次，保留 3 天（可在 app_config.json 调整）；恢复前会自动保存当前状态。</p>
          <div id="backup-list" style="max-height:260px;overflow-y:auto"></div>
          <button class="btn btn-primary btn-sm" id="btn-backup-now" style="margin-top:12px">立即备份</button>
        </div>
        <div class="card">
          <div class="section-title">网页字段显示配置</div>
          <p style="font-size:12px;color:#64748b;margin-bottom:10px">全局配置写入 config/fields.json；分组配置各自独立成文件（fields_group_*.json），仅覆盖显示开关</p>
          <div class="form-item" style="max-width:260px">
            <label>配置范围</label>
            <select id="field-scope">
              <option value="">全局默认配置</option>
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
  fieldCfg.scope = "";
  fieldCfg.fields = state.fields;
  renderFieldConfig();
  $("#field-scope").addEventListener("change", async e => {
    fieldCfg.scope = e.target.value;
    const r = await api("/api/config" + (fieldCfg.scope ? "?group_id=" + fieldCfg.scope : ""));
    fieldCfg.fields = r.fields;
    renderFieldConfig();
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

/* 备份列表 + 一键恢复（仅管理员） */
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
    : `<div class="empty" style="padding:16px">暂无备份，服务启动后会自动生成</div>`;
  $("#backup-list").querySelectorAll("[data-restore]").forEach(btn =>
    btn.addEventListener("click", () => confirmRestore(btn.dataset.restore)));
}

function confirmRestore(name) {
  openModal("恢复数据确认", `
    <p>确定将系统数据恢复至备份 <b>${esc(name)}</b> 吗？</p>
    <p style="font-size:12px;color:#64748b;line-height:1.8">
      · 恢复会覆盖当前的候选人、用户、分组与日志数据；<br>
      · 恢复前系统会自动保存当前状态为一份新的手动备份，误操作可再恢复回来；<br>
      · 恢复完成后页面将自动刷新。
    </p>`,
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
    ? [["editor", "组成员（本组增/改/查，无删除权）"],
       ["viewer", "只读（仅查看本组）"]]
    : [["editor", "组成员（本组增/改/查，无删除权）"],
       ["group_admin", "组管理员（本组增/删/改/查 + 添加本组成员）"],
       ["viewer", "只读（仅查看本组）"],
       ["global_viewer", "全局查看员（查看所有分组/总览/图表，只读，无系统管理）"],
       ["admin", "系统管理员（全部权限）"]])
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
        <input id="u-password" type="${isNew ? "text" : "password"}" autocomplete="new-password"
               ${isNew ? `value="123456"` : ""}></div>
      <div class="form-item"><label>角色</label>
        <select id="u-role">${roleOptions}</select></div>
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
      // 组管理员模式下无分组选择框，后端会强制归入其本组
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

const fieldCfg = { scope: "", fields: [] };  // scope: ""=全局, 数字=分组id, "self"=组管理员本组

function renderFieldConfig() {
  $("#field-config").innerHTML = fieldCfg.fields.map(f => `
    <label><input type="checkbox" data-fkey="${f.key}" ${f.visible ? "checked" : ""}> ${esc(f.label)}</label>`).join("");
}

async function saveFieldConfig() {
  const updates = [...$("#field-config").querySelectorAll("[data-fkey]")].map(el =>
    ({ key: el.dataset.fkey, visible: el.checked }));
  const payload = { fields: updates };
  if (fieldCfg.scope && fieldCfg.scope !== "self") payload.group_id = +fieldCfg.scope;
  try {
    const r = await api("/api/config", { method: "PUT", json: payload });
    fieldCfg.fields = r.fields;
    // 影响当前用户自己列表视图时同步刷新
    if (fieldCfg.scope === "self" || (isAdmin() && !fieldCfg.scope)) state.fields = r.fields;
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
