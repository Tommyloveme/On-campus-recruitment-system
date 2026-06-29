"use strict";

let _fbEditorSel = null;
const FB_PRIORITY_LABELS = { low: "低", normal: "中", high: "高", urgent: "紧急" };
const FB_PRIORITY_CLASS = { low: "gray", normal: "blue", high: "yellow", urgent: "red" };

const fbState = { items: [], filters: {}, isAdmin: false };

function fbPlainText(html) {
  const d = document.createElement("div");
  d.innerHTML = html || "";
  return (d.textContent || "").trim();
}

function feedbackSaveSelection() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  const ed = $("#feedback-editor");
  if (!ed || !ed.contains(sel.anchorNode)) return;
  _fbEditorSel = sel.getRangeAt(0).cloneRange();
}

function feedbackRestoreSelection() {
  const ed = $("#feedback-editor");
  if (!ed || !_fbEditorSel) return;
  ed.focus();
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(_fbEditorSel);
}

function feedbackEditorCommand(cmd) {
  document.execCommand(cmd, false, null);
  $("#feedback-editor")?.focus();
}

async function feedbackInsertImage(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch("/api/feedback/images", { method: "POST", body: fd, credentials: "same-origin" });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "图片上传失败");
    const ed = $("#feedback-editor");
    if (!ed) return;
    feedbackRestoreSelection();
    ed.focus();
    const img = document.createElement("img");
    img.src = data.url;
    img.alt = "反馈图片";
    const sel = window.getSelection();
    if (sel && sel.rangeCount) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(img);
      range.setStartAfter(img);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
      _fbEditorSel = range.cloneRange();
    } else {
      ed.appendChild(img);
    }
  } catch (e) {
    toast(e.message, true);
  }
}

function openFeedbackModal() {
  _fbEditorSel = null;
  openModal("提交问题反馈", `
    <div class="form-item">
      <label>标题 *</label>
      <input type="text" id="feedback-title" placeholder="简要概括问题" maxlength="120">
    </div>
    <div class="feedback-toolbar">
      <button type="button" class="btn btn-sm" data-fb-cmd="bold"><b>B</b></button>
      <button type="button" class="btn btn-sm" data-fb-cmd="italic"><i>I</i></button>
      <label class="btn btn-sm feedback-img-btn" id="feedback-img-label">
        插图
        <input type="file" id="feedback-img-input" accept="image/*" hidden>
      </label>
    </div>
    <div id="feedback-editor" class="feedback-editor" contenteditable="true" data-placeholder="描述问题或建议…"></div>
  `, `
    <button class="btn" onclick="closeModal()">取消</button>
    <button class="btn btn-primary" id="feedback-submit">提交</button>
  `);

  const ed = $("#feedback-editor");
  ed?.addEventListener("keyup", feedbackSaveSelection);
  ed?.addEventListener("mouseup", feedbackSaveSelection);
  $("#feedback-img-label")?.addEventListener("mousedown", e => {
    if (e.target.id !== "feedback-img-input") feedbackSaveSelection();
  });
  ed?.addEventListener("paste", e => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        feedbackSaveSelection();
        feedbackInsertImage(item.getAsFile());
        return;
      }
    }
  });
  document.querySelectorAll("[data-fb-cmd]").forEach(btn =>
    btn.addEventListener("click", () => feedbackEditorCommand(btn.dataset.fbCmd)));
  $("#feedback-img-input")?.addEventListener("change", e => {
    const f = e.target.files?.[0];
    if (f) feedbackInsertImage(f);
    e.target.value = "";
  });
  $("#feedback-submit")?.addEventListener("click", async () => {
    const title = ($("#feedback-title")?.value || "").trim();
    const html = (ed?.innerHTML || "").trim();
    const plain = (ed?.innerText || "").trim();
    if (!title) { toast("请填写标题", true); return; }
    if (!plain && !html.includes("<img")) { toast("请填写内容", true); return; }
    try {
      await api("/api/feedback", { method: "POST", json: { title, content_html: html } });
      toast("已提交");
      closeModal();
      if (state.tab === "feedback") loadFeedbackTable();
    } catch (e) { toast(e.message, true); }
  });
}

function filteredFeedbackItems() {
  const f = fbState.filters;
  return fbState.items.filter(item => {
    if (f.title && !item.title.toLowerCase().includes(f.title.toLowerCase())) return false;
    if (f.user && !(`${item.display_name} ${item.username}`.toLowerCase().includes(f.user.toLowerCase()))) return false;
    if (f.priority && item.priority !== f.priority) return false;
    if (f.reply === "replied" && !item.reply_html) return false;
    if (f.reply === "pending" && item.reply_html) return false;
    if (f.created && !String(item.created_at).includes(f.created)) return false;
    return true;
  });
}

function renderFeedbackRows() {
  const tbody = $("#fb-tbody");
  if (!tbody) return;
  const list = filteredFeedbackItems();
  const admin = fbState.isAdmin;
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="${admin ? 8 : 7}" class="empty">没有符合条件的反馈</td></tr>`;
    return;
  }
  tbody.innerHTML = list.map(item => {
    const replyPreview = item.reply_html
      ? esc(fbPlainText(item.reply_html).slice(0, 40) + (fbPlainText(item.reply_html).length > 40 ? "…" : ""))
      : `<span class="muted">—</span>`;
    const priCell = admin
      ? `<select class="fb-pri-sel" data-fb-pri="${item.id}">
          ${Object.entries(FB_PRIORITY_LABELS).map(([k, v]) =>
    `<option value="${k}" ${item.priority === k ? "selected" : ""}>${esc(v)}</option>`).join("")}
        </select>`
      : `<span class="badge badge-${FB_PRIORITY_CLASS[item.priority] || "gray"}">${esc(item.priority_label)}</span>`;
    const canDel = admin || item.is_mine;
    return `
      <tr>
        <td class="fb-col-title" title="${esc(item.title)}">${esc(item.title)}</td>
        <td>${esc(item.display_name)}</td>
        <td class="mono">${esc(item.created_at)}</td>
        <td>${priCell}</td>
        <td>${item.reply_html
          ? `<span class="badge badge-green">已回复</span>`
          : `<span class="badge badge-gray">待处理</span>`}</td>
        <td class="fb-col-reply">${replyPreview}</td>
        <td>
          <button type="button" class="btn btn-sm" data-fb-view="${item.id}">详情</button>
          ${canDel ? `<button type="button" class="btn btn-sm iv-action-muted" data-fb-del="${item.id}">删除</button>` : ""}
        </td>
      </tr>`;
  }).join("");

  tbody.querySelectorAll("[data-fb-view]").forEach(btn =>
    btn.addEventListener("click", () => {
      const item = fbState.items.find(x => x.id === +btn.dataset.fbView);
      if (item) openFeedbackDetailModal(item);
    }));
  tbody.querySelectorAll("[data-fb-del]").forEach(btn =>
    btn.addEventListener("click", () => confirmDeleteFeedback(+btn.dataset.fbDel)));
  tbody.querySelectorAll(".fb-pri-sel").forEach(sel =>
    sel.addEventListener("change", async () => {
      try {
        await api(`/api/feedback/${sel.dataset.fbPri}`, { method: "PATCH", json: { priority: sel.value } });
        const item = fbState.items.find(x => x.id === +sel.dataset.fbPri);
        if (item) {
          item.priority = sel.value;
          item.priority_label = FB_PRIORITY_LABELS[sel.value];
        }
        toast("优先级已更新");
      } catch (e) { toast(e.message, true); }
    }));
}

function confirmDeleteFeedback(id) {
  const item = fbState.items.find(x => x.id === id);
  if (!item) return;
  openModal("删除反馈", `<p class="iv-confirm-danger">确定删除「<b>${esc(item.title)}</b>」吗？</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn iv-action-muted" id="fb-del-go">确认删除</button>`);
  $("#fb-del-go")?.addEventListener("click", async () => {
    try {
      await api(`/api/feedback/${id}`, { method: "DELETE" });
      toast("已删除");
      closeModal();
      loadFeedbackTable();
    } catch (e) { toast(e.message, true); }
  });
}

function openFeedbackDetailModal(item) {
  const admin = fbState.isAdmin;
  openModal(item.title, `
    <div class="fb-detail-meta">
      <span>提出人：<b>${esc(item.display_name)}</b>（${esc(item.username)}）</span>
      <span class="muted">${esc(item.created_at)}</span>
      <span class="badge badge-${FB_PRIORITY_CLASS[item.priority] || "gray"}">${esc(item.priority_label)}</span>
    </div>
    <div class="fb-detail-block">
      <div class="fb-detail-label">反馈内容</div>
      <div class="fb-content rich-html">${item.content_html}</div>
    </div>
    ${item.reply_html ? `
    <div class="fb-detail-block">
      <div class="fb-detail-label">处理回复 ${item.reply_by ? `· ${esc(item.reply_by)} ${esc(item.reply_at || "")}` : ""}</div>
      <div class="fb-content rich-html">${item.reply_html}</div>
    </div>` : `<p class="muted" style="font-size:13px">暂无回复，请耐心等待处理。</p>`}
    ${admin ? `
    <div class="form-item" style="margin-top:12px">
      <label>优先级</label>
      <select id="fb-priority-sel">
        ${Object.entries(FB_PRIORITY_LABELS).map(([k, v]) =>
    `<option value="${k}" ${item.priority === k ? "selected" : ""}>${esc(v)}</option>`).join("")}
      </select>
    </div>
    <div class="form-item">
      <label>回复</label>
      <textarea id="fb-reply-text" rows="4" placeholder="填写处理回复">${esc(fbPlainText(item.reply_html))}</textarea>
    </div>` : ""}`,
    `<button class="btn" onclick="closeModal()">关闭</button>
     ${admin ? `<button class="btn btn-primary" id="fb-save-admin">保存</button>` : ""}`);

  $("#fb-save-admin")?.addEventListener("click", async () => {
    const priority = $("#fb-priority-sel").value;
    const replyText = ($("#fb-reply-text").value || "").trim();
    const reply_html = replyText ? `<p>${esc(replyText).replace(/\n/g, "<br>")}</p>` : "";
    try {
      await api(`/api/feedback/${item.id}`, { method: "PATCH", json: { priority, reply_html } });
      toast("已保存");
      closeModal();
      loadFeedbackTable();
    } catch (e) { toast(e.message, true); }
  });
}

async function loadFeedbackTable() {
  const tbody = $("#fb-tbody");
  if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="empty">加载中…</td></tr>`;
  try {
    const r = await api("/api/feedback?all=1&sort=created_at&order=desc");
    fbState.items = r.items || [];
    fbState.isAdmin = !!r.is_admin;
    renderFeedbackRows();
    const countEl = $("#fb-count");
    if (countEl) countEl.textContent = `${filteredFeedbackItems().length} / ${fbState.items.length} 条`;
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="empty">加载失败：${esc(e.message)}</td></tr>`;
  }
}

async function renderFeedback() {
  if (!moduleReadable("feedback")) {
    $("#main").innerHTML = `<div class="empty-state">无问题反馈模块访问权限。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card fb-card">
      <div class="fb-head">
        <div>
          <div class="section-title">问题反馈</div>
          <p class="fb-sub">查看全体反馈及处理回复；管理员可设优先级、回复与删除。</p>
        </div>
        <div class="fb-toolbar">
          <span id="fb-count" class="muted" style="font-size:13px"></span>
          <button type="button" class="btn btn-primary btn-sm" id="fb-add-btn">+ 新增反馈</button>
        </div>
      </div>
      <div class="table-wrap fb-table-wrap">
        <table class="fb-table" id="fb-table">
          <thead>
            <tr>
              <th>标题</th><th>提出人</th><th>提出时间</th><th>优先级</th>
              <th>状态</th><th>回复摘要</th><th>操作</th>
            </tr>
            <tr class="filter-row fb-filter-row">
              <th><input type="text" data-fb-filter="title" placeholder="筛选"></th>
              <th><input type="text" data-fb-filter="user" placeholder="筛选"></th>
              <th><input type="text" data-fb-filter="created" placeholder="筛选"></th>
              <th>
                <select data-fb-filter="priority">
                  <option value="">全部</option>
                  ${Object.entries(FB_PRIORITY_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}
                </select>
              </th>
              <th>
                <select data-fb-filter="reply">
                  <option value="">全部</option>
                  <option value="pending">待处理</option>
                  <option value="replied">已回复</option>
                </select>
              </th>
              <th></th><th></th>
            </tr>
          </thead>
          <tbody id="fb-tbody"><tr><td colspan="7" class="empty">加载中…</td></tr></tbody>
        </table>
      </div>
    </div>`;

  $("#fb-add-btn")?.addEventListener("click", () => openFeedbackModal());
  document.querySelectorAll("[data-fb-filter]").forEach(el => {
    const key = el.dataset.fbFilter;
    const run = () => {
      fbState.filters[key] = el.value.trim();
      renderFeedbackRows();
      const countEl = $("#fb-count");
      if (countEl) countEl.textContent = `${filteredFeedbackItems().length} / ${fbState.items.length} 条`;
    };
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", debounce(run, 200));
  });
  await loadFeedbackTable();
}

$("#feedback-btn")?.addEventListener("click", () => {
  if (moduleReadable("feedback")) switchTab("feedback");
  else openFeedbackModal();
});
