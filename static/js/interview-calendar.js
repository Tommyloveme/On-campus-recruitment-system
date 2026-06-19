/* 技术面/主管面：面试官日程设置与接口人预约日历 */
"use strict";

const ivCal = { type: null, weekStart: null, selectedCandidate: null };

function mondayOf(d) {
  const x = new Date(d);
  const day = x.getDay() || 7;
  x.setDate(x.getDate() - day + 1);
  x.setHours(0, 0, 0, 0);
  return x;
}

function fmtDate(d) {
  return d.toISOString().slice(0, 10);
}

function addDays(d, n) {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

async function renderInterviewCalendar(stageKey) {
  ivCal.type = stageKey;
  if (!ivCal.weekStart) ivCal.weekStart = mondayOf(new Date());
  const meta = state.stages.find(s => s.key === stageKey);
  const from = fmtDate(ivCal.weekStart);
  const to = fmtDate(addDays(ivCal.weekStart, 6));
  const icfg = state.app.interview || { slot_minutes: 45, time_step_minutes: 5 };
  const [cal, tOpts] = await Promise.all([
    api(`/api/interview/calendar?type=${stageKey}&from=${from}&to=${to}`),
    api("/api/interview/time-options"),
  ]);

  const days = Array.from({ length: 7 }, (_, i) => addDays(ivCal.weekStart, i));
  const slotsByDay = {};
  days.forEach(d => { slotsByDay[fmtDate(d)] = []; });
  (cal.slots || []).forEach(s => {
    if (slotsByDay[s.date]) slotsByDay[s.date].push(s);
  });

  const timeOpts = tOpts.options || [];
  const slotMin = icfg.slot_minutes || 45;
  const html = `
    <div class="iv-subnav">
      <button class="btn btn-sm" id="iv-back-list">← 候选人列表</button>
      <div class="spacer"></div>
      <button class="btn btn-sm" id="iv-prev-wk">上一周</button>
      <span style="font-weight:600">${from} ~ ${to}</span>
      <button class="btn btn-sm" id="iv-next-wk">下一周</button>
      ${canCreate() ? `<button class="btn btn-primary btn-sm" id="iv-set-avail">+ 设置我的可面试时间</button>` : ""}
    </div>
    <div class="iv-cal-grid">
      ${days.map(d => {
        const ds = fmtDate(d);
        const daySlots = slotsByDay[ds] || [];
        const grouped = {};
        daySlots.forEach(s => {
          if (!grouped[s.interviewer_name]) grouped[s.interviewer_name] = [];
          grouped[s.interviewer_name].push(s);
        });
        return `
          <div class="iv-day-col">
            <div class="iv-day-head">${d.getMonth() + 1}/${d.getDate()} 周${"日一二三四五六"[d.getDay()]}</div>
            <div class="iv-day-body">
              ${Object.keys(grouped).length ? Object.entries(grouped).map(([name, slots]) => `
                <div class="iv-interviewer-block">
                  <div class="iv-interviewer-name">${esc(name)}</div>
                  ${slots.map(s => `
                    <div class="iv-slot ${s.booked ? "booked" : "free"}" 
                         data-start="${esc(s.start_at)}" data-iid="${s.interviewer_id}"
                         data-booked="${s.booked ? "1" : "0"}" data-bid="${s.booking?.id || ""}"
                         title="${s.booked ? esc(s.booking?.candidate_name || "已约") : "点击预约"}">
                      ${esc(s.start)}-${esc(s.end)}
                      ${s.booked ? `<span class="iv-cname">${esc(s.booking?.candidate_name || "")}</span>` : ""}
                    </div>`).join("")}
                </div>`).join("") : `<div class="iv-empty">暂无时段</div>`}
            </div>
          </div>`;
      }).join("")}
    </div>`;

  const root = $("#stage-content");
  if (root) {
    root.innerHTML = html;
    document.querySelectorAll(".iv-view-btn").forEach(b =>
      b.classList.toggle("active", b.dataset.view === "calendar"));
  } else {
    $("#main").innerHTML = `
      <div class="stage-header">
        <h2>${meta.icon || ""} ${esc(meta.label)} · 面试日程</h2>
        <p class="stage-desc">面试官设置可面试起止时间（${slotMin} 分钟/人）</p>
      </div>${html}`;
  }

  $("#iv-back-list").addEventListener("click", () => renderStageView(stageKey));
  $("#iv-prev-wk").addEventListener("click", () => {
    ivCal.weekStart = addDays(ivCal.weekStart, -7);
    renderInterviewCalendar(stageKey);
  });
  $("#iv-next-wk").addEventListener("click", () => {
    ivCal.weekStart = addDays(ivCal.weekStart, 7);
    renderInterviewCalendar(stageKey);
  });
  if ($("#iv-set-avail")) {
    $("#iv-set-avail").addEventListener("click", () => openSetAvailabilityModal(stageKey, timeOpts, slotMin));
  }
  document.querySelectorAll(".iv-slot.free").forEach(el =>
    el.addEventListener("click", () => openBookModal(stageKey, el.dataset.iid, el.dataset.start)));
  document.querySelectorAll(".iv-slot.booked").forEach(el =>
    el.addEventListener("click", () => {
      if (canEdit() && el.dataset.bid)
        openCancelBookModal(el.dataset.bid, el.querySelector(".iv-cname")?.textContent);
    }));
}

function openSetAvailabilityModal(stageKey, timeOpts, slotMin) {
  const today = fmtDate(new Date());
  const opts = timeOpts.map(t => `<option value="${t}">${t}</option>`).join("");
  openModal("设置可面试时间", `
    <p style="font-size:12px;color:#64748b;margin-bottom:12px">设置后可面试的起止时间，系统将按 ${slotMin} 分钟/段、5 分钟间隔自动生成可预约时段</p>
    <div class="form-grid">
      <div class="form-item"><label>日期 *</label><input type="date" id="iv-avail-date" value="${today}"></div>
      <div class="form-item"><label>开始时间 *</label>
        <select id="iv-avail-start">${opts}</select></div>
      <div class="form-item"><label>结束时间 *</label>
        <select id="iv-avail-end">${opts}</select></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="iv-avail-save">保存</button>`);
  $("#iv-avail-save").addEventListener("click", async () => {
    try {
      await api("/api/interview/availability", {
        method: "POST",
        json: {
          type: stageKey,
          date: $("#iv-avail-date").value,
          start_time: $("#iv-avail-start").value,
          end_time: $("#iv-avail-end").value,
        },
      });
      toast("可面试时间已设置");
      closeModal();
      renderInterviewCalendar(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

function openBookModal(stageKey, interviewerId, startAt) {
  openModal("预约面试", `
    <div class="form-item">
      <label>选择候选人 *</label>
      <select id="iv-book-cand"><option value="">加载中…</option></select>
    </div>
    <p style="font-size:12px;color:#64748b">时段：<b>${esc(startAt)}</b></p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="iv-book-go">确认预约</button>`);
  api(`/api/candidates?stage=${stageKey}`).then(list => {
    const sel = $("#iv-book-cand");
    sel.innerHTML = `<option value="">请选择</option>` +
      list.map(c => `<option value="${c.id}">${esc(c.data.name)} (${esc(c.data.phone || "")})</option>`).join("");
  });
  $("#iv-book-go").addEventListener("click", async () => {
    const cid = +$("#iv-book-cand").value;
    if (!cid) { toast("请选择候选人", true); return; }
    try {
      await api("/api/interview/book", {
        method: "POST",
        json: { type: stageKey, candidate_id: cid, interviewer_id: +interviewerId, start_at: startAt },
      });
      toast("预约成功");
      closeModal();
      renderInterviewCalendar(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

function openCancelBookModal(bid, cname) {
  openModal("取消预约", `<p>确定取消「<b>${esc(cname || "")}</b>」的面试预约吗？</p>`,
    `<button class="btn" onclick="closeModal()">返回</button>
     <button class="btn btn-danger" id="iv-cancel-go">确认取消</button>`);
  $("#iv-cancel-go").addEventListener("click", async () => {
    try {
      await api(`/api/interview/book/${bid}`, { method: "DELETE" });
      toast("已取消预约");
      closeModal();
      renderInterviewCalendar(ivCal.type);
    } catch (e) { toast(e.message, true); }
  });
}
