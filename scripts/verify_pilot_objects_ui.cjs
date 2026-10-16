/* Disposable local accounts only; never use a real owner's key with this script. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8776';
const keys=process.env.PILOT_QA_DIR;
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
assert(keys?.startsWith('/tmp/zarya-objects-qa.'));
const out=path.resolve('output/pilot-objects-qa');fs.mkdirSync(out,{recursive:true});
const headers={'Origin':base,'X-Zarya-Studio':'1'};
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const errors=[];
  try {
    async function login(name) {
      const page=await browser.newPage({viewport:{width:1440,height:1050}});
      page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(base+'/studio');
      await page.locator('#pilot-key').fill(fs.readFileSync(path.join(keys,name+'.key'),'utf8').trim());
      await page.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await page.waitForURL('**/studio');
      return page;
    }
    const page=await login('alice');
    let state=await(await page.request.post(base+'/studio/api/draft',{headers})).json();
    const result=await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,answers:{
      residents:20,consumer_code:'residential_full_bath',apartments:8,floors:2,
      building_height_m:6.6,fire_height_m:4.8,hws_type:'central'
    }}});
    assert.equal(result.status(),200);state=await result.json();
    await page.goto(base+'/studio?view=project');await page.locator('#calculation-title').waitFor();
    await page.locator('[data-action="pilot-snapshot"]').click();await page.locator('#pilot-snapshot-form').waitFor();
    await page.locator('#pilot-snapshot [name="title"]').fill('Дом · UI-проверка');
    await page.locator('#pilot-snapshot [name="note"]').fill('Первая версия · 20 жителей');
    assert.equal(await page.locator('#pilot-snapshot [name="consent"]').isChecked(),false);
    await page.locator('#pilot-snapshot [type="submit"]').click();
    assert(!(await page.locator('[data-snapshot-result]').isVisible()));
    for(const width of [1440,390,320]) {
      await page.setViewportSize({width,height:1050});
      const box=await page.locator('#pilot-snapshot').boundingBox();
      assert(box.x>=0 && box.x+box.width<=width);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:out+`/save-${width}.png`});
    }
    await page.setViewportSize({width:1440,height:1050});
    await page.locator('#pilot-snapshot [name="consent"]').check();
    let first=null;const requests=[];
    await page.route('**/studio/api/pilot-versions',async route=>{
      requests.push(route.request().postDataJSON());
      if(!first) {const response=await route.fetch();first=await response.json();await route.abort('failed');}
      else await route.continue();
    });
    await page.locator('#pilot-snapshot [type="submit"]').click();
    await page.getByText('Ответ сервера не получен.',{exact:false}).waitFor();
    await page.locator('[data-snapshot-close]').click();
    await page.locator('[data-action="pilot-snapshot"]').click();
    await page.getByRole('button',{name:'Повторить сохранение'}).click();
    await page.locator('[data-snapshot-result]').waitFor();
    assert.deepEqual(requests[0],requests[1]);assert.equal(first.version,1);
    await page.locator('[data-snapshot-result] a').click();
    await page.locator('.pilot-metrics').waitFor();
    assert.match(await page.locator('.pilot-metrics').innerText(),/3\.6/);
    await page.screenshot({path:out+'/version-1.png',fullPage:true});
    state=await(await page.request.get(base+'/studio/api/draft')).json();
    assert.equal((await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:state.revision,answers:{residents:40}}})).status(),200);
    await page.goto(base+'/studio?view=project');await page.locator('#calculation-title').waitFor();
    await page.locator('[data-action="pilot-snapshot"]').click();await page.locator('#pilot-snapshot-form').waitFor();
    await page.locator('#pilot-snapshot [name="object_id"]').selectOption(first.object_id);
    assert(!(await page.locator('#pilot-snapshot [name="title"]').isVisible()));
    await page.locator('#pilot-snapshot [name="note"]').fill('Вторая версия · 40 жителей');
    await page.locator('#pilot-snapshot [name="consent"]').check();
    await page.locator('#pilot-snapshot [type="submit"]').click();await page.locator('[data-snapshot-result]').waitFor();
    assert.match(await page.locator('[data-snapshot-result]').innerText(),/Версия 2/);
    await page.goto(base+`/studio/pilot-objects/${first.object_id}`);
    assert.equal(await page.locator('.pilot-object').count(),2);
    await page.screenshot({path:out+'/history.png',fullPage:true});
    await page.goto(base+first.url);assert.match(await page.locator('.pilot-metrics').innerText(),/3\.6/);
    const bob=await login('bob');assert.equal((await bob.request.get(base+first.url)).status(),404);
    const owner=await login('owner');await owner.goto(base+'/studio/pilot-objects');
    assert.match(await owner.locator('.pilot-archive').innerText(),/Дом · UI-проверка/);
    await owner.screenshot({path:out+'/owner-objects.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: explicit unchecked consent, immutable two-version history, lost-reply retry without duplicate, tester/owner permissions, 320/390/1440px, no JS errors.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
