/* Only disposable localhost identities. No real invitation keys in output. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8776',keys=process.env.PILOT_QA_DIR;
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
assert(keys?.startsWith('/tmp/zarya-attachments-qa.'));
const out=path.resolve('output/pilot-admin-qa');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'}),errors=[];
  try{
    const owner=await browser.newPage({viewport:{width:1440,height:1050}});
    owner.on('pageerror',e=>errors.push(e.message));
    await owner.goto(base+'/access/login');await owner.locator('#pilot-key').fill(fs.readFileSync(path.join(keys,'owner.key'),'utf8').trim());
    await owner.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await owner.waitForURL('**/studio');
    await owner.goto(base+'/access/admin');
    for(const width of [1440,390,320]){
      await owner.setViewportSize({width,height:1050});assert(await owner.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await owner.screenshot({path:out+`/admin-${width}.png`,fullPage:true});
    }
    await owner.locator('[name="name"]').fill('QA приглашённый инженер');
    await owner.getByRole('button',{name:'Создать приглашение'}).click();
    const dialog=owner.locator('#admin-key');await dialog.waitFor();
    const invitation=await owner.locator('[data-invitation]').inputValue();
    const key=invitation.match(/zarya_[A-Za-z0-9_-]+/)[0];
    // Never screenshot the one-time secret.
    await owner.getByRole('button',{name:'Готово',exact:true}).click();await owner.waitForLoadState();
    const tester=await browser.newPage({viewport:{width:390,height:1050}});
    tester.on('pageerror',e=>errors.push(e.message));
    await tester.goto(base+'/access/login');await tester.locator('#pilot-key').fill(key);
    await tester.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await tester.waitForURL('**/access/participation');
    assert.equal(await tester.locator('[name="accepted"]').isChecked(),false);
    assert(await tester.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await tester.screenshot({path:out+'/participation-mobile.png',fullPage:true});
    await tester.locator('[name="accepted"]').check();await tester.getByRole('button',{name:'Принять и открыть Studio'}).click();await tester.waitForURL('**/studio');
    await tester.goto(base+'/studio/projects');await tester.locator('[name="title"]').fill('Дом QA-01');
    await tester.getByRole('button',{name:'Создать проект'}).click();await tester.waitForURL('**/studio?view=project');
    const h={'X-Zarya-Studio':'1','Origin':base};
    const state=await (await tester.request.get(base+'/studio/api/draft')).json();
    const calc=await tester.request.post(base+'/studio/api/calculate',{headers:h,data:{revision:state.revision,answers:{residents:20,consumer_code:'residential_full_bath',hws_type:'central'}}});
    assert.equal(calc.status(),200);const saved=(await calc.json()).pilot_archive;assert.equal(saved.state,'saved');
    await tester.goto(base+saved.url);assert.match(await tester.locator('main').innerText(),/Дом QA-01/);
    assert.equal((await tester.request.get(base+'/access/admin')).status(),403);
    await owner.goto(base+saved.url);assert.match(await owner.locator('main').innerText(),/Дом QA-01/);
    await owner.screenshot({path:out+'/baseline-mobile.png',fullPage:true});
    await owner.goto(base+'/access/admin');
    owner.once('dialog',d=>d.accept());
    await owner.locator('article').filter({hasText:'QA приглашённый инженер'}).getByRole('button',{name:'Отозвать доступ'}).click();
    await owner.waitForLoadState();await owner.locator('article').filter({hasText:'QA приглашённый инженер'}).getByText('Инженер · Отозван', {exact:false}).waitFor();
    assert.equal((await tester.request.get(base+'/studio/api/draft')).status(),401);
    assert.deepEqual(errors,[]);
    console.log('PASS: admin 320/390/1440px, one-time invitation, consent, separate project, automatic baseline, owner view, revoke, no JS errors.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
