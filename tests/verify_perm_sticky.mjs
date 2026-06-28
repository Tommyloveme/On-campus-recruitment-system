/**
 * 验证权限矩阵横向滚动后，左表（勾选/工号/姓名）及表头仍可见。
 * 运行: node tests/verify_perm_sticky.mjs
 */
import { chromium } from "playwright";

const BASE = "http://127.0.0.1:8000";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 } });

  await page.goto(BASE + "/");
  await page.waitForFunction(() => typeof boot === "function", null, { timeout: 10000 });
  const booted = await page.evaluate(async () => {
    const r = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "admin", password: "admin123" }),
    });
    if (!r.ok) return false;
    state.me = await r.json();
    state.me.is_admin = state.me.role === "admin";
    await boot();
    return true;
  });
  if (!booted) throw new Error("login/boot failed");
  await page.waitForSelector("#app-view:not(.hidden)", { timeout: 10000 });

  const adminGroup = page.locator('.nav-group[data-group="admin_board"]');
  if (!(await adminGroup.evaluate(el => el.classList.contains("expanded")))) {
    await adminGroup.locator(".nav-parent").click();
  }
  await page.click('[data-tab="permissions"]');
  await page.waitForSelector("#perm-grid-left", { timeout: 10000 });
  await page.waitForSelector("#perm-grid-left tbody tr td.col-username", { timeout: 10000 });

  await page.locator(".perm-grid-right-wrap").evaluate(el => { el.scrollLeft = 500; });
  await page.waitForTimeout(300);

  const result = await page.evaluate(() => {
    const shell = document.querySelector(".perm-grid-shell");
    const shellL = shell?.getBoundingClientRect().left ?? 0;
    const vis = (el, needText) => {
      if (!el) return { ok: false, reason: "missing" };
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return { ok: false, reason: "zero size", r };
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const top = document.elementFromPoint(cx, cy);
      const hit = el === top || el.contains(top);
      const text = (el.textContent || "").trim();
      const ok = r.left >= shellL - 2 && (!needText || text.length > 0) && hit;
      return { ok, text, hit, r: { left: r.left, width: r.width }, shellL };
    };
    const row = document.querySelector("#perm-grid-left tbody tr");
    const headUser = document.querySelector("#perm-grid-left thead tr:first-child th.col-username");
    const headName = document.querySelector("#perm-grid-left thead tr:first-child th.col-name");
    if (!row) return { error: "no rows" };
    return {
      headerUser: vis(headUser, true),
      headerName: vis(headName, true),
      check: vis(row.querySelector("td.col-check"), false),
      username: vis(row.querySelector("td.col-username"), true),
      name: vis(row.querySelector("td.col-name"), true),
      scrollLeft: document.querySelector(".perm-grid-right-wrap")?.scrollLeft,
    };
  });

  await browser.close();

  const ok = result.headerUser?.ok && result.headerName?.ok
    && result.username?.ok && result.name?.ok && result.check?.ok;
  console.log(JSON.stringify(result, null, 2));
  if (!ok) {
    console.error("FAIL: frozen columns/headers not visible after horizontal scroll");
    process.exit(1);
  }
  console.log("PASS: split-table frozen columns visible after horizontal scroll");
}

main().catch(e => {
  console.error(e);
  process.exit(1);
});
