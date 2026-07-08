/* 主数据表导入：applicationProcessList*.xlsx + 候选人面试安排管理列表*.xlsx
 * 单一入口：选择文件（自动识别数据源）→「导入并刷新」一步完成；
 * 也可不选新文件，直接基于已上传的表重新刷新合并。 */
"use strict";

async function fetchMasterImportStatus() {
  const page = state.masterImport?.page || "registration";
  return api(`/api/master-import/config?page=${page}`);
}

function masterFileStatusHtml(sources) {
  if (!sources?.length) return "";
  return sources.map(s => `
    <div class="master-file-row">
      <span class="badge badge-${s.ready ? "green" : "gray"}">${s.ready ? "已上传" : "未上传"}</span>
      <span class="master-file-pattern">${esc(s.label || s.pattern)}</span>
      ${s.ready
        ? `<span class="master-file-name" title="${esc(s.original_name || "")}">${esc(s.original_name || "")}</span>
           <span class="muted" style="font-size:11px">${esc(s.uploaded_at || "")}</span>`
        : `<span class="muted" style="font-size:11px">${esc(s.pattern || "")}</span>`}
    </div>`).join("");
}

function masterMappingHtml(status) {
  const fields = status.field_mappings?.fields || [];
  const srcKeys = (status.sources || []).map(s => s.key);
  const srcLabels = Object.fromEntries((status.sources || []).map(s => [s.key, s.label]));
  return `
    <div class="table-wrap" style="max-height:260px;overflow:auto">
      <table class="fc-table" style="font-size:12px">
        <thead><tr>
          <th>内部字段</th>
          ${srcKeys.map(k => `<th>${esc(srcLabels[k] || k)} 列名</th>`).join("")}
          <th>导入后锁定</th>
        </tr></thead>
        <tbody>
          ${fields.map(f => `
            <tr>
              <td>${esc(f.ui_label || f.field_key)}${f.ui_label ? "" : ` <span class="muted">(隐藏)</span>`}</td>
              ${srcKeys.map(k => `<td>${esc(f.excel_columns?.[k] || "—")}</td>`).join("")}
              <td>${f.lock_on_import ? `<span class="badge badge-yellow">锁定</span>` : "—"}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p class="muted" style="font-size:11px;margin:6px 0 0">
      映射配置：<code>config/master_import/registration/field_mappings.json</code>，未映射的 Excel 列按表头原文自动入库。</p>`;
}

async function openMasterImportModal() {
  let status;
  try {
    status = await fetchMasterImportStatus();
  } catch (e) {
    toast("主数据导入配置未加载", true);
    return;
  }

  openModal("主数据表导入", `
    <p style="font-size:12px;color:#64748b;line-height:1.7;margin-bottom:12px">
      支持 <strong>applicationProcessList*.xlsx</strong> 与 <strong>候选人面试安排管理列表*.xlsx</strong> 等业务表，
      可只上传其中一个；系统按文件名或表头自动识别，两表按<strong>应聘档案编号</strong>关联，
      并与界面手动登记的数据按 <strong>应聘档案编号 → 手机号</strong> 唯一化合并为同一候选人。
    </p>
    <div class="form-item">
      <label>选择 Excel 文件（可多选）</label>
      <input type="file" id="master-files" accept=".xlsx" multiple>
    </div>
    <div class="master-status card" style="padding:12px;margin-bottom:12px;background:#f8fafc">
      <div style="font-size:12px;font-weight:600;margin-bottom:8px;color:#475569">已上传的数据表</div>
      <div id="master-status-list">${masterFileStatusHtml(status.sources)}</div>
      <p id="master-last-refresh" style="font-size:11px;color:#94a3b8;margin:8px 0 0${status.last_refresh ? "" : ";display:none"}">
        上次刷新：${esc(status.last_refresh || "")}（新增 ${status.last_refresh_stats?.created ?? 0}，更新 ${status.last_refresh_stats?.updated ?? 0}）</p>
    </div>
    <details>
      <summary style="cursor:pointer;font-size:12px;color:#475569;font-weight:600">查看字段映射（外部列 ↔ 内部字段）</summary>
      <div style="margin-top:8px">${masterMappingHtml(status)}</div>
    </details>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="master-run" ${status.both_ready ? "" : "disabled"}>导入并刷新</button>`);

  const runBtn = $("#master-run");
  const fileInput = $("#master-files");
  fileInput.addEventListener("change", () => {
    // 选了新文件即可执行（上传后再刷新）；没选新文件时需已有上传的表
    runBtn.disabled = !(fileInput.files.length || status.both_ready);
  });

  runBtn.addEventListener("click", async () => {
    const page = status.page || "registration";
    runBtn.disabled = true;
    runBtn.textContent = "处理中…";
    try {
      if (fileInput.files.length) {
        const fd = new FormData();
        fd.append("page", page);
        for (const f of fileInput.files) fd.append("file", f);
        const up = await api("/api/master-import/upload", { method: "POST", body: fd });
        if (up.errors?.length) toast(up.errors.join("；"), true);
      }
      const fd2 = new FormData();
      fd2.append("page", page);
      const r = await api("/api/master-import/refresh", { method: "POST", body: fd2 });
      toast(`刷新完成：新增 ${r.created}，更新 ${r.updated}${r.skipped ? "，跳过 " + r.skipped : ""}`);
      closeModal();
      stageStates.clear();
      if (state.tab && !TOOL_TABS[state.tab]) renderStageView(state.tab);
    } catch (e) {
      toast(e.message, true);
      runBtn.disabled = false;
      runBtn.textContent = "导入并刷新";
    }
  });
}
