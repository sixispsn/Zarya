// Isolated local UI smoke. Never use against production or existing pilot projects.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const baseURL = process.env.ZARYA_QA_URL || 'http://127.0.0.1:8783';
  assert(['127.0.0.1', 'localhost'].includes(new URL(baseURL).hostname));
  const out = path.resolve('tmp/pdfs/studio-section-documents');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true,
    ...(process.env.ZARYA_QA_CHROME ? {executablePath: process.env.ZARYA_QA_CHROME} : {})});
  try {
    const context = await browser.newContext({baseURL, viewport: {width: 1440, height: 1050},
      extraHTTPHeaders: {'X-Zarya-Studio': '1'}, reducedMotion: 'reduce'});
    async function post(endpoint, data) {
      const response = await context.request.post('/studio/api/' + endpoint, {data});
      assert.equal(response.status(), 200, await response.text());
      return response.json();
    }
    let state = await post('draft', {});
    const answers = JSON.parse(fs.readFileSync('output/pdf/studio-section-documents/answers.json', 'utf8'));
    state = await post('calculate', {revision: state.revision, answers});
    assert.equal(state.project_calculation.can_release, false);
    state = await post('preview', {revision: state.revision});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/studio?view=project');
    await page.locator('[data-action="readiness"]').click();
    for (const key of ['ios2', 'ios3', 'common']) {
      assert.equal(await page.locator(`[data-review-section="${key}"]`).count(), 1);
    }
    await page.locator('#release-readiness').screenshot({path: path.join(out, 'readiness.png')});
    await page.locator('[data-review-section="ios2"] > summary').click();
    assert(await page.locator('[data-review-section="ios2"]').innerText().then(t => t.includes('Водомерные узлы')));
    assert.equal(await page.locator('[data-action="package"]').isDisabled(), true);
    for (const key of ['ios2', 'ios3']) {
      await page.locator(`[data-action="documents"][data-view="${key}"]`).click();
      const link = page.locator('.document-selection a');
      await link.waitFor();
      assert.equal(await link.count(), 1);
      const response = await context.request.get(await link.getAttribute('href'));
      assert.equal(response.status(), 200);
      assert.equal(response.headers()['x-zarya-preview'], 'true');
    }
    await page.locator('.delivery').screenshot({path: path.join(out, 'documents-desktop.png')});
    await page.setViewportSize({width: 390, height: 844});
    await page.locator('.delivery').screenshot({path: path.join(out, 'documents-mobile.png')});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out, 'browser-qa.json'), JSON.stringify({
      errors, sections: 3, pdfDownloads: 2, mobileWidth: 390, releaseStillBlocked: true,
    }, null, 2));
    console.log('PASS: 3 readiness groups, 2 private PDFs, release guard, desktop + mobile.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
