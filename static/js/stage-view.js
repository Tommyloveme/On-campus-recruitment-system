/* 阶段视图模块：各流程标签页共用的候选人表格 CRUD / 导入导出 */
"use strict";

const stageStates = new Map();

function getStageState(stageKey) {
  if (!stageStates.has(stageKey)) {
    stageStates.set(stageKey, {
      list: [], sort: null, selected: new Set(),
      uploadTarget: null, page: 1,
      pageSize: state.app.page_size ?? 15,
    });
  }
  return stageStates.get(stageKey);
}

async function renderStageView(stageKey) {
  state.tab = stageKey;
  const meta = state.stages.find(s => s.key === stageKey);
  const showCalendar = meta.has_interview_calendar;
  const ss = getStageState(stageKey);
  ss.stageFilter = ss.stageFilter !== false; // 默认仅显示当前流程候选人

  $("#main").innerHTML = `
    <div class="stage-header">
      <h2>${meta.icon || ""} ${esc(meta.label)}</h2>
      <p class="stage-desc">${esc(meta.description || "")}</p>
    </div>
    ${showCalendar ? `
    <div class="iv-subnav" style="margin-bottom:12px">
      <button class="btn btn-sm iv-view-btn active" data-view="list">候选人列表</button>
      <button class="btn btn-sm iv-view-btn" data-view="calendar">面试日程表</button>
    </div>` : ""}
    <div id="stage-content"></div>`;

  if (showCalendar) {
    document.querySelectorAll(".iv-view-btn").forEach(btn =>
      btn.addEventListener("click", () => {
        document.querySelectorAll(".iv-view-btn").forEach(b => b.classList.toggle("active", b === btn));
        if (btn.dataset.view === "calendar") renderInterviewCalendar(stageKey);
        else renderStageList(stageKey);
      }));
  }
  renderStageList(stageKey);
}

async function renderStageList(stageKey) {
  const meta = state.stages.find(s => s.key === stageKey);
  const ss = getStageState(stageKey);
  const fields = visibleFields(stageKey);
  const showGroupCol = canSeeAll();
  const showResume = stageKey === "registration";
  const canAdd = canCreate() && meta.can_create;
  const showMasterImport = stageKey === "registration" && canCreate();

  const headCells = fields.map(f => f.type === "date"
    ? `<th class="sortable" data-sortkey="${f.key}" title="点击排序">${esc(f.label)}<span class="sort-arrow" data-arrow="${f.key}"></span></th>`
    : `<th>${esc(f.label)}</th>`).join("");
  const filterCells = fields.map(f => {
    if (f.type === "select") {
      const opts = (f.options || []).map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
      return `<th><select data-filter="${f.key}"><option value="">全部</option>${opts}</select></th>`;
    }
    return `<th><input type="text" data-filter="${f.key}" placeholder="筛选"></th>`;
  }).join("");
  const groupFilter = showGroupCol
    ? `<th><select data-filter="__group"><option value="">全部</option>
        ${state.groups.map(g => `<option value="${g.id}">${esc(g.name)}</option>`).join("")}</select></th>`
    : "";

  const root = $("#stage-content") || $("#main");
  root.innerHTML = `
    <div class="toolbar">
      <input type="text" id="cand-search" placeholder="全局搜索：姓名 / 电话 / 部门 / 任意字段…">
      <button class="btn btn-sm" id="btn-clear-filter">清空筛选</button>
      <label class="chk-inline"><input type="checkbox" id="stage-filter-only" ${ss.stageFilter ? "checked" : ""}>
        仅当前流程</label>
      <div class="spacer"></div>
      ${canBatchDelete() && stageKey === "registration" ? `<button class="btn btn-danger" id="btn-batch-del" disabled>删除选中 (0)</button>` : ""}
      <button class="btn" id="btn-export-excel" disabled>导出选中Excel (0)</button>
      ${showResume ? `<button class="btn" id="btn-export-resume" disabled>导出选中简历 (0)</button>` : ""}
      ${showMasterImport ? `<button class="btn btn-primary" id="btn-master-import">主数据表导入</button>` : ""}
      ${canCreate() ? `
        <button class="btn" id="btn-template">下载导入模板</button>
        <button class="btn" id="btn-import">Excel 导入</button>
        ${canAdd ? `<button class="btn btn-primary" id="btn-add">+ 新增候选人</button>` : ""}` : ""}
    </div>
    <div id="cand-table" class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" id="sel-all" title="全选当前筛选结果"></th>
            ${showGroupCol ? "<th>二层部门</th>" : ""}${headCells}
            ${showResume ? "<th>简历</th>" : ""}<th>操作</th>
          </tr>
          <tr class="filter-row">
            <th></th>${groupFilter}${filterCells}${showResume ? "<th></th>" : ""}<th></th>
          </tr>
        </thead>
        <tbody id="cand-tbody"></tbody>
      </table>
    </div>
    <div id="cand-pager" class="pager-bar"></div>
    ${showResume ? `<input type="file" id="resume-input" accept=".pdf,.docx" style="display:none">` : ""}`;

  if (showMasterImport) $("#btn-master-import").addEventListener("click", openMasterImportModal);
  $("#stage-filter-only")?.addEventListener("change", e => {
    ss.stageFilter = e.target.checked;
    ss.page = 1;
    loadCandidateTable(stageKey);
  });
  if (canCreate()) {
    if ($("#btn-template")) $("#btn-template").addEventListener("click", () => {
      location.href = `/api/import/template?stage=${stageKey}`;
    });
    if ($("#btn-import")) $("#btn-import").addEventListener("click", () => openImportModal(stageKey));
    if ($("#btn-add")) $("#btn-add").addEventListener("click", () => openCandidateModal(null, stageKey));
  }
  if (canBatchDelete()) $("#btn-batch-del").addEventListener("click", () => batchDeleteSelected(stageKey));
  if (showResume) {
    $("#btn-export-resume").addEventListener("click", exportSelectedResumes);
    $("#resume-input").addEventListener("change", onResumeFilePicked);
  }
  $("#btn-export-excel").addEventListener("click", () => exportSelectedExcel(stageKey));
  enableColumnResize();
  const onFilterChange = () => { ss.page = 1; renderCandidateRows(stageKey); };
  $("#cand-search").addEventListener("input", debounce(onFilterChange, 250));
  $("#btn-clear-filter").addEventListener("click", () => {
    $("#cand-search").value = "";
    document.querySelectorAll("[data-filter]").forEach(el => { el.value = ""; });
    ss.sort = null;
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

  await loadCandidateTable(stageKey);
}

async function loadCandidateTable(stageKey) {
  const ss = getStageState(stageKey);
  const url = ss.stageFilter !== false
    ? `/api/candidates?stage=${stageKey}`
    : "/api/candidates";
  ss.list = await api(url);
  const ids = new Set(ss.list.map(c => c.id));
  ss.selected.forEach(id => { if (!ids.has(id)) ss.selected.delete(id); });
  renderCandidateRows(stageKey);
}

function filteredCandidates(stageKey) {
  const ss = getStageState(stageKey);
  let list = ss.list;
  const q = ($("#cand-search")?.value || "").trim().toLowerCase();
  if (q) {
    list = list.filter(c =>
      Object.values(c.data).some(v => String(v).toLowerCase().includes(q)) ||
      c.group_name.toLowerCase().includes(q));
  }
  document.querySelectorAll("[data-filter]").forEach(el => {
    const val = el.value.trim();
    if (!val) return;
    const key = el.dataset.filter;
    if (key === "__group") {
      list = list.filter(c => String(c.group_id) === val);
    } else if (el.tagName === "SELECT") {
      list = list.filter(c => (c.data[key] || "") === val);
    } else {
      const lv = val.toLowerCase();
      list = list.filter(c => String(c.data[key] || "").toLowerCase().includes(lv));
    }
  });
  if (ss.sort) {
    const { key, dir } = ss.sort;
    list = [...list].sort((a, b) => {
      const av = a.data[key] || "", bv = b.data[key] || "";
      if (!av && !bv) return 0;
      if (!av) return 1;
      if (!bv) return -1;
      return av.localeCompare(bv) * dir;
    });
  }
  return list;
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

function resumeCellHtml(c) {
  const editable = canEdit(c.group_id);
  if (c.resume_name) {
    return `
      <span class="resume-actions" title="${esc(c.resume_name)}">
        <button class="btn btn-sm" data-resprev="${c.id}">预览</button>
        <button class="btn btn-sm" data-resdl="${c.id}">下载</button>
        ${editable ? `<button class="btn btn-sm" data-resup="${c.id}">更换</button>` : ""}
        ${canDelete(c.group_id) ? `<button class="btn btn-sm btn-danger" data-resdel="${c.id}">删除</button>` : ""}
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
  const fields = visibleFields(stageKey);
  const showGroupCol = canSeeAll();
  const showResume = stageKey === "registration";
  const list = filteredCandidates(stageKey);
  const colCount = 3 + fields.length + (showGroupCol ? 1 : 0) + (showResume ? 1 : 0);

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
        ${showGroupCol ? `<td><span class="badge badge-gray">${esc(c.group_name)}</span></td>` : ""}
        ${fields.map(f => {
          let inner;
          if (f.key === "progress") {
            const full = c.data.progress || "";
            const first = full.split("\n")[0];
            inner = full
              ? `<span class="clip" title="${esc(full)}">${esc(first)}</span>`
              : `<span style="color:#cbd5e1">—</span>`;
            if (canEdit(c.group_id))
              inner += ` <button class="btn btn-sm" data-prog="${c.id}" title="更新进展">更新</button>`;
          } else {
            inner = cellHtml(f, c.data[f.key]);
          }
          return `<td>${inner}</td>`;
        }).join("")}
        ${showResume ? `<td>${resumeCellHtml(c)}</td>` : ""}
        <td>
          ${canEdit(c.group_id)
            ? `<button class="btn btn-sm" data-edit="${c.id}">编辑</button>` +
              (canDelete(c.group_id) && stageKey === "registration"
                ? `<button class="btn btn-sm btn-danger" data-del="${c.id}">删除</button>` : "")
            : `<span style="color:#94a3b8;font-size:12px">只读</span>`}
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

  renderPager(stageKey, total, pages);
  updateSelectionUI(stageKey, list);
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
}

function enableColumnResize() {
  const table = $("#cand-table table");
  if (!table) return;
  let styleEl = $("#col-width-style");
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = "col-width-style";
    document.head.appendChild(styleEl);
  }
  const colWidths = {};
  const applyWidths = () => {
    styleEl.textContent = Object.entries(colWidths).map(([i, w]) =>
      `#cand-table th:nth-child(${i}), #cand-table td:nth-child(${i}) { width:${w}px; min-width:${w}px; }
       #cand-table td:nth-child(${i}) .clip { max-width:${Math.max(40, w - 24)}px; }`).join("\n");
  };
  table.querySelectorAll("thead tr:first-child th").forEach((th, idx) => {
    const handle = document.createElement("span");
    handle.className = "th-resize";
    handle.title = "拖动调整列宽";
    th.appendChild(handle);
    handle.addEventListener("click", e => e.stopPropagation());
    handle.addEventListener("mousedown", e => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.pageX, startW = th.offsetWidth;
      const onMove = ev => {
        colWidths[idx + 1] = Math.max(48, startW + ev.pageX - startX);
        applyWidths();
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.style.cursor = "";
      };
      document.body.style.cursor = "col-resize";
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  });
}

function openCandidateModal(cand, stageKey) {
  const fields = fieldsForStage(stageKey).filter(f => f.editable);
  const isNew = !cand;
  const meta = state.stages.find(s => s.key === stageKey);
  const editableGroups = state.groups.filter(g => canEdit(g.id));
  const groupSelect = isNew ? `
    <div class="form-item">
      <label>所属分组 *</label>
      <select id="cand-modal-group">
        ${editableGroups.map(g => `<option value="${g.id}" ${state.me.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}
      </select>
    </div>` : `
    <div class="form-item"><label>所属分组</label><input value="${esc(cand.group_name)}" disabled></div>`;

  openModal(isNew ? `新增候选人 - ${meta.label}` : `编辑 - ${esc(cand.data.name || "")}（${meta.label}）`, `
    ${groupSelect}
    <div class="form-grid">
      ${fields.map(f => `
        <div class="form-item">
          <label>${esc(f.label)}${f.required ? " *" : ""}</label>
          ${fieldInput(f, cand ? cand.data[f.key]
                              : (f.key === "progress" ? todayPrefix() : ""))}
        </div>`).join("")}
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="cand-save">保存</button>`);

  $("#cand-save").addEventListener("click", async () => {
    const data = {};
    $("#modal-body").querySelectorAll("[data-field]").forEach(el => { data[el.dataset.field] = el.value; });
    const missing = fields.filter(f => f.required && !(data[f.key] || "").trim());
    if (missing.length) { toast(`请填写：${missing.map(f => f.label).join("、")}`, true); return; }
    try {
      if (isNew) {
        const gid = +$("#cand-modal-group").value;
        await api("/api/candidates", { method: "POST", json: { group_id: gid, data, stage: stageKey } });
        toast("候选人已新增");
      } else {
        const r = await api(`/api/candidates/${cand.id}`, { method: "PUT", json: { data, stage: stageKey } });
        toast(r.changed ? `已保存，更新了 ${r.changed} 项信息` : "内容无变化");
      }
      closeModal();
      state.groups = await api("/api/groups");
      loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
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
      state.groups = await api("/api/groups");
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
      state.groups = await api("/api/groups");
      await loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

function openImportModal(stageKey) {
  const meta = state.stages.find(s => s.key === stageKey);
  const editableGroups = state.groups.filter(g => canEdit(g.id));
  if (!editableGroups.length) { toast("您没有任何分组的编辑权限", true); return; }
  const importCols = fieldsForStage(stageKey).filter(f => f.importable).map(f => f.excel_column).join("、");
  openModal(`Excel 导入 - ${meta.label}`, `
    <div class="form-item">
      <label>导入到分组</label>
      <select id="import-group">
        ${editableGroups.map(g => `<option value="${g.id}" ${state.me.group_id === g.id ? "selected" : ""}>${esc(g.name)}</option>`).join("")}
      </select>
    </div>
    <div class="form-item">
      <label>选择 .xlsx 文件（第一行为表头）</label>
      <input type="file" id="import-file" accept=".xlsx">
    </div>
    <p style="font-size:12px;color:#64748b;line-height:1.8">
      当前阶段可导入的列（config/stages/${stageKey}/fields.json）：<br>${esc(importCols)}<br>
      已存在的候选人（按电话或姓名匹配）将被更新，其余新增。
    </p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="import-go">开始导入</button>`);

  $("#import-go").addEventListener("click", async () => {
    const file = $("#import-file").files[0];
    if (!file) { toast("请先选择文件", true); return; }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("group_id", $("#import-group").value);
    fd.append("stage", stageKey);
    try {
      const r = await api("/api/import", { method: "POST", body: fd });
      toast(`导入完成：新增 ${r.created} 人，更新 ${r.updated} 人${r.skipped ? "，跳过 " + r.skipped + " 行" : ""}`);
      closeModal();
      state.groups = await api("/api/groups");
      loadCandidateTable(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

async function onResumeFilePicked() {
  const ss = getStageState("registration");
  const file = $("#resume-input").files[0];
  if (!file || !ss.uploadTarget) return;
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (![".pdf", ".docx"].includes(ext)) { toast("仅支持 .pdf 和 .docx 格式", true); return; }
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
