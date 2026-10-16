/* Synthetic localhost-only evidence: no approval of real project data. */
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8782';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const fixture=JSON.parse(execFileSync('venv/bin/python',['-c',
  'import json; from dataclasses import asdict; from tests.test_rainwater_design import documented; print(json.dumps(asdict(documented().rainwater_reuse)))']));
const out='output/rainwater-design-ui';fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1080},extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    await page.goto(base+'/studio');await idle();
    let state=await(await page.request.post(base+'/studio/api/draft')).json();
    const answers={residents:20,apartments:8,consumer_code:'residential_full_bath',floors:2,
      building_height_m:6.6,fire_height_m:4.8,hws_type:'central',roof_type:'flat_accessible',rainwater_enabled:'yes'};
    for(const [key,value] of Object.entries(fixture)) if(!['enabled','design_review'].includes(key)) answers['rainwater_'+key]=value;
    let response=await page.request.post(base+'/studio/api/calculate',{data:{revision:state.revision,answers}});
    assert(response.ok(),await response.text());
    await page.goto(base+'/studio?view=project');await idle();
    await page.locator('.rainwater-result > summary').click();
    await page.locator('.rain-design > summary').click();
    await page.locator('#rain-reviewer').fill('Инженер регрессионного примера');
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('[data-action="rain-review"]').click();await idle();
    state=await(await page.request.get(base+'/studio/api/draft')).json();
    assert(state.rainwater_reuse.design.confirmed);
    assert.equal(state.project_calculation.can_release,false);
    await page.locator('[data-config="consumers"]').click();
    await page.locator('[data-config-extra="consumers-2"] > summary').click();
    const passport=page.locator('details').filter({has:page.locator('summary').filter({hasText:/^Паспорт решения · перед выпуском$/})}).last();
    await passport.locator(':scope > summary').click();
    assert.equal(await passport.locator('textarea').count(),6);
    const widths=await passport.locator('textarea').evaluateAll(xs=>xs.map(x=>x.getBoundingClientRect().width));
    assert(widths.every(w=>Math.abs(w-widths[0])<1));
    await page.locator('#next-rainwater_design_storage').fill('Изменённая ревизия бака, тест.');
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:1000});
      await page.locator('#next-rainwater_design_storage').scrollIntoViewIfNeeded();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:`${out}/passport-${width}.png`});
    }
    await page.locator('[data-config-form] button[type="submit"]').click();await idle();
    state=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(state.rainwater_reuse.design.status,'stale');
    assert.deepEqual(errors,[]);
    console.log('PASS: manual review, release still blocked by unrelated checks, six symmetric notes, stale after edit, responsive 320/390/1440, no JS errors.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
