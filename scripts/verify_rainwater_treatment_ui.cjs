/* Local synthetic data only: optional treatment, saved values and stale selection. */
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8781';
assert(['localhost','127.0.0.1'].includes(new URL(base).hostname));
const out=path.resolve('output/rainwater-treatment-ui');
fs.mkdirSync(out,{recursive:true});
const fixture=JSON.parse(execFileSync('venv/bin/python',['-c',
  'import json; from dataclasses import asdict; from tests.test_rainwater_treatment import example; print(json.dumps(asdict(example().rainwater_reuse)))'
]));
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1080},extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    await page.goto(base+'/studio');await idle();
    let response=await page.request.post(base+'/studio/api/draft');assert(response.ok());
    let state=await response.json();
    const answers={residents:20,apartments:8,consumer_code:'residential_full_bath',floors:2,
      building_height_m:6.6,fire_height_m:4.8,hws_type:'central',roof_type:'flat_accessible'};
    for(const [key,value] of Object.entries(fixture)) if(!['enabled','design_review'].includes(key)) answers['rainwater_'+key]=value;
    answers.rainwater_enabled='yes';
    response=await page.request.post(base+'/studio/api/calculate',{data:{revision:state.revision,answers}});
    assert(response.ok(),await response.text());state=await response.json();
    assert.equal(state.rainwater_reuse.pump.duty.h_m,30);
    await page.goto(base+'/studio?view=project');await idle();
    await page.locator('[data-config="consumers"]').click();
    await page.locator('[data-config-extra="consumers-2"] > summary').click();
    const treatment=page.locator('details').filter({has:page.locator('summary').filter({hasText:/^Очистка · жилая терраса$/})}).last();
    await treatment.locator(':scope > summary').click();
    assert.equal(await page.locator('#next-rainwater_treatment_setup').inputValue(),'residential_terrace_irrigation');
    assert.equal(await page.locator('#next-rainwater_treatment_surface').inputValue(),'hard_terrace');
    assert(!(await page.locator('#next-rainwater_pump_treatment_loss_m').isVisible()));
    await treatment.locator('details > summary').click();
    await page.locator('#next-rainwater_treatment_filter_loss_m').fill('2.1');
    assert.equal(await page.locator('#field-rainwater_treatment_filter_loss_m').inputValue(),'2.1');
    const boxes=await Promise.all(['selection_flow_lps','filter_loss_m','uv_loss_m'].map(k=>page.locator('#next-rainwater_treatment_'+k).boundingBox()));
    assert(boxes.every(b=>b && Math.abs(b.width-boxes[0].width)<1 && Math.abs(b.height-boxes[0].height)<1));
    await page.locator('#next-rainwater_treatment_setup').scrollIntoViewIfNeeded();
    await page.screenshot({path:out+'/desktop.png'});
    for(const width of [390,320]) {
      await page.setViewportSize({width,height:900});
      const box=await page.locator('#clarification-dialog').boundingBox();
      assert(box.x>=0 && box.x+box.width<=width);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      for(const input of await page.locator('#clarification-body .field-control:visible').all()) {
        const b=await input.boundingBox();assert(b.x>=box.x && b.x+b.width<=box.x+box.width);
      }
      await page.locator('#next-rainwater_treatment_setup').scrollIntoViewIfNeeded();
      await page.screenshot({path:out+`/mobile-${width}.png`});
    }
    await page.setViewportSize({width:1440,height:1080});
    await page.locator('[data-config-form] button[type="submit"]').click();await idle();
    state=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(state.rainwater_reuse.pump.duty.h_m,30.3);
    assert(Math.abs(state.rainwater_reuse.treatment.head_loss_m-2.3)<1e-12);
    await page.locator('[data-config="building"]').click();
    await page.locator('#next-roof_type').selectOption('gable');
    await page.locator('[data-config-form] button[type="submit"]').click();await idle();
    state=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(state.rainwater_reuse.treatment.status,'out_of_scope');
    assert.equal(state.rainwater_reuse.pump.selected,null);
    assert.deepEqual(errors,[]);
    console.log('PASS: optional treatment fields, hidden aggregate, saved component losses, roof invalidation, symmetric fields, 320/390/1440 px, no JS errors.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
