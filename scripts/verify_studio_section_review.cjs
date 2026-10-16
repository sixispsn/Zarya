/* Local UI proof, synthetic reviewer; never approves a real project. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8788';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out='output/studio-section-review-qa';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  const headers={Origin:base,'X-Zarya-Studio':'1'};
  const call=async(method,path,data)=>{const r=await page.request.fetch(base+path,{method,headers,data,timeout:240000});assert.equal(r.status(),200,await r.text());return r.json();};
  let state=await call('POST','/studio/api/draft');
  const answers=JSON.parse(fs.readFileSync('output/pdf/studio-section-documents/answers.json'));
  state=await call('POST','/studio/api/calculate',{revision:state.revision,answers});
  state=await call('POST','/studio/api/preview',{revision:state.revision});
  const before=state.project_calculation;
  await page.goto(base+'/studio?view=project');
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await idle();await page.locator('[data-action="documents"][data-view="scheme"]').click();await idle();
  assert.equal(await page.locator('#section-review').getAttribute('open'),null);
  await page.locator('#section-review > summary').click();
  for(const width of [1440,390,320]) {
   await page.setViewportSize({width,height:1050});
   await page.locator('#section-reviewer').scrollIntoViewIfNeeded();
   const sizes=await page.locator('#section-review .field-control').evaluateAll(els=>els.map(el=>{const b=el.getBoundingClientRect();return {w:b.width,h:b.height,x:b.x};}));
   assert.equal(sizes.length,2);assert(Math.abs(sizes[0].w-sizes[1].w)<1);assert(Math.abs(sizes[0].h-sizes[1].h)<1);
   assert(sizes.every(b=>b.x>=0&&b.x+b.w<=width+1));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
   await page.screenshot({path:`${out}/review-${width}.png`});
  }
  await page.locator('#section-reviewer').fill('Тестовый инженер <script>');
  await page.locator('#section-review-ar').fill('Учебная проверка — АР, лист 3');
  await page.locator('[data-action="section-review"]').click();await idle();
  assert((await page.locator('#section-review').innerText()).includes('просмотр сохранён'));
  assert((await page.locator('#section-review').innerText()).includes('Тестовый инженер <script>'));
  state=await call('GET','/studio/api/draft');
  assert.equal(state.section_review.state,'reviewed');assert.deepEqual(state.project_calculation,before);
  assert(await page.locator('[data-action="package"]').isDisabled());
  await page.screenshot({path:`${out}/saved.png`});
  state=await call('PATCH','/studio/api/answer',{revision:state.revision,field:'residents',value:501});
  assert.equal(state.section_review.state,'stale');
  assert.deepEqual(errors,[]);
  console.log('PASS: collapsed review, equal fields 1440/390/320, escaped values, actual save, unchanged calculation/release, stale after edit, no JS errors');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
