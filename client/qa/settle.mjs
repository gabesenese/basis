import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;
const SHOTS = process.env.BASIS_QA_SHOTS ?? "qa/shots";

/*
  Measures whether a company page arrives in one piece.

  "It glitches, then I can see everything" is a description of layout shift:
  the page renders, then each arriving piece resizes the one above it and
  throws the rest down the screen. The browser scores exactly that, so the
  assertion is the browser's own number rather than an opinion about a
  screenshot.

  A page that reserves its slots and fills them scores near zero. The web vitals
  threshold for good is 0.1, and this screen knows the shape of everything it is
  waiting for, so it is held to a tenth of that.
*/
const SHIFT_BUDGET = 0.01;

mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

await page.addInitScript(() => {
  window.__shift = 0;
  window.__moves = [];
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      if (entry.hadRecentInput) continue;
      window.__shift += entry.value;
      for (const source of entry.sources ?? []) {
        const node = source.node;
        if (node) window.__moves.push(`${node.tagName ?? "?"}.${(node.className ?? "").toString().slice(0, 40)}`);
      }
    }
  }).observe({ type: "layout-shift", buffered: true });
});

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });
await page.waitForTimeout(1500);

/*
  Opened the way a reader opens it, by clicking the row, so what is measured is
  the route change rather than a fresh document load.
*/
await page.evaluate(() => {
  window.__shift = 0;
  window.__moves = [];
});

await page.getByRole("button", { name: /NVDA/ }).first().click();
await page.waitForURL("**/empresa/**", { timeout: 10000 });

/*
  Long enough to outlast every arrival on this screen: the header from the
  store, the series behind it, and the quote after its round trip to the feed.
*/
await page.waitForTimeout(5000);

const settled = await page.evaluate(() => ({
  shift: window.__shift,
  moves: [...new Set(window.__moves)].slice(0, 6),
}));

await page.screenshot({ path: `${SHOTS}/40-empresa-assentada.png`, fullPage: true });

if (settled.shift > SHIFT_BUDGET) {
  problems.push(
    `opening a company shifted the layout by ${settled.shift.toFixed(4)}, over the ${SHIFT_BUDGET} budget`,
  );
}

/*
  Switching windows must not move the page either. The chart redraws inside a
  reserved box, so nothing below it should notice.
*/
await page.evaluate(() => {
  window.__shift = 0;
  window.__moves = [];
});

for (const window_ of ["1D", "1A", "6M"]) {
  await page.getByRole("button", { name: window_, exact: true }).click();
  await page.waitForTimeout(1200);
}

const switching = await page.evaluate(() => ({
  shift: window.__shift,
  moves: [...new Set(window.__moves)].slice(0, 6),
}));

if (switching.shift > SHIFT_BUDGET) {
  problems.push(
    `changing windows shifted the layout by ${switching.shift.toFixed(4)}, over the ${SHIFT_BUDGET} budget`,
  );
}

await browser.close();

console.log("opening a company, layout shift", settled.shift.toFixed(4), settled.moves);
console.log("changing windows, layout shift", switching.shift.toFixed(4), switching.moves);

if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("settle clean");
