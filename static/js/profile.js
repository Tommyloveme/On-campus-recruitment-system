/* 个人资料与账户选项（不提供用户自助注册，账号由系统管理员统一分配） */
"use strict";

let accountOptions = {
  employee_id_digits: 8,
  dept_level2_options: [],
  dept_level3_options: [],
};

async function loadAccountOptions() {
  try {
    accountOptions = await fetch("/api/account/options").then(r => r.json());
  } catch (_) {
    accountOptions = {
      employee_id_digits: 8,
      dept_level2_options: ["存储部", "计算部", "网络部", "软件部"],
      dept_level3_options: ["块存储", "对象存储", "通用计算", "研发一组"],
    };
  }
  window.accountOptions = accountOptions;
}

function userProfileConfig() {
  return window.accountOptions || accountOptions;
}

function renderDeptLevelSelects(l2El, l3El, l2Val, l3Val) {
  if (!l2El || !l3El) return;
  const cfg = userProfileConfig();
  const l2Opts = cfg.dept_level2_options || [];
  const l3Opts = cfg.dept_level3_options || [];
  l2El.innerHTML = "<option value=\"\">请选择</option>" +
    l2Opts.map(o => `<option value="${esc(o)}"${o === l2Val ? " selected" : ""}>${esc(o)}</option>`).join("");
  l3El.innerHTML = "<option value=\"\">（可选）</option>" +
    l3Opts.map(o => `<option value="${esc(o)}"${o === l3Val ? " selected" : ""}>${esc(o)}</option>`).join("");
}

function collectUserProfilePayload() {
  return {
    display_name: $("#profile-display").value.trim(),
    supervisor: $("#profile-supervisor").value.trim(),
    dept_level2: $("#profile-dept-level2").value,
    dept_level3: $("#profile-dept-level3").value.trim(),
  };
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
  const l2 = state.me.dept_level2 || "";
  const l3 = state.me.dept_level3 || "";
  openModal("我的账户", `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>工号</label>
        <input value="${esc(state.me.username)}" disabled></div>
      <div class="form-item"><label>姓名 *</label>
        <input id="profile-display" value="${esc(state.me.display_name)}">
        <p class="field-hint">姓名须为中文</p></div>
      <div class="form-item"><label>主管 *</label>
        <input id="profile-supervisor" value="${esc(state.me.supervisor || "")}">
        <p class="field-hint">主管须为中文</p></div>
      <div class="form-item"><label>二层部门 *</label>
        <select id="profile-dept-level2"></select></div>
      <div class="form-item"><label>三层部门</label>
        <select id="profile-dept-level3"></select></div>
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
  renderDeptLevelSelects($("#profile-dept-level2"), $("#profile-dept-level3"), l2, l3);
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

$("#profile-btn")?.addEventListener("click", () => openProfileModal());

loadAccountOptions();
