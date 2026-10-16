/* Local synthetic data only: sequential forms, source confirmation and geometry. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8775';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out = path.resolve('output/studio-configurator-qa');
fs.mkdirSync(out,{recursive:true});
const pdf = execFileSync('venv/bin/python',['-c','import sys; from tests.test_studio import pdf; sys.stdout.buffer.write(pdf("Этажность: 2. Высота типового этажа: 3,3 м. Общая высота здания: 6,6 м. Пожарно-техническая высота: 4,8 м. Число жителей: 20. Количество квартир: 8. Гарантированный напор: 5 м. Общая площадь здания: 500 м²."))']);

(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const errors=[];
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    page.on('pageerror',e=>errors.push(String(e)));
    const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    const saved=async()=>await(await page.request.get(base+'/studio/api/draft')).json();
    const row=(state,key)=>state.fields.find(f=>f.key===key);
    const next=async(title)=>{
      await page.locator('[data-config-form] button[type="submit"]').click();
      await page.waitForFunction(t=>document.querySelector('#next-title')?.textContent===t,title);
      await idle();
    };
    await page.goto(base+'/studio');await idle();
    await page.locator('#file-input').setInputFiles({name:'ТЗ-тест.pdf',mimeType:'application/pdf',buffer:pdf});
    await page.locator('#next-floors').waitFor();await idle();
    assert.equal(await page.locator('#next-title').textContent(),'Здание');
    assert.equal(await page.locator('.roof-profile').count(),0);
    assert.equal(row(await saved(),'residents').status,'review');
    assert.equal(await page.locator('#next-floors').inputValue(),'2');
    await page.locator('#next-basement_kind').selectOption('basement');
    await page.locator('#next-basement_floor_m').fill('-3.1');
    await page.locator('#next-floor_height_m').fill('3.3');
    await page.waitForTimeout(350);
    await page.screenshot({path:out+'/01-building.png'});
    await next('Подключение и ТУ');
    let state=await saved();
    assert.equal(row(state,'floors').status,'confirmed');
    assert.equal(row(state,'residents').status,'review','Unseen consumer PDF not confirmed');
    assert.equal(row(state,'guaranteed_head_m').status,'review','Unseen TU not confirmed');
    await page.locator('#next-h_geom_m').fill('6');
    await page.locator('#next-hws_heater_in_scope').selectOption('no');
    await page.screenshot({path:out+'/02-connection.png'});
    const boxes=await Promise.all(['guaranteed_head_m','inputs_count','h_geom_m','hws_heater_in_scope'].map(k=>page.locator('#next-'+k).boundingBox()));
    assert(boxes.every(b=>Math.abs(b.width-boxes[0].width)<1 && Math.abs(b.height-boxes[0].height)<1));
    assert(Math.abs(boxes[0].y-boxes[1].y)<1 && Math.abs(boxes[2].y-boxes[3].y)<1);
    await next('Потребители');
    assert.equal(row(await saved(),'guaranteed_head_m').status,'confirmed');
    assert.equal(row(await saved(),'residents').status,'review');
    await page.screenshot({path:out+'/03-consumers.png'});
    await page.locator('[data-config-form] button[type="submit"]').click();
    await page.locator('#calculation-title').waitFor();await idle();
    state=await saved();assert.equal(state.calculation.total.q_day,3.6);
    assert.equal(row(state,'residents').source.kind,'document_confirmed');
    assert.equal(row(state,'basement_floor_m').value,-3.1);
    await page.waitForTimeout(400);
    await page.screenshot({path:out+'/04-workspace.png',fullPage:true});
    // Unsubmitted edits survive Escape, another step, and repeated opening.
    await page.locator('[data-config="building"]').click();
    await page.locator('#next-floors').fill('3');await page.keyboard.press('Escape');
    await page.locator('[data-config="consumers"]').click();
    await page.locator('#next-residents').fill('24');await page.keyboard.press('Escape');
    await page.locator('[data-config="building"]').click();
    assert.equal(await page.locator('#next-floors').inputValue(),'3');
    await next('Подключение и ТУ');
    assert.equal(row(await saved(),'residents').value,24);
    await page.locator('[data-action="config-back"]').click();
    await page.locator('#next-floors').waitFor();await idle();
    assert.equal(await page.locator('#next-floors').inputValue(),'3');
    // Width of every visible input remains within the dialog at small screens.
    for(const width of [390,320]) {
      await page.setViewportSize({width,height:850});
      const box=await page.locator('#clarification-dialog').boundingBox();
      assert(box.x>=0 && box.x+box.width<=width);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      for(const input of await page.locator('#clarification-body .field-control:visible').all()) {
        const b=await input.boundingBox();assert(b.x>=box.x && b.x+b.width<=box.x+box.width);
      }
      await page.screenshot({path:out+`/building-${width}.png`});
    }
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:1440,height:1050});
    await page.locator('.site-brand').click();await idle();
    assert(await page.locator('#entry').isVisible());
    assert(!(await page.locator('#workspace').isVisible()));
    await page.locator('[data-action="resume"]').click();await idle();
    assert.equal(await page.locator('.config-card').count(),3);
    assert.deepEqual(errors,[]);
    const manual=await browser.newPage({viewport:{width:1280,height:950}});
    manual.on('pageerror',e=>errors.push(String(e)));
    await manual.goto(base+'/studio');
    await manual.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    await manual.locator('[data-action="manual"]').click();
    await manual.locator('#next-floors').waitFor();
    await manual.waitForTimeout(350);
    await manual.screenshot({path:out+'/05-manual-building.png'});
    for(const title of ['Подключение и ТУ','Потребители']) {
      await manual.locator('[data-config-form] button[type="submit"]').click();
      await manual.waitForFunction(t=>document.querySelector('#next-title')?.textContent===t,title);
      await manual.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    }
    await manual.locator('#next-residents').fill('20');
    await manual.locator('[data-config-form] button[type="submit"]').click();
    await manual.locator('#calculation-title').waitFor();
    const minimal=await(await manual.request.get(base+'/studio/api/draft')).json();
    assert.equal(minimal.calculation.total.q_day,3.6);
    assert.equal(row(minimal,'building_purpose').source.kind,'residential_preset');
    assert.deepEqual(errors,[]);
    console.log('PASS: 3 sequential dialogs, back/Escape/resume, PDF confirmation per step, calculation parity, symmetric fields, 320/390/1440 px, no JS errors.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
