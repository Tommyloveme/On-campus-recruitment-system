/* 主数据表双文件导入：Application*.xlsx + 候选人管理*.xlsx */
"use strict";

async function fetchMasterImportStatus() {
  const page = state.masterImport?.page || "registration";
  return api(`/api/master-import/config?page=${page}`);
}

function masterFileStatusHtml(sources) {
  if (!sources?.length) return "";
  return sources.map(s => `
    <div class="master-file-row">
      <span class="master-file-pattern">${esc(s.pattern || s.label)}</span>
      <span class="badge badge-${s.ready ? "green" : "gray"}">${s.ready ? "已上传" : "未上传"}</span>
      ${s.ready ? `<span class="master-file-name" title="${esc(s.original_name || "")}">${esc(s.original_name || "")}</span>` : ""}
    </div>`).join("");
}

async function openMasterImportModal() {
  let status;
  try {
    status = await fetchMasterImportStatus();
  } catch (e) {
    toast("主数据导入配置未加载", true);
    return;
  }
  const sources = status.sources || [];
  const patterns = status.file_patterns || {};
  const appPat = patterns.application || "Application*.xlsx";
  const mgmtPat = patterns.candidate_mgmt || "候选人管理*.xlsx";

  openModal("主数据表导入", `
    <p style="font-size:12px;color:#64748b;line-height:1.8;margin-bottom:12px">
      默认导入两张 Excel：<strong>${esc(appPat)}</strong> 与 <strong>${esc(mgmtPat)}</strong>。
      列映射见 <code>config/master_import/registration/field_mappings.json</code>（界面字段名与 Excel 表头可不一致）。
      两张表通过<strong>简历编号</strong>关联；与系统候选人通过<strong>手机号</strong>匹配合并。
      自主数据导入的候选人、电话、学历、毕业院校、专业等配置字段刷新后不可编辑。
      若登记手机号与主表不一致，请先编辑改为主表手机号后再刷新。
    </p>
    <div class="master-status card" style="padding:12px;margin-bottom:12px;background:#f8fafc">
      <div style="font-size:12px;font-weight:600;margin-bottom:8px;color:#475569">当前文件状态</div>
      <div id="master-status-list">${masterFileStatusHtml(sources)}</div>
      ${status.last_refresh ? `<p style="font-size:11px;color:#94a3b8;margin-top:8px">上次刷新：${esc(status.last_refresh)}（新增 ${status.last_refresh_stats?.created ?? 0}，更新 ${status.last_refresh_stats?.updated ?? 0}）</p>` : ""}
    </div>
    <div class="form-item">
      <label>${esc(appPat)}</label>
      <input type="file" id="master-file-application" accept=".xlsx" data-key="application">
    </div>
    <div class="form-item">
      <label>${esc(mgmtPat)}</label>
      <input type="file" id="master-file-candidate_mgmt" accept=".xlsx" data-key="candidate_mgmt">
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn" id="master-upload">上传文件</button>
     <button class="btn btn-primary" id="master-refresh" ${status.both_ready ? "" : "disabled"}>刷新全部候选人</button>`);

  async function reloadStatus() {
    const st = await fetchMasterImportStatus();
    $("#master-status-list").innerHTML = masterFileStatusHtml(st.sources);
    $("#master-refresh").disabled = !st.both_ready;
    return st;
  }

  $("#master-upload").addEventListener("click", async () => {
    const fd = new FormData();
    fd.append("page", status.page || "registration");
    const fApp = $("#master-file-application").files[0];
    const fMgmt = $("#master-file-candidate_mgmt").files[0];
    if (!fApp && !fMgmt) { toast("请至少选择一个文件", true); return; }
    if (fApp) fd.append("application", fApp);
    if (fMgmt) fd.append("candidate_mgmt", fMgmt);
    try {
      const r = await api("/api/master-import/upload", { method: "POST", body: fd });
      if (r.errors?.length) toast(r.errors.join("；"), true);
      toast(`已上传 ${r.uploaded.length} 个文件`);
      await reloadStatus();
    } catch (e) { toast(e.message, true); }
  });

  $("#master-refresh").addEventListener("click", async () => {
    const fd = new FormData();
    fd.append("page", status.page || "registration");
    try {
      $("#master-refresh").disabled = true;
      const r = await api("/api/master-import/refresh", { method: "POST", body: fd });
      toast(`刷新完成：新增 ${r.created}，更新 ${r.updated}${r.skipped ? "，跳过 " + r.skipped : ""}`);
      await reloadStatus();
      closeModal();
      stageStates.clear();
      if (state.tab && !TOOL_TABS[state.tab]) renderStageView(state.tab);
    } catch (e) {
      toast(e.message, true);
      $("#master-refresh").disabled = false;
    }
  });
}
