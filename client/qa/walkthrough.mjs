import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;
const SHOTS = process.env.BASIS_QA_SHOTS ?? "qa/shots";

const SCREENS = [
  { path: "/buscar", name: "buscar", expect: ["NVDA"] },
  { path: "/empresa/NVDA", name: "empresa", expect: ["NVIDIA", "CIK"] },
  { path: "/hoje", name: "hoje", expect: ["EUR/USD"] },
  { path: "/calendario", name: "calendario", expect: ["FOMC"] },
  { path: "/estudo", name: "estudo", expect: ["R²"] },
  { path: "/contexto", name: "contexto", expect: ["099741"] },
];

mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

/*
  A 401 is the expected answer while signed out and for the deliberate wrong
  password below, and the browser logs every one of them as a console error.
  Real API failures are still caught by the response listener.
*/
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

async function shoot(name) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function setTheme(theme) {
  await page.evaluate((next) => {
    localStorage.setItem("basis.theme", next);
  }, theme);
  await page.reload({ waitUntil: "networkidle" });
}

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await shoot("00-entrar-claro");
await setTheme("dark");
await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await shoot("01-entrar-escuro");
await setTheme("light");

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', "wrong@basis.invalid");
await page.fill('input[type="password"]', "definitely-wrong");
await page.click('button[type="submit"]');
await page.waitForSelector('[role="alert"]', { timeout: 5000 });
await shoot("02-entrar-erro");

await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });

for (const theme of ["light", "dark"]) {
  await setTheme(theme);
  for (const screen of SCREENS) {
    await page.goto(`${BASE}${screen.path}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(700);

    const body = await page.textContent("body");
    for (const needle of screen.expect) {
      if (!body.includes(needle)) {
        problems.push(`${screen.name} (${theme}) missing ${JSON.stringify(needle)}`);
      }
    }
    if (body.includes("NaN") || body.includes("undefined") || body.includes("Invalid Date")) {
      problems.push(`${screen.name} (${theme}) rendered NaN, undefined or Invalid Date`);
    }

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    if (overflow) problems.push(`${screen.name} (${theme}) scrolls horizontally`);

    await shoot(`${theme === "light" ? "1" : "2"}-${screen.name}-${theme}`);
  }
}

await setTheme("light");
await page.goto(`${BASE}/hoje`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: "EN", exact: true }).click();
await page.waitForTimeout(900);
const english = await page.textContent("body");
if (!english.includes("Today")) problems.push("language toggle did not switch to English");
await shoot("3-hoje-english");

await page.getByRole("button", { name: "PT", exact: true }).click();
await page.waitForTimeout(900);

await page.setViewportSize({ width: 420, height: 900 });
await page.goto(`${BASE}/estudo`, { waitUntil: "networkidle" });
await page.waitForTimeout(700);
const narrowOverflow = await page.evaluate(
  () => document.documentElement.scrollWidth > window.innerWidth + 1,
);
if (narrowOverflow) problems.push("estudo scrolls horizontally at 420px");
await shoot("4-estudo-mobile");

await browser.close();

if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("walkthrough clean");
