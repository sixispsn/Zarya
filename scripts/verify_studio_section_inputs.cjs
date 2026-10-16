/* Isolated local project: real optional controls, persistence and narrow layout. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8787';
assert(['localhost','127.0.0.1'].includes(new URL(base).hostname));
const answers=JSON.parse(fs.readFileSync('output/pdf/studio-section-documents/answers.json'));
const out='output/studio-section-inputs-qa';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  const headers={'X-Zarya-Studio':'1',Origin:base};
  let response=await page.request.post(base+'/studio/api/draft',{headers});
  assert.equal(response.status(),200);let state=await response.json();
  response=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,answers}});
  assert.equal(response.status(),200);state=await response.json();
  await page.goto(base+'/studio?view=project');
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await idle();await page.locator('[data-config="building"]').click();
  const fan=page.locator('[data-config-extra="building-1"]');
  assert(!(await fan.getAttribute('open')));
  await fan.locator('summary').click();
  assert.equal(await page.locator('#next-section_fan_mode').inputValue(),'common');
  assert.equal(await page.locator('#next-section_fan_working_diameter_mm').inputValue(),'100');
  await page.locator('#next-section_fan_mode').selectOption('individual');
  for(const key of ['working_diameter_mm','opening_distance_m','source_ref'])
   assert(await page.locator('#next-section_fan_'+key).isVisible());
  for(const key of ['member_ids','space','collector_low_m','collector_high_m'])
   assert(!(await page.locator('#next-section_fan_'+key).isVisible()));
  await page.locator('#next-section_fan_plastic_exposed').selectOption('no');
  assert(!(await page.locator('#next-section_fan_uv_protected').isVisible()));
  await page.locator('#next-section_fan_plastic_exposed').selectOption('yes');
  assert(await page.locator('#next-section_fan_uv_protected').isVisible());
  await page.locator('#next-section_fan_mode').selectOption('common');
  assert(await page.locator('#next-section_fan_collector_low_m').isVisible());
  for(const width of [1440,390,320]) {
   await page.setViewportSize({width,height:1050});
   const dialog=await page.locator('#clarification-dialog').boundingBox();
   assert(dialog.x>=0 && dialog.x+dialog.width<=width+1);
   const boxes=await page.locator('#clarification-body .field-control:visible').evaluateAll(
    rows=>rows.map(r=>{const b=r.getBoundingClientRect();return {x:b.x,w:b.width,h:b.height};}));
   assert(boxes.every(b=>b.x>=dialog.x && b.x+b.w<=dialog.x+dialog.width+1));
   // Source references intentionally span both columns; ordinary paired inputs match.
   const fanBoxes=await fan.locator('.setup-field:not(.setup-field-wide) .field-control:visible').evaluateAll(rows=>rows.map(r=>{
     const b=r.getBoundingClientRect();return {id:r.id,w:b.width,h:b.height};}));
   assert(Math.max(...fanBoxes.map(b=>b.w))-Math.min(...fanBoxes.map(b=>b.w))<1,JSON.stringify(fanBoxes));
   assert(Math.max(...fanBoxes.map(b=>b.h))-Math.min(...fanBoxes.map(b=>b.h))<1,JSON.stringify(fanBoxes));
   await page.locator('#next-section_fan_mode').scrollIntoViewIfNeeded();
   await page.screenshot({path:`${out}/fan-${width}.png`});
  }
  await page.setViewportSize({width:1440,height:1050});
  await fan.locator('summary').click();
  await page.locator('[data-config-extra="building-2"] > summary').click();
  await page.locator('#next-storm_funnels_count').fill('8');
  await page.locator('[data-config-extra="building-3"] > summary').click();
  assert.equal(await page.locator('#next-storm_selected_riser_dn_mm').inputValue(),'100');
  await page.screenshot({path:`${out}/k2.png`});
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  state=await(await page.request.get(base+'/studio/api/draft')).json();
  const values=Object.fromEntries(state.fields.map(r=>[r.key,r.value]));
  assert.equal(values.storm_funnels_count,8);
  assert.equal(values.section_fan_mode,'common');
  assert.equal(values.section_fan_collector_low_m,49.5);
  assert.equal(values.section_fan_working_diameter_mm,100);
  await page.reload();await idle();await page.locator('[data-config="building"]').click();
  await page.locator('[data-config-extra="building-2"] > summary').click();
  assert.equal(await page.locator('#next-storm_funnels_count').inputValue(),'8');
  assert.deepEqual(errors,[]);
  console.log('PASS: collapsed optional K2/fan controls, common/individual visibility, save/reload, symmetric 1440/390/320 px, no JS errors');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
