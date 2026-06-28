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
    <div class="card log-card">
      <div class="log-head">
        <div>
          <div class="section-title">操作日志</div>
          <p class="log-sub">按时间倒序记录用户操作，便于审计追溯。</p>
        </div>
      </div>
      <div class="log-table-wrap">
        <table class="log-table">
          <thead><tr><th>时间</th><th>类型</th><th>详情</th></tr></thead>
          <tbody id="log-list"><tr><td colspan="3" class="log-empty">加载中…</td></tr></tbody>
        </table>
      </div>
      <div id="log-foot" class="log-foot"></div>
    </div>`;
  const list = $("#log-list");
  const foot = $("#log-foot");
  try {
    const r = await api(`/api/logs?page=${page}`);
    const items = r.items.map(l => {
      const [txt, color] = ACTION_BADGE[l.action] || ["操作", "gray"];
      return `
        <tr>
          <td class="log-time">${esc(l.created_at)}</td>
          <td class="log-type"><span class="badge badge-${color}">${txt}</span></td>
          <td class="log-msg" title="${esc(l.message)}">${esc(l.message)}</td>
        </tr>`;
    }).join("");
    const pages = Math.max(1, Math.ceil(r.total / r.size));
    list.innerHTML = items || `<tr><td colspan="3" class="log-empty">暂无日志</td></tr>`;
    foot.innerHTML = `
      <span class="log-count">${r.total} 条 · 第 ${page}/${pages} 页</span>
      <div class="pager log-pager">
        <button class="btn btn-sm" data-log-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
        <button class="btn btn-sm" data-log-next ${page >= pages ? "disabled" : ""}>下一页</button>
      </div>`;
    foot.querySelector("[data-log-prev]")?.addEventListener("click", () => renderLogs(page - 1));
    foot.querySelector("[data-log-next]")?.addEventListener("click", () => renderLogs(page + 1));
  } catch (e) {
    list.innerHTML = `<tr><td colspan="3" class="log-empty">日志加载失败：${esc(e.message)}</td></tr>`;
    foot.innerHTML = "";
  }
}

/* ---------- 数据备份 ---------- */
async function renderBackups() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可管理数据备份。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card bk-card">
      <div class="bk-head">
        <div>
          <div class="section-title">数据备份与恢复</div>
          <p class="bk-sub">手动创建数据库快照；恢复前会自动保存当前状态。</p>
        </div>
        <button class="btn btn-primary btn-sm" id="bk-now">立即备份</button>
      </div>
      <div class="bk-table-wrap">
        <table class="bk-table">
          <thead><tr>
            <th>备份文件</th><th>时间</th><th>大小</th><th>类型</th><th></th>
          </tr></thead>
          <tbody id="bk-list"><tr><td colspan="5" class="bk-empty">加载中…</td></tr></tbody>
        </table>
      </div>
    </div>`;
  const list = $("#bk-list");
  const load = async () => {
    try {
      const backups = await api("/api/backups");
      list.innerHTML = backups.length
        ? backups.map(b => `
          <tr>
            <td class="mono" title="${esc(b.name)}">${esc(b.name)}</td>
            <td class="bk-time">${esc(b.time)}</td>
            <td class="bk-size">${b.size_kb} KB</td>
            <td><span class="badge badge-${b.manual ? "gray" : "blue"}">${b.manual ? "手动" : "自动"}</span></td>
            <td class="bk-act"><button class="btn btn-sm btn-danger" data-restore="${esc(b.name)}">恢复</button></td>
          </tr>`).join("")
        : `<tr><td colspan="5" class="bk-empty">暂无备份</td></tr>`;
      list.closest(".bk-table-wrap")?.querySelectorAll("[data-restore]").forEach(b =>
        b.addEventListener("click", async () => {
          if (!confirm(`确定恢复到备份「${b.dataset.restore}」？当前数据将被覆盖。`)) return;
          try {
            await api("/api/backups/restore", { method: "POST", json: { name: b.dataset.restore } });
            toast("备份已恢复，请刷新页面");
          } catch (e) { toast(e.message, true); }
        }));
    } catch (e) { list.innerHTML = `<tr><td colspan="5" class="bk-empty">备份加载失败：${esc(e.message)}</td></tr>`; }
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

/* ---------- 字段配置（嵌入权限管理页顶部） ---------- */
async function renderFieldConfigInto(container) {
  if (!container) return;
  container.innerHTML = `<div class="perm-embed-title">附属信息字段配置</div><div id="fc-body">加载中…</div>`;
  let fields = [];
  try {
    const opts = await api("/api/account/options");
    fields = opts.user_fields || [];
  } catch (e) {
    $("#fc-body").innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
    return;
  }
  $("#fc-body").innerHTML = `
    <p class="perm-embed-sub">
      在 <code>config/user_fields.json</code> 中新增字段并定义操作模式（<b>text</b> 自由输入 / <b>select</b> 单选下拉，<code>options</code> 为可选项）。
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
