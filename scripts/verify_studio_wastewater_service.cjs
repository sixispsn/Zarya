/* Isolated local QA: optional requirements, persistence and responsive layout. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8782';
assert(['localhost','127.0.0.1'].includes(new URL(base).hostname));
const out = path.resolve('output/studio-wastewater-service-qa');
fs.mkdirSync(out, {recursive:true});
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1360,height:1000}, reducedMotion:'reduce'});
    const errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    const headers={'X-Zarya-Studio':'1'};
    let response=await page.request.post(base+'/studio/api/draft',{headers});
    assert(response.ok(),await response.text());
    let draft=await response.json();
    response=await page.request.patch(base+'/studio/api/answers',{headers,data:{revision:draft.revision,answers:{
      residents:20, consumer_code:'residential_full_bath', floors:2, apartments:8,
      building_height_m:6.6,fire_height_m:4.8,hws_type:'central',
    }}});
    assert(response.ok(),await response.text());draft=await response.json();
    response=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:draft.revision}});
    assert(response.ok(),await response.text());
    await page.goto(base+'/studio?view=project');
    const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    await idle();
    await page.locator('[data-config="connection"]').click();
    const group = name=>page.locator('#clarification-body details').filter({has:page.locator('summary').filter({hasText:name})}).first();
    const meter=group('Узел учёта К1');
    const sump=group('Приямок · утечки и обслуживание');
    await meter.locator('summary').click();
    assert(!await page.locator('#next-sewer_service_k1_metering_location').isVisible());
    await page.locator('#next-sewer_service_k1_metering_enabled').check();
    await page.locator('#next-sewer_service_k1_metering_location').fill('Выпуск К1-1, помещение 001');
    await page.locator('#next-sewer_service_k1_metering_regime').selectOption('gravity');
    await page.locator('#next-sewer_service_k1_metering_basis').fill('ТУ, п. 4');
    await page.screenshot({path:out+'/01-meter.png'});
    await meter.locator('summary').click();
    await sump.locator('summary').click();
    assert(!await page.locator('#next-sewer_service_sump_room').isVisible());
    await page.locator('#next-sewer_service_sump_enabled').check();
    await page.locator('#next-sewer_service_sump_room').selectOption('pump_room');
    await page.locator('#next-sewer_service_sump_location').fill('Насосная 002');
    await page.locator('#next-sewer_service_sump_reserve_location').selectOption('warehouse');
    await page.locator('#next-sewer_service_sump_basis').fill('Задание ВК');
    await page.locator('#next-sewer_service_sump_discharge_note').fill('Точка подключения требует согласования');
    const boxes=await Promise.all(['room','location','reserve_location','discharge_note','basis'].map(k=>page.locator('#next-sewer_service_sump_'+k).boundingBox()));
    assert(boxes.every(b=>Math.abs(b.width-boxes[0].width)<1 && Math.abs(b.height-boxes[0].height)<1));
    await page.locator('#next-sewer_service_sump_room').scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/02-sump.png'});
    await page.setViewportSize({width:390,height:950});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const dialog=await page.locator('#clarification-dialog').boundingBox();
    for(const input of await page.locator('#clarification-body .field-control:visible').all()) {
      const box=await input.boundingBox();assert(box.x>=dialog.x && box.x+box.width<=dialog.x+dialog.width);
    }
    await page.screenshot({path:out+'/03-mobile.png'});
    await page.setViewportSize({width:1360,height:1000});
    await page.locator('[data-config-form] button[type="submit"]').click();await idle();
    await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
    let saved=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(saved.wastewater_service.sump.status,'invalid');
    assert.equal(saved.wastewater_service.meter.enabled,true);
    await page.keyboard.press('Escape');
    response=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:saved.revision}});
    assert(response.ok(),await response.text());
    await page.reload();await idle();
    const result=page.locator('.wastewater-service-result').filter({hasText:'Приямок · утечки и обслуживание'});
    await result.locator('summary').click();
    assert((await result.textContent()).includes('Хранение резервного насоса на складе'));
    await result.screenshot({path:out+'/04-requirements.png'});
    await result.locator('[data-action="wastewater-service-inputs"]').click();
    assert(await page.locator('#next-sewer_service_sump_enabled').isChecked());
    assert.equal(await page.locator('#next-sewer_service_sump_reserve_location').inputValue(),'warehouse');
    await page.locator('#next-sewer_service_sump_reserve_location').selectOption('installed');
    await page.locator('#next-sewer_service_sump_enabled').uncheck();
    assert(!await page.locator('#next-sewer_service_sump_room').isVisible());
    await page.locator('[data-config-form] button[type="submit"]').click();await idle();
    saved=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(saved.wastewater_service.sump.status,'disabled');
    assert.equal(saved.wastewater_service.input.sump_location,'Насосная 002');
    assert.equal(saved.wastewater_service.input.sump_reserve_location,'installed');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({ok:true,screenshots:out},null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
