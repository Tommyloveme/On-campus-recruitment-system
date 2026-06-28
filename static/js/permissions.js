"use strict";

/* 权限管理：单一 Excel 式 用户×模块 权限矩阵页，仅系统管理员。
 * 行=用户(工号唯一)；列=附属信息(由 config/user_fields.json 配置) + 各模块的 V/R/W/M 四勾选。
 * 每列支持模糊搜索/筛选；内联勾选即时保存；多选用户后批量填充某模块权限；列宽可拖拽调整。
 * 操作日志 / 数据备份 已剥离为「管理看板」同级标签页；附属信息字段配置置于本页顶部。
 */
let permOptions = { users: [], user_fields: [], modules: [], settings: {} };
let permAclMap = {};        // `${uid}|${moduleKey}` -> {v,r,w,m}
let permModuleCols = [];    // 扁平化的模块列 [{key,label,type}]
let permUsersCache = [];    // 用户列表
let permFilters = {};       // 列 id -> 过滤值（文本模糊 / 模块权限状态）

const PERM_FLAGS = [
  ["v", "perm_visibility", "可见", "#2563eb"],
  ["r", "perm_read", "读", "#0891b2"],
  ["w", "perm_write", "写", "#16a34a"],
  ["m", "perm_manage", "管理", "#d97706"],
];
const MOD_FILTERS = [
  ["any", "全部"], ["v", "可见"], ["r", "读"], ["w", "写"], ["m", "管理"], ["none", "无权限"],
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

function userFieldsForGrid() {
  return (permOptions.user_fields || []).filter(f => f.key !== "display_name");
}

async function renderPermissions() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可访问「权限管理」。</div>`;
    return;
  }
  permFilters = {};
  permLoadColWidths();
  $("#main").innerHTML = `
    <div class="card perm-card">
      <div class="perm-head">
        <div>
          <div class="section-title">权限管理 · 用户与模块权限矩阵</div>
          <p class="perm-sub">唯一性由工号决定，其余为附属信息（见 <code>config/user_fields.json</code>）。
            勾选即保存；每列表头支持模糊搜索/筛选；多选用户后可批量填充某模块的 V/R/W/M。</p>
        </div>
        <div class="perm-head-actions">
          <button class="btn btn-primary btn-sm" id="perm-add-user">+ 新增用户</button>
          <button class="btn btn-sm" id="perm-batch-edit" disabled>批量修改附属信息</button>
          <button class="btn btn-sm" id="perm-export">导出矩阵</button>
        </div>
      </div>

      <div id="perm-field-config" class="perm-embed perm-embed-top"></div>

      <div class="perm-batch-bar">
        <span class="perm-batch-label">批量授权</span>
        <span class="perm-batch-field"><label class="perm-batch-cap">模块</label><select id="perm-batch-module" class="perm-select"></select></span>
        <span class="perm-batch-flags">
          ${PERM_FLAGS.map(([s, , label, color]) =>
            `<label class="perm-flag-toggle" style="--flag-color:${color}"><input type="checkbox" id="perm-batch-${s}"><span>${label}</span></label>`).join("")}
        </span>
        <button class="btn btn-primary btn-sm" id="perm-batch-apply">应用到所选用户</button>
        <button class="btn btn-sm" id="perm-batch-revoke">清空所选用户该模块</button>
        <span class="perm-flex"></span>
        <span id="perm-row-count" class="muted"></span>
      </div>

      <div class="perm-grid-shell">
        <div class="perm-grid-left-wrap"><table id="perm-grid-left" class="perm-grid perm-grid-left"></table></div>
        <div class="perm-grid-right-wrap"><table id="perm-grid-right" class="perm-grid perm-grid-right"></table></div>
      </div>

      <div id="perm-roles" class="perm-embed"></div>
    </div>`;

  $("#perm-add-user").addEventListener("click", () => openUserModal(null));
  $("#perm-batch-edit").addEventListener("click", openBatchEditModal);
  $("#perm-batch-apply").addEventListener("click", () => permBatchApply(false));
  $("#perm-batch-revoke").addEventListener("click", () => permBatchApply(true));
  $("#perm-export").addEventListener("click", () => { window.location.href = "/api/module-acl/export"; });

  await loadPermData();
  $("#perm-batch-module").innerHTML = permModuleCols
    .map(m => `<option value="${m.key}">${esc(m.label)}${m.type === "section" ? "（板块）" : ""}</option>`).join("");
  renderPermGrid();
  refreshPermBatchBtn();
  renderRolesSection();
  renderFieldConfigInto($("#perm-field-config"));
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

/* ---------- 列定义 ---------- */
function permColumns() {
  const fields = userFieldsForGrid();
  const cols = [
    { id: "check", kind: "check", label: "" },
    { id: "username", kind: "text", label: "工号" },
    { id: "display_name", kind: "text", label: "姓名" },
  ];
  for (const f of fields) cols.push({ id: `f_${f.key}`, kind: "field", field: f, label: f.label });
  cols.push({ id: "role", kind: "role", label: "角色" });
  cols.push({ id: "actions", kind: "actions", label: "操作" });
  for (const m of permModuleCols) cols.push({ id: `m_${m.key}`, kind: "module", module: m, label: m.label });
  return cols;
}

function cellValue(u, col) {
  if (col.kind === "text") return u[col.id] ?? "";
  if (col.kind === "field") return u[col.field.key] ?? "";
  if (col.kind === "role") return u.role || "";
  return "";
}

function rowPassesFilter(u, cols) {
  for (const col of cols) {
    const f = permFilters[col.id];
    if (!f) continue;
    if (col.kind === "text" || col.kind === "field") {
      if (f && !String(cellValue(u, col)).toLowerCase().includes(String(f).toLowerCase())) return false;
    } else if (col.kind === "role") {
      if (f && u.role !== f) return false;
    } else if (col.kind === "module") {
      const a = aclOf(u.id, col.module.key);
      const match = {
        v: a.v, r: a.r, w: a.w, m: a.m,
        none: (a.v === 0 && a.r === 0 && a.w === 0 && a.m === 0),
        any: (a.v || a.r || a.w || a.m),
      };
      if (!match[f]) return false;
    }
  }
  return true;
}

/* ---------- 渲染（左表冻结：勾选/工号/姓名；右表横向滚动） ---------- */
const PERM_FROZEN_COUNT = 3;
const PERM_COL_WIDTH_KEY = "perm_col_widths_v1";
let permColWidths = {};
let _permMeasureEl;

function permLoadColWidths() {
  try {
    const raw = localStorage.getItem(PERM_COL_WIDTH_KEY);
    if (raw) permColWidths = JSON.parse(raw);
  } catch (_) { permColWidths = {}; }
}

function permSaveColWidths() {
  try { localStorage.setItem(PERM_COL_WIDTH_KEY, JSON.stringify(permColWidths)); } catch (_) {}
}

function permMeasureText(text, mono) {
  if (!_permMeasureEl) {
    _permMeasureEl = document.createElement("span");
    _permMeasureEl.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font-size:12px;padding:0;";
    document.body.appendChild(_permMeasureEl);
  }
  _permMeasureEl.className = mono ? "mono" : "";
  _permMeasureEl.textContent = text;
  return _permMeasureEl.offsetWidth;
}

function permDefaultColWidth(col) {
  const pad = 8;
  if (col.kind === "check") return 34;
  if (col.id === "username") return permMeasureText("0123456789", true) + pad;
  if (col.id === "display_name") return permMeasureText("一二三四", false) + pad;
  if (col.kind === "actions") return 96;
  if (col.kind === "role") return 72;
  if (col.kind === "field") return Math.max(56, permMeasureText(col.label || "字段", false) + pad + 12);
  if (col.kind === "module") return Math.max(64, permMeasureText(col.label || "模块", false) + pad);
  return 72;
}

function permColWidth(col) {
  const w = permColWidths[col.id];
  return (w != null && w > 0) ? w : permDefaultColWidth(col);
}

function permBuildColgroup(cols) {
  return `<colgroup>${cols.map(c =>
    `<col data-col-id="${c.id}" style="width:${permColWidth(c)}px">`).join("")}</colgroup>`;
}

function permUpdateLeftLayout(frozen) {
  const total = frozen.reduce((s, c) => s + permColWidth(c), 0);
  const left = $("#perm-grid-left");
  const wrap = document.querySelector(".perm-grid-left-wrap");
  if (left) {
    left.style.width = total + "px";
    left.style.minWidth = total + "px";
    left.style.maxWidth = total + "px";
  }
  if (wrap) {
    wrap.style.width = total + "px";
    wrap.style.maxWidth = total + "px";
    wrap.style.flex = `0 0 ${total}px`;
  }
}

function applyPermColWidths(cols) {
  const { frozen, scroll } = permSplitCols(cols);
  permUpdateLeftLayout(frozen);
  for (const [table, partCols] of [[$("#perm-grid-left"), frozen], [$("#perm-grid-right"), scroll]]) {
    if (!table) continue;
    table.querySelectorAll("colgroup col").forEach((colEl, i) => {
      if (partCols[i]) colEl.style.width = permColWidth(partCols[i]) + "px";
    });
    const total = partCols.reduce((s, c) => s + permColWidth(c), 0);
    if (table.id === "perm-grid-right") {
      table.style.width = Math.max(total, table.parentElement?.clientWidth || 0) + "px";
    }
  }
}

function bindPermColResize(cols) {
  const { frozen, scroll } = permSplitCols(cols);
  [[$("#perm-grid-left"), frozen], [$("#perm-grid-right"), scroll]].forEach(([table, partCols]) => {
    if (!table) return;
    table.querySelectorAll("thead tr:first-child th").forEach((th, idx) => {
      const col = partCols[idx];
      if (!col) return;
      let handle = th.querySelector(".th-resize");
      if (!handle) {
        handle = document.createElement("span");
        handle.className = "th-resize";
        handle.title = "拖动调整列宽";
        th.appendChild(handle);
      }
      handle.onclick = e => e.stopPropagation();
      handle.onmousedown = e => {
        e.preventDefault();
        e.stopPropagation();
        const startX = e.pageX, startW = permColWidth(col);
        const onMove = ev => {
          permColWidths[col.id] = Math.max(32, startW + ev.pageX - startX);
          applyPermColWidths(cols);
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          document.body.style.cursor = "";
          permSaveColWidths();
          requestAnimationFrame(() => syncPermGridLayout());
        };
        document.body.style.cursor = "col-resize";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      };
    });
  });
}

function permSplitCols(cols) {
  return { frozen: cols.slice(0, PERM_FROZEN_COUNT), scroll: cols.slice(PERM_FROZEN_COUNT) };
}

function permLabelRow(cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<th class="col-check perm-col-check"><input type="checkbox" id="perm-check-all" title="全选"></th>`;
    if (c.kind === "actions") return `<th class="perm-actions-col">操作</th>`;
    if (c.id === "username") return `<th class="col-username mono" title="${esc(c.label)}">${esc(c.label)}</th>`;
    if (c.id === "display_name") return `<th class="col-name" title="${esc(c.label)}">${esc(c.label)}</th>`;
    const modCls = c.kind === "module" ? ` col-module perm-mod-head${c.module.type === "section" ? " is-section" : ""}` : "";
    const fieldCls = c.kind === "field" ? " col-field" : "";
    const roleCls = c.kind === "role" ? " col-role-h" : "";
    return `<th class="${modCls}${fieldCls}${roleCls}" title="${esc(c.label)}">${esc(c.label)}</th>`;
  }).join("");
}

function permFilterRow(cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<th class="col-check perm-col-check"></th>`;
    if (c.kind === "actions") return `<th class="perm-actions-col"></th>`;
    if (c.kind === "role") {
      const ro = (permOptions.roles || []).map(r =>
        `<option value="${esc(r.key)}">${esc(r.label)}</option>`).join("");
      return `<th class="col-role-h"><select class="perm-col-filter perm-role-filter" data-col="${c.id}">
        <option value="">全部</option>${ro}</select></th>`;
    }
    if (c.kind === "module") {
      const opts = MOD_FILTERS.map(([v, label]) =>
        `<option value="${v}">${label}</option>`).join("");
      return `<th class="col-module perm-mod-head"><select class="perm-col-filter perm-mod-filter" data-col="${c.id}">${opts}</select></th>`;
    }
    const fieldCls = c.kind === "field" ? " col-field" : "";
    const sz = (c.id === "username" || c.id === "display_name") ? ' size="3"' : "";
    return `<th class="${fieldCls}"><input type="text" class="perm-col-filter" data-col="${c.id}" placeholder="筛选"${sz} value="${esc(permFilters[c.id] || "")}"></th>`;
  }).join("");
}

function permRowCells(u, cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<td class="col-check perm-col-check"><input type="checkbox" class="perm-row-check" value="${u.id}"></td>`;
    if (c.kind === "actions") return `<td class="perm-actions-col"><div class="perm-actions">
      <button class="btn btn-sm" data-uedit="${u.id}">编辑</button>
      ${u.id !== state.me.id ? `<button class="btn btn-sm btn-danger" data-udel="${u.id}">删除</button>` : ""}</div></td>`;
    if (c.kind === "role") {
      const rdef = (permOptions.roles || []).find(r => r.key === u.role);
      const label = rdef ? rdef.label : (ROLE_NAMES[u.role] || u.role || "—");
      const tone = (rdef && rdef.bypass) ? "blue" : "gray";
      return `<td class="col-role"><span class="badge badge-${tone}">${esc(label)}</span></td>`;
    }
    if (c.kind === "module") {
      const a = aclOf(u.id, c.module.key);
      return `<td class="col-module perm-mod-cell">${PERM_FLAGS.map(([s, , label, color]) =>
        `<label class="perm-flag" title="${label}"><input type="checkbox" class="perm-flag-cb"
          data-uid="${u.id}" data-mk="${c.module.key}" data-flag="${s}" ${a[s] ? "checked" : ""}
          style="--flag-color:${color}"></label>`).join("")}</td>`;
    }
    const val = cellValue(u, c);
    const inner = val === "" ? `<span class="perm-dash">—</span>` : esc(val);
    if (c.id === "username") return `<td class="col-username mono" title="${val === "" ? "" : esc(val)}">${inner}</td>`;
    if (c.id === "display_name") return `<td class="col-name" title="${val === "" ? "" : esc(val)}">${inner}</td>`;
    const cls = c.kind === "field" ? "perm-info-cell col-field" : "";
    return `<td class="${cls}" title="${val === "" ? "" : esc(val)}">${inner}</td>`;
  }).join("");
}

function permBuildThead(cols) {
  return `<thead><tr>${permLabelRow(cols)}</tr><tr class="perm-filter-row">${permFilterRow(cols)}</tr></thead>`;
}

function bindPermColFilters(cols) {
  document.querySelectorAll("#perm-grid-left .perm-col-filter, #perm-grid-right .perm-col-filter").forEach(el => {
    const col = el.dataset.col;
    const handler = () => { permFilters[col] = el.value; renderPermGridBody(cols); };
    el.addEventListener("input", handler);
    el.addEventListener("change", handler);
  });
}

function syncPermGridLayout() {
  const leftRows = $("#perm-grid-left")?.tBodies[0]?.rows;
  const rightRows = $("#perm-grid-right")?.tBodies[0]?.rows;
  if (!leftRows || !rightRows) return;
  const n = Math.min(leftRows.length, rightRows.length);
  for (let i = 0; i < n; i++) {
    leftRows[i].style.height = rightRows[i].style.height = "";
    const h = Math.max(leftRows[i].offsetHeight, rightRows[i].offsetHeight);
    if (h) leftRows[i].style.height = rightRows[i].style.height = h + "px";
  }
}

function renderPermGrid() {
  const cols = permColumns();
  const { frozen, scroll } = permSplitCols(cols);
  const left = $("#perm-grid-left");
  left.innerHTML = permBuildColgroup(frozen) + permBuildThead(frozen) + "<tbody></tbody>";
  left.style.tableLayout = "fixed";
  const right = $("#perm-grid-right");
  right.innerHTML = permBuildColgroup(scroll) + permBuildThead(scroll) + "<tbody></tbody>";
  right.style.tableLayout = "fixed";
  applyPermColWidths(cols);
  bindPermColFilters(cols);
  bindPermColResize(cols);
  const checkAll = $("#perm-check-all");
  if (checkAll) checkAll.addEventListener("change", e => {
    document.querySelectorAll(".perm-row-check").forEach(cb => cb.checked = e.target.checked);
    refreshPermBatchBtn();
  });
  renderPermGridBody(cols);
}

function renderPermGridBody(cols) {
  const { frozen, scroll } = permSplitCols(cols);
  const users = permUsersCache.filter(u => rowPassesFilter(u, cols));
  const leftTb = $("#perm-grid-left tbody");
  const rightTb = $("#perm-grid-right tbody");
  if (!leftTb || !rightTb) return;
  if (!users.length) {
    leftTb.innerHTML = `<tr><td colspan="${frozen.length}" class="empty" style="padding:24px">没有符合筛选条件的用户</td></tr>`;
    rightTb.innerHTML = `<tr><td colspan="${scroll.length}"></td></tr>`;
    $("#perm-row-count") && ($("#perm-row-count").textContent = "0 / " + permUsersCache.length + " 人");
    return;
  }
  leftTb.innerHTML = users.map(u => `<tr>${permRowCells(u, frozen)}</tr>`).join("");
  rightTb.innerHTML = users.map(u => `<tr>${permRowCells(u, scroll)}</tr>`).join("");
  $("#perm-row-count") && ($("#perm-row-count").textContent = `${users.length} / ${permUsersCache.length} 人`);

  leftTb.querySelectorAll(".perm-row-check").forEach(cb => cb.addEventListener("change", refreshPermBatchBtn));
  rightTb.querySelectorAll(".perm-flag-cb").forEach(cb =>
    cb.addEventListener("change", () => onPermFlagToggle(+cb.dataset.uid, cb.dataset.mk, cb.dataset.flag, cb.checked)));
  rightTb.querySelectorAll("[data-uedit]").forEach(b =>
    b.addEventListener("click", () => openUserModal(permUsersCache.find(u => u.id === +b.dataset.uedit))));
  rightTb.querySelectorAll("[data-udel]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm("确认删除该用户？其模块权限将一并清除。")) return;
      try {
        await api(`/api/users/${b.dataset.udel}`, { method: "DELETE" });
        toast("用户已删除");
        await loadPermData();
        renderPermGrid();
        refreshPermBatchBtn();
      } catch (e) { toast(e.message, true); }
    }));
  const checkAll = $("#perm-check-all");
  if (checkAll) checkAll.checked = false;
  requestAnimationFrame(() => syncPermGridLayout());
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
    } catch (e) { toast(e.message, true); await loadPermData(); renderPermGrid(); }
    return;
  }
  try {
    await api("/api/module-acl", { method: "PUT", json: body });
  } catch (e) {
    toast(e.message, true);
    await loadPermData();
    renderPermGrid();
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
    renderPermGrid();
    refreshPermBatchBtn();
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
  const roles = permOptions.roles || [];
  const roleOptions = roles.map(r =>
    `<option value="${esc(r.key)}" ${user?.role === r.key ? "selected" : ""}>${esc(r.label)}${r.bypass ? "（全权）" : ""}</option>`).join("");
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
    </div>
    <label class="perm-flag-toggle" style="margin-top:8px"><input type="checkbox" id="uf-apply-role" ${isNew ? "checked" : ""}>
      <span>${isNew ? "创建后应用该角色权限模板" : "重新应用该角色权限模板（覆盖此用户当前模块权限）"}</span></label>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="uf-save">保存</button>`);
  $("#uf-save").addEventListener("click", async () => {
    const payload = {
      username: $("#uf-username").value.trim(),
      password: $("#uf-password").value,
      role: $("#uf-role").value,
      apply_role: $("#uf-apply-role").checked,
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
      renderPermGrid();
      renderRolesSection();
      refreshPermBatchBtn();
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
      renderPermGrid();
      refreshPermBatchBtn();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------- 角色管理（角色=权限模板，持久化到 config/roles.json） ---------- */

function roleFlagMatrix(role) {
  const perms = role.perms || {};
  return permModuleCols.map(m => {
    const p = perms[m.key] || {v:0,r:0,w:0,m:0};
    const flags = PERM_FLAGS.map(([s, , , color]) =>
      `<span class="role-flag${p[s] ? " on" : ""}" style="--flag-color:${color}">${p[s] ? "✓" : "·"}</span>`).join("");
    return `<tr><td class="role-mod-name${m.type === "section" ? " is-section" : ""}">${esc(m.label)}</td>
      <td class="role-flag-cell">${flags}</td></tr>`;
  }).join("");
}

function renderRolesSection() {
  const box = $("#perm-roles");
  if (!box) return;
  const roles = permOptions.roles || [];
  const cards = roles.map(r => `
    <div class="role-card${r.bypass ? " is-bypass" : ""}" data-role="${esc(r.key)}">
      <div class="role-card-head">
        <div class="role-card-title">
          <span class="role-name">${esc(r.label)}</span>
          ${r.bypass ? `<span class="badge badge-blue">全权(绕过)</span>` : ""}
          ${r.builtin ? `<span class="badge badge-gray">内置</span>` : ""}
          <span class="role-key mono">${esc(r.key)}</span>
        </div>
        <div class="role-card-actions">
          <button class="btn btn-sm" data-role-edit="${esc(r.key)}">编辑</button>
          ${r.builtin ? "" : `<button class="btn btn-sm btn-danger" data-role-del="${esc(r.key)}">删除</button>`}
        </div>
      </div>
      ${r.bypass ? `<p class="role-bypass-note">该角色绕过所有模块权限，无需逐项配置。</p>`
        : `<table class="role-matrix"><tbody>${roleFlagMatrix(r)}</tbody></table>`}
    </div>`).join("");
  box.innerHTML = `
    <div class="perm-embed-title">角色管理 <span class="muted" style="font-weight:400;font-size:12px">（角色=权限模板，应用角色时写入对应用户的模块权限）</span></div>
    <div class="perm-embed-sub">默认角色配置承载于 <code>config/roles.json</code>；新增/编辑角色会写回该文件。在用户新增/编辑弹窗中选择角色并勾选"应用角色权限"即可把模板写入该用户。</div>
    <div class="perm-toolbar" style="margin-bottom:10px"><button class="btn btn-primary btn-sm" id="role-add">+ 新增角色</button></div>
    <div class="role-grid">${cards}</div>`;
  $("#role-add").addEventListener("click", () => openRoleModal(null));
  box.querySelectorAll("[data-role-edit]").forEach(b =>
    b.addEventListener("click", () => openRoleModal(roles.find(r => r.key === b.dataset.roleEdit))));
  box.querySelectorAll("[data-role-del]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm(`确认删除角色「${b.dataset.roleDel}」？已分配该角色的用户不会被删除，但其模块权限不会自动变更。`)) return;
      try {
        await api(`/api/roles/${encodeURIComponent(b.dataset.roleDel)}`, { method: "DELETE" });
        toast("角色已删除");
        await loadPermData();
        renderPermGrid();
        renderRolesSection();
      } catch (e) { toast(e.message, true); }
    }));
}

function openRoleModal(role) {
  const isNew = !role;
  const modules = permModuleCols;
  const perms = isNew ? {} : (role.perms || {});
  const rows = modules.map(m => {
    const p = perms[m.key] || {v:0,r:0,w:0,m:0};
    const flags = PERM_FLAGS.map(([s, , label, color]) =>
      `<label class="perm-flag-toggle" style="--flag-color:${color}"><input type="checkbox" class="rf-cb" data-mk="${m.key}" data-flag="${s}" ${p[s] ? "checked" : ""}><span>${label}</span></label>`).join("");
    return `<tr><td class="role-mod-name${m.type === "section" ? " is-section" : ""}">${esc(m.label)}</td>
      <td class="role-flag-cell">${flags}</td></tr>`;
  }).join("");
  openModal(isNew ? "新增角色" : `编辑角色 - ${esc(role.label)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>角色名称 *</label>
        <input id="rf-label" value="${role ? esc(role.label) : ""}"></div>
      <div class="form-item"><label>角色key ${isNew ? "（唯一，英文/数字/下划线）" : "（不可修改）"}</label>
        <input id="rf-key" value="${role ? esc(role.key) : ""}" ${isNew ? "" : "disabled"}></div>
    </div>
    <label class="perm-flag-toggle" style="margin:6px 0 10px"><input type="checkbox" id="rf-bypass" ${role?.bypass ? "checked" : ""}>
      <span>全权角色（绕过所有模块权限，如系统管理员）</span></label>
    <div class="role-modal-matrix"><table class="role-matrix"><tbody>${rows}</tbody></table></div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="rf-save">保存</button>`);

  const toggleMatrix = () => {
    const dis = $("#rf-bypass").checked;
    document.querySelectorAll(".rf-cb").forEach(cb => cb.disabled = dis);
    const m = document.querySelector(".role-modal-matrix");
    if (m) m.style.opacity = dis ? ".5" : "1";
  };
  $("#rf-bypass").addEventListener("change", toggleMatrix);
  toggleMatrix();

  $("#rf-save").addEventListener("click", async () => {
    const label = $("#rf-label").value.trim();
    const bypass = $("#rf-bypass").checked;
    const permsBody = {};
    document.querySelectorAll(".rf-cb").forEach(cb => {
      if (!cb.checked) return;
      const mk = cb.dataset.mk, f = cb.dataset.flag;
      (permsBody[mk] = permsBody[mk] || {v:0,r:0,w:0,m:0})[f] = 1;
    });
    const body = { label, perms: permsBody, bypass };
    try {
      if (isNew) {
        body.key = $("#rf-key").value.trim();
        await api("/api/roles", { method: "POST", json: body });
      } else {
        await api(`/api/roles/${encodeURIComponent(role.key)}`, { method: "PUT", json: body });
      }
      toast("角色已保存");
      closeModal();
      await loadPermData();
      renderPermGrid();
      renderRolesSection();
    } catch (e) { toast(e.message, true); }
  });
}
