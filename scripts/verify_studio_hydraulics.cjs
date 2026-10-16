/* Isolated local-browser regression: no real project or PDF is changed. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:1100}});
  const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
  await page.goto(base+'/studio'); await idle();
  await page.getByRole('button',{name:'Начать без документов'}).click(); await idle();
  let state=await (await page.request.get(base+'/studio/api/draft')).json();
  const seeded=await page.request.post(base+'/studio/api/calculate',{headers:{'X-Zarya-Studio':'1'},data:{revision:state.revision,answers:{
   residents:20,consumer_code:'residential_full_bath',floors:2,apartments:8,
   building_height_m:6.6,fire_height_m:4.8,hws_type:'none',h_geom_m:6,
   guaranteed_head_m:5,h_apartment_c_meter_m:.5,
  }}});
  assert.equal(seeded.status(),200);
  await page.reload(); await idle();
  assert.equal(await page.locator('#next-title').innerText(),'Напор: расчётный путь');
  assert.equal(await page.locator('#next-pressure_loss_mode').inputValue(),'sections');
  assert(!(await page.locator('#next-h_il_m').isVisible()));
  assert(!(await page.locator('#next-h_il_hot_m').isVisible()));
  const editor=page.locator('[data-next-step] [data-input="v1_sections"]');
  for(const row of [{length_m:'12',inner_diameter_mm:'40',roughness_mm:'0,1'},
                    {length_m:'16',inner_diameter_mm:'26',roughness_mm:'0,01',flow_lps:'0,35'}]) {
   await editor.getByRole('button',{name:'+ Добавить участок'}).click();
   const current=editor.locator('.route-row').last();
   for(const [key,value] of Object.entries(row)) await current.locator(`[data-column="${key}"]`).fill(value);
  }
  fs.mkdirSync('output/studio-preview/hydraulics',{recursive:true});
  await page.screenshot({path:'output/studio-preview/hydraulics/desktop.png',fullPage:true});
  await page.setViewportSize({width:375,height:850});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'output/studio-preview/hydraulics/mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Продолжить',exact:true}).click(); await idle();
  state=await (await page.request.get(base+'/studio/api/draft')).json();
  assert(state.project_calculation.head.ready);
  assert.equal(state.project_calculation.hydraulics.sections.length,2);
  assert(state.project_calculation.hydraulics.sections.every(row=>row.local_loss_factor===.3));
  const previousFlow=state.project_calculation.hydraulics.sections[0].flow_lps;
  await page.locator('#setup-details > summary').click();
  await page.locator('#field-residents').fill('100');
  assert(!(await page.locator('#calculation').isVisible()));
  await page.locator('[data-action="calculate"]').click(); await idle();
  state=await (await page.request.get(base+'/studio/api/draft')).json();
  assert(state.project_calculation.hydraulics.sections[0].flow_lps>previousFlow);
  assert.equal(state.project_calculation.hydraulics.sections[1].flow_lps,.35);
  await page.locator('#calculation-details > summary').click();
  await page.locator('#hydraulic-results > summary').click();
  await page.screenshot({path:'output/studio-preview/hydraulics/result.png',fullPage:true});
  await page.locator('#setup-details > summary').click();
  await page.locator('#manual-entry > summary').click();
  await page.locator('#field-pressure_loss_mode').selectOption('ready');
  assert(await page.locator('#field-h_il_m').isVisible());
  assert(!(await page.locator('#field-v1_sections').isVisible()));
  await page.locator('#field-h_il_m').fill('3');
  await page.locator('#field-h_vvod_m').fill('1');
  await page.locator('[data-action="calculate"]').click(); await idle();
  state=await (await page.request.get(base+'/studio/api/draft')).json();
  assert.equal(state.project_calculation.hydraulics,null);
  assert(state.project_calculation.head.ready);
  await page.reload(); await idle();
  assert.equal(await page.locator('#field-pressure_loss_mode').inputValue(),'ready');
  assert.deepEqual(errors,[]);
  console.log('PASS: sections, auto inlet, live demand, mobile, ready mode and reload');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
