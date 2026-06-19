/* 校招全流程管理系统 - 核心模块（API、状态、权限、工具） */
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

const ROLE_NAMES = {
  admin: "系统管理员", global_viewer: "全局查看员", group_admin: "组管理员",
  editor: "组成员", viewer: "只读",
};
const isAdmin = () => state.me && state.me.role === "admin";
const isGroupAdmin = () => state.me && state.me.role === "group_admin";
const canSeeAll = () => state.me && ["admin", "global_viewer"].includes(state.me.role);
const canCreate = () => state.me && ["admin", "group_admin", "editor"].includes(state.me.role);
const canEdit = gid => isAdmin() ||
  (["group_admin", "editor"].includes(state.me.role) && state.me.group_id === gid);
const canDelete = gid => isAdmin() || (isGroupAdmin() && state.me.group_id === gid);
const canBatchDelete = () => isAdmin() || isGroupAdmin();

function currentStageMeta() {
  return state.stages.find(s => s.key === state.tab) || state.stages[0];
}

function fieldsForStage(stageKey) {
  return state.stageFields[stageKey] || [];
}

function visibleFields(stageKey) {
  return fieldsForStage(stageKey || state.tab).filter(f => f.visible);
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

function cellHtml(field, value) {
  const v = value ?? "";
  if (v === "") return `<span style="color:#cbd5e1">—</span>`;
  const display = (field.option_labels && field.option_labels[v]) ? field.option_labels[v] : v;
  if (field.colors) return `<span class="badge badge-${field.colors[v] || "gray"}">${esc(display)}</span>`;
  return `<span class="clip" title="${esc(display)}">${esc(display)}</span>`;
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
