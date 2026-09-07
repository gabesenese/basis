import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;
const SHOTS = process.env.BASIS_QA_SHOTS ?? "qa/shots";
const TICKER = process.env.BASIS_QA_TICKER ?? "NVDA";

/*
  Drives the search and the company screen the way a person does, and checks
  the two things a screenshot cannot: that every window really redraws against
  its own series, and that a company nobody has opened before collects itself
  on the first open rather than answering with an empty chart.
*/
const WINDOWS = ["1D", "5D", "1M", "6M", "1A", "5A"];

const WINDOW_GRANULARITY = {
  "1D": "M1",
  "5D": "M5",
  "1M": "H1",
  "6M": "D",
  "1A": "D",
  "5A": "D",
};

mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

const EXPECTED_NOISE = /status of 401/;
page.on("console", (message) => {
  if (message.type() === "error" && !EXPECTED_NOISE.test(message.text())) {
    problems.push(`console: ${message.text()}`);
  }
});
page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
page.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400 && response.status() !== 401) {
    problems.push(`http ${response.status()} ${response.url()}`);
  }
});

/*
  The chart draws to a canvas, so the series cannot be counted by element. What
  it does render as text is the footer, which states how many bars of which
  granularity are on screen, and that is the number the assertion wants anyway:
  it comes from the payload the chart was handed.
*/
async function candleCount() {
  const footer = await page
    .locator("p")
    .filter({ hasText: /yahoo_chart/ })
    .first()
    .innerText();
  const leading = footer.match(/^[\d.,]+/);
  return leading ? Number(leading[0].replace(/\D/g, "")) : 0;
}

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });

await page.fill('input[aria-label="Buscar"]', "apple");
await page.waitForTimeout(900);
const hits = await page.textContent("body");
if (!hits.includes("AAPL")) problems.push("searching apple did not return AAPL");
await page.screenshot({ path: `${SHOTS}/10-buscar-digitando.png`, fullPage: true });

/*
  Enter opens whichever row the cursor is on, and the cursor starts on the
  first. Checking that the company which opens is the company that row named is
  the whole point: a route that lands somewhere plausible is not the same as a
  route that lands where the reader pointed.
*/
const chosen = await page.locator("button").filter({ hasText: "AAPL" }).first().innerText();
await page.keyboard.press("Enter");
await page.waitForURL("**/empresa/**", { timeout: 30000 });
await page.waitForTimeout(3000);
const landed = await page.textContent("body");
if (!chosen.includes("AAPL")) problems.push("the first result was not AAPL");
if (!landed.includes("Apple Inc"))
  problems.push("Enter on the first result did not open Apple Inc.");

await page.goto(`${BASE}/empresa/${TICKER}`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);

const drawn = {};
for (const window of WINDOWS) {
  await page.getByRole("button", { name: window, exact: true }).click();
  await page.waitForTimeout(2600);

  const body = await page.textContent("body");
  if (body.includes("NaN") || body.includes("undefined") || body.includes("Invalid Date")) {
    problems.push(`${window} rendered NaN, undefined or Invalid Date`);
  }
  if (body.includes("O feed não respondeu")) {
    problems.push(`${window} could not reach the feed`);
  }

  drawn[window] = await candleCount();
  if (drawn[window] < 20) problems.push(`${window} drew ${drawn[window]} bars, expected a series`);

  const painted = await page.evaluate(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) return "no canvas";
    return canvas.width > 100 && canvas.height > 100 ? "ok" : "canvas has no size";
  });
  if (painted !== "ok") problems.push(`${window}: ${painted}`);

  await page.screenshot({ path: `${SHOTS}/11-${TICKER}-${window}.png`, fullPage: true });
}

if (new Set(Object.values(drawn)).size === 1) {
  problems.push(`every window drew the same ${drawn["6M"]} bars, so the control changes nothing`);
}

/*
  A second pass over the same windows, timed.

  The first pass collected each series, and collecting means one round trip to
  a feed that cannot be hurried. Every pass after that is answered from the
  store, and it is the one a reader actually lives in: they change the window,
  change it back, and compare. What that costs is measured from the click to
  the moment the chart has finished redrawing at its new size, so it includes
  the request, the render and the paint rather than just the server.
*/
/*
  One budget, because there is only one thing happening.

  Every window whose series this machine already holds is answered from
  Postgres, and a refresh from the feed runs behind the response rather than in
  front of it. So a switch is a database read whether or not the series was due
  a refresh, and a single number is the honest way to hold it.

  The blocking fetch that remains is a series never collected here, which is
  collection rather than redrawing, and the first pass over the windows is what
  pays it.
*/
const SWITCH_BUDGET_MS = 250;
const took = {};
const blocked = [];

page.on("response", async (response) => {
  if (!response.url().includes("/bars?")) return;
  try {
    const body = await response.json();
    if (body.collected) blocked.push(body.granularity);
  } catch {
    /* a response that is not json is already reported by the status listener */
  }
});

/*
  Cleared here, so what it records is the timed pass. The first pass over the
  windows is allowed to block, because that is where a series this machine has
  never held gets collected.
*/
blocked.length = 0;

for (const window of WINDOWS) {
  const expected = drawn[window];
  const started = Date.now();

  await page.getByRole("button", { name: window, exact: true }).click();
  await page.waitForFunction(
    (want) => {
      const footer = [...document.querySelectorAll("p")].find((node) =>
        node.textContent.includes("yahoo_chart"),
      );
      if (!footer) return false;
      const leading = footer.textContent.trim().match(/^[\d.,]+/);
      return leading ? Number(leading[0].replace(/\D/g, "")) === want : false;
    },
    expected,
    { timeout: 8000 },
  );

  took[window] = Date.now() - started;
  if (took[window] > SWITCH_BUDGET_MS) {
    problems.push(
      `${window} took ${took[window]}ms to redraw, over the ${SWITCH_BUDGET_MS}ms budget`,
    );
  }
}

await page.evaluate(() => localStorage.setItem("basis.theme", "dark"));
await page.reload({ waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.screenshot({ path: `${SHOTS}/12-${TICKER}-escuro.png`, fullPage: true });
await page.evaluate(() => localStorage.setItem("basis.theme", "light"));

await browser.close();

console.log("bars per window", drawn);
console.log("warm switch, ms", took);
if (blocked.length) {
  problems.push(`a warm switch still blocked on the feed: ${blocked.join(", ")}`);
}
if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("company clean");
