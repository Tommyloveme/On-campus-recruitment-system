"use strict";

function feedbackEditorCommand(cmd, value) {
  document.execCommand(cmd, false, value);
  $("#feedback-editor")?.focus();
}

async function feedbackInsertImage(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch("/api/feedback/images", {
      method: "POST",
      body: fd,
      credentials: "same-origin",
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "图片上传失败");
    const ed = $("#feedback-editor");
    if (!ed) return;
    ed.focus();
    document.execCommand("insertImage", false, data.url);
  } catch (e) {
    toast(e.message, true);
  }
}

function openFeedbackModal() {
  openModal("问题反馈", `
    <p class="feedback-hint">请描述您遇到的问题或建议，可插入图片。提交后由系统管理员在「管理看板 → 问题反馈」中查看。</p>
    <div class="feedback-toolbar">
      <button type="button" class="btn btn-sm" data-fb-cmd="bold" title="加粗"><b>B</b></button>
      <button type="button" class="btn btn-sm" data-fb-cmd="italic" title="斜体"><i>I</i></button>
      <button type="button" class="btn btn-sm" data-fb-cmd="underline" title="下划线"><u>U</u></button>
      <button type="button" class="btn btn-sm" data-fb-cmd="insertUnorderedList" title="列表">• 列表</button>
      <label class="btn btn-sm feedback-img-btn">
        插入图片
        <input type="file" id="feedback-img-input" accept="image/*" hidden>
      </label>
    </div>
    <div id="feedback-editor" class="feedback-editor" contenteditable="true" data-placeholder="请输入反馈内容…"></div>
  `, `
    <button class="btn" onclick="closeModal()">取消</button>
    <button class="btn btn-primary" id="feedback-submit">提交反馈</button>
  `);

  $("#feedback-editor")?.addEventListener("paste", e => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
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
    const ed = $("#feedback-editor");
    const html = (ed?.innerHTML || "").trim();
    const plain = (ed?.innerText || "").trim();
    if (!plain && !html.includes("<img")) {
      toast("请填写反馈内容", true);
      return;
    }
    try {
      await api("/api/feedback", { method: "POST", json: { content_html: html } });
      toast("反馈已提交，感谢您的意见");
      closeModal();
    } catch (e) { toast(e.message, true); }
  });
}

async function renderFeedback(page = 1) {
  if (!isAdmin()) {
    $("#main").innerHTML = `<div class="empty-state">仅系统管理员可查看问题反馈。</div>`;
    return;
  }
  $("#main").innerHTML = `
    <div class="card fb-card">
      <div class="fb-head">
        <div>
          <div class="section-title">问题反馈</div>
          <p class="fb-sub">用户通过右上角「问题反馈」提交的内容，按时间倒序展示。</p>
        </div>
      </div>
      <div id="fb-list" class="fb-list"><div class="fb-empty">加载中…</div></div>
      <div id="fb-foot" class="log-foot"></div>
    </div>`;

  const listEl = $("#fb-list");
  const foot = $("#fb-foot");
  try {
    const r = await api(`/api/feedback?page=${page}`);
    if (!r.items.length) {
      listEl.innerHTML = `<div class="fb-empty">暂无反馈</div>`;
    } else {
      listEl.innerHTML = r.items.map(item => `
        <article class="fb-item">
          <header class="fb-item-head">
            <strong>${esc(item.display_name)}</strong>
            <span class="fb-meta mono">${esc(item.username)} · ${esc(item.created_at)}</span>
          </header>
          <div class="fb-content rich-html">${item.content_html}</div>
        </article>`).join("");
    }
    const pages = Math.max(1, Math.ceil(r.total / r.size));
    foot.innerHTML = `
      <span class="log-count">${r.total} 条 · 第 ${page}/${pages} 页</span>
      <div class="pager log-pager">
        <button class="btn btn-sm" data-fb-prev ${page <= 1 ? "disabled" : ""}>上一页</button>
        <button class="btn btn-sm" data-fb-next ${page >= pages ? "disabled" : ""}>下一页</button>
      </div>`;
    foot.querySelector("[data-fb-prev]")?.addEventListener("click", () => renderFeedback(page - 1));
    foot.querySelector("[data-fb-next]")?.addEventListener("click", () => renderFeedback(page + 1));
  } catch (e) {
    listEl.innerHTML = `<div class="fb-empty">加载失败：${esc(e.message)}</div>`;
    foot.innerHTML = "";
  }
}

$("#feedback-btn")?.addEventListener("click", () => openFeedbackModal());
