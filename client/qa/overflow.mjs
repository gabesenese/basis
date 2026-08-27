import { chromium } from "@playwright/test";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
await page.goto("http://localhost:5173/entrar", { waitUntil: "networkidle" });
await page.fill('input[type="email"]', process.env.E);
await page.fill('input[type="password"]', process.env.P);
await page.click('button[type="submit"]');
await page.waitForURL("**/hoje");
for (const path of ["/hoje", "/calendario", "/estudo", "/contexto"]) {
  await page.goto(`http://localhost:5173${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  const found = await page.evaluate(() => {
    const limit = document.documentElement.clientWidth;
    return [...document.querySelectorAll("*")]
      .filter((el) => el.getBoundingClientRect().right > limit + 1)
      .slice(0, 6)
      .map((el) => `${el.tagName}.${el.className?.toString().slice(0, 60)} right=${Math.round(el.getBoundingClientRect().right)} limit=${limit}`);
  });
  console.log(path, found.length ? found : "ok");
}
await browser.close();
