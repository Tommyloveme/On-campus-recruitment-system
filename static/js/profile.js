/* 个人资料与账户选项（不提供用户自助注册，账号由系统管理员统一分配） */
"use strict";

let accountOptions = {
  user_fields: [],
  employee_id_digits: 8,
};

function findField(key) {
  return (accountOptions.user_fields || []).find(f => f.key === key) || null;
}

async function loadAccountOptions() {
  try {
    accountOptions = await fetch("/api/account/options").then(r => r.json());
  } catch (_) {
    accountOptions = { user_fields: [], employee_id_digits: 8 };
  }
  window.accountOptions = accountOptions;
}

function userProfileConfig() {
  return window.accountOptions || accountOptions;
}

function profileFieldInputHtml(f, val) {
  const v = val ?? "";
  if (f.type === "select") {
    const opts = ["", ...(f.options || [])].map(o =>
      `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${o === "" ? "（未填写）" : esc(o)}</option>`).join("");
    return `<select id="profile-${f.key}">${opts}</select>`;
  }
  return `<input id="profile-${f.key}" value="${esc(v)}">`;
}

function renderDeptLevelSelect(l2El, l2Val) {
  if (!l2El) return;
  const f2 = findField("dept_level2");
  const l2Opts = (f2 && f2.options) || [];
  l2El.innerHTML = "<option value=\"\">请选择</option>" +
    l2Opts.map(o => `<option value="${esc(o)}"${o === l2Val ? " selected" : ""}>${esc(o)}</option>`).join("");
}

function collectUserProfilePayload() {
  const payload = { display_name: $("#profile-display").value.trim() };
  for (const f of (userProfileConfig().user_fields || [])) {
    if (f.key === "display_name") continue;
    const el = $(`#profile-${f.key}`);
    if (!el) continue;
    payload[f.key] = f.type === "select" ? el.value : el.value.trim();
  }
  return payload;
}

function bindPasswordToggles(root = document) {
  root.querySelectorAll(".pwd-toggle").forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.target);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "隐藏" : "显示";
      btn.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
    });
  });
}

function openProfileModal() {
  const showSysRole = isAdmin();
  const fields = (userProfileConfig().user_fields || []).filter(f => f.key !== "display_name");
  const fieldRows = fields.map(f => {
    const val = state.me[f.key] ?? "";
    if (f.key === "dept_level2") {
      return `<div class="form-item"><label>${esc(f.label)}${f.required ? " *" : ""}</label>
        <select id="profile-dept_level2"></select></div>`;
    }
    const hint = f.pattern === "chinese" ? `<p class="field-hint">${esc(f.label)}须为中文</p>` : "";
    return `<div class="form-item"><label>${esc(f.label)}${f.required ? " *" : ""}</label>
      ${profileFieldInputHtml(f, val)}${hint}</div>`;
  }).join("");
  openModal("我的账户", `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>工号</label>
        <input value="${esc(state.me.username)}" disabled></div>
      <div class="form-item"><label>姓名 *</label>
        <input id="profile-display" value="${esc(state.me.display_name)}">
        <p class="field-hint">姓名须为中文</p></div>
      ${fieldRows}
      ${showSysRole ? `<div class="form-item"><label>系统角色</label>
        <input value="${esc(ROLE_NAMES[state.me.role] || state.me.role)}" disabled></div>` : ""}
      <div class="form-item"><label>新密码（留空则不修改）</label>
        <div class="password-wrap">
          <input id="profile-password" type="password">
          <button type="button" class="btn btn-ghost btn-sm pwd-toggle" data-target="profile-password" aria-label="显示密码">显示</button>
        </div></div>
      <div class="form-item" style="grid-column:1/-1">
        <p class="field-hint">系统权限由管理员统一分配，如需调整请联系管理员</p>
      </div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="profile-save">保存</button>`);
  renderDeptLevelSelect($("#profile-dept_level2"), state.me.dept_level2 || "");
  bindPasswordToggles($("#modal-body"));
  $("#profile-save").addEventListener("click", async () => {
    const payload = {
      ...collectUserProfilePayload(),
      password: $("#profile-password").value,
    };
    try {
      state.me = await api("/api/profile", { method: "PUT", json: payload });
      const roleName = ROLE_NAMES[state.me.role] || state.me.role;
      $("#user-info").textContent = `${state.me.display_name}（${roleName}）`;
      toast("账户信息已更新");
      closeModal();
    } catch (e) { toast(e.message, true); }
  });
}

loadAccountOptions();
