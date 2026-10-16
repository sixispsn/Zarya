/* Optional elevation controls, no extra mandatory step or measured network. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8789';
assert.equal(new URL(base).hostname,'127.0.0.1');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  const headers={Origin:base,'X-Zarya-Studio':'1'};
  let r=await page.request.post(base+'/studio/api/draft',{headers});assert.equal(r.status(),200);
  let state=await r.json();
  r=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,
    answers:JSON.parse(fs.readFileSync('output/pdf/section-elevations/answers.json'))}});
  assert.equal(r.status(),200,await r.text());
  await page.goto(base+'/studio?view=project');
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await idle();await page.locator('[data-action="config"][data-config="building"]').click();
  const group=page.locator('details[data-config-extra]').filter({has:page.locator('#next-section_zero_absolute_m')});
  assert.equal(await group.getAttribute('open'),null);
  await group.locator(':scope > summary').click();
  assert.equal(await page.locator('#next-section_zero_absolute_m').inputValue(),'100');
  fs.mkdirSync('output/studio-section-elevations-qa',{recursive:true});
  for(const width of [1440,390,320]) {
   await page.setViewportSize({width,height:1000});
   await page.locator('#next-section_zero_absolute_m').scrollIntoViewIfNeeded();
   const boxes=await group.locator('.field-control').evaluateAll(els=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,w:r.width,h:r.height};}));
   assert.equal(boxes.length,2);assert(Math.abs(boxes[0].w-boxes[1].w)<1);assert(Math.abs(boxes[0].h-boxes[1].h)<1);
   assert(boxes.every(b=>b.x>=0&&b.x+b.w<=width+1));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await page.screenshot({path:`output/studio-section-elevations-qa/datum-${width}.png`});
  }
  await page.locator('#next-section_zero_absolute_m').fill('120');
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  const mains=page.locator('details[data-config-extra]').filter({has:page.locator('#next-section_k1_start_invert_m')});
  await mains.locator(':scope > summary').click();
  assert.equal(await page.locator('#next-section_k1_start_invert_m').inputValue(),'-0.65');
  state=await(await page.request.get(base+'/studio/api/draft')).json();
  assert.equal(state.fields.find(f=>f.key==='section_zero_absolute_m').value,120);
  assert.equal(state.preview,null);
  assert.deepEqual(errors,[]);
  console.log('PASS: optional collapsed datum, symmetric 1440/390/320, persisted input, main elevation visible, no JS errors');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
