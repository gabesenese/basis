import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASIS_QA_BASE ?? "http://localhost:5173";
const EMAIL = process.env.BASIS_QA_EMAIL;
const PASSWORD = process.env.BASIS_QA_PASSWORD;
const SHOTS = process.env.BASIS_QA_SHOTS ?? "qa/shots";

/*
  The theme switch has one requirement that a screenshot cannot check: that the
  whole surface moves as a single animation rather than as a crowd of them
  arriving at their own pace.

  So the test samples the running animations while the switch is in flight. One
  cross-fade is correct. A colour transition on a nav link running beside it is
  the exact defect this was built to remove, and it is invisible in a still.
*/
mkdirSync(SHOTS, { recursive: true });

const problems = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));

const themeGroup = '[role="group"][aria-label="Tema"] button';

/*
  Counted by duration rather than by object, because the two are not the same
  thing. Under reduced motion the stylesheet holds every transition to a
  hundredth of a millisecond rather than removing it, so the browser still
  reports transition objects that are over before a frame is drawn. Those are
  the setting working, not motion.
*/
const MOVING_MS = 50;

async function reading(target) {
  return target.evaluate(
    (floor) => ({
      theming: document.documentElement.hasAttribute("data-theming"),
      theme: document.documentElement.getAttribute("data-theme"),
      moving: document
        .getAnimations()
        .filter((animation) => {
          const timing = animation.effect?.getComputedTiming?.();
          return (timing?.duration ?? 0) > floor;
        })
        .map((animation) => {
          const pseudo = animation.effect?.pseudoElement ?? "";
          const target = animation.effect?.target;
          return pseudo || (target?.tagName ?? "unknown").toLowerCase();
        }),
    }),
    MOVING_MS,
  );
}

const running = () => reading(page);

await page.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await page.fill('input[type="email"]', EMAIL);
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/buscar", { timeout: 10000 });

const supported = await page.evaluate(
  () => typeof document.startViewTransition === "function",
);
if (!supported) problems.push("this browser has no view transitions, the switch will be instant");

await page.goto(`${BASE}/empresa/NVDA`, { waitUntil: "networkidle" });
await page.waitForTimeout(4000);

const before = await running();
if (before.theme !== "light") problems.push(`expected to start light, found ${before.theme}`);

await page.locator(themeGroup).nth(1).click();
await page.waitForTimeout(70);

const during = await running();
await page.screenshot({ path: `${SHOTS}/20-troca-no-meio.png` });

if (!during.theming) {
  problems.push("nothing marked the switch as in flight, so element transitions were not held");
}
if (during.moving.length === 0) {
  problems.push("no animation was running mid-switch, so the change was instant");
}

const strays = during.moving.filter(
  (name) => !name.startsWith("::view-transition"),
);
if (strays.length) {
  problems.push(
    `${strays.length} animation(s) ran beside the cross-fade, so the surface moves in pieces: ${[...new Set(strays)].join(", ")}`,
  );
}

await page.waitForTimeout(500);

/*
  The chart paints to a canvas, so no assertion can read its gridlines from the
  outside. What it can read is the colour the chart says it painted with, and
  the invariant is that it equals the theme now on the root.

  This is the check for a real bug: the theme flipped React state before it
  flipped the attribute, so anything reading the stylesheet during its layout
  effect painted itself in the theme being left. The chart came back with the
  other mode's gridlines and kept them until the next switch.
*/
async function chartMatchesTheme() {
  return page.evaluate(() => {
    const box = document.querySelector("[data-painted-line]");
    if (!box) return { painted: null, current: null };
    return {
      painted: box.getAttribute("data-painted-line"),
      current: getComputedStyle(document.documentElement)
        .getPropertyValue("--line")
        .trim(),
    };
  });
}

const painted = await chartMatchesTheme();
if (painted.painted === null) {
  problems.push("no chart on screen to check, so the theme check proved nothing");
} else if (painted.painted !== painted.current) {
  problems.push(
    `the chart is painted with ${painted.painted} while the theme says ${painted.current}`,
  );
}

const after = await running();
if (after.theme !== "dark") problems.push(`the switch did not land dark, found ${after.theme}`);
if (after.theming) problems.push("the in-flight mark was never cleared, transitions stay disabled");
if (after.moving.some((name) => name.startsWith("::view-transition"))) {
  problems.push("the cross-fade was still running after 570ms");
}
await page.screenshot({ path: `${SHOTS}/21-escuro.png` });

await page.locator(themeGroup).nth(0).click();
await page.waitForTimeout(600);

const back = await running();
if (back.theme !== "light") problems.push(`switching back did not land light, found ${back.theme}`);

const repainted = await chartMatchesTheme();
if (repainted.painted !== repainted.current) {
  problems.push(
    `after switching back the chart is painted with ${repainted.painted} while the theme says ${repainted.current}`,
  );
}
if (back.theming) problems.push("the in-flight mark survived the second switch");
await page.screenshot({ path: `${SHOTS}/22-claro.png` });

/*
  A reader who asked for less motion gets the change and not the animation, so
  the same switch under that setting must land instantly and leave nothing
  running behind it.
*/
await context.close();
const still = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const quiet = await still.newPage();
await quiet.goto(`${BASE}/entrar`, { waitUntil: "networkidle" });
await quiet.fill('input[type="email"]', EMAIL);
await quiet.fill('input[type="password"]', PASSWORD);
await quiet.click('button[type="submit"]');
await quiet.waitForURL("**/buscar", { timeout: 10000 });
await quiet.waitForTimeout(800);

await quiet.locator(themeGroup).nth(1).click();
await quiet.waitForTimeout(40);
const reduced = await reading(quiet);

if (reduced.theme !== "dark") {
  problems.push(`reduced motion did not switch the theme, found ${reduced.theme}`);
}
if (reduced.moving.length > 0) {
  problems.push(
    `reduced motion still moved ${reduced.moving.length}: ${[...new Set(reduced.moving)].join(", ")}`,
  );
}

await browser.close();

console.log("mid-switch, moving:", during.moving);
console.log("reduced motion, moving:", reduced.moving, "landed on", reduced.theme);
if (problems.length) {
  console.log("PROBLEMS");
  for (const problem of problems) console.log(`  ${problem}`);
  process.exit(1);
}
console.log("theme clean");
