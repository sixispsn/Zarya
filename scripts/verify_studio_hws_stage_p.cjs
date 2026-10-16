/* Reproducible local-only UI acceptance; never touches real user drafts. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.STUDIO_URL;
assert(base && ['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out='output/studio-hws-stage-p'; fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[]; page.on('pageerror',error=>errors.push(String(error)));
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  const state=async()=>await(await page.request.get(base+'/studio/api/draft')).json();
  await page.goto(base+'/studio'); await idle();
  await page.locator('[data-action="manual"]').click();
  await page.locator('#next-floors').waitFor();
  for(const [k,v] of Object.entries({floors:'2',floor_height_m:'3.3'})) await page.locator('#next-'+k).fill(v);
  await page.locator('#next-basement_kind').selectOption('none');
  await page.locator('[data-config-form] button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Подключение и ТУ'); await idle();
  await page.locator('[data-config-form] button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители'); await idle();
  await page.locator('#next-residents').fill('20');
  await page.locator('#next-apartments').fill('8');
  const extra=page.locator('[data-config-extra]').filter({has:page.locator('#next-hws_stage_p_enabled')});
  await extra.locator('summary').first().click();
  assert(!(await page.locator('#next-hws_delta_t_c').isVisible()));
  await page.locator('#next-hws_stage_p_enabled').selectOption('yes');
  await page.locator('#next-hws_water_towel_rails').selectOption('yes');
  await page.locator('#next-hws_circulation_zones').selectOption('1');
  await page.locator('#next-hws_delta_t_c').fill('5');
  for(const width of [1440,390,320]) {
   await page.setViewportSize({width,height:1050});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const box=await page.locator('#clarification-dialog').boundingBox();
   for(const input of await page.locator('#clarification-body .field-control:visible').all()) {
    const b=await input.boundingBox(); assert(b.x>=box.x && b.x+b.width<=box.x+box.width+1);
   }
   await page.screenshot({path:`${out}/input-${width}.png`});
  }
  await page.setViewportSize({width:1440,height:1050});
  await page.locator('[data-config-form] button[type="submit"]').click(); await idle();
  // Complete existing optional envelope fields through the same public API,
  // leaving pipes, lengths, PDF input and hydraulic paths entirely absent.
  let saved=await state();
  const response=await page.request.post(base+'/studio/api/calculate',{
   headers:{'X-Zarya-Studio':'1'},data:{revision:saved.revision,answers:{building_height_m:6.6,fire_height_m:4.8}}});
  assert.equal(response.status(),200,await response.text());
  await page.reload(); await idle();
  const details=page.locator('#calculation-details');
  if(await details.count()) await details.locator('summary').first().click();
  const result=page.locator('[data-hws-stage-p]'); await result.waitFor({state:'visible'});
  saved=await state();
  assert.equal(saved.project_calculation.hws_circulation.status,'preliminary');
  assert.equal(saved.project_calculation.hws_circulation.selected_flow_lps,null);
  await result.screenshot({path:out+'/range.png'});
  await page.locator('[data-action="hws-circulation"]').click();
  await page.locator('#next-hws_loss_percent').fill('35');
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  if(!(await result.isVisible())) await page.locator('#calculation-details > summary').click();
  assert((await state()).project_calculation.hws_circulation.selected_flow_lps>0);
  await result.screenshot({path:out+'/selected.png'});
  await page.reload();await idle();
  assert((await state()).project_calculation.hws_circulation.selected_flow_lps>0);
  assert.deepEqual(errors,[]);
  console.log('PASS: no plans, lengths or assistant-prepared geometry; range -> explicit choice -> reload; symmetric 320/390/1440px; no JS errors.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
