"use strict";

/* 操作日志与数据备份渲染（合并入「权限管理」页，仅系统管理员可见） */
const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], export: ["导出", "yellow"], backup: ["备份", "gray"],
  user: ["用户", "gray"], config: ["配置", "gray"], permission: ["权限", "blue"],
};

async function renderLogsInto(container, page = 1) {
  if (!container) return;
  container.innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const r = await api(`/api/logs?page=${page}`);
    const items = r.items.map(l => {
      const [txt, color] = ACTION_BADGE[l.action] || ["操作", "gray"];
      return `
        <div class="log-item">
          <span class="log-time">${esc(l.created_at)}</span>
          <span class="badge badge-${color}">${txt}</span>
          <span class="log-msg">${esc(l.message)}</span>
        </div>`;
    }).join("");
    const pages = Math.max(1, Math.ceil(r.total / r.size));
    container.className = "log-list";
    container.innerHTML = (items || `<div class="empty">暂无日志</div>`) + `
      <div class="pager">
        <button class="btn btn-sm" data-log-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
        <span>第 ${page} / ${pages} 页（共 ${r.total} 条）</span>
        <button class="btn btn-sm" data-log-next ${page >= pages ? "disabled" : ""}>下一页</button>
      </div>`;
    container.querySelector("[data-log-prev]")?.addEventListener("click", () => renderLogsInto(container, page - 1));
    container.querySelector("[data-log-next]")?.addEventListener("click", () => renderLogsInto(container, page + 1));
  } catch (e) {
    container.innerHTML = `<div class="empty">日志加载失败：${esc(e.message)}</div>`;
  }
}

async function renderBackupsInto(container) {
  if (!container) return;
  const list = container.querySelector(".backup-list-body");
  const render = async () => {
    try {
      const backups = await api("/api/backups");
      list.innerHTML = backups.length
        ? backups.map(b => `
          <div class="backup-row">
            <span>${esc(b.name)}</span>
            <span class="muted">${esc(b.time)} · ${b.size_kb} KB</span>
            <button class="btn btn-sm btn-danger" data-restore="${esc(b.name)}">恢复</button>
          </div>`).join("")
        : `<div class="empty" style="padding:12px">暂无备份</div>`;
      list.querySelectorAll("[data-restore]").forEach(b =>
        b.addEventListener("click", async () => {
          if (!confirm(`确定恢复到备份「${b.dataset.restore}」？当前数据将被覆盖。`)) return;
          try {
            await api("/api/backups/restore", { method: "POST", json: { name: b.dataset.restore } });
            toast("备份已恢复，请刷新页面");
          } catch (e) { toast(e.message, true); }
        }));
    } catch (e) { list.innerHTML = `<div class="empty">备份加载失败：${esc(e.message)}</div>`; }
  };
  await render();
  container.querySelector(".btn-backup-now")?.addEventListener("click", async () => {
    try {
      const r = await api("/api/backups", { method: "POST" });
      toast(`备份完成：${r.name}`);
      render();
    } catch (e) { toast(e.message, true); }
  });
}
