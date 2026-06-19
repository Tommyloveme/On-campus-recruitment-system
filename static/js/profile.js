/* 用户注册与个人资料 */
"use strict";

let registerOptions = {
  job_roles: [],
  default_job_roles: ["拓源人", "接口人"],
  employee_id_digits: 8,
  dept_level2_options: [],
  dept_level3_options: [],
};

async function loadRegisterOptions() {
  try {
    registerOptions = await fetch("/api/register/options").then(r => r.json());
  } catch (_) {
    registerOptions = {
      job_roles: ["拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA"],
      default_job_roles: ["拓源人", "接口人"],
      employee_id_digits: 8,
      dept_level2_options: ["存储部", "计算部", "网络部", "软件部"],
      dept_level3_options: ["块存储", "对象存储", "通用计算", "研发一组"],
    };
  }
  window.registerOptions = registerOptions;
  applyRegisterFormConfig();
}

function userProfileConfig() {
  return window.registerOptions || registerOptions;
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

function collectUserProfilePayload(mode) {
  if (mode === "reg") {
    return {
      display_name: $("#reg-display-name").value.trim(),
      supervisor: $("#reg-supervisor").value.trim(),
      dept_level2: $("#reg-dept-level2").value,
      dept_level3: $("#reg-dept-level3").value.trim(),
    };
  }
  return {
    display_name: $("#profile-display").value.trim(),
    supervisor: $("#profile-supervisor").value.trim(),
    dept_level2: $("#profile-dept-level2").value,
    dept_level3: $("#profile-dept-level3").value.trim(),
  };
}

function applyRegisterFormConfig() {
  const cfg = userProfileConfig();
  const digits = cfg.employee_id_digits || 8;
  const emp = $("#reg-employee-id");
  if (emp) {
    emp.placeholder = `${digits}位数字工号`;
    emp.maxLength = digits;
    emp.pattern = `\\d{${digits}}`;
  }
  renderDeptLevelSelects($("#reg-dept-level2"), $("#reg-dept-level3"), "", "");
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

function showRegisterView() {
  $("#login-view").classList.add("hidden");
  $("#register-view").classList.remove("hidden");
  $("#app-view").classList.add("hidden");
  const pwd = $("#reg-password");
  if (pwd && !pwd.value) pwd.value = "123456";
  applyRegisterFormConfig();
  bindPasswordToggles($("#register-view"));
}

function openProfileModal() {
  const roles = (window.registerOptions && window.registerOptions.job_roles) ||
    ["拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA"];
  window.registerOptions = { ...(window.registerOptions || {}), job_roles: roles };
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
      ${showSysRole ? `<div class="form-item"><label>系统权限</label>
        <input value="${esc(ROLE_NAMES[state.me.role] || state.me.role)}" disabled></div>` : ""}
      <div class="form-item"><label>新密码（留空则不修改）</label>
        <div class="password-wrap">
          <input id="profile-password" type="password">
          <button type="button" class="btn btn-ghost btn-sm pwd-toggle" data-target="profile-password" aria-label="显示密码">显示</button>
        </div></div>
      <div class="form-item" style="grid-column:1/-1">
        <label>业务角色</label>
        <input value="${esc((state.me.job_roles || []).join("、") || "—")}" disabled>
      </div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="profile-save">保存</button>`);
  renderDeptLevelSelects($("#profile-dept-level2"), $("#profile-dept-level3"), l2, l3);
  bindPasswordToggles($("#modal-body"));
  $("#profile-save").addEventListener("click", async () => {
    const payload = {
      ...collectUserProfilePayload("profile"),
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

async function doRegister() {
  const errEl = $("#register-error");
  errEl.classList.add("hidden");
  const defaultRoles = registerOptions.default_job_roles || ["拓源人", "接口人"];
  const payload = {
    employee_id: $("#reg-employee-id").value.trim(),
    ...collectUserProfilePayload("reg"),
    password: $("#reg-password").value,
    job_roles: defaultRoles,
  };
  try {
    await api("/api/register", { method: "POST", json: payload });
    toast("注册成功，请登录");
    showLogin();
    $("#login-username").value = payload.employee_id;
    $("#login-password").value = payload.password;
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  }
}

$("#goto-register")?.addEventListener("click", e => { e.preventDefault(); showRegisterView(); });
$("#goto-login")?.addEventListener("click", e => { e.preventDefault(); showLogin(); });
$("#register-btn")?.addEventListener("click", doRegister);
$("#profile-btn")?.addEventListener("click", () => openProfileModal());

loadRegisterOptions();
