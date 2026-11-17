import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { chromium } from "playwright-core";
import { describeModel } from "../model-label.ts";

const PLUGIN_ID = "sidebar-model-label";
const LABEL = "[data-sidebar-model-label]";
const NARROW_SIDEBAR_PX = 220;
const KEEP_SAVED_SIDEBAR_WIDTH = null;
const SCENARIOS = {
  wide: { sidebarWidth: KEEP_SAVED_SIDEBAR_WIDTH, windowHeight: 1000 },
  narrow: { sidebarWidth: NARROW_SIDEBAR_PX, windowHeight: 1000 },
  scrollingStickyRows: { sidebarWidth: KEEP_SAVED_SIDEBAR_WIDTH, windowHeight: 360 },
};

const serverUrl = process.env.BB_SERVER_URL;
if (!serverUrl) throw new Error("Set BB_SERVER_URL to the bb server.");
const executablePath = process.env.BB_VERIFY_CHROMIUM ?? chromium.executablePath();
if (!existsSync(executablePath)) {
  throw new Error("Set BB_VERIFY_CHROMIUM to an existing Chromium executable.");
}
function parseRun([argument]) {
  if (argument === "--baseline") return { kind: "baseline" };
  if (argument === "--cleanup") return { kind: "cleanup" };
  return { kind: "check", baselinePath: argument ?? null };
}
const run = parseRun(process.argv.slice(2));

function pluginEnabled() {
  const plugins = JSON.parse(
    execFileSync("bb", ["plugin", "list", "--json"], { encoding: "utf8" }),
  );
  return (Array.isArray(plugins) ? plugins : plugins.plugins).some(
    (plugin) => plugin.id === PLUGIN_ID && plugin.enabled,
  );
}

function measureRows() {
  const px = (value) => Math.round(value * 2) / 2;
  const sidebarLeft = document.querySelector('[data-sidebar="content"]').getBoundingClientRect().left;
  const rect = (element) => {
    const box = element.getBoundingClientRect();
    return { left: px(box.left - sidebarLeft), right: px(box.right - sidebarLeft), top: px(box.top), bottom: px(box.bottom) };
  };
  const probe = document.createElement("div");
  probe.style.height = "var(--bb-sidebar-row-height)";
  document.body.append(probe);
  const rowHeight = probe.getBoundingClientRect().height;
  probe.remove();
  const seen = new Map();
  const rows = [...document.querySelectorAll("a[data-sidebar-thread-id]")].map((anchor) => {
    const id = anchor.dataset.sidebarThreadId;
    const occurrence = seen.get(id) ?? 0;
    seen.set(id, occurrence + 1);
    const row = anchor.closest("[data-sidebar-rename-row]");
    const leading = anchor.parentElement;
    const title = leading?.querySelector(".bb-thread-title");
    const label = title?.parentElement?.querySelector(":scope > [data-sidebar-model-label]");
    const icon = leading?.querySelector("[data-sidebar-thread-provider]");
    const trailing = row?.querySelector("[data-sidebar-thread-trailing]");
    return {
      key: `${id}#${occurrence}`,
      threadId: id,
      providerId: icon?.dataset.sidebarThreadProvider ?? null,
      stickyTier: row?.dataset.sidebarStickyTier ?? null,
      row: row && rect(row),
      rowPaddingLeft: row && getComputedStyle(row).paddingLeft,
      anchor: rect(anchor),
      title: title && rect(title),
      titleTextOverflow: title?.firstElementChild
        ? getComputedStyle(title.firstElementChild).textOverflow
        : null,
      titleTruncated: title?.firstElementChild
        ? title.firstElementChild.scrollWidth > title.firstElementChild.clientWidth
        : null,
      icon: icon && rect(icon),
      trailing: trailing && rect(trailing),
      label: label && {
        ...rect(label),
        text: label.textContent,
        textWidth: px(label.getBoundingClientRect().width - parseFloat(getComputedStyle(label).paddingLeft)),
        afterTitle: label.previousElementSibling === title,
        lines: Math.round(label.getBoundingClientRect().height / parseFloat(getComputedStyle(label).lineHeight)),
      },
      labelCount: title?.parentElement?.querySelectorAll(":scope > [data-sidebar-model-label]").length ?? 0,
    };
  });
  return { rowHeight, rows };
}

function checkRows({ rowHeight, rows }, where) {
  const labeled = rows.filter((row) => row.label);
  assert.ok(labeled.length > 0, `${where}: no sidebar title line shows a model label`);
  for (const row of rows) {
    const at = `${where} ${row.key}`;
    assert.ok(row.labelCount <= 1, `${at}: ${row.labelCount} labels on one title`);
    if (!row.row) continue;
    const height = row.row.bottom - row.row.top;
    if (row.stickyTier !== "label") {
      assert.equal(height, rowHeight, `${at}: row is ${height}px tall, expected ${rowHeight}px`);
    }
    if (!row.label) continue;
    const { label, title } = row;
    assert.ok(label.afterTitle, `${at}: label is not right after the title`);
    assert.equal(label.lines, 1, `${at}: label wraps`);
    assert.ok(label.left >= title.right - 0.5, `${at}: label overlaps the title`);
    const labelMiddle = (label.top + label.bottom) / 2;
    const titleMiddle = (title.top + title.bottom) / 2;
    assert.ok(Math.abs(labelMiddle - titleMiddle) <= 1.5, `${at}: label is not on the title line`);
    assert.ok(label.top >= row.row.top && label.bottom <= row.row.bottom, `${at}: label leaves the row`);
    assert.ok(label.right <= row.anchor.right + 0.5, `${at}: label leaves the click target`);
    if (row.trailing) {
      assert.ok(label.right <= row.trailing.left + 0.5, `${at}: label overlaps the row actions`);
    }
    if (row.icon) assert.ok(row.icon.right <= title.left, `${at}: provider icon moved after the title`);
    assert.equal(row.titleTextOverflow, "ellipsis", `${at}: title lost its ellipsis`);
    assert.ok(title.right - title.left >= label.textWidth, `${at}: label text is wider than the title`);
  }
  return labeled.length;
}

async function checkStickyWhileScrolling(page, where) {
  let stuckChecks = 0;
  let deepestStack = 0;
  const max = await page.evaluate(() => {
    const scroller = document.querySelector('[data-sidebar="content"]');
    return scroller ? scroller.scrollHeight - scroller.clientHeight : 0;
  });
  for (let offset = 0; offset <= max; offset += 20) {
    const stuck = await page.evaluate(async (top) => {
      const scroller = document.querySelector('[data-sidebar="content"]');
      scroller.scrollTop = top;
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const scrollerTop = scroller.getBoundingClientRect().top;
      return [...scroller.querySelectorAll("[data-sidebar-sticky-tier]")]
        .map((row) => {
          const box = row.getBoundingClientRect();
          const title = row.querySelector(".bb-thread-title");
          const label = row.querySelector("[data-sidebar-model-label]");
          const stickyTop = parseFloat(getComputedStyle(row).top);
          return {
            tier: row.dataset.sidebarStickyTier,
            stuck: Math.abs(box.top - scrollerTop - stickyTop) < 1 && top > 0,
            top: box.top,
            bottom: box.bottom,
            title: title && title.getBoundingClientRect().toJSON(),
            label: label && label.getBoundingClientRect().toJSON(),
          };
        })
        .filter((row) => row.stuck)
        .sort((a, b) => a.top - b.top);
    }, offset);
    deepestStack = Math.max(deepestStack, stuck.length);
    for (let index = 0; index < stuck.length; index++) {
      const row = stuck[index];
      const at = `${where} scrollTop=${offset} stuck row ${index}`;
      const previous = stuck[index - 1];
      if (previous) {
        assert.ok(row.top >= previous.bottom - 0.5, `${at}: overlaps the sticky row above it`);
      }
      if (row.title) {
        assert.ok(row.title.top >= row.top - 0.5 && row.title.bottom <= row.bottom + 0.5, `${at}: title is clipped`);
      }
      if (row.label) {
        const middle = (row.label.top + row.label.bottom) / 2;
        assert.ok(Math.abs(middle - (row.title.top + row.title.bottom) / 2) <= 1.5, `${at}: label left the title line`);
      }
      stuckChecks++;
    }
  }
  await page.evaluate(() => {
    document.querySelector('[data-sidebar="content"]').scrollTop = 0;
  });
  return { stuckChecks, deepestStack };
}

const withoutVerticalPosition = (box) => box && { left: box.left, right: box.right, height: box.bottom - box.top };

function compareWithBaseline(baseline, current, where) {
  const before = new Map(baseline.rows.map((row) => [row.key, row]));
  let compared = 0;
  for (const row of current.rows) {
    const old = before.get(row.key);
    if (!old || !old.row || !row.row) continue;
    const at = `${where} ${row.key}`;
    assert.deepEqual(withoutVerticalPosition(row.row), withoutVerticalPosition(old.row), `${at}: row box changed`);
    assert.equal(row.rowPaddingLeft, old.rowPaddingLeft, `${at}: indentation changed`);
    assert.deepEqual(withoutVerticalPosition(row.anchor), withoutVerticalPosition(old.anchor), `${at}: click target changed`);
    assert.deepEqual(withoutVerticalPosition(row.icon), withoutVerticalPosition(old.icon), `${at}: provider icon moved`);
    assert.deepEqual(withoutVerticalPosition(row.trailing), withoutVerticalPosition(old.trailing), `${at}: row actions moved`);
    assert.equal(row.title?.left, old.title?.left, `${at}: title moved`);
    compared++;
  }
  return compared;
}

const catalogs = new Map();
function catalogOf(providerId) {
  if (!catalogs.has(providerId)) {
    const listed = JSON.parse(
      execFileSync("bb", ["provider", "models", providerId, "--json"], { encoding: "utf8" }),
    );
    const models = Array.isArray(listed) ? listed : listed.models;
    catalogs.set(
      providerId,
      models.flatMap(({ id, model, displayName }) => [
        { model, displayName },
        ...(id && id !== model ? [{ model: id, displayName }] : []),
      ]),
    );
  }
  return catalogs.get(providerId);
}

async function checkLabelText({ rows }, where) {
  let checked = 0;
  for (const row of rows) {
    if (!row.label || !row.providerId) continue;
    const response = await fetch(`${serverUrl}/api/v1/threads/${row.threadId}/default-execution-options`);
    assert.ok(response.ok, `${where} ${row.key}: model lookup returned HTTP ${response.status}`);
    const options = await response.json();
    const expected = describeModel(options?.model ?? null, catalogOf(row.providerId));
    assert.equal(row.label.text, expected, `${where} ${row.key}: label shows the wrong model`);
    checked++;
  }
  return checked;
}

async function narrowSidebarInPageOnly(page, sidebarWidth) {
  await page.evaluate((width) => {
    for (const element of document.querySelectorAll('[data-sidebar="panel"], [data-sidebar="gap"]')) {
      element.style.setProperty("--sidebar-width", `${width}px`);
    }
    const body = document.querySelector('[data-testid="app-sidebar-body"]').parentElement;
    body.style.width = `calc(${width}px - var(--sidebar-rail-width))`;
  }, sidebarWidth);
  await page.waitForTimeout(500);
  const widths = await page.evaluate(() => ({
    panel: document.querySelector('[data-sidebar="panel"]').getBoundingClientRect().width,
    content: document.querySelector('[data-sidebar="content"]').getBoundingClientRect().width,
  }));
  assert.equal(widths.panel, sidebarWidth, "The sidebar panel did not narrow.");
  assert.ok(widths.content < sidebarWidth, `The sidebar body did not narrow (${widths.content}px).`);
}

async function openSidebar(browser, { sidebarWidth, windowHeight } = SCENARIOS.wide) {
  const page = await browser.newPage({ viewport: { width: 1440, height: windowHeight } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(serverUrl);
  await page.locator("a[data-sidebar-thread-id]").first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1_000);
  if (sidebarWidth !== KEEP_SAVED_SIDEBAR_WIDTH) await narrowSidebarInPageOnly(page, sidebarWidth);
  return { page, errors };
}

async function waitForLabels(page) {
  await page.waitForSelector(LABEL, { timeout: 15_000 }).catch(() => {});
  await page.waitForTimeout(500);
}

const browser = await chromium.launch({ executablePath, headless: true });
try {
  if (run.kind === "baseline") {
    assert.equal(pluginEnabled(), false, `Disable ${PLUGIN_ID} before taking a baseline.`);
    const baseline = {};
    for (const [where, scenario] of Object.entries(SCENARIOS)) {
      const { page } = await openSidebar(browser, scenario);
      baseline[where] = await page.evaluate(measureRows);
      await page.close();
    }
    console.log(JSON.stringify(baseline));
  } else if (run.kind === "cleanup") {
    assert.equal(pluginEnabled(), true, `Enable ${PLUGIN_ID} before the cleanup check.`);
    const { page, errors } = await openSidebar(browser);
    await waitForLabels(page);
    const labeled = checkRows(await page.evaluate(measureRows), "before reload");
    execFileSync("bb", ["plugin", "reload", PLUGIN_ID], { stdio: "pipe" });
    await page.waitForTimeout(3_000);
    await waitForLabels(page);
    checkRows(await page.evaluate(measureRows), "after reload");
    execFileSync("bb", ["plugin", "disable", PLUGIN_ID], { stdio: "pipe" });
    await page.waitForFunction((selector) => !document.querySelector(selector), LABEL, { timeout: 15_000 });
    const after = await page.evaluate(measureRows);
    assert.equal(after.rows.filter((row) => row.labelCount > 0).length, 0);
    assert.deepEqual(errors, []);
    console.log(`PASS cleanup: ${labeled} labels survived a reload without duplicates and disappeared on disable without a page reload.`);
  } else {
    assert.equal(pluginEnabled(), true, `Enable ${PLUGIN_ID} before the layout check.`);
    const baseline = run.baselinePath ? JSON.parse(readFileSync(run.baselinePath, "utf8")) : null;
    for (const [where, scenario] of Object.entries(SCENARIOS)) {
      const { page, errors } = await openSidebar(browser, scenario);
      await waitForLabels(page);
      const current = await page.evaluate(measureRows);
      const labeled = checkRows(current, where);
      const texts = await checkLabelText(current, where);
      const compared = baseline ? compareWithBaseline(baseline[where], current, where) : 0;
      const { stuckChecks, deepestStack } = await checkStickyWhileScrolling(page, where);
      if (where === "scrollingStickyRows") {
        assert.ok(deepestStack >= 2, `${where}: sticky rows never stacked while scrolling`);
      }
      assert.deepEqual(errors, [], `${where}: page errors`);
      await page.close();
      console.log(`PASS ${where}: ${labeled} labeled rows at ${current.rowHeight}px, ${texts} label texts match the thread's model, ${compared} rows match the baseline, ${stuckChecks} stuck row positions checked, up to ${deepestStack} stacked.`);
    }
  }
} finally {
  await browser.close();
}
