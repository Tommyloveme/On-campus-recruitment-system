/* 可复用操作日志面板：任意页面挂载，按模块过滤展示（操作人/时间/详情）。
 * 用法：renderLogPanel(容器元素, { module: "registration" })
 * module 省略时展示全量日志（仅系统管理员）。 */
"use strict";

/* 操作类型 → [标签, 颜色]。刻意收敛为 4 色：新增=绿 / 修改类=蓝 / 删除=红 / 其他=灰 */
const LOG_ACTION_BADGE = {
  create: ["新增", "green"],
  update: ["修改", "blue"], permission: ["权限", "blue"], user: ["用户", "blue"], config: ["配置", "blue"],
  delete: ["删除", "red"],
  import: ["导入", "gray"], export: ["导出", "gray"], backup: ["备份", "gray"],
};

function logActionBadge(action) {
  const [txt, color] = LOG_ACTION_BADGE[action] || ["操作", "gray"];
  return `<span class="badge badge-${color}">${txt}</span>`;
}

function logPanelLegendHtml() {
  const seen = new Set();
  const items = [];
  for (const [txt, color] of Object.values(LOG_ACTION_BADGE)) {
    if (seen.has(color)) continue;
    seen.add(color);
    const label = { green: "新增", blue: "修改/配置", red: "删除", gray: "导入导出等" }[color] || txt;
    items.push(`<span class="badge badge-${color}">${label}</span>`);
  }
  return `<span class="log-legend">${items.join("")}</span>`;
}

/**
 * 渲染日志面板。返回 { reload }。
 * opts: { module: 模块key|null, pageSize: 每页条数 }
 */
function renderLogPanel(rootEl, opts = {}) {
  if (!rootEl) return null;
  const module = opts.module || null;
  let pageSize = Number(opts.pageSize) || defaultLogPageSize();
  let page = 1;

  rootEl.innerHTML = `
    <div class="log-panel">
      <div class="log-panel-bar">
        ${logPanelLegendHtml()}
        <span class="spacer"></span>
        <button class="btn btn-sm" data-lp-export title="导出当前页日志为 CSV">导出</button>
        <button class="btn btn-sm" data-lp-refresh title="重新加载日志">刷新</button>
      </div>
      <div class="log-table-wrap">
        <table class="log-table">
          <thead><tr><th>时间</th><th>类型</th><th style="width:90px">操作人</th><th>详情</th></tr></thead>
          <tbody data-lp-body><tr><td colspan="4" class="log-empty">加载中…</td></tr></tbody>
        </table>
      </div>
      <div class="log-foot" data-lp-foot></div>
    </div>`;

  const body = rootEl.querySelector("[data-lp-body]");
  const foot = rootEl.querySelector("[data-lp-foot]");

  const renderFoot = total => {
    mountPagerBar(foot, {
      total,
      page,
      pageSize,
      unit: "条",
      sizes: logPageSizeOptions(),
      idPrefix: "lp",
      extraClass: "log-pager-wrap",
      onChange: ({ page: p, pageSize: s }) => {
        page = p;
        pageSize = s;
        load();
      },
    });
  };

  const load = async () => {
    try {
      const q = `page=${page}&size=${pageSize}` + (module ? `&module=${encodeURIComponent(module)}` : "");
      const r = await api(`/api/logs?${q}`);
      body.innerHTML = r.items.length ? r.items.map(l => `
        <tr>
          <td class="log-time">${esc(l.created_at)}</td>
          <td class="log-type">${logActionBadge(l.action)}<span class="log-level" title="日志等级（1最敏感，10常规）">L${l.level ?? 10}</span></td>
          <td class="log-user" title="${esc(l.user_name)}">${esc(l.user_name)}</td>
          <td class="log-msg" title="${esc(l.message)}">${esc(l.message)}</td>
        </tr>`).join("") : `<tr><td colspan="4" class="log-empty">暂无日志</td></tr>`;
      page = r.page || page;
      pageSize = r.size || pageSize;
      renderFoot(r.total || 0);
    } catch (e) {
      body.innerHTML = `<tr><td colspan="4" class="log-empty">日志加载失败：${esc(e.message)}</td></tr>`;
      foot.innerHTML = "";
    }
  };
  rootEl.querySelector("[data-lp-refresh]")?.addEventListener("click", () => load());
  rootEl.querySelector("[data-lp-export]")?.addEventListener("click", () =>
    exportTableCsv(rootEl.querySelector(".log-table"), "操作日志"));
  load();
  return { reload: () => { page = 1; load(); } };
}
