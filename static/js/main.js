/* 主框架：左侧分组导航（可折叠层级） + 路由 */
"use strict";

const TOOL_TABS = {
  overview: { label: "全局总览", render: renderOverview },
  charts: { label: "数据图表", render: renderCharts },
  logs: { label: "操作日志", render: renderLogs },
  admin: { label: "系统管理", render: renderAdmin },
};

/** 分组 id -> 子菜单 tab id 列表（用于展开与高亮） */
const NAV_GROUP_CHILDREN = {};

/** 左侧导航结构 */
function buildNavStructure() {
  const sections = [];

  sections.push({ type: "item", id: "registration", label: "候选人登记" });

  sections.push({
    type: "group", id: "recruit_flow", label: "校招流程", items: [
      { id: "resume_screening", label: "简历筛选" },
      { id: "qualification", label: "资格审查" },
      { id: "written_test", label: "笔试" },
      { id: "tech_interview", label: "技术面" },
      { id: "manager_interview", label: "主管面" },
    ],
  });

  sections.push({
    type: "group", id: "offer_strategy", label: "Offer策略", items: [
      { id: "approval", label: "报批" },
      { id: "salary", label: "谈薪" },
      { id: "offer", label: "Offer管理" },
    ],
  });

  sections.push({ type: "item", id: "onboarding", label: "入职管理" });

  if (canSeeAll() || isGroupAdmin()) {
    const dataItems = [];
    if (canSeeAll()) dataItems.push({ id: "overview", label: "全局总览" });
    dataItems.push({ id: "charts", label: "数据图表" });
    sections.push({ type: "group", id: "data_board", label: "数据看板", items: dataItems });
  }

  if (isAdmin()) {
    sections.push({
      type: "group", id: "admin_board", label: "管理看板", items: [
        { id: "logs", label: "操作日志" },
        { id: "admin", label: "系统管理" },
      ],
    });
  }

  Object.keys(NAV_GROUP_CHILDREN).forEach(k => delete NAV_GROUP_CHILDREN[k]);
  sections.forEach(s => {
    if (s.type === "group") NAV_GROUP_CHILDREN[s.id] = s.items.map(i => i.id);
  });
  return sections;
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

  const [cfg] = await Promise.all([api("/api/config")]);
  state.stages = cfg.stages;
  state.stageFields = cfg.stage_fields;
  state.masterImport = cfg.master_import || {};
  state.app = cfg.app || {};

  if (state.app.clip_max_width)
    document.documentElement.style.setProperty("--clip-max", state.app.clip_max_width + "px");

  navExpandedGroups.clear();
  buildSidebar();
  switchTab("registration");
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
