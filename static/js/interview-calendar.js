/* 技术面/主管面：面试官日程设置与接口人预约日历 */
"use strict";

const ivCal = {
  type: null,
  weekStart: null,
  positionFilter: "",
  deptFilter: "",
};

function ivPositionOptions() {
  return (state.app.interview && state.app.interview.position_options)
    || ["软件岗", "测试岗", "算法岗"];
}

function ivDeptOptions(cal) {
  const fromApi = (cal && cal.filter_options && cal.filter_options.departments) || [];
  const fromCfg = (state.app.user_profile && state.app.user_profile.dept_level2_options) || [];
  return [...new Set([...fromCfg, ...fromApi].filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "zh-CN"));
}

function ivCanManage(stageKey) {
  return typeof moduleWritable === "function" && moduleWritable(stageKey || ivCal.type);
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

function dayLabel(d) {
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function dayLabelFull(d) {
  return `${dayLabel(d)} 周${"日一二三四五六"[d.getDay()]}`;
}

function ivSplitHm(hm) {
  const parts = String(hm || "09:00").split(":");
  return {
    h: Math.max(0, Math.min(23, parseInt(parts[0], 10) || 0)),
    m: Math.max(0, Math.min(59, parseInt(parts[1], 10) || 0)),
  };
}

function ivComposeHm(h, m) {
  const hh = Math.max(0, Math.min(23, parseInt(h, 10) || 0));
  const mm = Math.max(0, Math.min(59, parseInt(m, 10) || 0));
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

function ivHmInputsHtml(clsPrefix, hm) {
  const { h, m } = ivSplitHm(hm);
  return `
    <div class="iv-hm-inputs">
      <input type="number" class="iv-hm-h ${clsPrefix}-h" min="0" max="23" value="${h}" aria-label="时">
      <span class="iv-hm-sep">:</span>
      <input type="number" class="iv-hm-m ${clsPrefix}-m" min="0" max="59" step="1" value="${m}" aria-label="分">
    </div>`;
}

/** 汇总本周：行=面试官，列=日期 */
function buildWeekMatrix(allSlots) {
  const ivMap = new Map();
  allSlots.forEach(s => {
    const key = String(s.interviewer_id);
    if (!ivMap.has(key)) {
      ivMap.set(key, {
        id: s.interviewer_id,
        name: s.interviewer_name,
        roles: s.job_roles || [],
        dept: s.interviewer_dept || "",
      });
    }
  });
  const interviewers = [...ivMap.values()].sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
  const byIvDate = {};
  allSlots.forEach(s => {
    const ik = String(s.interviewer_id);
    if (!byIvDate[ik]) byIvDate[ik] = {};
    if (!byIvDate[ik][s.date]) byIvDate[ik][s.date] = [];
    byIvDate[ik][s.date].push(s);
  });
  Object.values(byIvDate).forEach(byDate => {
    Object.values(byDate).forEach(list => list.sort((a, b) => a.start.localeCompare(b.start)));
  });
  return { interviewers, byIvDate };
}

function renderSlotChip(s, ivName, stageKey, canManage) {
  const { h, m } = ivSplitHm(s.start);
  const timeLabel = `${h}时${String(m).padStart(2, "0")}分`;
  if (s.booked) {
    const pos = s.booking?.interview_position;
    const cname = s.booking?.candidate_name || "已约";
    return `<div class="iv-slot-chip booked">
      <span class="iv-chip-time">${esc(timeLabel)}</span>
      <span class="iv-cname" title="${esc(cname)}">${esc(cname)}</span>
      ${pos ? `<span class="iv-tag">${esc(pos)}</span>` : ""}
      ${canManage ? `<button type="button" class="iv-cancel-btn iv-action-muted" data-bid="${s.booking?.id || ""}" data-cname="${esc(cname)}">取消</button>` : ""}
    </div>`;
  }
  return `<div class="iv-slot-chip free" data-start="${esc(s.start_at)}" data-iid="${s.interviewer_id}" data-aid="${s.availability_id || ""}">
    <span class="iv-chip-time">${esc(timeLabel)}</span>
    <button type="button" class="iv-book-btn">可约</button>
    ${canManage && s.availability_id
      ? `<button type="button" class="iv-del-avail-btn iv-action-muted" data-aid="${s.availability_id}" data-label="${esc(ivName)} ${esc(s.date)} ${esc(timeLabel)}">删除</button>`
      : ""}
  </div>`;
}

/** 周视图：纵轴=面试官，横轴=日期，单元格嵌入各时段 */
function renderWeekMatrix(allSlots, days, stageKey) {
  const { interviewers, byIvDate } = buildWeekMatrix(allSlots);
  const canManage = ivCanManage(stageKey);

  if (!interviewers.length) {
    return `<div class="iv-empty">本周暂无面试官可约时段</div>`;
  }

  return `
    <div class="iv-matrix-wrap">
      <table class="iv-matrix iv-matrix-week">
        <thead>
          <tr>
            <th class="iv-iv-head">面试官</th>
            ${days.map(d => {
              const ds = fmtDate(d);
              const dayCount = interviewers.reduce((n, iv) =>
                n + ((byIvDate[String(iv.id)] || {})[ds] || []).length, 0);
              const freeCount = interviewers.reduce((n, iv) =>
                n + ((byIvDate[String(iv.id)] || {})[ds] || []).filter(x => !x.booked).length, 0);
              return `<th class="iv-date-col">
                <div class="iv-date-main">${dayLabelFull(d)}</div>
                <div class="iv-day-count">${freeCount} 可约 / ${dayCount} 段</div>
              </th>`;
            }).join("")}
          </tr>
        </thead>
        <tbody>
          ${interviewers.map(iv => `
            <tr>
              <td class="iv-iv-head">
                <div class="iv-iv-name">${esc(iv.name)}</div>
                ${iv.dept ? `<div class="iv-iv-dept muted">${esc(iv.dept)}</div>` : ""}
                ${iv.roles && iv.roles.length
                  ? `<div class="iv-iv-tags">${iv.roles.map(r => `<span class="iv-tag">${esc(r)}</span>`).join("")}</div>`
                  : `<div class="iv-iv-tags muted">未配置岗位</div>`}
              </td>
              ${days.map(d => {
                const ds = fmtDate(d);
                const slots = (byIvDate[String(iv.id)] || {})[ds] || [];
                if (!slots.length) return `<td class="iv-day-cell empty"><span class="iv-dash">—</span></td>`;
                return `<td class="iv-day-cell">
                  <div class="iv-slot-stack">${slots.map(s => renderSlotChip(s, iv.name, stageKey, canManage)).join("")}</div>
                </td>`;
              }).join("")}
            </tr>`).join("")}
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
  const posQ = ivCal.positionFilter ? `&position=${encodeURIComponent(ivCal.positionFilter)}` : "";
  const deptQ = ivCal.deptFilter ? `&department=${encodeURIComponent(ivCal.deptFilter)}` : "";
  const cal = await api(`/api/interview/calendar?type=${stageKey}&from=${from}&to=${to}${posQ}${deptQ}`);

  const days = Array.from({ length: 7 }, (_, i) => addDays(ivCal.weekStart, i));
  const allSlots = cal.slots || [];
  const posOpts = ivPositionOptions();
  const deptOpts = ivDeptOptions(cal);
  const defaultSlotMin = (cal.config && cal.config.slot_minutes) || (state.app.interview || {}).slot_minutes || 45;

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
      <label class="iv-filter-label">面试官部门
        <select id="iv-dept-filter">
          <option value="">全部</option>
          ${deptOpts.map(d => `<option value="${esc(d)}" ${ivCal.deptFilter === d ? "selected" : ""}>${esc(d)}</option>`).join("")}
        </select>
      </label>
      <button class="btn btn-sm" id="iv-prev-wk">上一周</button>
      <span style="font-weight:600">${from} ~ ${to}</span>
      <button class="btn btn-sm" id="iv-next-wk">下一周</button>
      <button class="btn btn-primary btn-sm" id="iv-set-avail">+ 设置可面试时间</button>
    </div>
    <p class="iv-hint">纵轴为面试官，横轴为日期；可按岗位、部门筛选。绿色「可约」可预约，黄色为已预约。</p>
    <div class="iv-week-panel">
      ${renderWeekMatrix(allSlots, days, stageKey)}
    </div>`;

  const root = $("#stage-content");
  if (root) {
    root.innerHTML = html;
    document.querySelectorAll(".iv-view-btn").forEach(b =>
      b.classList.toggle("active", b.dataset.view === "calendar"));
  } else {
    $("#main").innerHTML = `
      <div class="page-wrap">
        <div class="card pagehead">
          <div class="pagehead-text">
            <div class="pagehead-title">${esc(meta.numbered_label || meta.label)} · 面试日程</div>
            <div class="pagehead-sub">面试官 × 日期矩阵，支持岗位、部门筛选</div>
          </div>
        </div>
        <div>${html}</div>
      </div>`;
  }

  bindInterviewCalendarEvents(stageKey, defaultSlotMin);
}

function bindInterviewCalendarEvents(stageKey, defaultSlotMin) {
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
  $("#iv-dept-filter").addEventListener("change", e => {
    ivCal.deptFilter = e.target.value;
    renderInterviewCalendar(stageKey);
  });
  $("#iv-set-avail").addEventListener("click", () => openSetAvailabilityModal(stageKey, defaultSlotMin));

  document.querySelectorAll(".iv-book-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const chip = btn.closest(".iv-slot-chip.free");
      if (chip) openBookModal(stageKey, chip.dataset.iid, chip.dataset.start);
    });
  });
  document.querySelectorAll(".iv-cancel-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openCancelBookModal(btn.dataset.bid, btn.dataset.cname, stageKey);
    });
  });
  document.querySelectorAll(".iv-del-avail-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      openDeleteAvailabilityModal(btn.dataset.aid, btn.dataset.label, stageKey);
    });
  });
}

function ivEmployeeSuggestHtml() {
  return `
    <div class="iv-avail-interviewer">
      <label class="iv-avail-label">面试官</label>
      <div class="emp-suggest-wrap">
        <input type="text" id="iv-interviewer-q" class="iv-avail-input emp-suggest-input" placeholder="工号或姓名" autocomplete="off">
        <div class="emp-suggest-list hidden" id="iv-interviewer-suggest" role="listbox"></div>
      </div>
      <div class="iv-avail-resolved">
        <span>姓名：<b id="iv-interviewer-name">—</b></span>
        <span>工号：<b id="iv-interviewer-username" class="mono">—</b></span>
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

function ivAvailRowHtml(today, row) {
  const date = row?.date || today;
  const start = row?.start_time || "09:00";
  const mins = row?.slot_minutes ?? 45;
  return `
    <div class="iv-avail-row">
      <div class="iv-avail-field">
        <label>日期</label>
        <input type="date" class="iv-row-date iv-avail-input" value="${esc(date)}">
      </div>
      <div class="iv-avail-field iv-avail-field-hm">
        <label>开始</label>
        ${ivHmInputsHtml("iv-row", start)}
      </div>
      <div class="iv-avail-field iv-avail-field-sm">
        <label>间隔(分)</label>
        <input type="number" class="iv-row-min iv-avail-input" min="15" max="180" step="5" value="${mins}">
      </div>
      <button type="button" class="iv-row-rm iv-action-muted" title="删除此行">×</button>
    </div>`;
}

function bindIvAvailRows(container) {
  container.querySelectorAll(".iv-row-rm").forEach(btn => {
    btn.addEventListener("click", () => {
      const rows = container.querySelectorAll(".iv-avail-row");
      if (rows.length <= 1) {
        toast("至少保留一行", true);
        return;
      }
      btn.closest(".iv-avail-row")?.remove();
    });
  });
}

function collectIvAvailEntries(container) {
  const entries = [];
  container.querySelectorAll(".iv-avail-row").forEach(row => {
    const date = row.querySelector(".iv-row-date")?.value?.trim();
    const start_time = ivComposeHm(
      row.querySelector(".iv-row-h")?.value,
      row.querySelector(".iv-row-m")?.value,
    );
    const slot_minutes = Math.max(15, Math.min(180, parseInt(row.querySelector(".iv-row-min")?.value, 10) || 45));
    if (date) entries.push({ date, start_time, slot_minutes });
  });
  return entries;
}

function formatStartAtLabel(startAt) {
  const parts = String(startAt || "").split(" ");
  if (parts.length < 2) return startAt || "";
  const { h, m } = ivSplitHm(parts[1]);
  return `${parts[0]} ${h}时${String(m).padStart(2, "0")}分`;
}

function openSetAvailabilityModal(stageKey, defaultSlotMin) {
  const today = fmtDate(new Date());

  openModal("设置可面试时间", `
    <div class="iv-avail-modal">
      ${ivEmployeeSuggestHtml()}
      <div class="iv-avail-section">
        <div class="iv-avail-rows-head">
          <span>日期</span><span>开始时刻</span><span>间隔</span><span></span>
        </div>
        <div id="iv-avail-rows">${ivAvailRowHtml(today, { slot_minutes: defaultSlotMin || 45 })}</div>
        <button type="button" class="btn btn-sm iv-avail-add" id="iv-avail-add">+ 添加时段</button>
      </div>
    </div>`,
    `<button class="btn" onclick="closeModal()">取消</button>
     <button class="btn btn-primary" id="iv-avail-save">保存</button>`);

  bindIvInterviewerSuggest();

  const rowsEl = $("#iv-avail-rows");
  bindIvAvailRows(rowsEl);

  $("#iv-avail-add").addEventListener("click", () => {
    rowsEl.insertAdjacentHTML("beforeend", ivAvailRowHtml(today, { slot_minutes: defaultSlotMin || 45 }));
    bindIvAvailRows(rowsEl);
  });

  $("#iv-avail-save").addEventListener("click", async () => {
    const q = ($("#iv-interviewer-q").value || "").trim();
    if (!q || !$("#iv-interviewer-valid").value) {
      toast("请先选择面试官", true);
      return;
    }
    const entries = collectIvAvailEntries(rowsEl);
    if (!entries.length) {
      toast("请至少填写一行完整的可面试时间", true);
      return;
    }
    try {
      const r = await api("/api/interview/availability", {
        method: "POST",
        json: { type: stageKey, interviewer: q, entries },
      });
      toast(`已设置 ${r.created} 段可面试时间`);
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
    <p class="iv-modal-hint">时段：<b>${esc(formatStartAtLabel(startAt))}</b>（电话不存在则无法预约）</p>`,
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
        infoEl.innerHTML = `已匹配：<b>${esc(r.name)}</b>${r.interview_position ? ` · 岗位 ${esc(r.interview_position)}` : ""}`;
        infoEl.classList.remove("hidden");
        if (r.interview_position && !ivCal.positionFilter) {
          ivCal.positionFilter = r.interview_position;
        }
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
        json: { type: stageKey, phone, interviewer_id: +interviewerId, start_at: startAt },
      });
      toast("预约成功");
      closeModal();
      renderInterviewCalendar(stageKey);
    } catch (e) { toast(e.message, true); }
  });
}

function openCancelBookModal(bid, cname, stageKey) {
  if (!bid) return;
  openModal("取消预约", `<p class="iv-confirm-danger">确定取消「<b>${esc(cname || "")}</b>」的面试预约吗？时段将恢复为可约。</p>`,
    `<button class="btn" onclick="closeModal()">返回</button>
     <button class="btn iv-action-muted" id="iv-cancel-go">确认取消</button>`);
  $("#iv-cancel-go").addEventListener("click", async () => {
    try {
      await api(`/api/interview/book/${bid}`, { method: "DELETE" });
      toast("已取消预约");
      closeModal();
      renderInterviewCalendar(stageKey || ivCal.type);
    } catch (e) { toast(e.message, true); }
  });
}

function openDeleteAvailabilityModal(aid, label, stageKey) {
  if (!aid) return;
  openModal("删除可面试时间", `<p class="iv-confirm-danger">确定删除「<b>${esc(label || "该时段")}</b>」的可面试安排吗？</p>`,
    `<button class="btn" onclick="closeModal()">返回</button>
     <button class="btn iv-action-muted" id="iv-del-avail-go">确认删除</button>`);
  $("#iv-del-avail-go").addEventListener("click", async () => {
    try {
      await api(`/api/interview/availability/${aid}`, { method: "DELETE" });
      toast("已删除可面试时间");
      closeModal();
      renderInterviewCalendar(stageKey || ivCal.type);
    } catch (e) { toast(e.message, true); }
  });
}
