/* 用户注册与个人资料 */
"use strict";

let registerOptions = { job_roles: [], default_job_roles: [] };

async function loadRegisterOptions() {
  try {
    registerOptions = await fetch("/api/register/options").then(r => r.json());
  } catch (_) {
    registerOptions = {
      job_roles: ["拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA"],
      default_job_roles: ["拓源人", "接口人"],
    };
  }
  window.registerOptions = registerOptions;
}

function renderJobRoleCheckboxes(containerId, selectedRoles) {
  const el = $(containerId);
  if (!el) return;
  const selected = new Set(selectedRoles || []);
  el.innerHTML = registerOptions.job_roles.map(role => `
    <label class="checkbox-item">
      <input type="checkbox" value="${esc(role)}" ${selected.has(role) ? "checked" : ""}>
      <span>${esc(role)}</span>
    </label>`).join("");
}

function getCheckedJobRoles(containerId) {
  const el = $(containerId);
  if (!el) return [];
  return [...el.querySelectorAll("input[type=checkbox]:checked")].map(cb => cb.value);
}

function showRegisterView() {
  $("#login-view").classList.add("hidden");
  $("#register-view").classList.remove("hidden");
  $("#app-view").classList.add("hidden");
  renderJobRoleCheckboxes("#reg-job-roles", registerOptions.default_job_roles);
  const pwd = $("#reg-password");
  if (pwd && !pwd.value) pwd.value = "123456";
}

function openProfileModal() {
  const roles = (window.registerOptions && window.registerOptions.job_roles) ||
    ["拓源人", "接口人", "技术面试官", "主管面试官", "HR", "BA"];
  window.registerOptions = { ...(window.registerOptions || {}), job_roles: roles };
  openModal("我的账户", `
    <div class="form-grid" style="grid-template-columns:1fr 1fr">
      <div class="form-item"><label>工号</label>
        <input value="${esc(state.me.username)}" disabled></div>
      <div class="form-item"><label>姓名 *</label>
        <input id="profile-display" value="${esc(state.me.display_name)}"></div>
      <div class="form-item"><label>主管 *</label>
        <input id="profile-supervisor" value="${esc(state.me.supervisor || "")}"></div>
      <div class="form-item"><label>部门 *</label>
        <input id="profile-department" value="${esc(state.me.department || "")}"></div>
      <div class="form-item"><label>系统权限</label>
        <input value="${esc(ROLE_NAMES[state.me.role] || state.me.role)}" disabled></div>
      <div class="form-item"><label>新密码（留空则不修改）</label>
        <input id="profile-password" type="password"></div>
      <div class="form-item" style="grid-column:1/-1">
        <label>业务角色 *（可多选）</label>
        <div id="profile-job-roles" class="checkbox-group"></div>
      </div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="profile-save">保存</button>`);
  renderJobRoleCheckboxes("#profile-job-roles", state.me.job_roles || []);
  $("#profile-save").addEventListener("click", async () => {
    const payload = {
      display_name: $("#profile-display").value.trim(),
      supervisor: $("#profile-supervisor").value.trim(),
      department: $("#profile-department").value.trim(),
      password: $("#profile-password").value,
      job_roles: getCheckedJobRoles("#profile-job-roles"),
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
  const payload = {
    employee_id: $("#reg-employee-id").value.trim(),
    display_name: $("#reg-display-name").value.trim(),
    supervisor: $("#reg-supervisor").value.trim(),
    department: $("#reg-department").value.trim(),
    password: $("#reg-password").value,
    job_roles: getCheckedJobRoles("#reg-job-roles"),
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
