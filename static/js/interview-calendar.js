/* 技术面/主管面：面试官日程设置与接口人预约日历 */
"use strict";

const ivCal = {
  type: null,
  weekStart: null,
  positionFilter: "",
  slotMinutes: null,
};

function ivSlotMinutes(defaultVal) {
  if (ivCal.slotMinutes != null) return ivCal.slotMinutes;
  const saved = parseInt(localStorage.getItem("iv_slot_minutes"), 10);
  if (!Number.isNaN(saved) && saved >= 15 && saved <= 180) return saved;
  return defaultVal || 45;
}

function ivPositionOptions() {
  return (state.app.interview && state.app.interview.position_options)
    || ["软件岗", "测试岗", "算法岗"];
}

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

function buildDayMatrix(daySlots) {
  const byIv = {};
  daySlots.forEach(s => {
    const key = String(s.interviewer_id);
    if (!byIv[key]) {
      byIv[key] = {
        id: s.interviewer_id,
        name: s.interviewer_name,
        roles: s.job_roles || [],
        slots: {},
      };
    }
    byIv[key].slots[s.start_at] = s;
  });
  const interviewers = Object.values(byIv).sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  const times = [...new Set(daySlots.map(s => s.start_at))].sort();
  return { interviewers, times };
}

function renderDayMatrix(ds, daySlots) {
  if (!daySlots.length) return `<div class="iv-empty">暂无时段</div>`;
  const { interviewers, times } = buildDayMatrix(daySlots);
  return `
    <div class="iv-matrix-wrap">
      <table class="iv-matrix">
        <thead>
          <tr>
            <th class="iv-time-col">时间</th>
            ${interviewers.map(iv => `
              <th class="iv-iv-col" title="${esc((iv.roles || []).join("、"))}">
                <div class="iv-iv-name">${esc(iv.name)}</div>
                ${iv.roles && iv.roles.length
                  ? `<div class="iv-iv-tags">${iv.roles.map(r => `<span class="iv-tag">${esc(r)}</span>`).join("")}</div>`
                  : `<div class="iv-iv-tags muted">未配置岗位</div>`}
              </th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${times.map(startAt => {
            const sample = daySlots.find(s => s.start_at === startAt);
            return `<tr>
              <td class="iv-time-col">${esc(sample ? `${sample.start}-${sample.end}` : startAt.slice(11))}</td>
              ${interviewers.map(iv => {
                const s = iv.slots[startAt];
                if (!s) return `<td class="iv-cell empty"></td>`;
                if (s.booked) {
                  const pos = s.booking?.interview_position;
                  return `<td class="iv-cell booked" data-bid="${s.booking?.id || ""}" title="${esc(s.booking?.candidate_name || "")}">
                    <span class="iv-cname">${esc(s.booking?.candidate_name || "已约")}</span>
                    ${pos ? `<span class="iv-tag">${esc(pos)}</span>` : ""}
                  </td>`;
                }
                return `<td class="iv-cell free" data-start="${esc(s.start_at)}" data-iid="${s.interviewer_id}"
                  title="点击预约">可约</td>`;
              }).join("")}
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>`;
}

async function renderInterviewCalendar(stageKey) {
  ivCal.type = stageKey;
  if (!ivCal.weekStart) ivCal.weekStart = mondayOf(new Date());
  const meta = state.stages.find(s => s.key === stageKey);
  const from = fmtDate(ivCal.weekStart);
  const to = fmtDate(addDays(ivCal.weekStart, 6));
  const slotMin = ivSlotMinutes((state.app.interview || {}).slot_minutes || 45);
  const posQ = ivCal.positionFilter ? `&position=${encodeURIComponent(ivCal.positionFilter)}` : "";
  const [cal, tOpts] = await Promise.all([
    api(`/api/interview/calendar?type=${stageKey}&from=${from}&to=${to}&slot_minutes=${slotMin}${posQ}`),
    api("/api/interview/time-options"),
  ]);

  const days = Array.from({ length: 7 }, (_, i) => addDays(ivCal.weekStart, i));
  const slotsByDay = {};
  days.forEach(d => { slotsByDay[fmtDate(d)] = []; });
  (cal.slots || []).forEach(s => {
    if (slotsByDay[s.date]) slotsByDay[s.date].push(s);
  });

  const timeOpts = tOpts.options || [];
  const posOpts = ivPositionOptions();
  const html = `
    <div class="iv-subnav">
      <button class="btn btn-sm" id="iv-back-list">← 候选人列表</button>
      <div class="spacer"></div>
      <label class="iv-filter-label">待面试岗位
        <select id="iv-pos-filter">
          <option value="">全部</option>
          ${posOpts.map(p => `<option value="${esc(p)}" ${ivCal.positionFilter === p ? "selected" : ""}>${esc(p)}</option>`).join("")}
        </select>
      </label>
      <label class="iv-filter-label">面试时长(分)
        <input type="number" id="iv-slot-min" min="15" max="180" step="5" value="${slotMin}" style="width:64px">
      </label>
      <button class="btn btn-sm" id="iv-prev-wk">上一周</button>
      <span style="font-weight:600">${from} ~ ${to}</span>
      <button class="btn btn-sm" id="iv-next-wk">下一周</button>
      <button class="btn btn-primary btn-sm" id="iv-set-avail">+ 设置可面试时间</button>
    </div>
    <p class="iv-hint">横向滚动查看同一天多位面试官；绿色「可约」点击预约，黄色为已预约。默认每段 ${slotMin} 分钟。</p>
    <div class="iv-week-grid">
      ${days.map(d => {
        const ds = fmtDate(d);
        const daySlots = slotsByDay[ds] || [];
        return `
          <div class="iv-day-panel">
            <div class="iv-day-head">${d.getMonth() + 1}/${d.getDate()} 周${"日一二三四五六"[d.getDay()]}
              <span class="iv-day-count">${daySlots.filter(s => !s.booked).length} 可约 / ${daySlots.length} 段</span>
            </div>
            ${renderDayMatrix(ds, daySlots)}
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
        <p class="stage-desc">矩阵视图展示各面试官可约时段，支持按岗位筛选</p>
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
  $("#iv-pos-filter").addEventListener("change", e => {
    ivCal.positionFilter = e.target.value;
    renderInterviewCalendar(stageKey);
  });
  $("#iv-slot-min").addEventListener("change", e => {
    const v = Math.max(15, Math.min(180, parseInt(e.target.value, 10) || 45));
    ivCal.slotMinutes = v;
    localStorage.setItem("iv_slot_minutes", String(v));
    renderInterviewCalendar(stageKey);
  });
  $("#iv-set-avail").addEventListener("click", () => openSetAvailabilityModal(stageKey, timeOpts, slotMin));
  document.querySelectorAll(".iv-cell.free").forEach(el =>
    el.addEventListener("click", () => openBookModal(stageKey, el.dataset.iid, el.dataset.start)));
  document.querySelectorAll(".iv-cell.booked").forEach(el =>
    el.addEventListener("click", () => {
      if (canEdit() && el.dataset.bid) {
        const name = el.querySelector(".iv-cname")?.textContent;
        openCancelBookModal(el.dataset.bid, name);
      }
    }));
}

function ivEmployeeSuggestHtml() {
  return `
    <div class="form-item form-item-full">
      <label>面试官（工号或姓名） *</label>
      <div class="emp-suggest-wrap">
        <input type="text" id="iv-interviewer-q" class="emp-suggest-input" placeholder="输入工号或姓名，须为已注册用户" autocomplete="off">
        <div class="emp-suggest-list hidden" id="iv-interviewer-suggest" role="listbox"></div>
      </div>
      <div class="emp-resolved-meta" style="margin-top:6px">
        <span class="emp-meta-item"><span class="emp-meta-label">姓名</span><span id="iv-interviewer-name">—</span></span>
        <span class="emp-meta-item"><span class="emp-meta-label">工号</span><span id="iv-interviewer-username" class="mono">—</span></span>
      </div>
      <input type="hidden" id="iv-interviewer-valid" value="">
    </div>`;
}

function bindIvInterviewerSuggest() {
  const input = $("#iv-interviewer-q");
  const listEl = $("#iv-interviewer-suggest");
  if (!input || !listEl) return;
  let timer = null;
  let resolved = null;

  const applyUser = u => {
    resolved = u;
    input.value = u.username || "";
    $("#iv-interviewer-name").textContent = u.display_name || "—";
    $("#iv-interviewer-username").textContent = u.username || "—";
    $("#iv-interviewer-valid").value = "1";
    listEl.classList.add("hidden");
    listEl.innerHTML = "";
  };

  const clearResolved = () => {
    resolved = null;
    $("#iv-interviewer-name").textContent = "—";
    $("#iv-interviewer-username").textContent = "—";
    $("#iv-interviewer-valid").value = "";
  };

  input.addEventListener("input", () => {
    clearResolved();
    const q = input.value.trim();
    clearTimeout(timer);
    if (!q) { listEl.classList.add("hidden"); return; }
    timer = setTimeout(async () => {
      try {
        const r = await suggestEmployeesForRegistration(q);
        if (!r.items || !r.items.length) {
          listEl.innerHTML = `<div class="emp-suggest-empty">未找到匹配用户</div>`;
        } else {
          listEl.innerHTML = r.items.map(u => `
            <button type="button" class="emp-suggest-item" data-uname="${esc(u.username)}">
              <span class="mono">${esc(u.username)}</span> ${esc(u.display_name)}
              <span class="muted">${esc(u.department || "")}</span>
            </button>`).join("");
          listEl.querySelectorAll(".emp-suggest-item").forEach(btn =>
            btn.addEventListener("click", async () => {
              const body = await lookupEmployeeForRegistration(btn.dataset.uname);
              if (body.found) applyUser(body);
            }));
        }
        listEl.classList.remove("hidden");
      } catch (_) { listEl.classList.add("hidden"); }
    }, 150);
  });

  input.addEventListener("blur", () => {
    setTimeout(async () => {
      listEl.classList.add("hidden");
      if (resolved) return;
      const q = input.value.trim();
      if (!q) return;
      const body = await lookupEmployeeForRegistration(q);
      if (body.found) applyUser(body);
    }, 200);
  });
}

function openSetAvailabilityModal(stageKey, timeOpts, slotMin) {
  const today = fmtDate(new Date());
  const opts = timeOpts.map(t => `<option value="${t}">${t}</option>`).join("");
  openModal("设置可面试时间", `
    <p class="iv-modal-hint">填写面试官与可面试起止时间；系统将按 ${slotMin} 分钟/段自动生成可预约时段。</p>
    ${ivEmployeeSuggestHtml()}
    <div class="form-grid">
      <div class="form-item"><label>日期 *</label><input type="date" id="iv-avail-date" value="${today}"></div>
      <div class="form-item"><label>开始时间 *</label><select id="iv-avail-start">${opts}</select></div>
      <div class="form-item"><label>结束时间 *</label><select id="iv-avail-end">${opts}</select></div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="iv-avail-save">保存</button>`);
  bindIvInterviewerSuggest();
  $("#iv-avail-save").addEventListener("click", async () => {
    const q = ($("#iv-interviewer-q").value || "").trim();
    if (!q || !$("#iv-interviewer-valid").value) {
      toast("请先选择有效的面试官（工号或姓名须匹配已注册用户）", true);
      return;
    }
    try {
      await api("/api/interview/availability", {
        method: "POST",
        json: {
          type: stageKey,
          interviewer: q,
          date: $("#iv-avail-date").value,
          start_time: $("#iv-avail-start").value,
          end_time: $("#iv-avail-end").value,
          slot_minutes: ivSlotMinutes(slotMin),
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
      <label>候选人电话 *</label>
      <input type="text" id="iv-book-phone" placeholder="输入电话精确匹配候选人">
      <div id="iv-book-cand-info" class="iv-cand-info hidden"></div>
    </div>
    <p class="iv-modal-hint">时段：<b>${esc(startAt)}</b>（电话不存在则无法预约）</p>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="iv-book-go">确认预约</button>`);

  let matched = null;
  const phoneEl = $("#iv-book-phone");
  const infoEl = $("#iv-book-cand-info");
  let timer = null;

  phoneEl.addEventListener("input", () => {
    matched = null;
    infoEl.classList.add("hidden");
    clearTimeout(timer);
    const phone = phoneEl.value.trim();
    if (!phone) return;
    timer = setTimeout(async () => {
      try {
        const r = await api(`/api/interview/candidate-by-phone?phone=${encodeURIComponent(phone)}`);
        matched = r;
        infoEl.innerHTML = `已匹配：<b>${esc(r.name)}</b>${r.interview_position ? ` · ${esc(r.interview_position)}` : ""}`;
        infoEl.classList.remove("hidden");
      } catch (e) {
        infoEl.innerHTML = `<span class="text-danger">${esc(e.message || "未找到")}</span>`;
        infoEl.classList.remove("hidden");
      }
    }, 300);
  });

  $("#iv-book-go").addEventListener("click", async () => {
    const phone = phoneEl.value.trim();
    if (!phone) { toast("请填写候选人电话", true); return; }
    if (!matched) {
      try {
        matched = await api(`/api/interview/candidate-by-phone?phone=${encodeURIComponent(phone)}`);
      } catch (e) { toast(e.message, true); return; }
    }
    try {
      await api("/api/interview/book", {
        method: "POST",
        json: {
          type: stageKey,
          phone,
          interviewer_id: +interviewerId,
          start_at: startAt,
          slot_minutes: ivSlotMinutes(),
        },
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
