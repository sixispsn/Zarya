/* Synthetic local-only UI exercise; never reads a production key or project. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8774';
const keyPath = process.env.PILOT_QA_KEY;
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
assert(keyPath?.startsWith('/tmp/zarya-feedback-qa.'), 'Synthetic local key only');
const out = path.resolve('output/pilot-feedback-qa');
fs.mkdirSync(out, {recursive:true});
const pdf = Buffer.from(execFileSync('venv/bin/python', ['-c', 'import base64; from tests.test_pilot_access import pdf_bytes; print(base64.b64encode(pdf_bytes()).decode())'], {encoding:'utf8'}).trim(), 'base64');

(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error=>errors.push(String(error)));
    await page.goto(base+'/studio');
    await page.locator('#pilot-key').fill(fs.readFileSync(keyPath, 'utf8').trim());
    await page.getByRole('button',{name:'Войти в ЗАРЮ'}).click();
    await page.waitForURL('**/studio');
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    let initial = await (await page.request.get(base+'/studio/api/draft')).json();
    for (const doc of initial.documents || []) {
      const removed = await page.request.post(base+'/studio/api/files/delete', {headers:{'Origin':base,'X-Zarya-Studio':'1'}, data:{revision:initial.revision,document_id:doc.id}});
      assert.equal(removed.status(),200); initial = await removed.json();
    }
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    await page.locator('[data-feedback-open]').click();
    await page.locator('#pilot-feedback textarea').fill('После нажатия кнопки получилось неожиданное поведение. Проверка интерфейса.');
    await page.screenshot({path:out+'/feedback-desktop.png'});
    const requestPromise = page.waitForRequest(request=>request.url()===base+'/access/feedback' && request.method()==='POST');
    await page.locator('#pilot-feedback [type="submit"]').click();
    const request = await requestPromise;
    assert.deepEqual(Object.keys(request.postDataJSON()).sort(), ['category','message','request_id']);
    await page.locator('#feedback-result').waitFor();
    assert.match(await page.locator('#feedback-result').textContent(), /ZR-\d+/);
    await page.locator('[data-feedback-close]').click();
    await page.locator('#file-input').setInputFiles({name:'Проверка.pdf', mimeType:'application/pdf', buffer:pdf});
    await page.locator('.document-chip').waitFor();
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    if (await page.locator('#clarification-dialog').evaluate(d=>d.open)) await page.getByRole('button',{name:'Закрыть уточнение'}).click();
    await page.locator('[data-config="building"]').click();
    await page.locator('#next-floors').fill('3');
    await page.getByRole('button',{name:'Закрыть уточнение'}).click();
    await page.locator('[data-action="delete-document"]').click();
    await page.locator('#delete-document-dialog').waitFor();
    await page.screenshot({path:out+'/delete-desktop.png'});
    await page.locator('[data-action="cancel-delete-document"]').click();
    assert.equal(await page.locator('.document-chip').count(),1);
    await page.locator('[data-action="delete-document"]').click();
    await page.locator('[data-action="confirm-delete-document"]').click();
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    assert.equal(await page.locator('.document-chip').count(),0);
    const saved = await (await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(saved.fields.find(row=>row.key==='floors').value,3);
    for (const width of [390,320]) {
      await page.setViewportSize({width,height:850});
      await page.goto(base+'/studio');
      await page.locator('[data-feedback-open]').click();
      const box = await page.locator('#pilot-feedback').boundingBox();
      assert(box.x>=0 && box.x+box.width<=width);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:out+`/feedback-${width}.png`});
      await page.keyboard.press('Escape');
    }
    await page.setViewportSize({width:1440,height:1050});
    await page.goto(base+'/access/feedback');
    assert(await page.locator('.feedback-item').count()>=1);
    await page.screenshot({path:out+'/owner-inbox.png'});
    assert.deepEqual(errors,[]);
    console.log('PASS: feedback, text-only payload, owner inbox, confirmed deletion, preserved unsaved input, 320/390/1440px; no browser errors.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
