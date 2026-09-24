import puppeteer from 'puppeteer-core';
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
});
const page = await browser.newPage();
for (const [name, w, h] of [['mobile', 390, 844], ['desktop', 1280, 800], ['user-800', 800, 772]]) {
  await page.setViewport({ width: w, height: h });
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle0' });
  await page.evaluate(() => document.fonts.ready);
  await new Promise(r => setTimeout(r, 600));
  const m = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const bad = [];
    document.querySelectorAll('*').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width > 0) bad.push(`${el.tagName}.${String(el.className).slice(0,50)} right=${Math.round(r.right)}`);
    });
    return { vw, scrollW: document.documentElement.scrollWidth, bad: bad.slice(0, 6) };
  });
  console.log(name, JSON.stringify(m));
  await page.screenshot({ path: `../.impeccable/review/${name}.png` });
}
await browser.close();
