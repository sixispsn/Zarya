/* Isolated local browser context: an unverified meter must not get a green lamp. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1000}});
    const errors=[]; page.on('pageerror', e => errors.push(String(e)));
    const idle=()=>page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    const state=async()=>await (await page.request.get(base+'/studio/api/draft')).json();
    await page.goto(base+'/studio'); await idle();
    await page.getByRole('button',{name:'Начать без документов'}).click(); await idle();
    const response=await page.request.post(base+'/studio/api/calculate', {
      headers:{'X-Zarya-Studio':'1'}, data:{revision:(await state()).revision,answers:{
        residents:20,consumer_code:'residential_full_bath',floors:2,apartments:8,
        building_height_m:6.6,fire_height_m:4.8,hws_type:'central',h_geom_m:6,
        guaranteed_head_m:5,h_apartment_c_meter_m:.5,h_apartment_h_meter_m:.7,
        pressure_loss_mode:'ready',h_il_m:2,h_vvod_m:1,t3_loss_mode:'ready',h_il_hot_m:2,
      }},
    });
    assert.equal(response.status(),200,await response.text());
    await page.reload(); await idle();
    const result=(await state()).project_calculation;
    assert(result.meters.length > 0);
    assert(result.meters.every(m=>m.ok_v===null));
    assert.equal(result.can_release,false);
    const tile=page.locator('.result-tile').filter({has:page.getByRole('heading',{name:'Водомерные узлы',exact:true})});
    if (!(await tile.isVisible())) await page.locator('#calculation-details > summary').click();
    await tile.locator('.status.review').waitFor();
    assert(await tile.locator('.status.review').isVisible());
    assert.equal(await tile.locator('.status.confirmed').count(),0);
    assert((await tile.innerText()).includes('Проверка минимального расхода здания пока не завершена'));
    assert(result.meters.every(m=>m.product.id && m.q_min_passport_m3h>0));
    await tile.getByText('Модели и паспорта',{exact:true}).click();
    await tile.getByRole('link',{name:'Паспорт изготовителя ↗'}).first().waitFor();
    assert((await tile.innerText()).includes('предложение каталога'));
    assert((await tile.innerText()).includes('12.15'));
    assert((await tile.innerText()).includes('Δp ≤ 0,1 МПа'));
    assert((await tile.innerText()).includes('не характеристика h(Q)'));
    assert(result.meters.every(m=>m.product.hydraulic_evidence.exact_loss_m===null));
    fs.mkdirSync('output/studio-preview/meters',{recursive:true});
    await tile.screenshot({path:'output/studio-preview/meters/needs-data.png'});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await tile.screenshot({path:'output/studio-preview/meters/passports-mobile.png'});
    // L05 rendering fixture in this isolated page, never a saved user project.
    const overflow = await state();
    const p = overflow.project_calculation;
    p.meters=[];
    p.meter_error='Счётчик ХВС: нет подходящего водомера. Qсред=400 м³/ч превышает предел каталога Qэкспл=380 м³/ч (п. 12.14 СП 30).';
    p.head={ready:false,paths:[],required_m:null,pump_m:null,pump_needed:null};
    p.pumps=null; p.can_preview=false; p.can_release=false;
    await page.route('**/studio/api/draft', route=>route.fulfill({json:overflow}));
    await page.reload(); await idle();
    if (!(await tile.isVisible())) await page.locator('#calculation-details > summary').click();
    assert((await tile.innerText()).includes('Qсред=400'));
    assert((await tile.innerText()).includes('Qэкспл=380'));
    assert.equal(await tile.locator('.status.confirmed').count(),0);
    assert.equal((await tile.innerText()).includes('DN250'),false);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await tile.screenshot({path:'output/studio-preview/meters/catalog-exhausted.png'});
    assert.deepEqual(errors,[]);
    console.log('PASS: unknown minimum and L05 overflow, no false green/selected DN, mobile, no JS errors');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
