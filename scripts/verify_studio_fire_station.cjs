/* Local-only UI acceptance of the optional expert import. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:18879';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const output = process.env.UI_OUTPUT || 'output/studio-fire-station-ui';
const caseDir = process.env.CASE_DIR || 'output/pdf/studio-fire-station';
const modelFile = process.env.MODEL_FILE || 'explicit-control-model.json';
const answersFile = process.env.ANSWERS_FILE || 'control-answers.json';
fs.mkdirSync(output,{recursive:true});
(async()=>{
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}}), errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    await page.goto(base+'/studio');
    const idle = () => page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
    await idle();
    const headers={'X-Zarya-Studio':'1'};
    let state = await (await page.request.post(base+'/studio/api/draft',{headers})).json();
    const answers = JSON.parse(fs.readFileSync(`${caseDir}/${answersFile}`,'utf8'));
    const pressureReview = !!answers.fire_station_model.pressure_review;
    const adoption = answers.fire_station_model.pressure_review?.document_use === 'preliminary_project';
    delete answers.fire_station_model;
    const response = await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,answers}});
    assert(response.ok(),await response.text());
    state = await response.json();
    assert.equal(state.project_calculation.fire_station,null);
    await page.goto(base+'/studio?view=project');await idle();
    await page.locator('[data-config="connection"]').click();
    const section=page.locator('.config-extra').filter({has:page.locator('[data-fire-station-import]')});
    await section.locator('summary').click();
    const input=section.locator('[data-fire-station-import]');
    await input.setInputFiles(`${caseDir}/${modelFile}`);
    await page.waitForFunction(()=>document.querySelector('#next-fire_station_model')?.value.includes('schema_version'));
    assert((await section.locator('[data-fire-station-status]').textContent()).includes('6 участков'));
    if(adoption) {
      const toggle=section.locator('[data-fire-station-adopt]');
      assert(await toggle.isChecked());
      await toggle.uncheck();
      assert((await page.locator('#next-fire_station_model').inputValue()).includes('review_only'));
      await toggle.check();
      assert((await page.locator('#next-fire_station_model').inputValue()).includes('preliminary_project'));
    }
    for(const width of [1440,390]) {
      await page.setViewportSize({width,height:1000});
      await input.scrollIntoViewIfNeeded();
      assert(await page.locator('#clarification-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth+2));
      await page.screenshot({path:`${output}/import-${width}.png`});
    }
    await page.setViewportSize({width:1440,height:1050});
    await page.locator('[data-config-form] button[type="submit"]').click();
    await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');await idle();
    await page.locator('[data-config-form] button[type="submit"]').click();
    await page.locator('#fire-station-results').waitFor({state:'attached'});await idle();
    if(!await page.locator('#calculation-details').evaluate(el=>el.open)) {
      await page.locator('#calculation-details > summary').click();
    }
    await page.locator('#fire-station-results').waitFor();await idle();
    await page.locator('#fire-station-results').scrollIntoViewIfNeeded();
    if(pressureReview) {
      const review=page.locator('.fire-pressure-review');
      await review.scrollIntoViewIfNeeded();
      assert((await review.textContent()).includes('Решено 45 из 45'));
      assert((await review.textContent()).includes(`Минимумы обеспечены в ${adoption?45:42}`));
    }
    await page.screenshot({path:`${output}/result.png`});
    const saved=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(saved.project_calculation.fire_station.flow_lps,5.2);
    assert.equal(saved.project_calculation.fire_station.pump.curve_kind,adoption?'pressure_flow_study':'duty_only');
    if(adoption) assert.equal(saved.project_calculation.fire_station.adopted,true);
    assert.equal(saved.project_calculation.can_release,false);
    // Reopening and clearing actually removes the model, not only its caption.
    await page.locator('[data-config="connection"]').click();
    const reopened=page.locator('.config-extra').filter({has:page.locator('[data-fire-station-import]')});
    await reopened.locator('summary').click();
    await reopened.locator('[data-action="fire-station-remove"]').click();
    assert.equal(await page.locator('#field-fire_station_model').inputValue(),'null');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({desktop:true,mobile:true,import:true,calculation:true,clear:true,errors}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
