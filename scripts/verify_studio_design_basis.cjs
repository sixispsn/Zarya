/* Synthetic local inputs: real dialogs, persistence, no extra required wizard. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'), fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8787';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out='output/studio-design-basis-qa';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  const headers={Origin:base,'X-Zarya-Studio':'1'};
  let r=await page.request.post(base+'/studio/api/draft',{headers});assert.equal(r.status(),200);
  let state=await r.json();
  const answers=JSON.parse(fs.readFileSync('output/pdf/studio-section-documents/answers.json'));
  r=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,answers}});
  assert.equal(r.status(),200);
  await page.goto(base+'/studio?view=project');
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await idle();await page.locator('#calculation-details > summary').click();
  assert.equal(await page.locator('#design-basis').getAttribute('open'),null);
  await page.locator('#design-basis > summary').click();
  await page.locator('[data-basis="assignment"]').click();
  assert(await page.locator('#next-project_assignment_ref').isVisible());
  assert.equal(await page.evaluate(()=>document.activeElement.id),'next-project_assignment_ref');
  await page.locator('#next-project_assignment_ref').fill('ТЕСТ-ПЗ, приложение А');
  await page.locator('#next-project_survey_ref').fill('ТЕСТ-ИИ, том 1');
  await page.locator('#next-project_service_life_years').fill('100');
  await page.locator('#next-project_overhaul_period_years').fill('30');
  for(const width of [1440,390,320]) {
   await page.setViewportSize({width,height:1050});
   const box=await page.locator('#clarification-dialog').boundingBox();
   const rows=await page.locator('#clarification-body [data-input^="project_"] .field-control').evaluateAll(
    els=>els.map(el=>{const r=el.getBoundingClientRect();return {w:r.width,h:r.height,x:r.x};}));
   assert.equal(rows.length,4);assert(rows.every(r=>r.x>=box.x && r.x+r.w<=box.x+box.width+1));
   assert(Math.max(...rows.map(r=>r.w))-Math.min(...rows.map(r=>r.w))<1);
   assert(Math.max(...rows.map(r=>r.h))-Math.min(...rows.map(r=>r.h))<1);
   await page.locator('#next-project_assignment_ref').scrollIntoViewIfNeeded();
   await page.screenshot({path:`${out}/basis-${width}.png`});
  }
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  const water=page.locator('details[data-config-extra]').filter({has:page.locator('#next-water_tu_number')});
  await water.locator(':scope > summary').click();
  for(const [key,value] of Object.entries({water_source_description:'Учебная сеть',water_connection_point:'ВК-7',water_tu_org:'Тест В1',water_tu_number:'УЧ-В-001',water_tu_date:'2026-10-01'}))
   await page.locator('#next-'+key).fill(value);
  const sewer=page.locator('details[data-config-extra]').filter({has:page.locator('#next-wastewater_disposal_mode')});
  await sewer.locator(':scope > summary').click();
  assert(!(await page.locator('#next-wastewater_tu_number').isVisible()));
  await page.locator('#next-wastewater_disposal_mode').selectOption('centralized');
  assert(await page.locator('#next-wastewater_tu_number').isVisible());
  for(const [key,value] of Object.entries({wastewater_tu_org:'Тест К1',wastewater_tu_number:'УЧ-К-002',wastewater_tu_date:'02.10.2026'}))
   await page.locator('#next-'+key).fill(value);
  await page.locator('#next-wastewater_disposal_mode').selectOption('local');
  assert(!(await page.locator('#next-wastewater_tu_number').isVisible()));
  await page.locator('#next-wastewater_disposal_mode').selectOption('centralized');
  assert.equal(await page.locator('#next-wastewater_tu_number').inputValue(),'УЧ-К-002');
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  state=await(await page.request.get(base+'/studio/api/draft')).json();
  assert.equal(state.design_basis.filled,7);assert.equal(state.project_calculation.can_release,false);
  assert.equal(state.fields.find(f=>f.key==='water_tu_date').value,'01.10.2026');
  await page.reload();await idle();await page.locator('#calculation-details > summary').click();
  await page.locator('#design-basis > summary').click();
  await page.locator('[data-basis="water_tu"]').click();
  assert.equal(await page.locator('#next-water_tu_number').inputValue(),'УЧ-В-001');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'next-water_tu_org');
  assert.deepEqual(errors,[]);
  console.log('PASS: 3 sequential dialogs; optional references, targeted focus, separate TU, conditional fields, symmetric 1440/390/320, persistence, no JS errors');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
