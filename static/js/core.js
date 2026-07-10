/* 校招全流程管理系统 - 核心模块（API、状态、权限、工具）
 *
 * 前端为无构建原生 SPA，加载顺序见 static/index.html 底部 <script> 列表：
 * core.js 必须最先加载（定义全局 state 与 api()），其余模块（main/stage-view/
 * overview/permissions/...）均依赖本文件。权限判断与后端 campus/services/acl.py
 * 的模块四权限（visibility/read/write/manage）保持一致，数据来自 /api/me。
 */
"use strict";

const state = {
  me: null,
  stages: [],
  stageFields: {},   // stage_key -> fields[]
  app: {},
  tab: "registration",
  logPage: 1,
};

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
    toast("网络异常：无法连接服务器，请确认服务是否在线", true);
    throw new Error("网络异常");
  }
  let body = null;
  try { body = await res.json(); } catch (_) {}
  if (!res.ok) {
    if (res.status === 401 && state.me) {
      toast("登录已失效，请重新登录", true);
      showLogin();
      throw new Error("登录已失效");
    }
    let msg = (body && body.error) ||
      (res.status === 403 ? "无权限执行该操作" : `操作失败 (${res.status})`);
    if (res.status === 413) {
      msg = (body && body.error) || "上传文件过大，请减小文件或联系管理员提高上传上限";
    }
    const err = new Error(msg);
    err.status = res.status;
    if (body) {
      err.code = body.code;
      err.existing = body.existing;
      err.can_merge = body.can_merge;
    }
    throw err;
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
function closeModal() {
  $("#modal-mask").classList.add("hidden");
  window.dispatchEvent(new CustomEvent("modal-closed"));
}

const ROLE_NAMES = {
  admin: "系统管理员", user: "普通用户",
};
const isAdmin = () => state.me && (state.me.is_admin === true || state.me.role === "admin");
const canEdit = () => {
  if (!state.me) return false;
  // 模块级写权限：当前 tab 即模块 key，须具备写权限（admin 直通）
  if (state.tab && typeof moduleWritable === "function" && !moduleWritable(state.tab)) return false;
  return true;
};
const canDelete = () => isAdmin();
const canBatchDelete = () => isAdmin();

function currentStageMeta() {
  return state.stages.find(s => s.key === state.tab) || state.stages[0];
}

function fieldsForStage(stageKey) {
  return state.stageFields[stageKey] || [];
}

function stageTableCfg(stageKey) {
  const key = stageKey || state.tab;
  return (state.stageTable && state.stageTable[key]) || {};
}

function visibleFields(stageKey) {
  const key = stageKey || state.tab;
  let fields = fieldsForStage(key).filter(f => f.visible);
  const order = stageTableCfg(key).column_order;
  if (order && order.length) {
    const byKey = Object.fromEntries(fields.map(f => [f.key, f]));
    const ordered = [];
    const seen = new Set();
    for (const k of order) {
      if (byKey[k]) {
        ordered.push(byKey[k]);
        seen.add(k);
      }
    }
    fields.forEach(f => {
      if (!seen.has(f.key)) ordered.push(f);
    });
    fields = ordered;
  }
  return fields;
}

function allFieldsFlat() {
  const seen = new Set();
  const out = [];
  for (const s of state.stages) {
    for (const f of fieldsForStage(s.key)) {
      if (!seen.has(f.key)) { seen.add(f.key); out.push(f); }
    }
  }
  return out;
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function todayPrefix() {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}：`;
}

/** 登记备注行首前缀：当天日期（角色名）： */
function registrationRemarkPrefix() {
  const role = (state.me && state.me.display_name) ? state.me.display_name : "用户";
  const d = new Date();
  const ds = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${ds}（${role}）：`;
}

function normalizeRegistrationRemark(value) {
  const v = (value || "").trim();
  if (!v) return "";
  const prefix = registrationRemarkPrefix();
  const lines = v.split("\n");
  if (lines[0].trim() === prefix) {
    return lines.slice(1).join("\n").trim();
  }
  return v;
}

function multilineCellHtml(full) {
  const text = (full || "").trim();
  if (!text) return `<span style="color:#cbd5e1">—</span>`;
  const first = (text.split("\n")[0] || "").trim();
  // 原生 title 对多行支持差：用 data-tip 自定义悬浮框展示全量备注
  return `<span class="clip multiline-cell" data-tip="${esc(text)}">${esc(first)}</span>`;
}

let _tipEl = null;
function ensureTipEl() {
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement("div");
  _tipEl.className = "cell-tip hidden";
  document.body.appendChild(_tipEl);
  return _tipEl;
}

function hideCellTip() {
  if (_tipEl) _tipEl.classList.add("hidden");
}

function showCellTip(anchor, text) {
  const tip = ensureTipEl();
  tip.textContent = text;
  tip.classList.remove("hidden");
  const r = anchor.getBoundingClientRect();
  const pad = 8;
  let left = r.left;
  let top = r.bottom + 6;
  // 先放到视口内再量宽高，避免首次显示偏移
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  if (left + tw + pad > window.innerWidth) left = Math.max(pad, window.innerWidth - tw - pad);
  if (top + th + pad > window.innerHeight) top = Math.max(pad, r.top - th - 6);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}

document.addEventListener("mouseover", e => {
  const el = e.target.closest("[data-tip]");
  if (!el) return;
  const text = el.getAttribute("data-tip") || "";
  if (!text.trim()) return;
  showCellTip(el, text);
});
document.addEventListener("mouseout", e => {
  const el = e.target.closest("[data-tip]");
  if (!el) return;
  const to = e.relatedTarget;
  if (to && (el.contains(to) || (to.closest && to.closest("[data-tip]") === el))) return;
  hideCellTip();
});
document.addEventListener("scroll", hideCellTip, true);

function cellHtml(field, value) {
  const v = value ?? "";
  if (v === "") return `<span style="color:#cbd5e1">—</span>`;
  const display = (field.option_labels && field.option_labels[v]) ? field.option_labels[v] : v;
  if (field.colors) return `<span class="badge badge-${field.colors[v] || "gray"}">${esc(display)}</span>`;
  return `<span class="clip" title="${esc(display)}">${esc(display)}</span>`;
}

function fieldInput(f, value, opts) {
  opts = opts || {};
  const v = value ?? "";
  const ve = esc(v);
  if (opts.locked) {
    const title = "该字段已由主数据表导入，不可修改";
    if (f.type === "select") {
      const display = (f.option_labels && f.option_labels[v]) ? f.option_labels[v] : v;
      return `<select data-field="${f.key}" class="master-locked-field" disabled title="${title}">
        <option selected>${esc(display || "（未填写）")}</option></select>`;
    }
    if (f.multiline) {
      return `<textarea data-field="${f.key}" class="master-locked-field" rows="3" disabled title="${title}">${ve}</textarea>`;
    }
    const type = f.type === "date" ? "date" : "text";
    return `<input type="${type}" data-field="${f.key}" class="master-locked-field" value="${ve}" disabled title="${title}">`;
  }
  if (f.type === "select") {
    const selectOpts = ["", ...(f.options || [])].map(o =>
      `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${o === "" ? "（未填写）" : esc(o)}</option>`).join("");
    return `<select data-field="${f.key}">${selectOpts}</select>`;
  }
  if (f.multiline) {
    const rows = f.key === "registration_remark" ? 6 : 3;
    return `<textarea data-field="${f.key}" rows="${rows}">${ve}</textarea>`;
  }
  const type = f.type === "date" ? "date" : "text";
  return `<input type="${type}" data-field="${f.key}" value="${ve}">`;
}

/** 按后端导出方案（config/export_profiles.json）导出候选人 Excel。 */
async function exportByProfile(profile, ids) {
  try {
    const res = await fetch("/api/export/candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, ids: ids || [] }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error || `导出失败 (${res.status})`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${profile}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${res.headers.get("X-Export-Count") || ids?.length || ""} 条`);
  } catch (e) { toast(e.message, true); }
}

/** 把页面上的表格导出为 CSV（通用，所有界面表格可用）。 */
function exportTableCsv(tableEl, filename) {
  if (!tableEl) { toast("没有可导出的表格", true); return; }
  const lines = [];
  tableEl.querySelectorAll("tr").forEach(tr => {
    if (tr.classList.contains("filter-row") || tr.classList.contains("fb-filter-row")
        || tr.classList.contains("perm-filter-row")) return;
    const cells = [...tr.querySelectorAll("th,td")].map(td => {
      const inp = td.querySelector("input[type=text],input[type=number],select");
      const v = inp ? (inp.value || "") : (td.innerText || "").trim().replace(/\s*\n\s*/g, " ");
      return `"${v.replace(/"/g, '""')}"`;
    });
    if (cells.length) lines.push(cells.join(","));
  });
  if (!lines.length) { toast("表格为空", true); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
  a.download = `${filename || "表格导出"}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** 数据看板 / 总览 / 图表 共享缓存（与候选人列表缓存独立） */
const DASH_CACHE_TTL_MS = 60_000;
const dashCache = {
  overview: { data: null, loadedAt: 0, stale: true },
  charts: { data: null, loadedAt: 0, stale: true },
  pivot: new Map(),
};

function invalidateDashboardCaches() {
  dashCache.overview.stale = true;
  dashCache.charts.stale = true;
  for (const v of dashCache.pivot.values()) v.stale = true;
}

function dashCacheFresh(entry) {
  return entry && !entry.stale && entry.loadedAt > 0
    && (Date.now() - entry.loadedAt) < DASH_CACHE_TTL_MS;
}

function formatRefreshTime(ts) {
  if (!ts) return "尚未加载";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "尚未加载";
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
    + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

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
$("#modal-mask").addEventListener("click", e => { if (e.target.id === "modal-mask") closeModal(); });
