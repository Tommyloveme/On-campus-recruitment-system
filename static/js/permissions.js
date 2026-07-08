"use strict";

/* 权限管理：单一 Excel 式 用户×模块 权限矩阵页，仅系统管理员。
 * 行=用户(工号唯一)；列=附属信息(由 config/user_fields.json 配置) + 各模块的 V/R/W/M 四勾选。
 * 每列支持模糊搜索/筛选；内联勾选即时保存；多选用户后批量填充某模块权限；列宽可拖拽调整（默认按表头/单元格/筛选项最长内容计算）。
 * 操作日志 / 数据备份 已剥离为「管理看板」同级标签页；附属信息字段配置置于本页顶部。
 */
let permOptions = { users: [], user_fields: [], modules: [], settings: {} };
let permAclMap = {};        // `${uid}|${moduleKey}` -> {v,r,w,m,feats}
let permModuleCols = [];    // 扁平化的模块列 [{key,label,type}]
let permUsersCache = [];    // 用户列表
let permFilters = {};       // 列 id -> 过滤值（文本模糊 / 模块权限状态）
let permFeatureRegistry = {}; // moduleKey -> [{key,label,kind}] 可配置的细粒度特性

const PERM_FLAGS = [
  ["v", "perm_visibility", "可见", "#2563eb"],
  ["r", "perm_read", "读", "#0891b2"],
  ["w", "perm_write", "写", "#16a34a"],
  ["m", "perm_manage", "管理", "#d97706"],
];
const MOD_FILTERS = [
  ["any", "全部"], ["v", "可见"], ["r", "读"], ["w", "写"], ["m", "管理"], ["none", "无权限"],
];

/* 细粒度权限入口按钮的图标（内联 SVG 齿轮，替代 emoji） */
const PERM_GEAR_SVG = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.8v1.7M8 12.5v1.7M1.8 8h1.7M12.5 8h1.7M3.6 3.6l1.2 1.2M11.2 11.2l1.2 1.2M12.4 3.6l-1.2 1.2M4.8 11.2l-1.2 1.2"/></svg>`;

function aclKey(uid, mk) { return `${uid}|${mk}`; }
function aclOf(uid, mk) { return permAclMap[aclKey(uid, mk)] || {v:0,r:0,w:0,m:0,feats:{}}; }

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
  roleFilters = {};
  permLoadColWidths();
  $("#main").innerHTML = `
    <div class="perm-page">
      <div class="card perm-pagehead">
        <div class="perm-pagehead-text">
          <div class="perm-pagetitle">权限管理</div>
          <div class="perm-pagesub">统一管理用户账号、角色模板与各业务模块的访问权限，支持页面内子标签 / 按钮级细粒度管控</div>
        </div>
        <div class="iv-subnav perm-pagetabs">
          <button class="btn btn-sm iv-view-btn active" data-perm-view="main">权限矩阵</button>
          <button class="btn btn-sm iv-view-btn" data-perm-view="logs">操作日志</button>
        </div>
      </div>
      <div id="perm-view-logs" class="hidden"></div>
      <div id="perm-view-main">

      <section class="card perm-section">
        <div class="perm-section-head">
          <div class="perm-section-title">用户 × 模块权限矩阵
            <span class="perm-section-sub">勾选即时保存；点击齿轮按钮配置页面内细粒度权限</span></div>
          <div class="perm-head-actions">
            <button class="btn btn-primary btn-sm" id="perm-add-user">+ 新增用户</button>
            <button class="btn btn-sm" id="perm-batch-edit" disabled>批量修改附属信息</button>
            <button class="btn btn-sm" id="perm-export">导出矩阵</button>
          </div>
        </div>
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
      </section>

      <section class="card perm-section" id="perm-roles">
        <div class="perm-section-head">
          <div class="perm-section-title">角色管理
            <span class="perm-section-sub">角色 = 权限模板，应用后写入用户模块权限</span></div>
          <div class="perm-head-actions">
            <button class="btn btn-primary btn-sm" id="role-add">+ 新增角色</button>
          </div>
        </div>
        <div class="perm-batch-bar">
          <span class="perm-batch-label">批量授权</span>
          <span class="perm-batch-field"><label class="perm-batch-cap">模块</label><select id="role-batch-module" class="perm-select"></select></span>
          <span class="perm-batch-flags">
            ${PERM_FLAGS.map(([s, , label, color]) =>
              `<label class="perm-flag-toggle" style="--flag-color:${color}"><input type="checkbox" id="role-batch-${s}"><span>${label}</span></label>`).join("")}
          </span>
          <button class="btn btn-primary btn-sm" id="role-batch-apply">应用到所选角色</button>
          <button class="btn btn-sm" id="role-batch-revoke">清空所选角色该模块</button>
          <span class="perm-flex"></span>
          <span id="role-row-count" class="muted"></span>
        </div>
        <div class="perm-grid-shell">
          <div class="perm-grid-left-wrap"><table id="role-grid-left" class="perm-grid perm-grid-left"></table></div>
          <div class="perm-grid-right-wrap"><table id="role-grid-right" class="perm-grid perm-grid-right"></table></div>
        </div>
      </section>

      <section class="card perm-section">
        <div class="perm-section-head">
          <div class="perm-section-title">附属信息字段配置
            <span class="perm-section-sub">用户表格中显示的附属信息列，由此配置驱动</span></div>
        </div>
        <div id="perm-field-config"></div>
      </section>
      </div>
    </div>`;

  let permLogsInit = false;
  document.querySelectorAll("[data-perm-view]").forEach(btn =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-perm-view]").forEach(b => b.classList.toggle("active", b === btn));
      const logs = btn.dataset.permView === "logs";
      $("#perm-view-main").classList.toggle("hidden", logs);
      $("#perm-view-logs").classList.toggle("hidden", !logs);
      if (logs && !permLogsInit) { permLogsInit = true; renderLogPanel($("#perm-view-logs"), { module: "permissions" }); }
    }));

  $("#perm-add-user").addEventListener("click", () => openUserModal(null));
  $("#perm-batch-edit").addEventListener("click", openBatchEditModal);
  $("#perm-batch-apply").addEventListener("click", () => permBatchApply(false));
  $("#perm-batch-revoke").addEventListener("click", () => permBatchApply(true));
  $("#perm-export").addEventListener("click", () => { window.location.href = "/api/module-acl/export"; });
  $("#role-add").addEventListener("click", () => openRoleModal(null));
  $("#role-batch-apply").addEventListener("click", () => roleBatchApply(false));
  $("#role-batch-revoke").addEventListener("click", () => roleBatchApply(true));

  await loadPermData();
  $("#perm-batch-module").innerHTML = permModuleCols
    .map(m => `<option value="${m.key}">${esc(m.label)}${m.type === "section" ? "（板块）" : ""}</option>`).join("");
  $("#role-batch-module").innerHTML = $("#perm-batch-module").innerHTML;
  roleLoadColWidths();
  renderPermGrid();
  refreshPermBatchBtn();
  renderRoleGrid();
  renderFieldConfigInto($("#perm-field-config"));
}

async function loadPermData() {
  const [opts, acls, feats] = await Promise.all([
    api("/api/permissions/options"),
    api("/api/module-acl"),
    api("/api/permissions/features"),
  ]);
  permOptions = opts;
  permUsersCache = opts.users || [];
  permModuleCols = flattenModuleCols(opts.modules || []);
  permFeatureRegistry = (feats && feats.features) || {};
  permAclMap = {};
  for (const r of (acls || [])) {
    permAclMap[aclKey(r.subject_id, r.module_key)] = {
      v: +r.perm_visibility, r: +r.perm_read, w: +r.perm_write, m: +r.perm_manage,
      feats: r.features || {},
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
const PERM_COL_WIDTH_KEY = "perm_col_widths_v2";
let permColWidths = {};
let permComputedDefaults = {};
let _permMeasureEl;
let _permBadgeEl;
let _permActionsEl;
let _permModCellEl;

function permLoadColWidths() {
  try {
    const raw = localStorage.getItem(PERM_COL_WIDTH_KEY);
    if (raw) permColWidths = JSON.parse(raw);
  } catch (_) { permColWidths = {}; }
}

function permSaveColWidths() {
  try { localStorage.setItem(PERM_COL_WIDTH_KEY, JSON.stringify(permColWidths)); } catch (_) {}
}

function permMeasureText(text, mono, fontSize, bold) {
  if (!_permMeasureEl) {
    _permMeasureEl = document.createElement("span");
    _permMeasureEl.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;padding:0;";
    document.body.appendChild(_permMeasureEl);
  }
  _permMeasureEl.className = mono ? "mono" : "";
  _permMeasureEl.style.fontSize = (fontSize || 12) + "px";
  _permMeasureEl.style.fontWeight = bold ? "600" : "400";
  _permMeasureEl.textContent = text || "";
  return _permMeasureEl.offsetWidth;
}

function permMeasureHeader(text) {
  // 表头为粗体，另预留拖拽手柄 + 排序空间
  return permMeasureText(text, false, 12, true) + 10;
}

function permMeasureBadge(text) {
  if (!_permBadgeEl) {
    _permBadgeEl = document.createElement("span");
    _permBadgeEl.className = "badge badge-gray";
    _permBadgeEl.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font-size:11px;padding:1px 5px;";
    document.body.appendChild(_permBadgeEl);
  }
  _permBadgeEl.textContent = text || "";
  return _permBadgeEl.offsetWidth;
}

function permMeasureActions() {
  if (!_permActionsEl) {
    _permActionsEl = document.createElement("div");
    _permActionsEl.className = "perm-actions";
    _permActionsEl.style.cssText = "position:absolute;visibility:hidden;display:flex;gap:3px;";
    _permActionsEl.innerHTML = `<button class="btn btn-sm">编辑</button><button class="btn btn-sm btn-danger">删除</button>`;
    document.body.appendChild(_permActionsEl);
  }
  return _permActionsEl.offsetWidth;
}

function permMeasureModuleCell() {
  if (!_permModCellEl) {
    _permModCellEl = document.createElement("div");
    _permModCellEl.className = "perm-mod-cell";
    _permModCellEl.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;";
    // 四个权限勾选 + 细粒度齿轮按钮（有 features 的模块会渲染，宽度按最大情况预留）
    _permModCellEl.innerHTML = PERM_FLAGS.map(([, , , color]) =>
      `<label class="perm-flag" style="--flag-color:${color}"><input type="checkbox" style="width:13px;height:13px;margin:0"></label>`).join("")
      + `<button class="perm-feat-btn">${PERM_GEAR_SVG}</button>`;
    document.body.appendChild(_permModCellEl);
  }
  return _permModCellEl.offsetWidth;
}

function permRoleLabel(u) {
  const rdef = (permOptions.roles || []).find(r => r.key === u.role);
  return rdef ? rdef.label : (ROLE_NAMES[u.role] || u.role || "—");
}

function permFilterOptionTexts(col) {
  if (col.kind === "role") return ["全部", ...(permOptions.roles || []).map(r => r.label)];
  if (col.kind === "module") return MOD_FILTERS.map(([, label]) => label);
  return ["筛选"];
}

function permRecomputeDefaultColWidths(cols) {
  const cellPad = 24;
  const filterPad = 30;
  permComputedDefaults = {};

  for (const col of cols) {
    let maxW = 0;
    const header = col.label || "";

    if (col.kind === "check") {
      permComputedDefaults[col.id] = 34;
      continue;
    }

    if (col.id === "username") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureText("0123456789", true) + cellPad);
      for (const u of permUsersCache) {
        const v = String(u.username ?? "");
        if (v) maxW = Math.max(maxW, permMeasureText(v, true) + cellPad);
      }
      maxW = Math.max(maxW, permMeasureText("筛选", false, 10) + filterPad);
    } else if (col.id === "display_name") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureText("一二三四", false) + cellPad);
      for (const u of permUsersCache) {
        const v = String(u.display_name ?? "");
        if (v) maxW = Math.max(maxW, permMeasureText(v, false) + cellPad);
      }
      maxW = Math.max(maxW, permMeasureText("筛选", false, 10) + filterPad);
    } else if (col.kind === "field") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      for (const u of permUsersCache) {
        const v = String(u[col.field.key] ?? "");
        if (v) maxW = Math.max(maxW, permMeasureText(v, false) + cellPad);
      }
      maxW = Math.max(maxW, permMeasureText("筛选", false, 11) + filterPad);
    } else if (col.kind === "role") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      for (const u of permUsersCache) maxW = Math.max(maxW, permMeasureBadge(permRoleLabel(u)) + cellPad);
      for (const r of (permOptions.roles || [])) maxW = Math.max(maxW, permMeasureBadge(r.label) + cellPad);
      for (const t of permFilterOptionTexts(col)) maxW = Math.max(maxW, permMeasureText(t, false, 11) + filterPad);
    } else if (col.kind === "actions") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureActions() + cellPad);
    } else if (col.kind === "module") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureModuleCell() + cellPad);
      for (const t of permFilterOptionTexts(col)) maxW = Math.max(maxW, permMeasureText(t, false, 10) + filterPad);
    } else {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
    }

    permComputedDefaults[col.id] = Math.max(40, Math.ceil(maxW));
  }
}

function permDefaultColWidth(col) {
  if (permComputedDefaults[col.id] != null) return permComputedDefaults[col.id];
  const pad = 8;
  if (col.kind === "check") return 34;
  if (col.id === "username") return permMeasureText("0123456789", true) + pad;
  if (col.id === "display_name") return permMeasureText("一二三四", false) + pad;
  if (col.kind === "actions") return permMeasureActions() + pad;
  if (col.kind === "role") return 72;
  if (col.kind === "field") return Math.max(56, permMeasureText(col.label || "字段", false) + pad + 12);
  if (col.kind === "module") return Math.max(permMeasureModuleCell() + pad, permMeasureText(col.label || "模块", false) + pad);
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
      const feats = permFeatureRegistry[c.module.key];
      const hasCustom = feats && Object.values(a.feats || {}).some(v => v === 0);
      const gear = feats
        ? `<button class="perm-feat-btn${hasCustom ? " has-custom" : ""}" data-feat-uid="${u.id}"
             data-feat-mk="${c.module.key}" title="细粒度权限（子标签/按钮可见性）">${PERM_GEAR_SVG}</button>`
        : "";
      return `<td class="col-module perm-mod-cell">${PERM_FLAGS.map(([s, , label, color]) =>
        `<label class="perm-flag" title="${label}"><input type="checkbox" class="perm-flag-cb"
          data-uid="${u.id}" data-mk="${c.module.key}" data-flag="${s}" ${a[s] ? "checked" : ""}
          style="--flag-color:${color}"></label>`).join("")}${gear}</td>`;
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
  permRecomputeDefaultColWidths(cols);
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
  rightTb.querySelectorAll("[data-feat-uid]").forEach(b =>
    b.addEventListener("click", () => openFeatureModal(+b.dataset.featUid, b.dataset.featMk)));
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

/* ---------- 细粒度权限（子标签 / 按钮级） ---------- */

function openFeatureModal(uid, mk) {
  const feats = permFeatureRegistry[mk] || [];
  const u = permUsersCache.find(x => x.id === uid);
  const mod = permModuleCols.find(m => m.key === mk);
  const cur = aclOf(uid, mk);
  const isOn = k => !((cur.feats || {})[k] === 0);
  const kinds = [["tab", "子标签可见性"], ["button", "按钮可见性"]];
  const sections = kinds.map(([kind, title]) => {
    const items = feats.filter(f => f.kind === kind);
    if (!items.length) return "";
    return `
      <div class="feat-section">
        <div class="feat-section-title">${title}</div>
        <div class="feat-list">
          ${items.map(f => `
            <label class="feat-switch">
              <input type="checkbox" class="feat-cb" data-fk="${f.key}" ${isOn(f.key) ? "checked" : ""}>
              <span class="feat-slider"></span>
              <span class="feat-name">${esc(f.label)}</span>
            </label>`).join("")}
        </div>
      </div>`;
  }).join("");

  openModal(`细粒度权限 · ${esc(u?.display_name || "用户#" + uid)} × ${esc(mod?.label || mk)}`, `
    <p class="muted" style="font-size:12px;margin:0 0 12px">
      在模块读写权限之内进一步控制页面内部元素：关闭后该用户在此页面看不到对应子标签或按钮。默认全部开启。</p>
    ${sections}`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-sm" id="feat-reset">全部恢复默认</button>
     <button class="btn btn-primary" id="feat-save">保存</button>`);

  $("#feat-reset").addEventListener("click", () => {
    document.querySelectorAll(".feat-cb").forEach(cb => { cb.checked = true; });
  });
  $("#feat-save").addEventListener("click", async () => {
    const features = {};
    document.querySelectorAll(".feat-cb").forEach(cb => { features[cb.dataset.fk] = cb.checked ? 1 : 0; });
    try {
      await api("/api/module-acl", { method: "PUT", json: {
        subject_type: "user", subject_id: uid, module_key: mk,
        perm_visibility: cur.v, perm_read: cur.r, perm_write: cur.w, perm_manage: cur.m,
        features,
      } });
      toast("细粒度权限已保存");
      closeModal();
      await loadPermData();
      renderPermGrid();
    } catch (e) { toast(e.message, true); }
  });
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

function jobRolesCheckboxHtml(selected, roleKey) {
  const opts = permOptions.interview_position_options || [];
  const sel = new Set(selected || []);
  const show = roleKey === "interviewer";
  return `
    <div class="form-item form-item-full uf-interviewer-extra" id="uf-job-roles-wrap" style="display:${show ? "" : "none"}">
      <label>可面试岗位（多选，用于日程匹配）</label>
      ${opts.length ? `
      <div class="checkbox-group">
        ${opts.map(p => `
          <label class="checkbox-item">
            <input type="checkbox" class="uf-job-role" value="${esc(p)}" ${sel.has(p) ? "checked" : ""}> ${esc(p)}
          </label>`).join("")}
      </div>` : `<p class="muted" style="font-size:12px;margin:0">未配置岗位选项，请在系统配置 interview.position_options 中维护。</p>`}
    </div>`;
}

function bindUserJobRolesVisibility() {
  const roleEl = $("#uf-role");
  if (!roleEl) return;
  const sync = () => {
    const wrap = $("#uf-job-roles-wrap");
    if (wrap) wrap.style.display = roleEl.value === "interviewer" ? "" : "none";
  };
  roleEl.addEventListener("change", sync);
  sync();
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
    ${jobRolesCheckboxHtml(user?.job_roles, user?.role || "user")}
    <label class="perm-flag-toggle" style="margin-top:8px"><input type="checkbox" id="uf-apply-role" ${isNew ? "checked" : ""}>
      <span>${isNew ? "创建后应用该角色权限模板" : "重新应用该角色权限模板（覆盖此用户当前模块权限）"}</span></label>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="uf-save">保存</button>`);
  bindUserJobRolesVisibility();
  $("#uf-save").addEventListener("click", async () => {
    const role = $("#uf-role").value;
    const payload = {
      username: $("#uf-username").value.trim(),
      password: $("#uf-password").value,
      role,
      apply_role: $("#uf-apply-role").checked,
    };
    if (role === "interviewer") {
      payload.job_roles = [...document.querySelectorAll(".uf-job-role:checked")].map(cb => cb.value);
    } else {
      payload.job_roles = [];
    }
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
      renderRoleGrid();
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

/* ---------- 角色管理（与用户矩阵同构：Excel 式表格 + 内联勾选 + 批量授权） ---------- */

const ROLE_FROZEN_COUNT = 3;
const ROLE_COL_WIDTH_KEY = "role_col_widths_v2";
let roleFilters = {};
let roleColWidths = {};
let roleComputedDefaults = {};

function rolesCache() { return permOptions.roles || []; }

function roleColumns() {
  const cols = [
    { id: "rcheck", kind: "check", label: "" },
    { id: "r_label", kind: "text", label: "角色名称" },
    { id: "r_key", kind: "text", label: "角色key" },
    { id: "r_bypass", kind: "bool", label: "全权" },
    { id: "r_builtin", kind: "bool", label: "内置" },
    { id: "r_actions", kind: "actions", label: "操作" },
  ];
  for (const m of permModuleCols) cols.push({ id: `rm_${m.key}`, kind: "module", module: m, label: m.label });
  return cols;
}

function roleCellValue(role, col) {
  if (col.id === "r_label") return role.label || "";
  if (col.id === "r_key") return role.key || "";
  if (col.id === "r_bypass") return role.bypass ? "1" : "0";
  if (col.id === "r_builtin") return role.builtin ? "1" : "0";
  return "";
}

function rolePermOf(roleKey, mk) {
  const role = rolesCache().find(r => r.key === roleKey);
  const p = role?.perms?.[mk] || {};
  return {
    v: +(p.v || 0), r: +(p.r || 0), w: +(p.w || 0), m: +(p.m || 0),
    feats: p.features || {},
  };
}

function rowPassesRoleFilter(role, cols) {
  for (const col of cols) {
    const f = roleFilters[col.id];
    if (!f) continue;
    if (col.kind === "text") {
      if (!String(roleCellValue(role, col)).toLowerCase().includes(String(f).toLowerCase())) return false;
    } else if (col.kind === "bool") {
      if (roleCellValue(role, col) !== f) return false;
    } else if (col.kind === "module") {
      if (role.bypass) {
        if (f === "none") return false;
        if (f && f !== "any") return false;
        continue;
      }
      const a = rolePermOf(role.key, col.module.key);
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

function roleLoadColWidths() {
  try {
    const raw = localStorage.getItem(ROLE_COL_WIDTH_KEY);
    if (raw) roleColWidths = JSON.parse(raw);
  } catch (_) { roleColWidths = {}; }
}

function roleSaveColWidths() {
  try { localStorage.setItem(ROLE_COL_WIDTH_KEY, JSON.stringify(roleColWidths)); } catch (_) {}
}

function roleRecomputeDefaultColWidths(cols) {
  const cellPad = 24;
  const filterPad = 30;
  const roles = rolesCache();
  roleComputedDefaults = {};

  for (const col of cols) {
    let maxW = 0;
    const header = col.label || "";

    if (col.kind === "check") {
      roleComputedDefaults[col.id] = 34;
      continue;
    }

    if (col.id === "r_label") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureText("一二三四", false) + cellPad);
      for (const r of roles) maxW = Math.max(maxW, permMeasureText(r.label || "", false) + cellPad);
      maxW = Math.max(maxW, permMeasureText("筛选", false, 10) + filterPad);
    } else if (col.id === "r_key") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      for (const r of roles) maxW = Math.max(maxW, permMeasureText(r.key || "", true) + cellPad);
      maxW = Math.max(maxW, permMeasureText("筛选", false, 10) + filterPad);
    } else if (col.kind === "bool") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureBadge(col.id === "r_bypass" ? "全权" : "内置") + cellPad);
      maxW = Math.max(maxW, permMeasureText("普通", false, 11) + filterPad);
    } else if (col.kind === "actions") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureActions() + cellPad);
    } else if (col.kind === "module") {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
      maxW = Math.max(maxW, permMeasureModuleCell() + cellPad);
      for (const t of MOD_FILTERS.map(([, label]) => label)) maxW = Math.max(maxW, permMeasureText(t, false, 10) + filterPad);
    } else {
      maxW = Math.max(maxW, permMeasureHeader(header) + cellPad);
    }

    roleComputedDefaults[col.id] = Math.max(40, Math.ceil(maxW));
  }
}

function roleDefaultColWidth(col) {
  if (roleComputedDefaults[col.id] != null) return roleComputedDefaults[col.id];
  return permDefaultColWidth(col);
}

function roleColWidth(col) {
  const w = roleColWidths[col.id];
  return (w != null && w > 0) ? w : roleDefaultColWidth(col);
}

function roleSplitCols(cols) {
  return { frozen: cols.slice(0, ROLE_FROZEN_COUNT), scroll: cols.slice(ROLE_FROZEN_COUNT) };
}

function roleBuildColgroup(cols) {
  return `<colgroup>${cols.map(c =>
    `<col data-col-id="${c.id}" style="width:${roleColWidth(c)}px">`).join("")}</colgroup>`;
}

function roleUpdateLeftLayout(frozen) {
  const total = frozen.reduce((s, c) => s + roleColWidth(c), 0);
  const left = $("#role-grid-left");
  const wrap = left?.closest(".perm-grid-left-wrap");
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

function applyRoleColWidths(cols) {
  const { frozen, scroll } = roleSplitCols(cols);
  roleUpdateLeftLayout(frozen);
  for (const [table, partCols] of [[$("#role-grid-left"), frozen], [$("#role-grid-right"), scroll]]) {
    if (!table) continue;
    table.querySelectorAll("colgroup col").forEach((colEl, i) => {
      if (partCols[i]) colEl.style.width = roleColWidth(partCols[i]) + "px";
    });
    if (table.id === "role-grid-right") {
      const total = partCols.reduce((s, c) => s + roleColWidth(c), 0);
      table.style.width = Math.max(total, table.parentElement?.clientWidth || 0) + "px";
    }
  }
}

function bindRoleColResize(cols) {
  const { frozen, scroll } = roleSplitCols(cols);
  [[$("#role-grid-left"), frozen], [$("#role-grid-right"), scroll]].forEach(([table, partCols]) => {
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
        const startX = e.pageX, startW = roleColWidth(col);
        const onMove = ev => {
          roleColWidths[col.id] = Math.max(32, startW + ev.pageX - startX);
          applyRoleColWidths(cols);
        };
        const onUp = () => {
          document.removeEventListener("mousemove", onMove);
          document.removeEventListener("mouseup", onUp);
          document.body.style.cursor = "";
          roleSaveColWidths();
          requestAnimationFrame(() => syncRoleGridLayout());
        };
        document.body.style.cursor = "col-resize";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
      };
    });
  });
}

function roleLabelRow(cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<th class="col-check perm-col-check"><input type="checkbox" id="role-check-all" title="全选"></th>`;
    if (c.kind === "actions") return `<th class="perm-actions-col">操作</th>`;
    if (c.id === "r_key") return `<th class="col-username mono" title="${esc(c.label)}">${esc(c.label)}</th>`;
    if (c.id === "r_label") return `<th class="col-name" title="${esc(c.label)}">${esc(c.label)}</th>`;
    const modCls = c.kind === "module" ? ` col-module perm-mod-head${c.module.type === "section" ? " is-section" : ""}` : "";
    return `<th class="${modCls}" title="${esc(c.label)}">${esc(c.label)}</th>`;
  }).join("");
}

function roleFilterRow(cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<th class="col-check perm-col-check"></th>`;
    if (c.kind === "actions") return `<th class="perm-actions-col"></th>`;
    if (c.kind === "bool") {
      const opts = c.id === "r_bypass"
        ? `<option value="">全部</option><option value="1">全权</option><option value="0">普通</option>`
        : `<option value="">全部</option><option value="1">内置</option><option value="0">自定义</option>`;
      return `<th><select class="perm-col-filter role-col-filter" data-col="${c.id}">${opts}</select></th>`;
    }
    if (c.kind === "module") {
      const opts = MOD_FILTERS.map(([v, label]) => `<option value="${v}">${label}</option>`).join("");
      return `<th class="col-module perm-mod-head"><select class="perm-col-filter role-col-filter perm-mod-filter" data-col="${c.id}">${opts}</select></th>`;
    }
    const sz = (c.id === "r_label" || c.id === "r_key") ? ' size="3"' : "";
    return `<th><input type="text" class="perm-col-filter role-col-filter" data-col="${c.id}" placeholder="筛选"${sz} value="${esc(roleFilters[c.id] || "")}"></th>`;
  }).join("");
}

function roleRowCells(role, cols) {
  return cols.map(c => {
    if (c.kind === "check") return `<td class="col-check perm-col-check"><input type="checkbox" class="role-row-check" value="${esc(role.key)}"></td>`;
    if (c.kind === "actions") return `<td class="perm-actions-col"><div class="perm-actions">
      <button class="btn btn-sm" data-role-edit="${esc(role.key)}">编辑</button>
      ${role.builtin ? "" : `<button class="btn btn-sm btn-danger" data-role-del="${esc(role.key)}">删除</button>`}
    </div></td>`;
    if (c.id === "r_bypass") return `<td><span class="badge badge-${role.bypass ? "blue" : "gray"}">${role.bypass ? "全权" : "—"}</span></td>`;
    if (c.id === "r_builtin") return `<td><span class="badge badge-${role.builtin ? "gray" : "blue"}">${role.builtin ? "内置" : "自定义"}</span></td>`;
    if (c.kind === "module") {
      if (role.bypass) return `<td class="col-module perm-mod-cell"><span class="perm-dash" title="全权角色">—</span></td>`;
      const a = rolePermOf(role.key, c.module.key);
      const feats = permFeatureRegistry[c.module.key];
      const hasCustom = feats && Object.values(a.feats || {}).some(v => v === 0);
      const gear = feats
        ? `<button class="perm-feat-btn${hasCustom ? " has-custom" : ""}" data-role-feat="${esc(role.key)}"
             data-feat-mk="${c.module.key}" title="细粒度权限（子标签/按钮可见性）">${PERM_GEAR_SVG}</button>`
        : "";
      return `<td class="col-module perm-mod-cell">${PERM_FLAGS.map(([s, , label, color]) =>
        `<label class="perm-flag" title="${label}"><input type="checkbox" class="role-flag-cb"
          data-rkey="${esc(role.key)}" data-mk="${c.module.key}" data-flag="${s}" ${a[s] ? "checked" : ""}
          style="--flag-color:${color}"></label>`).join("")}${gear}</td>`;
    }
    const val = roleCellValue(role, c);
    const inner = val === "" ? `<span class="perm-dash">—</span>` : esc(val);
    if (c.id === "r_key") return `<td class="col-username mono" title="${esc(val)}">${inner}</td>`;
    if (c.id === "r_label") return `<td class="col-name" title="${esc(val)}">${inner}</td>`;
    return `<td title="${esc(val)}">${inner}</td>`;
  }).join("");
}

function roleBuildThead(cols) {
  return `<thead><tr>${roleLabelRow(cols)}</tr><tr class="perm-filter-row">${roleFilterRow(cols)}</tr></thead>`;
}

function bindRoleColFilters(cols) {
  document.querySelectorAll("#role-grid-left .role-col-filter, #role-grid-right .role-col-filter").forEach(el => {
    const col = el.dataset.col;
    const handler = () => { roleFilters[col] = el.value; renderRoleGridBody(cols); };
    el.addEventListener("input", handler);
    el.addEventListener("change", handler);
  });
}

function syncRoleGridLayout() {
  const leftRows = $("#role-grid-left")?.tBodies[0]?.rows;
  const rightRows = $("#role-grid-right")?.tBodies[0]?.rows;
  if (!leftRows || !rightRows) return;
  const n = Math.min(leftRows.length, rightRows.length);
  for (let i = 0; i < n; i++) {
    leftRows[i].style.height = rightRows[i].style.height = "";
    const h = Math.max(leftRows[i].offsetHeight, rightRows[i].offsetHeight);
    if (h) leftRows[i].style.height = rightRows[i].style.height = h + "px";
  }
}

function renderRoleGrid() {
  const cols = roleColumns();
  roleRecomputeDefaultColWidths(cols);
  const { frozen, scroll } = roleSplitCols(cols);
  const left = $("#role-grid-left");
  if (!left) return;
  left.innerHTML = roleBuildColgroup(frozen) + roleBuildThead(frozen) + "<tbody></tbody>";
  left.style.tableLayout = "fixed";
  const right = $("#role-grid-right");
  right.innerHTML = roleBuildColgroup(scroll) + roleBuildThead(scroll) + "<tbody></tbody>";
  right.style.tableLayout = "fixed";
  applyRoleColWidths(cols);
  bindRoleColFilters(cols);
  bindRoleColResize(cols);
  const checkAll = $("#role-check-all");
  if (checkAll) checkAll.addEventListener("change", e => {
    document.querySelectorAll(".role-row-check").forEach(cb => cb.checked = e.target.checked);
  });
  renderRoleGridBody(cols);
}

function renderRoleGridBody(cols) {
  const { frozen, scroll } = roleSplitCols(cols);
  const roles = rolesCache().filter(r => rowPassesRoleFilter(r, cols));
  const leftTb = $("#role-grid-left tbody");
  const rightTb = $("#role-grid-right tbody");
  if (!leftTb || !rightTb) return;
  if (!roles.length) {
    leftTb.innerHTML = `<tr><td colspan="${frozen.length}" class="empty" style="padding:24px">没有符合筛选条件的角色</td></tr>`;
    rightTb.innerHTML = `<tr><td colspan="${scroll.length}"></td></tr>`;
    $("#role-row-count") && ($("#role-row-count").textContent = "0 / " + rolesCache().length + " 个");
    return;
  }
  leftTb.innerHTML = roles.map(r => `<tr>${roleRowCells(r, frozen)}</tr>`).join("");
  rightTb.innerHTML = roles.map(r => `<tr>${roleRowCells(r, scroll)}</tr>`).join("");
  $("#role-row-count") && ($("#role-row-count").textContent = `${roles.length} / ${rolesCache().length} 个`);

  rightTb.querySelectorAll(".role-flag-cb").forEach(cb =>
    cb.addEventListener("change", () => onRoleFlagToggle(cb.dataset.rkey, cb.dataset.mk, cb.dataset.flag, cb.checked)));
  rightTb.querySelectorAll("[data-role-feat]").forEach(b =>
    b.addEventListener("click", () => openRoleFeatureModal(b.dataset.roleFeat, b.dataset.featMk)));
  rightTb.querySelectorAll("[data-role-edit]").forEach(b =>
    b.addEventListener("click", () => openRoleModal(rolesCache().find(r => r.key === b.dataset.roleEdit))));
  rightTb.querySelectorAll("[data-role-del]").forEach(b =>
    b.addEventListener("click", async () => {
      if (!confirm(`确认删除角色「${b.dataset.roleDel}」？已分配该角色的用户不会被删除，但其模块权限不会自动变更。`)) return;
      try {
        await api(`/api/roles/${encodeURIComponent(b.dataset.roleDel)}`, { method: "DELETE" });
        toast("角色已删除");
        await loadPermData();
        renderPermGrid();
        renderRoleGrid();
      } catch (e) { toast(e.message, true); }
    }));
  const checkAll = $("#role-check-all");
  if (checkAll) checkAll.checked = false;
  requestAnimationFrame(() => syncRoleGridLayout());
}

function roleSelectedKeys() {
  return [...document.querySelectorAll(".role-row-check:checked")].map(cb => cb.value);
}

async function onRoleFlagToggle(roleKey, mk, flag, checked) {
  const role = rolesCache().find(r => r.key === roleKey);
  if (!role || role.bypass) return;
  const perms = JSON.parse(JSON.stringify(role.perms || {}));
  if (!perms[mk]) perms[mk] = { v: 0, r: 0, w: 0, m: 0 };
  perms[mk][flag] = checked ? 1 : 0;
  if (!perms[mk].v && !perms[mk].r && !perms[mk].w && !perms[mk].m) delete perms[mk];
  try {
    await api(`/api/roles/${encodeURIComponent(roleKey)}`, { method: "PUT", json: { perms } });
    role.perms = perms;
  } catch (e) {
    toast(e.message, true);
    await loadPermData();
    renderRoleGrid();
  }
}

function openRoleFeatureModal(roleKey, mk) {
  const feats = permFeatureRegistry[mk] || [];
  const role = rolesCache().find(r => r.key === roleKey);
  if (!role || role.bypass) return;
  const mod = permModuleCols.find(m => m.key === mk);
  const cur = rolePermOf(roleKey, mk);
  const isOn = k => !((cur.feats || {})[k] === 0);
  const kinds = [["tab", "子标签可见性"], ["button", "按钮可见性"]];
  const sections = kinds.map(([kind, title]) => {
    const items = feats.filter(f => f.kind === kind);
    if (!items.length) return "";
    return `
      <div class="feat-section">
        <div class="feat-section-title">${title}</div>
        <div class="feat-list">
          ${items.map(f => `
            <label class="feat-switch">
              <input type="checkbox" class="role-feat-cb" data-fk="${f.key}" ${isOn(f.key) ? "checked" : ""}>
              <span class="feat-slider"></span>
              <span class="feat-name">${esc(f.label)}</span>
            </label>`).join("")}
        </div>
      </div>`;
  }).join("");

  openModal(`细粒度权限 · 角色「${esc(role?.label || roleKey)}」× ${esc(mod?.label || mk)}`, `
    <p class="muted" style="font-size:12px;margin:0 0 12px">
      配置该角色权限模板在页面内的子标签/按钮可见性。应用角色到用户时会一并写入。默认全部开启。</p>
    ${sections}`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-sm" id="role-feat-reset">全部恢复默认</button>
     <button class="btn btn-primary" id="role-feat-save">保存</button>`);

  $("#role-feat-reset").addEventListener("click", () => {
    document.querySelectorAll(".role-feat-cb").forEach(cb => { cb.checked = true; });
  });
  $("#role-feat-save").addEventListener("click", async () => {
    const features = {};
    document.querySelectorAll(".role-feat-cb").forEach(cb => { features[cb.dataset.fk] = cb.checked ? 1 : 0; });
    const perms = JSON.parse(JSON.stringify(role.perms || {}));
    if (!perms[mk]) perms[mk] = { v: 0, r: 0, w: 0, m: 0 };
    perms[mk].features = features;
    try {
      await api(`/api/roles/${encodeURIComponent(roleKey)}`, { method: "PUT", json: { perms } });
      toast("角色细粒度权限已保存");
      closeModal();
      await loadPermData();
      renderRoleGrid();
    } catch (e) { toast(e.message, true); }
  });
}

async function roleBatchApply(revoke) {
  const keys = roleSelectedKeys();
  if (!keys.length) { toast("请先勾选角色"); return; }
  const mk = $("#role-batch-module").value;
  const flags = { v: 0, r: 0, w: 0, m: 0 };
  if (!revoke) {
    flags.v = $("#role-batch-v").checked ? 1 : 0;
    flags.r = $("#role-batch-r").checked ? 1 : 0;
    flags.w = $("#role-batch-w").checked ? 1 : 0;
    flags.m = $("#role-batch-m").checked ? 1 : 0;
    if (!flags.v && !flags.r && !flags.w && !flags.m) { toast("请至少勾选一项权限"); return; }
    if (flags.m && !confirm("确认批量授予「管理」权限？")) return;
  }
  let affected = 0;
  try {
    for (const key of keys) {
      const role = rolesCache().find(r => r.key === key);
      if (!role || role.bypass) continue;
      const perms = JSON.parse(JSON.stringify(role.perms || {}));
      if (revoke) {
        delete perms[mk];
      } else {
        perms[mk] = { ...flags };
      }
      await api(`/api/roles/${encodeURIComponent(key)}`, { method: "PUT", json: { perms } });
      role.perms = perms;
      affected++;
    }
    toast(`${revoke ? "已清空" : "已应用"} ${affected} 个角色的模块权限`);
    renderRoleGrid();
  } catch (e) { toast(e.message, true); await loadPermData(); renderRoleGrid(); }
}

function roleInterviewPositionsHtml(role) {
  if (role && role.key !== "interviewer") return "";
  const opts = permOptions.interview_position_options || [];
  const sel = new Set(role?.interview_positions || []);
  if (!opts.length) return "";
  return `
    <div class="form-item form-item-full" id="rf-interview-pos-wrap">
      <label>可面试岗位模板（多选，新建面试官用户时可作默认）</label>
      <div class="checkbox-group">
        ${opts.map(p => `
          <label class="checkbox-item">
            <input type="checkbox" class="rf-interview-pos" value="${esc(p)}" ${sel.has(p) ? "checked" : ""}> ${esc(p)}
          </label>`).join("")}
      </div>
    </div>`;
}

function openRoleModal(role) {
  const isNew = !role;
  openModal(isNew ? "新增角色" : `编辑角色 - ${esc(role.label)}`, `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>角色名称 *</label>
        <input id="rf-label" value="${role ? esc(role.label) : ""}"></div>
      <div class="form-item"><label>角色key ${isNew ? "（唯一，英文/数字/下划线）" : "（不可修改）"}</label>
        <input id="rf-key" value="${role ? esc(role.key) : ""}" ${isNew ? "" : "disabled"}></div>
    </div>
    <label class="perm-flag-toggle" style="margin:6px 0 4px"><input type="checkbox" id="rf-bypass" ${role?.bypass ? "checked" : ""}>
      <span>全权角色（绕过所有模块权限，如系统管理员）</span></label>
    ${roleInterviewPositionsHtml(role)}
    <p style="font-size:12px;color:#64748b;margin:0">模块权限请在下方表格中勾选；勾选即保存。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="rf-save">保存</button>`);

  $("#rf-save").addEventListener("click", async () => {
    const label = $("#rf-label").value.trim();
    const bypass = $("#rf-bypass").checked;
    const body = { label, bypass };
    const roleKey = isNew ? $("#rf-key").value.trim() : role.key;
    if (roleKey === "interviewer") {
      body.interview_positions = [...document.querySelectorAll(".rf-interview-pos:checked")].map(cb => cb.value);
    }
    try {
      if (isNew) {
        body.key = $("#rf-key").value.trim();
        body.perms = {};
        await api("/api/roles", { method: "POST", json: body });
      } else {
        await api(`/api/roles/${encodeURIComponent(role.key)}`, { method: "PUT", json: body });
      }
      toast("角色已保存");
      closeModal();
      await loadPermData();
      renderPermGrid();
      renderRoleGrid();
    } catch (e) { toast(e.message, true); }
  });
}
