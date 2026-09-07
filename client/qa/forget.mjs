import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;
const SHOTS = process.env.BASIS_QA_SHOTS ?? "qa/shots";

/*
  Removing a company deletes a real collection, so this drives the whole round
  trip rather than the endpoint: collect a throwaway name, remove it through
  the interface, and prove it is gone from the list and from the store.

  It also proves the ask cannot be skipped and can be backed out of, because a
  single stray click must not be able to delete ten years of sessions.

  IBM is the throwaway. It is collected here and removed here, so a run leaves
  the store exactly as it found it.
*/
const THROWAWAY = "IBM";

mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
/*
  The refusal below is deliberate: this run asks the API to delete a reference
  instrument on purpose, to prove it says no. Every other failure is real.
*/
const EXPECTED_REFUSAL = /company\/EUR_USD\/collected/;

page.on("response", (response) => {
  if (
    response.url().includes("/api/") &&
    response.status() >= 400 &&
    response.status() !== 401 &&
    !(response.status() === 409 && EXPECTED_REFUSAL.test(response.url()))
  ) {
    problems.push(`http ${response.status()} ${response.url()}`);
  }
});

async function collected() {
  return page.evaluate(async () => {
    const answer = await fetch("/api/companies/collected", { credentials: "include" });
    const body = await answer.json();
    return body.companies.map((company) => company.ticker);
  });
}

/*
  Waits on the condition rather than on a stopwatch. A fixed pause is a guess
  about how long a click takes to reach the store and back, and a guess that is
  a little short reports a working removal as a broken one.
*/
async function until(check, what, limit = 10000) {
  const deadline = Date.now() + limit;
  for (;;) {
    if (check(await collected())) return true;
    if (Date.now() > deadline) {
      problems.push(`gave up after ${limit}ms waiting for ${what}`);
      return false;
    }
    await page.waitForTimeout(250);
  }
}

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });

const before = await collected();
if (before.includes(THROWAWAY)) {
  problems.push(`${THROWAWAY} was already collected, so this run cannot leave the store as it found it`);
}

await page.goto(`${BASE}/empresa/${THROWAWAY}`, { waitUntil: "networkidle" });
await until((names) => names.includes(THROWAWAY), `opening ${THROWAWAY} to collect it`);

await page.goto(`${BASE}/buscar`, { waitUntil: "networkidle" });
await page.waitForTimeout(1200);

/*
  Playwright clicks an element at zero opacity without complaint, so clicking
  the control proves nothing about whether a person can find it. What has to be
  checked is that it is invisible at rest and visible once the row is under the
  pointer, which is the whole design of the thing.
*/
const control = page.getByRole("button", { name: `Remover ${THROWAWAY}` });
const opacityNow = () => control.evaluate((node) => getComputedStyle(node).opacity);

const atRest = await opacityNow();
if (atRest !== "0") {
  problems.push(`the remove icon shows at rest with opacity ${atRest}, expected it hidden`);
}

await control.hover();
await page.waitForTimeout(400);
await page.screenshot({ path: `${SHOTS}/29-remover-hover.png`, fullPage: true });

const hovered = await opacityNow();
if (hovered !== "1") {
  problems.push(`the remove icon stayed at opacity ${hovered} on hover, so it cannot be reached`);
}

const drawn = await control.evaluate((node) => node.querySelector("svg") !== null);
if (!drawn) problems.push("the remove control is not an icon");

await control.click();
await page.waitForTimeout(400);

const asking = await page.textContent("body");
if (!asking.includes("Remover o histórico?")) {
  problems.push("removing did not ask first");
}
await page.screenshot({ path: `${SHOTS}/30-remover-pergunta.png`, fullPage: true });

await page.getByRole("button", { name: "Manter", exact: true }).click();
await page.waitForTimeout(600);

const kept = await collected();
if (!kept.includes(THROWAWAY)) {
  problems.push("backing out of the question removed the company anyway");
}

await page.getByRole("button", { name: `Remover ${THROWAWAY}` }).click();
await page.waitForTimeout(400);
await page.getByRole("button", { name: "Remover", exact: true }).click();
await until((names) => !names.includes(THROWAWAY), `${THROWAWAY} to be removed`);

const after = await collected();
if (!(await page.textContent("body")).includes("NVDA")) {
  problems.push("the collected list lost the other companies too");
}
await page.screenshot({ path: `${SHOTS}/31-removida.png`, fullPage: true });

/*
  A reference instrument is not a collected company and the API must say so.
  It is checked here rather than only in a shell, because this is the guard
  that stands between a stray request and the FOMC study.
*/
const guarded = await page.evaluate(async () => {
  const answer = await fetch("/api/company/EUR_USD/collected", {
    method: "DELETE",
    credentials: "include",
  });
  return answer.status;
});
if (guarded !== 409) {
  problems.push(`removing a reference instrument answered ${guarded}, expected 409`);
}

const stillThere = await page.evaluate(async () => {
  const answer = await fetch("/api/today", { credentials: "include" });
  const body = await answer.json();
  return body.instrument?.id ?? null;
});
if (stillThere !== "EUR_USD") {
  problems.push(`EUR_USD is no longer readable after the refused delete: ${stillThere}`);
}

await browser.close();

console.log("collected before", before.join(", "));
console.log("collected after ", after.join(", "));
if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("forget clean");
