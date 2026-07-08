/* 阶段视图模块：各流程标签页共用的候选人表格 CRUD / 导入导出 */
"use strict";

const stageStates = new Map();

function defaultStageSort(stageKey) {
  const cfg = stageTableCfg(stageKey).default_sort;
  if (cfg && cfg.key) return { key: cfg.key, dir: cfg.dir === -1 ? -1 : 1 };
  if (stageKey === "registration") return { key: "registration_time", dir: -1 };
  return null;
}

function getStageState(stageKey) {
  if (!stageStates.has(stageKey)) {
    stageStates.set(stageKey, {
      list: [], sort: defaultStageSort(stageKey), selected: new Set(),
      uploadTarget: null, page: 1,
      pageSize: state.app.page_size ?? 15,
      duplicatePhones: null,
      colWidths: {},
      colWidthsTouched: false,
    });
  }
  return stageStates.get(stageKey);
}

async function renderStageView(stageKey) {
  state.tab = stageKey;
  const meta = state.stages.find(s => s.key === stageKey);
  const showCalendar = meta.has_interview_calendar;
  getStageState(stageKey);

  const showDashboard = featureAllowed(stageKey, "tab_dashboard");
  const showLogs = featureAllowed(stageKey, "tab_logs");

  $("#main").innerHTML = `
    <div class="page-wrap">
      <div class="card pagehead">
        <div class="pagehead-text">
          <div class="pagehead-title">${esc(meta.label)}</div>
          ${meta.description ? `<div class="pagehead-sub">${esc(meta.description)}</div>` : ""}
        </div>
        <div class="iv-subnav pagehead-tabs">
          <button class="btn btn-sm iv-view-btn active" data-view="list">候选人列表</button>
          ${showCalendar ? `<button class="btn btn-sm iv-view-btn" data-view="calendar">面试日程表</button>` : ""}
          ${showDashboard ? `<button class="btn btn-sm iv-view-btn" data-view="dashboard">数据看板</button>` : ""}
          ${showLogs ? `<button class="btn btn-sm iv-view-btn" data-view="logs">日志</button>` : ""}
        </div>
      </div>
      <div id="stage-content"></div>
    </div>`;

  document.querySelectorAll(".iv-view-btn").forEach(btn =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".iv-view-btn").forEach(b => b.classList.toggle("active", b === btn));
      if (btn.dataset.view === "calendar") renderInterviewCalendar(stageKey);
      else if (btn.dataset.view === "logs") renderLogPanel($("#stage-content"), { module: stageKey });
      else if (btn.dataset.view === "dashboard") renderPivotPanel($("#stage-content"), { stageKey });
      else renderStageList(stageKey);
    }));
  renderStageList(stageKey);
}

function stageUiColumns(stageKey) {
  return stageTableCfg(stageKey).ui_columns || [];
}

/** 列表展示字段：在「候选人」列前注入“流程状态”列（由规则匹配生成，存于 data.流程状态）。 */
function stageListFields(stageKey) {
  const fields = visibleFields(stageKey).slice();
  if (!fields.some(f => f.key === "流程状态" || f.legacy_key === "process_status")) {
    const idx = fields.findIndex(f => f.legacy_key === "name" || f.key === "候选人");
    fields.splice(idx >= 0 ? idx : 0, 0, {
      key: "流程状态", legacy_key: "process_status", label: "流程状态", type: "text",
    });
  }
  return fields;
}

function candHubKey(c) {
  // 与后端 hub_resume_key 保持一致：应聘档案编号 → 简历编号 → 无编号-<手机号>
  const aid = String(c.data["应聘档案编号"] || c.data.application_archive_id || "").trim();
  if (aid) return aid;
  const rid = String(c.data.resume_id || "").trim();
  if (rid) return rid;
  const phone = String(c.data.phone || "").trim();
  return phone ? `无编号-${phone}` : "";
}

async function renderStageList(stageKey) {
  const meta = state.stages.find(s => s.key === stageKey);
  const ss = getStageState(stageKey);
  const fields = stageListFields(stageKey);
  const uiCols = stageUiColumns(stageKey);
  const showResume = stageKey === "registration";
  const canAdd = typeof moduleWritable === "function" && moduleWritable(stageKey) && meta.can_create
    && featureAllowed(stageKey, "btn_add");
  const showMasterImport = stageKey === "registration" && canAdd && featureAllowed(stageKey, "btn_master_import");
  const showExportExcel = featureAllowed(stageKey, "btn_export_excel");
  const showExportResume = showResume && featureAllowed(stageKey, "btn_export_resume");
  const showBatchDelete = canBatchDelete() && stageKey === "registration" && featureAllowed(stageKey, "btn_batch_delete");

  const headCells = fields.map(f =>
    `<th class="sortable" data-sortkey="${f.key}" title="点击排序">${esc(f.label)}<span class="sort-arrow" data-arrow="${f.key}"></span></th>`
  ).join("") + uiCols.map(c =>
    `<th title="界面专属列（存于汇总总表）">${esc(c.label)} <span class="ui-col-mark">UI</span></th>`
  ).join("");
  const filterCells = fields.map(f => {
    if (f.type === "select") {
      const opts = (f.options || []).map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
      return `<th><select data-filter="${f.key}"><option value="">全部</option>${opts}</select></th>`;
    }
    return `<th><input type="text" data-filter="${f.key}" placeholder="筛选"></th>`;
  }).join("") + uiCols.map(() => "<th></th>").join("");

  const root = $("#stage-content") || $("#main");
  root.innerHTML = `
    <div class="toolbar">
      <input type="text" id="cand-search" placeholder="全局搜索：姓名 / 电话 / 部门 / 任意字段…">
      <button class="btn btn-sm" id="btn-clear-filter">清空筛选</button>
      <div class="spacer"></div>
      ${showBatchDelete ? `<button class="btn btn-danger" id="btn-batch-del" disabled>删除选中 (0)</button>` : ""}
      ${showExportExcel ? `<button class="btn" id="btn-export-excel" disabled>导出选中Excel (0)</button>` : ""}
      ${showExportResume ? `<button class="btn" id="btn-export-resume" disabled>导出选中简历 (0)</button>` : ""}
      ${canAdd ? `<button class="btn btn-primary" id="btn-add">+ 新增候选人</button>` : ""}
      ${showMasterImport ? `<button class="btn btn-primary" id="btn-master-import">主数据表导入</button>` : ""}
    </div>
    <div id="cand-table" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" id="sel-all" title="全选当前筛选结果"></th>
            ${headCells}
            ${showResume ? "<th>简历</th>" : ""}<th>操作</th>
          </tr>
          <tr class="filter-row">
            <th></th>${filterCells}${showResume ? "<th></th>" : ""}<th></th>
          </tr>
        </thead>
        <tbody id="cand-tbody"></tbody>
      </table>
    </div>
    <div id="cand-pager" class="pager-bar"></div>
    ${showResume ? `<input type="file" id="resume-input" style="display:none">` : ""}`;

  if (showMasterImport) $("#btn-master-import").addEventListener("click", openMasterImportModal);
  if (canAdd && $("#btn-add")) {
    $("#btn-add").addEventListener("click", () => openCandidateModal(null, stageKey));
  }
  if (showBatchDelete) $("#btn-batch-del").addEventListener("click", () => batchDeleteSelected(stageKey));
  if (showExportResume) $("#btn-export-resume").addEventListener("click", exportSelectedResumes);
  if (showResume) $("#resume-input").addEventListener("change", onResumeFilePicked);
  $("#btn-export-excel")?.addEventListener("click", () => exportSelectedExcel(stageKey));
  enableColumnResize(stageKey);
  const onFilterChange = () => { ss.page = 1; renderCandidateRows(stageKey); };
  $("#cand-search").addEventListener("input", debounce(onFilterChange, 250));
  $("#btn-clear-filter").addEventListener("click", () => {
    $("#cand-search").value = "";
    document.querySelectorAll("[data-filter]").forEach(el => { el.value = ""; });
    ss.sort = defaultStageSort(stageKey);
    document.querySelectorAll("[data-arrow]").forEach(el => {
      el.textContent = (ss.sort && ss.sort.key === el.dataset.arrow)
        ? (ss.sort.dir === 1 ? " ↑" : " ↓") : "";
    });
    onFilterChange();
  });
  document.querySelectorAll("[data-filter]").forEach(el =>
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", debounce(onFilterChange, 250)));
  document.querySelectorAll(".sortable").forEach(th =>
    th.addEventListener("click", () => toggleSort(stageKey, th.dataset.sortkey)));
  $("#sel-all").addEventListener("change", e => {
    const ids = filteredCandidates(stageKey).map(c => c.id);
    if (e.target.checked) ids.forEach(id => ss.selected.add(id));
    else ids.forEach(id => ss.selected.delete(id));
    renderCandidateRows(stageKey);
  });

  if (ss.sort) {
    document.querySelectorAll("[data-arrow]").forEach(el => {
      el.textContent = ss.sort.key === el.dataset.arrow
        ? (ss.sort.dir === 1 ? " ↑" : " ↓") : "";
    });
  }

  await loadCandidateTable(stageKey);
  applyCandFrozenColumns(stageKey);
}

async function loadCandidateTable(stageKey) {
  const ss = getStageState(stageKey);
  // 各流程列表固定按当前流程加载（不再提供「仅登记阶段 / 仅当前流程」开关）
  ss.list = await api(`/api/candidates?stage=${stageKey}`);
  if (stageUiColumns(stageKey).length) {
    try {
      ss.uiValues = (await api(`/api/data-hub/ui-values?tab=${stageKey}`)).values || {};
    } catch { ss.uiValues = {}; }
  }
  if (stageKey === "registration") {
    const all = await api("/api/candidates");
    ss.allCandidates = all;
    ss.duplicatePhones = computeDuplicatePhones(all);
  } else {
    ss.allCandidates = null;
    ss.duplicatePhones = null;
  }
  const ids = new Set(ss.list.map(c => c.id));
  ss.selected.forEach(id => { if (!ids.has(id)) ss.selected.delete(id); });
  renderCandidateRows(stageKey);
  autoFitCandColumns(stageKey);
  applyCandFrozenColumns(stageKey);
}

function filteredCandidates(stageKey) {
  const ss = getStageState(stageKey);
  let list = ss.list;
  const q = ($("#cand-search")?.value || "").trim().toLowerCase();
  if (q) {
    list = list.filter(c =>
      Object.values(c.data).some(v => String(v).toLowerCase().includes(q)));
  }
  document.querySelectorAll("[data-filter]").forEach(el => {
    const val = el.value.trim();
    if (!val) return;
    const key = el.dataset.filter;
    if (el.tagName === "SELECT") {
      list = list.filter(c => candidateFilterValue(c, key) === val);
    } else {
      const lv = val.toLowerCase();
      list = list.filter(c => String(candidateFilterValue(c, key)).toLowerCase().includes(lv));
    }
  });
  if (ss.sort) {
    const { key, dir } = ss.sort;
    list = [...list].sort((a, b) => compareCandidateField(a, b, key, dir));
  }
  return list;
}

function compareCandidateField(a, b, key, dir) {
  let av = candidateCellValue(a, { key }) ?? a.data[key] ?? "";
  let bv = candidateCellValue(b, { key }) ?? b.data[key] ?? "";
  av = String(av).trim();
  bv = String(bv).trim();
  if (!av && !bv) return 0;
  if (!av) return 1;
  if (!bv) return -1;
  const an = Number(av), bn = Number(bv);
  if (av !== "" && bv !== "" && !Number.isNaN(an) && !Number.isNaN(bn)) {
    return (an - bn) * dir;
  }
  return av.localeCompare(bv, "zh-CN", { numeric: true }) * dir;
}

function toggleSort(stageKey, key) {
  const ss = getStageState(stageKey);
  if (!ss.sort || ss.sort.key !== key) ss.sort = { key, dir: 1 };
  else if (ss.sort.dir === 1) ss.sort = { key, dir: -1 };
  else ss.sort = null;
  document.querySelectorAll("[data-arrow]").forEach(el => {
    el.textContent = (ss.sort && ss.sort.key === el.dataset.arrow)
      ? (ss.sort.dir === 1 ? " ↑" : " ↓") : "";
  });
  renderCandidateRows(stageKey);
}

function candTerminated(c) {
  return (c.data["流程终止"] || c.data.process_terminated || "") === "是";
}

function candidateCellValue(c, f) {
  // 列表展示：拓源人/接口人读已存姓名字段（不实时查用户表）；编辑表单仍用工号
  if (f.key === "sourcer" || f.legacy_key === "sourcer") {
    return c.data["拓源人姓名"] || c.data.sourcer_name || c.data["拓源人"] || c.data.sourcer || "";
  }
  if (f.key === "interface_person" || f.legacy_key === "interface_person") {
    return c.data["接口人姓名"] || c.data.interface_person_name
      || c.data["接口人"] || c.data.interface_person || "";
  }
  return c.data[f.key];
}

function candidateFilterValue(c, key) {
  if (key === "sourcer" || key === "拓源人") {
    return c.data["拓源人姓名"] || c.data.sourcer_name || c.data["拓源人"] || c.data.sourcer || "";
  }
  if (key === "interface_person" || key === "接口人") {
    return c.data["接口人姓名"] || c.data.interface_person_name
      || c.data["接口人"] || c.data.interface_person || "";
  }
  return c.data[key] || "";
}

function resumeCellHtml(c) {
  const editable = canEdit();
  if (c.resume_name) {
    return `
      <span class="resume-actions" title="${esc(c.resume_name)}">
        <button class="btn btn-sm" data-resprev="${c.id}">预览</button>
        <button class="btn btn-sm" data-resdl="${c.id}">下载</button>
        ${editable ? `<button class="btn btn-sm" data-resup="${c.id}">更换</button>` : ""}
        ${canDelete() ? `<button class="btn btn-sm btn-danger" data-resdel="${c.id}">删除</button>` : ""}
      </span>`;
  }
  return editable
    ? `<button class="btn btn-sm" data-resup="${c.id}">上传</button>`
    : `<span style="color:#cbd5e1">—</span>`;
}

function renderCandidateRows(stageKey) {
  const tbody = $("#cand-tbody");
  if (!tbody) return;
  const ss = getStageState(stageKey);
  const fields = stageListFields(stageKey);
  const uiCols = stageUiColumns(stageKey);
  const showResume = stageKey === "registration";
  const list = filteredCandidates(stageKey);
  const colCount = 3 + fields.length + uiCols.length + (showResume ? 1 : 0);
  const uiEditable = uiCols.length && moduleWritable(stageKey);
  const canFlow = (state.stageFlow?.stages || []).includes(stageKey) &&
    state.stageFlow?.can_transition && featureAllowed(stageKey, "btn_stage_transition");
  const canTerminate = stageKey === "registration" && canEdit() &&
    featureAllowed(stageKey, "btn_terminate");

  const total = list.length;
  const pages = ss.pageSize > 0 ? Math.max(1, Math.ceil(total / ss.pageSize)) : 1;
  ss.page = Math.min(Math.max(1, ss.page), pages);
  const pageList = ss.pageSize > 0
    ? list.slice((ss.page - 1) * ss.pageSize, ss.page * ss.pageSize)
    : list;

  if (!pageList.length) {
    tbody.innerHTML = `<tr><td colspan="${colCount}" class="empty">没有符合条件的候选人</td></tr>`;
  } else {
    tbody.innerHTML = pageList.map(c => `
      <tr>
        <td class="col-check"><input type="checkbox" data-sel="${c.id}" ${ss.selected.has(c.id) ? "checked" : ""}></td>
        ${fields.map(f => {
          let inner;
          if (f.key === "progress") {
            const full = c.data.progress || "";
            inner = multilineCellHtml(full);
            if (canEdit())
              inner += ` <button class="btn btn-sm" data-prog="${c.id}" title="更新进展">更新</button>`;
          } else if (f.key === "registration_remark") {
            inner = multilineCellHtml(c.data.registration_remark || "");
          } else if (f.key === "registration_source" && c.data.registration_source === "其他") {
            const custom = (c.data.registration_source_custom || "").trim();
            inner = cellHtml(f, custom ? `其他：${custom}` : "其他");
          } else if (f.key === "phone" && stageKey === "registration" && ss.duplicatePhones &&
            ss.duplicatePhones.has(normalizeCandidatePhone(c.data.phone))) {
            inner = `<span class="cell-phone-dup">${esc(candidateCellValue(c, f) || "")}</span>`;
          } else if (f.key === "流程状态" && candTerminated(c)) {
            inner = `<span class="badge badge-red" title="已流程终止，可在候选人登记页恢复">流程终止</span>`;
          } else {
            inner = cellHtml(f, candidateCellValue(c, f));
          }
          return `<td>${inner}</td>`;
        }).join("")}
        ${uiCols.map(col => {
          const hk = candHubKey(c);
          const val = hk ? ((ss.uiValues || {})[hk] || {})[col.key] ?? "" : "";
          if (!uiEditable || !hk) return `<td>${esc(val) || '<span style="color:#cbd5e1">—</span>'}</td>`;
          const itype = col.format === "date" ? "date" : (col.format === "number" ? "number" : "text");
          return `<td><input type="${itype}" class="ui-col-input" data-uicol="${col.key}" data-uikey="${esc(hk)}" value="${esc(val)}"></td>`;
        }).join("")}
        ${showResume ? `<td>${resumeCellHtml(c)}</td>` : ""}
        <td>
          ${canEdit()
            ? `<button class="btn btn-sm" data-edit="${c.id}">编辑</button>` +
              (canDelete() && stageKey === "registration"
                ? `<button class="btn btn-sm btn-danger" data-del="${c.id}">删除</button>` : "")
            : `<span style="color:#94a3b8;font-size:12px">只读</span>`}
          ${canTerminate ? (candTerminated(c)
            ? `<button class="btn btn-sm" data-term-restore="${c.id}" title="恢复到终止前的状态（按规则/手动状态重新判定）">恢复</button>`
            : `<button class="btn btn-sm btn-danger" data-terminate="${c.id}" title="终止该候选人的招聘流程（可随时恢复）">终止</button>`) : ""}
          ${canFlow && !candTerminated(c) ? `
            <span class="flow-btns" title="手动流转（写入手动状态，优先于自动判定）">
              <button class="btn btn-sm" data-flowprev="${c.id}" title="退回上一流程">←退回</button>
              <button class="btn btn-sm" data-flownext="${c.id}" title="切换到下一流程">推进→</button>
              ${c.data.manual_stage ? `<button class="btn btn-sm" data-flowauto="${c.id}" title="清除手动状态，恢复按规则自动判定">自动</button>` : ""}
            </span>` : ""}
        </td>
      </tr>`).join("");
  }

  tbody.querySelectorAll("[data-sel]").forEach(cb =>
    cb.addEventListener("change", () => {
      const id = +cb.dataset.sel;
      cb.checked ? ss.selected.add(id) : ss.selected.delete(id);
      updateSelectionUI(stageKey, list);
    }));
  tbody.querySelectorAll("[data-edit]").forEach(b =>
    b.addEventListener("click", () =>
      openCandidateModal(ss.list.find(c => c.id === +b.dataset.edit), stageKey)));
  tbody.querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () =>
      deleteCandidate(ss.list.find(c => c.id === +b.dataset.del), stageKey)));
  if (showResume) {
    tbody.querySelectorAll("[data-resdl]").forEach(b =>
      b.addEventListener("click", () => { location.href = `/api/candidates/${b.dataset.resdl}/resume`; }));
    tbody.querySelectorAll("[data-resup]").forEach(b =>
      b.addEventListener("click", () => {
        ss.uploadTarget = +b.dataset.resup;
        $("#resume-input").value = "";
        $("#resume-input").click();
      }));
    tbody.querySelectorAll("[data-resdel]").forEach(b =>
      b.addEventListener("click", () => deleteResume(ss.list.find(c => c.id === +b.dataset.resdel), stageKey)));
    tbody.querySelectorAll("[data-resprev]").forEach(b =>
      b.addEventListener("click", () => window.open(`/api/candidates/${b.dataset.resprev}/resume/preview`, "_blank")));
  }
  tbody.querySelectorAll("[data-prog]").forEach(b =>
    b.addEventListener("click", () => openProgressModal(ss.list.find(c => c.id === +b.dataset.prog), stageKey)));

  if (uiEditable) {
    tbody.querySelectorAll(".ui-col-input").forEach(inp =>
      inp.addEventListener("change", async () => {
        try {
          await api("/api/data-hub/ui-value", { method: "PUT", json: {
            tab: stageKey, resume_key: inp.dataset.uikey,
            field_key: inp.dataset.uicol, value: inp.value,
          } });
          ss.uiValues = ss.uiValues || {};
          (ss.uiValues[inp.dataset.uikey] = ss.uiValues[inp.dataset.uikey] || {})[inp.dataset.uicol] = inp.value;
          inp.classList.add("ui-col-saved");
          setTimeout(() => inp.classList.remove("ui-col-saved"), 800);
        } catch (e) { alert(e.message || "保存失败"); }
      }));
  }
  if (canFlow) {
    const doFlow = async (id, direction) => {
      try {
        await api(`/api/candidates/${id}/stage-transition`, { method: "POST", json: { direction } });
        await loadCandidateTable(stageKey);
      } catch (e) { alert(e.message || "流转失败"); }
    };
    tbody.querySelectorAll("[data-flownext]").forEach(b =>
      b.addEventListener("click", () => doFlow(+b.dataset.flownext, "next")));
    tbody.querySelectorAll("[data-flowprev]").forEach(b =>
      b.addEventListener("click", () => doFlow(+b.dataset.flowprev, "prev")));
    tbody.querySelectorAll("[data-flowauto]").forEach(b =>
      b.addEventListener("click", () => doFlow(+b.dataset.flowauto, "auto")));
  }

  const doTerminate = async (id, action) => {
    try {
      const r = await api(`/api/candidates/${id}/terminate`, { method: "POST", json: { action } });
      toast(action === "terminate" ? "已终止流程（可随时恢复）"
        : `已恢复到终止前状态（${(state.stages.find(s => s.key === r.current_stage) || {}).label || r.current_stage}）`);
      await loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  };
  tbody.querySelectorAll("[data-terminate]").forEach(b =>
    b.addEventListener("click", () => {
      const c = pageList.find(x => x.id === +b.dataset.terminate);
      if (confirm(`确定终止候选人「${c?.data?.name || ""}」的招聘流程？\n终止后冻结在当前阶段、不再流转，可随时点「恢复」回到终止前状态。`)) {
        doTerminate(+b.dataset.terminate, "terminate");
      }
    }));
  tbody.querySelectorAll("[data-term-restore]").forEach(b =>
    b.addEventListener("click", () => doTerminate(+b.dataset.termRestore, "restore")));

  renderPager(stageKey, total, pages);
  updateSelectionUI(stageKey, list);
  applyCandColWidths(getStageState(stageKey));
}

function measureTextWidth(text, font) {
  const canvas = measureTextWidth._c || (measureTextWidth._c = document.createElement("canvas"));
  const ctx = canvas.getContext("2d");
  ctx.font = font || "600 13px system-ui, -apple-system, 'Segoe UI', sans-serif";
  return ctx.measureText(String(text ?? "")).width;
}

function candFieldDisplayText(c, f, stageKey, ss) {
  if (f.key === "registration_remark") {
    return ((c.data.registration_remark || "").split("\n")[0] || "").trim();
  }
  if (f.key === "registration_source" && c.data.registration_source === "其他") {
    const custom = (c.data.registration_source_custom || "").trim();
    return custom ? `其他：${custom}` : "其他";
  }
  if (f.key === "phone" && stageKey === "registration" && ss.duplicatePhones &&
    ss.duplicatePhones.has(normalizeCandidatePhone(c.data.phone))) {
    return String(candidateCellValue(c, f) || "");
  }
  const v = candidateCellValue(c, f);
  if (v === "" || v == null) return "—";
  if (f.option_labels && f.option_labels[v]) return f.option_labels[v];
  return String(v);
}

function applyCandColWidths(ss) {
  let styleEl = $("#col-width-style");
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "col-width-style";
    document.head.appendChild(styleEl);
  }
  if (!Object.keys(ss.colWidths || {}).length) return;
  styleEl.textContent = Object.entries(ss.colWidths).map(([i, w]) =>
    `#cand-table th:nth-child(${i}), #cand-table td:nth-child(${i}) { width:${w}px; min-width:${w}px; }
     #cand-table td:nth-child(${i}) .clip { max-width:${Math.max(40, w - 24)}px; }`).join("\n");
  const table = $("#cand-table table");
  if (table) {
    const sum = Object.values(ss.colWidths).reduce((a, b) => a + b, 0);
    table.style.minWidth = `${sum}px`;
  }
}

function autoFitCandColumns(stageKey) {
  const ss = getStageState(stageKey);
  if (ss.colWidthsTouched) {
    applyCandColWidths(ss);
    return;
  }
  const fields = stageListFields(stageKey);
  const showResume = stageKey === "registration";
  const list = ss.list || [];
  const widths = {};
  let colIdx = 1;
  widths[colIdx++] = 40;
  fields.forEach(f => {
    let maxW = measureTextWidth(f.label) + 44;
    list.forEach(c => {
      maxW = Math.max(maxW, measureTextWidth(candFieldDisplayText(c, f, stageKey, ss), "13px system-ui, sans-serif") + 28);
    });
    widths[colIdx] = Math.min(480, Math.max(64, Math.ceil(maxW)));
    colIdx++;
  });
  stageUiColumns(stageKey).forEach(() => { widths[colIdx++] = 150; });
  if (showResume) widths[colIdx++] = 148;
  const hasFlow = (state.stageFlow?.stages || []).includes(stageKey) && state.stageFlow?.can_transition;
  const hasTerm = stageKey === "registration" && canEdit() && featureAllowed(stageKey, "btn_terminate");
  widths[colIdx] = 108 + (hasFlow ? 128 : 0) + (hasTerm ? 52 : 0);
  ss.colWidths = widths;
  applyCandColWidths(ss);
}

function renderPager(stageKey, total, pages) {
  const ss = getStageState(stageKey);
  const sizes = state.app.page_size_options || [15, 30, 50, 100, 0];
  if (!sizes.includes(ss.pageSize)) sizes.unshift(ss.pageSize);
  $("#cand-pager").innerHTML = `
    <span>共 ${total} 人</span>
    <label>每页
      <select id="page-size">
        ${sizes.map(s => `<option value="${s}" ${s === ss.pageSize ? "selected" : ""}>${s === 0 ? "全部" : s}</option>`).join("")}
      </select>
    </label>
    <button class="btn btn-sm" id="page-prev" ${ss.page <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${ss.page} / ${pages} 页</span>
    <button class="btn btn-sm" id="page-next" ${ss.page >= pages ? "disabled" : ""}>下一页</button>`;
  $("#page-size").addEventListener("change", e => {
    ss.pageSize = +e.target.value;
    ss.page = 1;
    renderCandidateRows(stageKey);
  });
  $("#page-prev").addEventListener("click", () => { ss.page--; renderCandidateRows(stageKey); });
  $("#page-next").addEventListener("click", () => { ss.page++; renderCandidateRows(stageKey); });
}

function updateSelectionUI(stageKey, list) {
  const ss = getStageState(stageKey);
  const n = ss.selected.size;
  const btnE = $("#btn-export-excel");
  const btnR = $("#btn-export-resume");
  const btnD = $("#btn-batch-del");
  if (btnE) {
    btnE.textContent = `导出选中Excel (${n})`;
    btnE.disabled = n === 0;
  }
  if (btnR) {
    btnR.textContent = `导出选中简历 (${n})`;
    btnR.disabled = n === 0;
  }
  if (btnD) {
    btnD.textContent = `删除选中 (${n})`;
    btnD.disabled = n === 0;
  }
  const all = $("#sel-all");
  if (all) all.checked = list.length > 0 && list.every(c => ss.selected.has(c.id));
  applyCandFrozenColumns(stageKey);
}

function applyCandFrozenColumns(stageKey) {
  const table = $("#cand-table table");
  if (!table) return;
  const frozenCount = Math.max(0, stageTableCfg(stageKey).frozen_column_count || 0);
  const headerRow = table.querySelector("thead tr:first-child");
  if (!headerRow) return;
  const headerCells = [...headerRow.children];
  if (frozenCount <= 0) {
    table.querySelectorAll(".cand-frozen, .cand-frozen-last").forEach(cell => {
      cell.classList.remove("cand-frozen", "cand-frozen-last");
      cell.style.left = "";
    });
    return;
  }
  const offsets = [];
  let left = 0;
  for (let i = 0; i < headerCells.length; i++) {
    if (i < frozenCount) {
      offsets[i] = left;
      left += headerCells[i].offsetWidth;
    }
  }
  table.querySelectorAll("tr").forEach(row => {
    [...row.children].forEach((cell, i) => {
      cell.classList.remove("cand-frozen", "cand-frozen-last");
      cell.style.left = "";
      if (i < frozenCount) {
        cell.classList.add("cand-frozen");
        cell.style.left = `${offsets[i]}px`;
        if (i === frozenCount - 1) cell.classList.add("cand-frozen-last");
      }
    });
  });
}

function enableColumnResize(stageKey) {
  const table = $("#cand-table table");
  if (!table) return;
  const ss = getStageState(stageKey);
  const applyWidths = () => applyCandColWidths(ss);
  if (Object.keys(ss.colWidths).length) applyWidths();
  table.querySelectorAll("thead tr:first-child th").forEach((th, idx) => {
    if (th.querySelector(".th-resize")) return;
    const handle = document.createElement("span");
    handle.className = "th-resize";
    handle.title = "拖动调整列宽";
    th.appendChild(handle);
    handle.addEventListener("click", e => e.stopPropagation());
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      e.stopPropagation();
      ss.colWidthsTouched = true;
      const startX = e.pageX, startW = th.offsetWidth;
      const onMove = ev => {
        ss.colWidths[idx + 1] = Math.max(48, startW + ev.pageX - startX);
        applyWidths();
        applyCandFrozenColumns(state.tab);
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
        applyCandFrozenColumns(state.tab);
      };
      document.body.style.cursor = "col-resize";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

function registrationCreateHiddenKeys() {
  return new Set([
    "registration_time", "registration_status", "delivery_time",
    "resume_id", "work_location", "sourcer_dept", "graduation_time", "interface_dept",
    "registration_source_custom",
  ]);
}

const REGISTRATION_CREATE_FIELD_ORDER = [
  "name", "phone", "sourcer", "interface_person",
  "education", "school", "major", "registration_source", "registration_remark",
];

function registrationDeptFieldHtml(deptKey, value) {
  const f = fieldsForStage("registration").find(x => x.key === deptKey || x.legacy_key === deptKey);
  const label = f ? f.label : (deptKey === "sourcer_dept" ? "拓源人部门" : "接口人部门");
  const v = (value || "").trim();
  return `
    <div class="emp-dept-row">
      <span class="emp-dept-label">${esc(label)}</span>
      <span class="dept-display-value emp-dept-value" id="dept-display-${deptKey}">${esc(v || "—")}</span>
      <input type="hidden" data-field="${deptKey}" value="${esc(v)}">
    </div>`;
}

function registrationEmployeeFieldHtml(f, cand, locked) {
  const empKey = f.key;
  const isSourcer = empKey === "sourcer" || empKey === "拓源人";
  const deptKey = isSourcer ? "sourcer_dept" : "interface_dept";
  const empVal = cand
    ? (cand.data[empKey] || cand.data[isSourcer ? "拓源人" : "接口人"] || "")
    : "";
  const deptVal = cand
    ? (cand.data[deptKey] || cand.data[isSourcer ? "拓源人部门" : "接口人部门"] || "")
    : "";
  // 姓名从已存字段读取（不实时查用户表）；输入框仍显示工号
  const nameVal = cand
    ? (isSourcer
      ? (cand.data["拓源人姓名"] || cand.data.sourcer_name || "")
      : (cand.data["接口人姓名"] || cand.data.interface_person_name || ""))
    : "";
  // 输入框始终存工号（保存校验按工号），姓名在下方 meta 行展示
  const ve = esc(empVal);
  const inputHtml = locked
    ? `<input type="text" data-field="${empKey}" class="master-locked-field" value="${ve}" disabled title="该字段已由主数据表导入，不可修改">`
    : `<input type="text" class="emp-suggest-input" data-field="${empKey}" value="${ve}" placeholder="输入工号或姓名" autocomplete="off">`;
  return `
    <div class="form-item registration-emp-block form-item-full${locked ? " is-master-locked" : ""}">
      <label>${esc(f.label)}${f.required ? " *" : ""}${locked ? "（主数据锁定）" : ""}</label>
      <div class="emp-suggest-wrap">
        ${inputHtml}
        <div class="emp-suggest-list hidden" data-suggest-for="${empKey}" role="listbox"></div>
      </div>
      <div class="emp-resolved-meta">
        <span class="emp-meta-item"><span class="emp-meta-label">姓名</span><span class="emp-name-display" id="emp-name-${empKey}">${esc(nameVal || "—")}</span></span>
        ${registrationDeptFieldHtml(deptKey, deptVal)}
      </div>
    </div>`;
}

async function lookupEmployeeForRegistration(query) {
  const q = (query || "").trim();
  if (!q) return { found: false, department: "" };
  try {
    const body = await api(`/api/users/lookup-employee?q=${encodeURIComponent(q)}`);
    return body.found ? body : { found: false, department: "", error: body.error || "未找到" };
  } catch (e) {
    return { found: false, department: "", error: e.message || "查询失败" };
  }
}

let _empSuggestCtrl = null;
async function suggestEmployeesForRegistration(q) {
  if (_empSuggestCtrl) _empSuggestCtrl.abort();
  _empSuggestCtrl = new AbortController();
  const signal = _empSuggestCtrl.signal;
  try {
    const res = await fetch(
      `/api/users/suggest-employee?q=${encodeURIComponent(q.trim())}`,
      { signal },
    );
    if (!res.ok) throw new Error("查询失败");
    return await res.json();
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw e;
  }
}

function clearRegistrationEmployeeResolved(modal, emp, dept) {
  const nameEl = modal.querySelector("#emp-name-" + emp);
  const displayEl = modal.querySelector("#dept-display-" + dept);
  const hidden = modal.querySelector(`[data-field='${dept}']`);
  if (nameEl) nameEl.textContent = "—";
  if (displayEl) displayEl.textContent = "—";
  if (hidden) hidden.value = "";
}

function applyRegistrationEmployeeSelection(modal, emp, dept, user) {
  const input = modal.querySelector(`[data-field='${emp}']`);
  const listEl = modal.querySelector(`[data-suggest-for='${emp}']`);
  const nameEl = modal.querySelector("#emp-name-" + emp);
  const displayEl = modal.querySelector("#dept-display-" + dept);
  const hidden = modal.querySelector(`[data-field='${dept}']`);
  if (input) input.value = user.username || "";
  if (nameEl) nameEl.textContent = user.display_name || "—";
  if (displayEl) displayEl.textContent = user.department || "—";
  if (hidden) hidden.value = user.department || "";
  if (listEl) listEl.classList.add("hidden");
}

async function resolveRegistrationEmployeeInput(modal, emp, dept, input, lastItems) {
  const q = input.value.trim();
  if (!q) {
    clearRegistrationEmployeeResolved(modal, emp, dept);
    return;
  }
  if (lastItems.length === 1) {
    applyRegistrationEmployeeSelection(modal, emp, dept, lastItems[0]);
    return;
  }
  const body = await lookupEmployeeForRegistration(q);
  if (body.found) applyRegistrationEmployeeSelection(modal, emp, dept, body);
}

function bindRegistrationEmployeeLookup() {
  const pairs = [
    { emp: "sourcer", dept: "sourcer_dept" },
    { emp: "interface_person", dept: "interface_dept" },
  ];
  const modal = $("#modal-body");
  if (!modal) return;

  pairs.forEach(({ emp, dept }) => {
    const input = modal.querySelector(`[data-field='${emp}']`);
    const listEl = modal.querySelector(`[data-suggest-for='${emp}']`);
    if (!input || input.disabled || !listEl) return;

    let lastItems = [];
    let searchSeq = 0;
    let activeIdx = -1;
    const hideList = () => { listEl.classList.add("hidden"); activeIdx = -1; };

    const updateActive = () => {
      listEl.querySelectorAll(".emp-suggest-item").forEach(btn =>
        btn.classList.toggle("active", +btn.dataset.idx === activeIdx));
      listEl.querySelector(".emp-suggest-item.active")?.scrollIntoView({ block: "nearest" });
    };

    const bindSuggestItem = (btn, idx) => {
      btn.addEventListener("mousedown", e => e.preventDefault());
      btn.addEventListener("mouseenter", () => { activeIdx = idx; updateActive(); });
      btn.addEventListener("click", () => {
        const u = lastItems[idx];
        if (u) applyRegistrationEmployeeSelection(modal, emp, dept, u);
      });
    };

    const renderList = (body) => {
      lastItems = body.items || [];
      activeIdx = lastItems.length ? 0 : -1;
      if (body.too_many && lastItems.length) {
        listEl.innerHTML = `<div class="emp-suggest-hint">共 ${body.total || lastItems.length} 条匹配，仅显示前 ${lastItems.length} 条</div>` +
          lastItems.map((u, i) => `
        <button type="button" class="emp-suggest-item" data-idx="${i}" role="option">
          <span class="emp-suggest-id mono">${esc(u.username)}</span>
          <span class="emp-suggest-name">${esc(u.display_name)}</span>
          <span class="emp-suggest-dept">${esc(u.department || "—")}</span>
        </button>`).join("");
        listEl.querySelectorAll(".emp-suggest-item").forEach(btn => bindSuggestItem(btn, +btn.dataset.idx));
        listEl.classList.remove("hidden");
        updateActive();
        return;
      }
      if (body.too_many) {
        listEl.innerHTML = `<div class="emp-suggest-hint">匹配 ${body.total || "过多"} 条，请缩小关键词</div>`;
        lastItems = [];
        listEl.classList.remove("hidden");
        return;
      }
      if (!lastItems.length) {
        listEl.innerHTML = `<div class="emp-suggest-hint">无匹配用户</div>`;
        listEl.classList.remove("hidden");
        return;
      }
      listEl.innerHTML = lastItems.map((u, i) => `
        <button type="button" class="emp-suggest-item" data-idx="${i}" role="option">
          <span class="emp-suggest-id mono">${esc(u.username)}</span>
          <span class="emp-suggest-name">${esc(u.display_name)}</span>
          <span class="emp-suggest-dept">${esc(u.department || "—")}</span>
        </button>`).join("");
      listEl.querySelectorAll(".emp-suggest-item").forEach(btn => bindSuggestItem(btn, +btn.dataset.idx));
      listEl.classList.remove("hidden");
      updateActive();
    };

    const runSearch = debounce(async () => {
      const q = input.value.trim();
      if (!q) {
        hideList();
        clearRegistrationEmployeeResolved(modal, emp, dept);
        return;
      }
      const seq = ++searchSeq;
      try {
        const body = await suggestEmployeesForRegistration(q);
        if (seq !== searchSeq) return;
        renderList(body);
      } catch (e) {
        if (e.name === "AbortError" || seq !== searchSeq) return;
        hideList();
      }
    }, 150);

    const onInput = e => {
      if (e.isComposing) return;
      runSearch();
    };
    // 键盘导航：↑↓ 移动高亮，Enter 选中，Esc 关闭
    input.addEventListener("keydown", e => {
      if (e.isComposing) return;
      const open = !listEl.classList.contains("hidden") && lastItems.length > 0;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!open) { if (input.value.trim()) runSearch(); return; }
        const step = e.key === "ArrowDown" ? 1 : -1;
        activeIdx = (activeIdx + step + lastItems.length) % lastItems.length;
        updateActive();
      } else if (e.key === "Enter") {
        if (open && activeIdx >= 0 && lastItems[activeIdx]) {
          e.preventDefault();
          applyRegistrationEmployeeSelection(modal, emp, dept, lastItems[activeIdx]);
        }
      } else if (e.key === "Escape") {
        hideList();
      }
    });
    input.addEventListener("input", onInput);
    input.addEventListener("compositionend", () => runSearch());
    input.addEventListener("focus", () => {
      if (input.value.trim()) runSearch();
    });
    input.addEventListener("blur", () => {
      setTimeout(async () => {
        hideList();
        await resolveRegistrationEmployeeInput(modal, emp, dept, input, lastItems);
      }, 160);
    });
  });
}

const REGISTRATION_CREATE_OPTIONAL = new Set(["registration_remark"]);

/** 表单层字段视图：key 用英文 legacy_key（表单逻辑/提交用），storage_key 保留中文库内键。
 *  提交英文键后端会统一 normalize 为中文存储键。 */
function legacyFieldView(fields) {
  return fields.map(f => ({ ...f, key: f.legacy_key || f.key, storage_key: f.key }));
}

function registrationCreateFields(stageKey) {
  const hide = registrationCreateHiddenKeys();
  return legacyFieldView(visibleFields(stageKey)).filter(f => f.editable && !hide.has(f.key));
}

const REGISTRATION_EDIT_INTERNAL_KEYS = new Set(["registration_source_custom"]);

function registrationEditFields(stageKey) {
  const fields = legacyFieldView(visibleFields(stageKey))
    .filter(f => !REGISTRATION_EDIT_INTERNAL_KEYS.has(f.key));
  const hasSourcer = fields.some(f => f.key === "sourcer");
  const hasIface = fields.some(f => f.key === "interface_person");
  return fields.filter(f => {
    if (f.key === "sourcer_dept" && hasSourcer) return false;
    if (f.key === "interface_dept" && hasIface) return false;
    return true;
  });
}

function registrationFormFieldHtml(f, cand, stageKey, isRegCreate, lockedFields) {
  // 锁定字段列表存中文 storage_key，也兼容英文 legacy_key
  const locked = lockedFields.has(f.key) || (f.storage_key && lockedFields.has(f.storage_key))
    || (!isRegCreate && !f.editable);
  if (stageKey === "registration" && (f.key === "sourcer" || f.key === "interface_person")) {
    return registrationEmployeeFieldHtml(f, cand, locked);
  }
  if (stageKey === "registration" && f.key === "phone") {
    return `
    <div class="form-item phone-field-wrap${locked ? " is-master-locked" : ""}">
      <label>${esc(f.label)}${f.required ? " *" : ""}${locked ? "（主数据锁定）" : ""}</label>
      ${fieldInput(f, candidateFieldDefault(f, cand, isRegCreate), { locked })}
      <div class="phone-dup-hint hidden" data-phone-dup-hint role="status"></div>
    </div>`;
  }
  return `
    <div class="form-item${locked ? " is-master-locked" : ""}${f.key === "registration_remark" ? " form-item-full" : ""}">
      <label>${esc(f.label)}${f.required ? " *" : ""}${locked ? "（主数据锁定）" : ""}${f.key === "registration_remark" ? '<span class="field-hint-inline">（最新写在第一行）</span>' : ""}</label>
      ${fieldInput(f, candidateFieldDefault(f, cand, isRegCreate), { locked })}
    </div>`;
}

function candidateFieldDefault(f, cand, isRegCreate) {
  if (f.key === "registration_remark") {
    const prefix = registrationRemarkPrefix();
    if (cand) {
      const cur = (cand.data.registration_remark || "").trim();
      return cur ? `${prefix}\n${cur}` : prefix;
    }
    return prefix;
  }
  if (cand) return cand.data[f.key];
  if (f.key === "progress") return todayPrefix();
  return "";
}

function bindRegistrationRemarkInput() {
  const ta = $("#modal-body")?.querySelector("[data-field='registration_remark']");
  if (!ta || ta.disabled) return;
  const prefix = registrationRemarkPrefix();
  ta.focus();
  if (ta.value.startsWith(prefix)) {
    ta.setSelectionRange(prefix.length, prefix.length);
  } else if (!ta.value.trim()) {
    ta.value = prefix;
    ta.setSelectionRange(prefix.length, prefix.length);
  }
}

function bindRegistrationSourceCustom() {
  const sel = $("#modal-body").querySelector("[data-field='registration_source']");
  const wrap = $("#reg-source-custom-wrap");
  if (!sel || !wrap) return;
  const toggle = () => {
    const isOther = sel.value === "其他";
    wrap.classList.toggle("hidden", !isOther);
    const inp = $("#reg-source-custom");
    if (inp) inp.required = isOther;
  };
  sel.addEventListener("change", toggle);
  toggle();
}

let _modalResumeFile = null;

function registrationResumeBlockHtml(cand) {
  const current = cand?.resume_name
    ? `<span class="resume-dropzone-current">当前：${esc(cand.resume_name)}</span>`
    : "";
  return `
    <div class="form-item form-item-full registration-resume-block">
      <label>简历 *</label>
      <div class="resume-dropzone" id="reg-resume-dropzone" role="button" tabindex="0">
        <p class="resume-dropzone-hint">拖拽文件到此处，或点击选择</p>
        <p class="resume-dropzone-name" id="reg-resume-filename">尚未选择文件</p>
        ${current}
        <input type="file" id="reg-resume-input" hidden>
      </div>
    </div>`;
}

function bindRegistrationResumeDropzone(cand) {
  _modalResumeFile = null;
  const zone = $("#reg-resume-dropzone");
  const input = $("#reg-resume-input");
  const nameEl = $("#reg-resume-filename");
  if (!zone || !input || !nameEl) return;

  const refreshLabel = () => {
    if (_modalResumeFile) {
      nameEl.textContent = _modalResumeFile.name;
      zone.classList.add("has-file");
      return;
    }
    if (cand?.resume_name) {
      nameEl.textContent = "保留当前简历（可拖拽或点击更换）";
      zone.classList.add("has-file");
      return;
    }
    nameEl.textContent = "尚未选择文件";
    zone.classList.remove("has-file");
  };

  const pickFile = file => {
    _modalResumeFile = file || null;
    refreshLabel();
  };

  refreshLabel();

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => pickFile(input.files[0] || null));
  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
  zone.addEventListener("dragleave", e => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove("dragover");
  });
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("dragover");
    const file = e.dataTransfer?.files?.[0];
    if (file) pickFile(file);
  });
}

function registrationResumeReady(cand) {
  return !!(_modalResumeFile || cand?.resume_name);
}

async function uploadCandidateResume(cid, file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api/candidates/${cid}/resume`, { method: "POST", body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || "简历上传失败");
  return body;
}

function collectCandidateFormData(fields) {
  const data = {};
  $("#modal-body").querySelectorAll("[data-field]").forEach(el => {
    data[el.dataset.field] = el.value;
  });
  return data;
}

function validateRegistrationCreateForm(fields, data) {
  const missing = fields.filter(f => f.required && !(data[f.key] || "").trim());
  if (data.registration_source === "其他" && !(data.registration_source_custom || "").trim()) {
    missing.push({ label: "自定义简历来源" });
  }
  if (missing.length) {
    toast(`请填写：${missing.map(f => f.label).join("、")}`, true);
    return false;
  }
  return true;
}

async function validateRegistrationUserRefs(data) {
  const params = new URLSearchParams();
  if ((data.sourcer || "").trim()) params.set("sourcer", data.sourcer.trim());
  if ((data.interface_person || "").trim()) params.set("interface_person", data.interface_person.trim());
  if (!params.toString()) return true;
  try {
    const body = await fetch(`/api/users/check-registration-refs?${params}`).then(r => r.json());
    if (!body.ok) {
      toast(body.error || "拓源人或接口人未在本系统注册", true);
      return false;
    }
    return true;
  } catch (_) {
    toast("无法校验拓源人/接口人，请稍后重试", true);
    return false;
  }
}

function normalizeCandidatePhone(phone) {
  return (phone || "").trim();
}

function computeDuplicatePhones(candidates) {
  const counts = new Map();
  for (const c of candidates) {
    const ph = normalizeCandidatePhone(c.data.phone);
    if (!ph) continue;
    counts.set(ph, (counts.get(ph) || 0) + 1);
  }
  const dups = new Set();
  counts.forEach((n, ph) => { if (n > 1) dups.add(ph); });
  return dups;
}

function findCandidateByPhoneInList(phone, excludeId = null) {
  const ph = normalizeCandidatePhone(phone);
  if (!ph) return null;
  const ss = getStageState("registration");
  const pool = ss.allCandidates || ss.list;
  return pool.find(c => {
    if (excludeId != null && c.id === excludeId) return false;
    return normalizeCandidatePhone(c.data.phone) === ph;
  }) || null;
}

function updateRegistrationPhoneDuplicateUI(phone, excludeId, hintEl) {
  const dup = findCandidateByPhoneInList(phone, excludeId);
  if (dup) {
    const name = (dup.data.name || "").trim() || "—";
    hintEl.textContent = `该电话已登记，候选人：${name}`;
    hintEl.classList.remove("hidden");
  } else {
    hintEl.classList.add("hidden");
    hintEl.textContent = "";
  }
}

function bindRegistrationPhoneDuplicateCheck(cand, stageKey) {
  const modal = $("#modal-body");
  if (!modal) return;
  const input = modal.querySelector("[data-field='phone']");
  const hint = modal.querySelector("[data-phone-dup-hint]");
  if (!input || !hint) return;
  const excludeId = cand?.id ?? null;
  const run = () => updateRegistrationPhoneDuplicateUI(input.value, excludeId, hint);
  input.addEventListener("input", run);
  input.addEventListener("change", run);
  run();
}

async function postCandidateCreate(data, stageKey) {
  const res = await fetch("/api/candidates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data, stage: stageKey }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(body.error || "操作失败");
    err.status = res.status;
    err.code = body.code;
    err.existing = body.existing;
    throw err;
  }
  return body;
}

function stageEditFields(stageKey) {
  if (stageKey === "registration") return registrationEditFields(stageKey);
  return visibleFields(stageKey);
}

function openCandidateModal(cand, stageKey) {
  const isNew = !cand;
  const isRegCreate = isNew && stageKey === "registration";
  const fields = isRegCreate
    ? registrationCreateFields(stageKey).map(f => ({
      ...f,
      required: f.required || !REGISTRATION_CREATE_OPTIONAL.has(f.key),
    }))
    : stageEditFields(stageKey);
  const meta = state.stages.find(s => s.key === stageKey);
  const lockedFields = new Set(cand?.data?._master_locked_fields || []);

  const sourceCustomField = isRegCreate ? `
    <div id="reg-source-custom-wrap" class="form-item form-item-full hidden">
      <label>自定义简历来源 *</label>
      <input type="text" id="reg-source-custom" data-field="registration_source_custom"
             placeholder="请填写具体简历来源">
    </div>` : "";

  const resumeBlock = stageKey === "registration" ? registrationResumeBlockHtml(cand) : "";

  openModal(isNew ? `新增候选人 - ${meta.label}` : `编辑 - ${esc(cand.data.name || "")}（${meta.label}）`, `
    <div class="registration-modal-body">
      <div class="form-grid registration-form-grid">
        ${fields.map(f => {
          let html = registrationFormFieldHtml(f, cand, stageKey, isRegCreate, lockedFields);
          if (isRegCreate && f.key === "registration_source") html += sourceCustomField;
          return html;
        }).join("")}
      </div>
      ${resumeBlock}
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="cand-save">保存</button>`);

  if (isRegCreate) bindRegistrationSourceCustom();
  if (stageKey === "registration") {
    bindRegistrationEmployeeLookup();
    bindRegistrationPhoneDuplicateCheck(cand, stageKey);
    bindRegistrationRemarkInput();
    bindRegistrationResumeDropzone(cand);
  }

  $("#cand-save").addEventListener("click", async () => {
    const data = collectCandidateFormData(fields);
    if (stageKey === "registration" && "registration_remark" in data) {
      data.registration_remark = normalizeRegistrationRemark(data.registration_remark);
    }
    if (isRegCreate && !validateRegistrationCreateForm(fields, data)) return;
    const missing = fields.filter(f => f.required && !(data[f.key] || "").trim());
    if (!isRegCreate && missing.length) {
      toast(`请填写：${missing.map(f => f.label).join("、")}`, true);
      return;
    }
    if (stageKey === "registration") {
      if (!registrationResumeReady(cand)) {
        toast("请上传简历", true);
        return;
      }
      if (isNew && findCandidateByPhoneInList(data.phone, null)) {
        toast("该电话已被其他候选人使用，请修改后再保存", true);
        return;
      }
      if (!await validateRegistrationUserRefs(data)) return;
    }
    try {
      let cid;
      if (isNew) {
        const r = await postCandidateCreate(data, stageKey);
        cid = r.id;
      } else {
        try {
          await api(`/api/candidates/${cand.id}`, { method: "PUT", json: { data, stage: stageKey } });
          cid = cand.id;
        } catch (e) {
          // 双手机号同一人：电话撞上已有候选人，确认后合并（主数据侧优先）
          if (e.status !== 409 || !e.can_merge) throw e;
          const other = e.existing || {};
          const ok = confirm(
            `电话 ${data.phone} 已属于候选人「${other.name || "未知"}」。\n` +
            `确认后两条记录将合并为一条（重复字段优先使用主数据表导入的数据）。\n\n是否合并？`);
          if (!ok) return;
          const r = await api(`/api/candidates/${cand.id}`,
            { method: "PUT", json: { data, stage: stageKey, merge_on_conflict: true } });
          cid = r.id;
          toast("两条记录已合并（主数据优先）");
        }
      }
      if (stageKey === "registration" && _modalResumeFile && cid) {
        await uploadCandidateResume(cid, _modalResumeFile);
      }
      toast(isNew ? "候选人已新增" : "已保存");
      closeModal();
      loadCandidateTable(stageKey);
    } catch (e) {
      toast(e.message, true);
    }
  });
}

function openProgressModal(c, stageKey) {
  const cur = (c.data.progress || "").trim();
  const prefix = todayPrefix();
  const initial = cur ? prefix + "\n" + cur : prefix;
  openModal(`更新进展 - ${esc(c.data.name || "")}`, `
    <div class="form-item">
      <label>当前进展（最新一条写在第一行，列表只显示第一行）</label>
      <textarea id="prog-text" rows="8" style="width:100%">${esc(initial)}</textarea>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="prog-save">保存</button>`);
  const ta = $("#prog-text");
  ta.focus();
  ta.setSelectionRange(prefix.length, prefix.length);
  $("#prog-save").addEventListener("click", async () => {
    try {
      const r = await api(`/api/candidates/${c.id}`, {
        method: "PUT", json: { data: { progress: ta.value.trim() }, stage: stageKey },
      });
      toast(r.changed ? "进展已更新" : "内容无变化");
      closeModal();
      await loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

async function exportSelectedExcel(stageKey) {
  const ss = getStageState(stageKey);
  if (!ss.selected.size) return;
  try {
    const res = await fetch("/api/candidates/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...ss.selected], stage: stageKey }),
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      toast(j.error || "导出失败", true);
      return;
    }
    const count = res.headers.get("X-Export-Count") || ss.selected.size;
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `候选人导出_${new Date().toISOString().slice(0, 10)}.xlsx`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${count} 名候选人的Excel`);
  } catch (e) { toast(e.message, true); }
}

function deleteCandidate(cand, stageKey) {
  openModal("删除确认",
    `<p>确定删除候选人「<b>${esc(cand.data.name || "")}</b>」吗？该操作会记录到日志，但数据不可恢复。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="del-confirm">确认删除</button>`);
  $("#del-confirm").addEventListener("click", async () => {
    try {
      await api(`/api/candidates/${cand.id}`, { method: "DELETE" });
      toast("已删除");
      closeModal();
      loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

function batchDeleteSelected(stageKey) {
  const ss = getStageState(stageKey);
  const n = ss.selected.size;
  if (!n) return;
  openModal("批量删除确认",
    `<p>确定删除选中的 <b>${n}</b> 名候选人吗？其简历文件将一并删除，操作不可恢复。</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="batch-del-confirm">确认删除</button>`);
  $("#batch-del-confirm").addEventListener("click", async () => {
    try {
      const r = await api("/api/candidates/batch_delete", { method: "POST", json: { ids: [...ss.selected] } });
      toast(`已删除 ${r.deleted} 名` + (r.skipped ? `，跳过 ${r.skipped} 名` : ""));
      closeModal();
      ss.selected.clear();
      await loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

async function onResumeFilePicked() {
  const ss = getStageState("registration");
  const file = $("#resume-input").files[0];
  if (!file || !ss.uploadTarget) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    await api(`/api/candidates/${ss.uploadTarget}/resume`, { method: "POST", body: fd });
    toast("简历已保存");
    await loadCandidateTable("registration");
  } catch (e) { toast(e.message, true); }
  ss.uploadTarget = null;
}

function deleteResume(c, stageKey) {
  openModal("删除简历",
    `<p>确定删除候选人「<b>${esc(c.data.name || "")}</b>」的简历（${esc(c.resume_name)}）吗？</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-danger" id="resdel-confirm">确认删除</button>`);
  $("#resdel-confirm").addEventListener("click", async () => {
    try {
      await api(`/api/candidates/${c.id}/resume`, { method: "DELETE" });
      toast("简历已删除");
      closeModal();
      await loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

async function exportSelectedResumes() {
  const ss = getStageState("registration");
  if (!ss.selected.size) return;
  try {
    const res = await fetch("/api/resumes/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...ss.selected] }),
    });
    if (!res.ok) {
      const j = await res.json();
      toast(j.error || "导出失败", true);
      return;
    }
    const count = res.headers.get("X-Export-Count") || ss.selected.size;
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `简历导出_${new Date().toISOString().slice(0, 10)}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast(`已导出 ${count} 份简历`);
  } catch (e) { toast(e.message, true); }
}
