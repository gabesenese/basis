import { chromium } from "@playwright/test";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;

/*
  Kept a little above the screen's own interval, so a run that sees no second
  read is reporting a screen that stopped rather than a test that was impatient.

  The window has to outlast a minute because the stamp is rendered to the
  minute. Anything shorter can start and end inside the same one, and then a
  screen refreshing perfectly well is reported as frozen.
*/
const INTERVAL_MS = 20_000;
const WINDOW_MS = 66_000;

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

let reads = 0;
page.on("request", (request) => {
  if (request.url().includes("/api/today")) reads += 1;
});

async function setVisibility(state) {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", {
      value,
      configurable: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

function stamp() {
  return page.locator('[role="status"]').first().innerText();
}

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });
await page.goto(`${BASE}/hoje`, { waitUntil: "networkidle" });
await page.waitForSelector('[role="status"]', { timeout: 10000 });

const opened = await stamp();
reads = 0;

await page.waitForTimeout(WINDOW_MS);
const refreshes = reads;
const later = await stamp();

if (refreshes < 2) {
  problems.push(`expected at least 2 background reads in ${WINDOW_MS}ms, saw ${refreshes}`);
}
if (later === opened) {
  problems.push(`the reading did not move: still ${JSON.stringify(opened)}`);
}
if (!later.includes("Atualizado")) {
  problems.push(`a healthy refresh should read as updated, got ${JSON.stringify(later)}`);
}

await setVisibility("hidden");
reads = 0;
await page.waitForTimeout(INTERVAL_MS + 4_000);
const whileHidden = reads;
if (whileHidden !== 0) {
  problems.push(`a hidden tab kept reading: ${whileHidden} requests`);
}

await setVisibility("visible");
await page.waitForTimeout(1_500);
if (reads < 1) problems.push("returning to the tab did not read immediately");

const priceBefore = await page.locator("text=/EUR\\/USD/").first().isVisible();
await page.route("**/api/today", (route) => route.abort());
await setVisibility("hidden");
await setVisibility("visible");
await page.waitForTimeout(2_500);

const failed = await stamp();
if (!failed.includes("atualização falhou")) {
  problems.push(`a failed refresh was not announced, status reads ${JSON.stringify(failed)}`);
}
const priceAfter = await page.locator("text=/EUR\\/USD/").first().isVisible();
if (!priceBefore || !priceAfter) {
  problems.push("a failed refresh replaced the reading instead of keeping it");
}

await page.unroute("**/api/today");
await setVisibility("hidden");
await setVisibility("visible");
await page.waitForTimeout(2_500);
const recovered = await stamp();
if (!recovered.includes("Atualizado")) {
  problems.push(`the screen did not recover after the API came back: ${JSON.stringify(recovered)}`);
}

await browser.close();

if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("refresh clean");
