/* Disposable local users only. Tests real upload, consent, retry and downloads. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8776',keys=process.env.PILOT_QA_DIR;
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
assert(keys?.startsWith('/tmp/zarya-attachments-qa.'));
const out=path.resolve('output/pilot-attachments-qa');fs.mkdirSync(out,{recursive:true});
const headers={'Origin':base,'X-Zarya-Studio':'1'};
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'}),errors=[];
  try{
    async function login(name){
      const page=await browser.newPage({viewport:{width:1440,height:1050}});
      page.on('pageerror',e=>errors.push(String(e)));
      await page.goto(base+'/studio');await page.locator('#pilot-key').fill(fs.readFileSync(path.join(keys,name+'.key'),'utf8').trim());
      await page.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await page.waitForURL('**/studio');return page;
    }
    const page=await login('alice');
    const draft=await(await page.request.post(base+'/studio/api/draft',{headers})).json();
    assert.equal((await page.request.post(base+'/studio/api/calculate',{headers,data:{revision:draft.revision,answers:{residents:20,apartments:8,floors:2,consumer_code:'residential_full_bath',hws_type:'central'}}})).status(),200);
    const preview=await(await page.request.get(base+'/studio/api/pilot-snapshot')).json();
    const saved=await(await page.request.post(base+'/studio/api/pilot-versions',{headers,data:{revision:preview.revision,snapshot_sha256:preview.snapshot_sha256,request_id:crypto.randomUUID().replaceAll('-',''),title:'Дом-01 · экспертиза',consent:true}})).json();
    await page.goto(base+saved.url);await page.locator('[data-bundle-open]').click();
    const dialog=page.locator('#pilot-attachment');
    await dialog.locator('[name="files"]').setInputFiles([{name:'ПЗ.pdf',mimeType:'application/pdf',buffer:fs.readFileSync(path.join(keys,'test.pdf'))},{name:'Схемы.pdf',mimeType:'application/pdf',buffer:fs.readFileSync(path.join(keys,'test.pdf'))}]);
    await dialog.locator('[name="note"]').fill('Уточнили диаметры труб. Сохраняем итог для разбора замечаний.');
    await dialog.locator('[name="expertise_ref"]').fill('Тестовое заключение № 123');
    for(const name of ['consent','expertise_declared'])assert.equal(await dialog.locator(`[name="${name}"]`).isChecked(),false);
    await dialog.locator('[type="submit"]').click();assert.equal(await page.locator('.pilot-bundle').count(),0);
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1050});await dialog.locator('h2').click();
      const box=await dialog.boundingBox();assert(box.x>=0 && box.x+box.width<=width);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:out+`/upload-${width}.png`});
    }
    await page.setViewportSize({width:1440,height:1050});
    await dialog.locator('[name="consent"]').check();await dialog.locator('[name="expertise_declared"]').check();
    let first=null,calls=0;
    await page.route('**/studio/api/pilot-attachments',async route=>{
      calls++;
      if(!first){const response=await route.fetch();assert.equal(response.status(),200);first=await response.json();await route.abort('failed');}
      else await route.continue();
    });
    await dialog.locator('[type="submit"]').click();await dialog.locator('[data-bundle-error]').waitFor();
    assert.match(await dialog.locator('[data-bundle-error]').innerText(),/Ответ не получен/);
    await dialog.locator('[data-bundle-close]').click();await page.locator('[data-bundle-open]').click();
    await page.getByRole('button',{name:'Повторить сохранение'}).click();
    await page.locator('.pilot-bundle').waitFor();assert.equal(calls,2);assert.equal(await page.locator('.pilot-bundle').count(),1);
    assert.match(await page.locator('.pilot-bundle').innerText(),/со слов инженера/);
    const fileUrl=await page.locator('.pilot-bundle a').first().getAttribute('href');
    const file=await page.request.get(base+fileUrl);assert.equal(file.status(),200);assert.match(file.headers()['content-disposition'],/attachment/);
    assert.deepEqual(await file.body(),fs.readFileSync(path.join(keys,'test.pdf')));
    await page.screenshot({path:out+'/saved-desktop.png',fullPage:true});
    await page.setViewportSize({width:320,height:1050});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:out+'/saved-mobile.png',fullPage:true});
    const bob=await login('bob');assert.equal((await bob.request.get(base+fileUrl)).status(),404);
    const owner=await login('owner');await owner.goto(base+saved.url);assert.equal(await owner.locator('[data-bundle-open]').count(),0);
    assert.equal((await owner.request.get(base+fileUrl)).status(),200);
    assert.deepEqual(errors,[]);
    console.log('PASS: two explicit consents, 2 PDF, 320/390/1440px, immutable version, uncertain reply retry, owner download, Bob denied, no JS errors.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
