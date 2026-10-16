/* Isolated browser session, local Studio only. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
  const state=async()=>await (await page.request.get(base+'/studio/api/draft')).json();
  await page.goto(base+'/studio');await idle();
  await page.getByRole('button',{name:'Начать без документов'}).click();await idle();
  const response=await page.request.post(base+'/studio/api/calculate',{headers:{'X-Zarya-Studio':'1'},data:{revision:(await state()).revision,answers:{
   residents:20,consumer_code:'residential_full_bath',floors:2,apartments:8,
   building_height_m:6.6,fire_height_m:4.8,hws_type:'central',h_geom_m:6,
   guaranteed_head_m:5,h_apartment_c_meter_m:.5,h_apartment_h_meter_m:.7,
   hws_heater_in_scope:'yes',h_tepl_m:3,pressure_loss_mode:'ready',h_il_m:2,h_vvod_m:1,
   t3_loss_mode:'sections',
  }}});
  assert.equal(response.status(),200,await response.text());
  await page.reload();await idle();
  const editor=page.locator('[data-next-step] [data-input="t3_sections"]');
  assert(await editor.isVisible());
  await editor.getByRole('button',{name:'+ Добавить участок Т3',exact:true}).click();
  const row=editor.locator('.route-row');
  for(const [key,value] of Object.entries({length_m:'12',inner_diameter_mm:'26',roughness_mm:'0,01',flow_lps:'0,4',velocity_limit_mps:'1'}))
   await row.locator(`[data-column="${key}"]`).fill(value);
  await row.locator('[data-column="flow_mode"]').selectOption('main');
  assert(await row.locator('[data-column="circulation_flow_lps"]').isVisible());
  await page.getByRole('button',{name:'Продолжить',exact:true}).click();await idle();
  assert(!(await state()).project_calculation.head.ready);
  assert((await state()).project_calculation.hot_hydraulics.missing[0].includes('qcir'));
  await editor.locator('[data-column="circulation_flow_lps"]').fill('0,1');
  fs.mkdirSync('output/studio-preview/t3',{recursive:true});
  await page.screenshot({path:'output/studio-preview/t3/editor.png',fullPage:true});
  await page.getByRole('button',{name:'Продолжить',exact:true}).click();await idle();
  let draft=await state();
  assert(draft.project_calculation.head.ready);
  assert.equal(draft.project_calculation.hot_hydraulics.sections[0].circulation_factor,0);
  await page.locator('#calculation-details > summary').click();
  await page.locator('#hot-hydraulic-results > summary').click();
  await page.locator('#hot-hydraulic-results').screenshot({path:'output/studio-preview/t3/result.png'});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'output/studio-preview/t3/mobile.png',fullPage:true});
  await page.locator('#setup-details > summary').click();
  await page.locator('#manual-entry > summary').click();
  await page.locator('#field-t3_loss_mode').selectOption('ready');
  assert(await page.locator('#field-h_il_hot_m').isVisible());
  await page.locator('#field-h_il_hot_m').fill('7');
  await page.locator('[data-action="calculate"]').click();await idle();
  assert.equal((await state()).project_calculation.hot_hydraulics,null);
  await page.reload();await idle();
  assert.equal(await page.locator('#field-t3_loss_mode').inputValue(),'ready');
  await page.locator('#setup-details > summary').click();
  await page.locator('#manual-entry > summary').click();
  await page.locator('#field-t3_loss_mode').selectOption('sections');
  await page.locator('#setup-form [data-input="t3_sections"] [data-column="length_m"]').fill('24');
  await page.locator('[data-action="calculate"]').click();await idle();
  draft=await state();
  assert(draft.project_calculation.head.ready);
  assert(draft.project_calculation.hot_hydraulics.total_loss_m<7);
  assert.equal(draft.project_calculation.hot_hydraulics.sections[0].length_m,24);
  assert.deepEqual(errors,[]);
  console.log('PASS: T3 editor, missing qcir gate, live calculation, ready/sections switch, reload, mobile');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
