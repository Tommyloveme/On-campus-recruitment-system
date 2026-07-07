"use strict";

/* 管理看板同级页：操作日志 / 数据备份 / 字段配置（仅系统管理员） */

/* ---------- 操作日志（全量，复用 log-panel 组件） ---------- */
async function renderLogs() {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可查看操作日志。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card log-card">
      <div class="log-head">
        <div class="iv-subnav" style="margin:0">
          <button class="btn btn-sm iv-view-btn active" data-lg-view="list">日志列表</button>
          <button class="btn btn-sm iv-view-btn" data-lg-view="levels">日志权限</button>
        </div>
      </div>
      <div id="log-view-list"><div id="log-panel-root"></div></div>
      <div id="log-view-levels" class="hidden"></div>
    </div>`;
  renderLogPanel($("#log-panel-root"), { pageSize: state.app?.logs_page_size || 30 });

  $("#main").querySelectorAll("[data-lg-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      $("#main").querySelectorAll("[data-lg-view]").forEach(b =>
        b.classList.toggle("active", b === btn));
      const view = btn.dataset.lgView;
      $("#log-view-list").classList.toggle("hidden", view !== "list");
      $("#log-view-levels").classList.toggle("hidden", view !== "levels");
      if (view === "levels") renderLogLevelSettings($("#log-view-levels"));
    });
  });
}

/* 日志权限设置：1 最高（全部可见）… 10 最低（仅常规业务日志） */
async function renderLogLevelSettings(rootEl) {
  rootEl.innerHTML = `<div class="log-empty">加载中…</div>`;
  let users;
  try {
    users = await api("/api/logs/levels");
  } catch (e) {
    rootEl.innerHTML = `<div class="log-empty">加载失败：${esc(e.message)}</div>`;
    return;
  }
  rootEl.innerHTML = `
    <p class="muted" style="font-size:12px;margin:8px 0">
      数字 1-10：1 最高（可见全部日志），10 最低（仅常规业务日志）。管理员默认 1，普通用户默认 10。</p>
    <div class="table-wrap"><table>
      <thead><tr><th>工号</th><th>姓名</th><th>角色</th><th style="width:140px">日志权限</th></tr></thead>
      <tbody>
        ${users.map(u => `
          <tr>
            <td>${esc(u.username)}</td>
            <td>${esc(u.display_name)}</td>
            <td>${esc(u.role_label || u.role)}</td>
            <td><input type="number" min="1" max="10" value="${u.log_level}"
                       data-loglv-uid="${u.id}" style="width:80px"></td>
          </tr>`).join("")}
      </tbody>
    </table></div>`;
  rootEl.querySelectorAll("[data-loglv-uid]").forEach(inp => {
    inp.addEventListener("change", async () => {
      const v = parseInt(inp.value, 10);
      if (!(v >= 1 && v <= 10)) { toast("日志权限须为 1-10", true); return; }
      try {
        await api(`/api/logs/levels/${inp.dataset.loglvUid}`, { method: "PUT", json: { log_level: v } });
        toast("已保存");
      } catch (e) { toast(e.message, true); }
    });
  });
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
        <div class="iv-subnav" style="margin:0">
          <button class="btn btn-sm iv-view-btn active" data-bk-view="list">备份列表</button>
          <button class="btn btn-sm iv-view-btn" data-bk-view="logs">日志</button>
        </div>
        <button class="btn btn-primary btn-sm" id="bk-now" title="恢复前会自动保存当前状态">立即备份</button>
      </div>
      <div id="bk-view-list">
        <div class="bk-table-wrap">
          <table class="bk-table">
            <thead><tr>
              <th>备份文件</th><th>时间</th><th>大小</th><th>类型</th><th></th>
            </tr></thead>
            <tbody id="bk-list"><tr><td colspan="5" class="bk-empty">加载中…</td></tr></tbody>
          </table>
        </div>
      </div>
      <div id="bk-view-logs" class="hidden"></div>
    </div>`;
  let bkLogsInit = false;
  document.querySelectorAll("[data-bk-view]").forEach(btn =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-bk-view]").forEach(b => b.classList.toggle("active", b === btn));
      const logs = btn.dataset.bkView === "logs";
      $("#bk-view-list").classList.toggle("hidden", logs);
      $("#bk-view-logs").classList.toggle("hidden", !logs);
      if (logs && !bkLogsInit) { bkLogsInit = true; renderLogPanel($("#bk-view-logs"), { module: "backups" }); }
    }));
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
    <p class="perm-embed-sub">字段定义于 <code>config/user_fields.json</code>，改后刷新生效。</p>
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
