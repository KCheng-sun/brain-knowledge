const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto('http://127.0.0.1:7860/', { waitUntil: 'networkidle0', timeout: 15000 });

  // 找到输入框，输入问题并发送
  const inputSelector = 'textarea, input[type="text"]';
  await page.waitForSelector(inputSelector, { timeout: 8000 });
  await page.type(inputSelector, '知识库里有什么');
  // 按回车或点发送按钮
  const sendBtn = await page.$('button[type="button"]');
  if (sendBtn) await sendBtn.click();
  await new Promise(r => setTimeout(r, 8000));

  // 测量 timeline 和 answer-text 的间距
  const info = await page.evaluate(() => {
    const tl = document.querySelector('.ant-timeline');
    const ans = document.querySelector('.answer-text');
    if (!tl || !ans) return { error: 'not found', tl: !!tl, ans: !!ans };
    const tr = tl.getBoundingClientRect();
    const ar = ans.getBoundingClientRect();
    return {
      timelineBottom: tr.bottom,
      answerTop: ar.top,
      gap: ar.top - tr.bottom,
      timelineHTML: tl.outerHTML.substring(0, 200),
      ansPrev: ans.previousElementSibling ? ans.previousElementSibling.className : 'none',
    };
  });
  console.log(JSON.stringify(info, null, 2));

  await browser.close();
})();
