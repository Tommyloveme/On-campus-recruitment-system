"use strict";

/* 管理看板同级页：操作日志 / 数据备份 / 字段配置（仅系统管理员） */
const ACTION_BADGE = {
  create: ["新增", "green"], update: ["修改", "blue"], delete: ["删除", "red"],
  import: ["导入", "yellow"], export: ["导出", "yellow"], backup: ["备份", "gray"],
  user: ["用户", "gray"], config: ["配置", "gray"], permission: ["权限", "blue"],
};

/* ---------- 操作日志 ---------- */
async function renderLogs(page = 1) {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可查看操作日志。</div>`;
    return;
  }
  state.logPage = page;
  $("#main").innerHTML = `
    <div class="card">
      <div class="section-title">操作日志</div>
      <p style="font-size:12px;color:#64748b;margin-bottom:10px">按时间倒序记录所有用户操作，便于审计追溯。</p>
      <div id="log-list" class="empty">加载中…</div>
    </div>`;
  const box = $("#log-list");
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
    box.className = "log-list";
    box.innerHTML = (items || `<div class="empty">暂无日志</div>`) + `
      <div class="pager">
        <button class="btn btn-sm" data-log-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
        <span>第 ${page} / ${pages} 页（共 ${r.total} 条）</span>
        <button class="btn btn-sm" data-log-next ${page >= pages ? "disabled" : ""}>下一页</button>
      </div>`;
    box.querySelector("[data-log-prev]")?.addEventListener("click", () => renderLogs(page - 1));
    box.querySelector("[data-log-next]")?.addEventListener("click", () => renderLogs(page + 1));
  } catch (e) {
    box.innerHTML = `<div class="empty">日志加载失败：${esc(e.message)}</div>`;
  }
}

/* ---------- 数据备份 ---------- */
async function renderBackups() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可管理数据备份。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card">
      <div class="section-title">数据备份与恢复</div>
      <p style="font-size:12px;color:#64748b;margin-bottom:10px">手动创建数据库快照，可在误操作后一键恢复至指定备份（恢复前会自动保存当前状态）。</p>
      <div class="perm-toolbar" style="margin-bottom:12px">
        <button class="btn btn-primary btn-sm" id="bk-now">立即备份</button>
      </div>
      <div id="bk-list" class="empty">加载中…</div>
    </div>`;
  const list = $("#bk-list");
  const load = async () => {
    try {
      const backups = await api("/api/backups");
      list.className = "backup-list";
      list.innerHTML = backups.length
        ? backups.map(b => `
          <div class="backup-row">
            <span class="mono">${esc(b.name)}</span>
            <span class="muted">${esc(b.time)} · ${b.size_kb} KB${b.manual ? " · 手动" : ""}</span>
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
  await load();
  $("#bk-now").addEventListener("click", async () => {
    try {
      const r = await api("/api/backups", { method: "POST" });
      toast(`备份完成：${r.name}`);
      load();
    } catch (e) { toast(e.message, true); }
  });
}

/* ---------- 字段配置 ---------- */
async function renderFieldConfig() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可查看字段配置。</div>`;
    return;
  }
  $("#main").innerHTML = `<div class="card"><div class="section-title">附属信息字段配置</div><div id="fc-body">加载中…</div></div>`;
  let fields = [];
  try {
    const opts = await api("/api/account/options");
    fields = opts.user_fields || [];
  } catch (e) {
    $("#fc-body").innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
    return;
  }
  $("#fc-body").innerHTML = `
    <p style="font-size:12px;color:#64748b;margin-bottom:10px">
      在 <code>config/user_fields.json</code> 中新增字段并定义操作模式（<b>text</b> 自由输入 / <b>select</b> 单选下拉，<code>options</code> 为可选项）。<br>
      <b>builtin</b> 字段对应 users 表内置列；非 builtin 字段存入 <code>users.extra</code>(JSON)。修改后刷新页面即生效。
    </p>
    <div class="table-wrap"><table class="fc-table">
      <thead><tr><th>字段key</th><th>标签</th><th>类型</th><th>操作模式 / 可选项</th><th>必填</th><th>归属</th><th>说明</th></tr></thead>
      <tbody>${fields.map(f => `
        <tr>
          <td class="mono">${esc(f.key)}</td>
          <td>${esc(f.label)}</td>
          <td><span class="badge badge-${f.type === "select" ? "blue" : "gray"}">${esc(f.type)}</span></td>
          <td>${f.type === "select" ? (f.options || []).map(esc).join("、") : "自由输入"}</td>
          <td>${f.required ? "是" : "否"}</td>
          <td>${f.builtin ? "内置列" : "extra(JSON)"}</td>
          <td>${f.readonly ? "只读/自动" : (f.pattern === "chinese" ? "须中文" : "—")}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
}
