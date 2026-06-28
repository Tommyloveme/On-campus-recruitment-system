/* 主框架：左侧分组导航（可折叠层级） + 路由 */
"use strict";

const TOOL_TABS = {
  overview: { label: "全局总览", render: renderOverview },
  charts: { label: "数据图表", render: renderCharts },
  permissions: { label: "权限管理", render: renderPermissions },
  op_logs: { label: "操作日志", render: renderLogs },
  backups: { label: "数据备份", render: renderBackups },
  feedback: { label: "问题反馈", render: renderFeedback },
};

/** 分组 id -> 子菜单 tab id 列表（用于展开与高亮） */
const NAV_GROUP_CHILDREN = {};

/** 模块有效权限（来自 /api/permissions/modules，含 visible/readable/writable）。 */
let modulePerms = [];

function moduleByKey(key) {
  for (const s of modulePerms) {
    if (s.key === key) return s;
    for (const it of (s.items || [])) if (it.key === key) return it;
  }
  return null;
}
function moduleVisible(key) { const m = moduleByKey(key); return m ? !!m.visible : false; }
function moduleReadable(key) { const m = moduleByKey(key); return m ? !!m.readable : false; }
function moduleWritable(key) { const m = moduleByKey(key); return m ? !!m.writable : false; }

/** 左侧导航结构（依据后端模块注册表与当前用户有效权限过滤） */
function buildNavStructure() {
  const sections = [];
  for (const entry of modulePerms) {
    if (entry.type === "item") {
      if (entry.visible) sections.push({ type: "item", id: entry.key, label: entry.label });
      continue;
    }
    const items = (entry.items || []).filter(it => it.visible).map(it => ({ id: it.key, label: it.label }));
    if (items.length) sections.push({ type: "group", id: entry.key, label: entry.label, items });
  }

  Object.keys(NAV_GROUP_CHILDREN).forEach(k => delete NAV_GROUP_CHILDREN[k]);
  sections.forEach(s => {
    if (s.type === "group") NAV_GROUP_CHILDREN[s.id] = s.items.map(i => i.id);
  });
  return sections;
}

/** 第一个可见的 tab（用于默认/回退） */
function firstVisibleTab() {
  const nav = buildNavStructure();
  for (const s of nav) {
    if (s.type === "item") return s.id;
    if (s.items && s.items.length) return s.items[0].id;
  }
  return null;
}

/** 当前展开的分组 id 集合（默认全部折叠） */
const navExpandedGroups = new Set();

function groupForTab(tabId) {
  for (const [gid, ids] of Object.entries(NAV_GROUP_CHILDREN)) {
    if (ids.includes(tabId)) return gid;
  }
  return null;
}

async function boot() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  const roleName = ROLE_NAMES[state.me.role] || state.me.role;
  $("#user-info").textContent = `${state.me.display_name}（${roleName}）`;

  const [cfg, mods] = await Promise.all([api("/api/config"), api("/api/permissions/modules")]);
  state.stages = cfg.stages;
  state.stageFields = cfg.stage_fields;
  state.stageTable = cfg.stage_table || {};
  state.masterImport = cfg.master_import || {};
  state.app = cfg.app || {};
  modulePerms = (mods && mods.modules) || [];

  if (state.app.clip_max_width)
    document.documentElement.style.setProperty("--clip-max", state.app.clip_max_width + "px");

  navExpandedGroups.clear();
  buildSidebar();
  switchTab(moduleVisible("registration") ? "registration" : (firstVisibleTab() || "registration"));
}

function buildSidebar() {
  const nav = buildNavStructure();
  const html = nav.map(section => {
    if (section.type === "item") {
      return `
        <div class="nav-entry">
          <button class="nav-row nav-leaf" data-tab="${section.id}">
            <span class="nav-slot" aria-hidden="true"></span>
            <span class="nav-label">${esc(section.label)}</span>
          </button>
        </div>`;
    }
    const expanded = navExpandedGroups.has(section.id);
    const children = section.items.map(it => `
      <button class="nav-row nav-child" data-tab="${it.id}">
        <span class="nav-dot" aria-hidden="true"></span>
        <span class="nav-label">${esc(it.label)}</span>
      </button>`).join("");
    return `
      <div class="nav-entry nav-group${expanded ? " expanded" : ""}" data-group="${section.id}">
        <button type="button" class="nav-row nav-parent" data-group="${section.id}" aria-expanded="${expanded}">
          <span class="nav-slot nav-chevron" aria-hidden="true"></span>
          <span class="nav-label">${esc(section.label)}</span>
        </button>
        <div class="nav-children">${children}</div>
      </div>`;
  }).join("");

  $("#sidebar").innerHTML = html;

  $("#sidebar").querySelectorAll(".nav-parent").forEach(btn => {
    btn.addEventListener("click", () => toggleNavGroup(btn.dataset.group));
  });
  $("#sidebar").querySelectorAll(".nav-row[data-tab]").forEach(btn => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
}

function toggleNavGroup(groupId) {
  if (navExpandedGroups.has(groupId)) navExpandedGroups.delete(groupId);
  else navExpandedGroups.add(groupId);
  const el = $(`.nav-group[data-group="${groupId}"]`);
  if (el) {
    el.classList.toggle("expanded", navExpandedGroups.has(groupId));
    el.querySelector(".nav-parent")?.setAttribute("aria-expanded", navExpandedGroups.has(groupId));
  }
}

function updateSidebarActive(tab) {
  $("#sidebar").querySelectorAll(".nav-row[data-tab]").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === tab));
  const gid = groupForTab(tab);
  $("#sidebar").querySelectorAll(".nav-group").forEach(g => {
    g.classList.toggle("has-active", g.dataset.group === gid);
  });
}

function switchTab(tab) {
  // 模块级权限拦截：不可见/不可读的模块不允许切换
  if (!moduleVisible(tab) || !moduleReadable(tab)) {
    const fallback = firstVisibleTab();
    if (fallback && fallback !== tab) return switchTab(fallback);
    $("#main-content").innerHTML = `<div class="empty-state">无可用模块，请联系管理员开通权限。</div>`;
    return;
  }
  state.tab = tab;
  const gid = groupForTab(tab);
  if (gid && !navExpandedGroups.has(gid)) {
    navExpandedGroups.add(gid);
    const el = $(`.nav-group[data-group="${gid}"]`);
    if (el) {
      el.classList.add("expanded");
      el.querySelector(".nav-parent")?.setAttribute("aria-expanded", "true");
    }
  }
  updateSidebarActive(tab);

  if (TOOL_TABS[tab]) {
    TOOL_TABS[tab].render();
  } else if (state.stages.some(s => s.key === tab)) {
    renderStageView(tab);
  }
}

(async function init() {
  try {
    state.me = await api("/api/me");
    await boot();
  } catch (_) {
    showLogin();
  }
})();
