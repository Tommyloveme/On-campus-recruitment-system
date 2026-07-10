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

function setMasterProgress(pct, message, detail) {
  const wrap = $("#master-progress");
  const bar = $("#master-progress-bar");
  const msg = $("#master-progress-msg");
  const det = $("#master-progress-detail");
  if (!wrap || !bar || !msg) return;
  wrap.classList.remove("hidden");
  const p = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
  bar.style.width = `${p}%`;
  bar.setAttribute("aria-valuenow", String(p));
  msg.textContent = message || "";
  if (det) det.textContent = detail || "";
}

function hideMasterProgress() {
  $("#master-progress")?.classList.add("hidden");
}

/** 带上传进度的 FormData POST（XHR） */
function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText || "null"); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body);
        return;
      }
      const msg = (body && body.error) || `上传失败 (${xhr.status})`;
      const err = new Error(msg);
      err.status = xhr.status;
      reject(err);
    };
    xhr.onerror = () => reject(new Error("网络异常：上传失败"));
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const pct = Math.round((e.loaded / e.total) * 100);
      if (onProgress) onProgress(pct, e.loaded, e.total);
    };
    xhr.send(formData);
  });
}

function formatBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

async function pollMasterProgress(page, stopFlag) {
  while (!stopFlag.stopped) {
    try {
      const p = await api(`/api/master-import/progress?page=${encodeURIComponent(page)}`);
      if (p && p.status === "running") {
        const detail = p.total
          ? `${p.current || 0}/${p.total}`
            + (p.created || p.updated || p.skipped
              ? ` · +${p.created || 0} ~${p.updated || 0} skip${p.skipped || 0}`
              : "")
          : "";
        setMasterProgress(p.percent || 0, p.message || "处理中…", detail);
      } else if (p && p.status === "done") {
        setMasterProgress(100, p.message || "完成", "");
      } else if (p && p.status === "error") {
        setMasterProgress(p.percent || 0, p.message || "失败", p.error || "");
      }
    } catch (_) { /* 轮询失败不打断主流程 */ }
    await new Promise(r => setTimeout(r, 600));
  }
}

async function openMasterImportModal() {
  let status;
  try {
    status = await fetchMasterImportStatus();
  } catch (e) {
    toast("主数据导入配置未加载", true);
    return;
  }

  const priorityNote = status.merge_priority_note
    || "两表同列名且均有值时，优先采用 Application 主表内容，面试安排管理表仅补空。";

  openModal("主数据表导入", `
    <p style="font-size:12px;color:#64748b;line-height:1.7;margin-bottom:12px">
      支持 <strong>applicationProcessList*.xlsx</strong>（Application 主表）与
      <strong>候选人面试安排管理列表*.xlsx</strong>（面试安排管理表），
      可只上传其中一个；系统按文件名或表头自动识别，两表按<strong>应聘档案编号</strong>关联，
      并与界面手动登记的数据按 <strong>应聘档案编号 → 手机号</strong> 唯一化合并为同一候选人。
    </p>
    <div class="master-priority-note" style="font-size:12px;line-height:1.7;margin-bottom:12px;
         padding:10px 12px;border-radius:8px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e3a8a">
      <strong>合并优先级：</strong>${esc(priorityNote)}
    </div>
    <div class="form-item">
      <label>选择 Excel 文件（可多选，不限制大小）</label>
      <input type="file" id="master-files" accept=".xlsx" multiple>
      <p class="muted" style="font-size:11px;margin-top:6px">大文件导入可能需要数分钟，请保持页面打开并等待进度完成。</p>
    </div>
    <div id="master-progress" class="master-progress hidden">
      <div class="master-progress-track">
        <div id="master-progress-bar" class="master-progress-bar" style="width:0%" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"></div>
      </div>
      <div class="master-progress-text">
        <span id="master-progress-msg">准备中…</span>
        <span id="master-progress-detail" class="muted"></span>
      </div>
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
    `<button class="btn" id="master-cancel" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="master-run" ${status.both_ready ? "" : "disabled"}>导入并刷新</button>`);

  const runBtn = $("#master-run");
  const cancelBtn = $("#master-cancel");
  const fileInput = $("#master-files");
  fileInput.addEventListener("change", () => {
    // 选了新文件即可执行（上传后再刷新）；没选新文件时需已有上传的表
    runBtn.disabled = !(fileInput.files.length || status.both_ready);
  });

  runBtn.addEventListener("click", async () => {
    const page = status.page || "registration";
    runBtn.disabled = true;
    if (cancelBtn) cancelBtn.disabled = true;
    runBtn.textContent = "处理中…";
    const stopFlag = { stopped: false };
    let pollPromise = null;
    try {
      if (fileInput.files.length) {
        setMasterProgress(0, "正在上传文件…", "");
        const fd = new FormData();
        fd.append("page", page);
        for (const f of fileInput.files) fd.append("file", f);
        const up = await uploadWithProgress("/api/master-import/upload", fd, (pct, loaded, total) => {
          // 上传阶段占整体 0–20%
          setMasterProgress(Math.round(pct * 0.2), `正在上传文件… ${pct}%`,
            `${formatBytes(loaded)} / ${formatBytes(total)}`);
        });
        if (up.errors?.length) toast(up.errors.join("；"), true);
        setMasterProgress(20, "上传完成，开始解析与写入…", "");
      } else {
        setMasterProgress(5, "开始解析与写入…", "");
      }

      pollPromise = pollMasterProgress(page, stopFlag);
      const fd2 = new FormData();
      fd2.append("page", page);
      const r = await api("/api/master-import/refresh", { method: "POST", body: fd2 });
      stopFlag.stopped = true;
      if (pollPromise) await pollPromise.catch(() => {});
      setMasterProgress(100,
        `完成：新增 ${r.created}，更新 ${r.updated}${r.skipped ? "，跳过 " + r.skipped : ""}`,
        "");
      toast(`刷新完成：新增 ${r.created}，更新 ${r.updated}${r.skipped ? "，跳过 " + r.skipped : ""}`);
      await new Promise(r => setTimeout(r, 400));
      closeModal();
      stageStates.clear();
      invalidateCandidateCaches();
      if (typeof invalidateDashboardCaches === "function") invalidateDashboardCaches();
      if (state.tab && !TOOL_TABS[state.tab]) renderStageView(state.tab);
    } catch (e) {
      stopFlag.stopped = true;
      if (pollPromise) await pollPromise.catch(() => {});
      setMasterProgress(0, e.message || "导入失败", "");
      toast(e.message, true);
      runBtn.disabled = false;
      if (cancelBtn) cancelBtn.disabled = false;
      runBtn.textContent = "导入并刷新";
    }
  });
}
