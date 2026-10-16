/* Synthetic local UI checks. Public map tiles must not be scraped by QA bots. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8776';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out='output/site-location-qa';fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[],tiles=[];page.on('pageerror',e=>errors.push(String(e)));
  // Synthetic grid, not a downloaded real map. No external provider calls.
  await page.route('https://tile.openstreetmap.org/**',async route=>{
   tiles.push(route.request());
   await route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#edf0ed"/><path d="M0 75H256M75 0V256M0 200H256M200 0V256" stroke="white" stroke-width="12"/><path d="M10 100h45v70H10ZM100 10h75v45h-75ZM100 100h65v65h-65Z" fill="#d6ddd6"/></svg>'});
  });
  await page.route('**/studio/api/location/search',r=>r.fulfill({json:{results:[{latitude:55.75,longitude:37.62,label:'Москва · тестовый адрес',source:'search'}]}}));
  await page.goto(base+'/studio');
  if((await page.locator('#pilot-login-form').count()) || new URL(page.url()).pathname==='/access/login') {
   const key=fs.readFileSync(process.env.PILOT_UI_KEY_FILE,'utf8').trim();
   const login=await page.request.post(base+'/access/login',{data:{key},headers:{'X-Zarya-Access':'1','Origin':base}});assert.equal(login.status(),200);await page.goto(base+'/studio');
  }
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await idle();
  await page.locator('[data-action="manual"]').click();await page.locator('#next-floors').waitFor();await idle();
  await page.locator('#next-floors').fill('3');
  await page.locator('[data-action="site-location"]').click();
  assert.equal(tiles.length,0);
  assert.equal(await page.locator('#location-lat').inputValue(),'');
  // Offline/manual fallback, and unrelated unsaved engineering edits survive.
  await page.locator('.location-manual summary').click();
  await page.locator('#location-lat').fill('55,75');await page.locator('#location-lon').fill('37,62');
  await page.locator('#location-label').fill('Тестовый объект');
  await page.locator('[data-location-save]').click();await page.waitForFunction(()=>!document.querySelector('#site-location-dialog').open);
  assert.equal(tiles.length,0);assert.equal(await page.locator('#next-floors').inputValue(),'3');
  assert.equal(await page.locator('[data-location-summary]').textContent(),'Тестовый объект');
  const state=await(await page.request.get(base+'/studio/api/draft')).json();
  assert.equal(state.site_location.latitude,55.75);assert.equal(state.fields.find(f=>f.key==='floors').value,null);
  await page.locator('[data-action="site-location"]').click();
  assert.equal(await page.locator('#location-label').inputValue(),'Тестовый объект');
  await page.locator('[data-location-enable]').click();await page.locator('.leaflet-container').waitFor();
  await page.waitForFunction(()=>!document.querySelector('[data-location-search]').disabled);
  assert(tiles.length>0);assert(tiles.every(r=>r.headers().referer===base+'/'),'Tiles send origin only, not private paths');
  assert.equal(await page.locator('#location-map .leaflet-tile').first().getAttribute('referrerpolicy'),'origin');
  await page.locator('#location-query').fill('Москва');await page.locator('[data-location-search]').click();
  await page.locator('.location-results button').click();
  await page.screenshot({path:out+'/desktop.png'});
  for(const width of [390,320]) {
   await page.setViewportSize({width,height:850});
   await page.screenshot({path:out+`/mobile-${width}.png`});
   const box=await page.locator('#site-location-dialog').boundingBox();assert(box.x>=0 && box.x+box.width<=width);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   const widths=await page.locator('.location-coordinates input').evaluateAll(els=>els.map(e=>e.getBoundingClientRect().width));
   assert(Math.abs(widths[0]-widths[1])<1);
  }
  await page.locator('[data-location-save]').click();await page.waitForFunction(()=>!document.querySelector('#site-location-dialog').open);
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  assert.equal(await page.locator('#next-title').textContent(),'Подключение и ТУ');
  const saved=await(await page.request.get(base+'/studio/api/draft')).json();
  assert.equal(saved.fields.find(f=>f.key==='floors').value,3);
  assert.equal(saved.site_location.label,'Москва · тестовый адрес');
  assert.deepEqual(errors,[]);
  console.log('PASS: manual + map + search, lazy external calls, origin referrer, persisted point, unsaved form preserved, 320/390/1440 px, no JS errors.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
