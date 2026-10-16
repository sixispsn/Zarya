const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base='http://127.0.0.1:8776',root=process.env.PILOT_QA_DIR;
assert(root?.startsWith('/tmp/zarya-attachments-qa.'));
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  try{
    const context=await browser.newContext(),page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/access/login');
    assert(await page.locator('#pilot-remember').isChecked());
    fs.mkdirSync('output/remember-device-qa',{recursive:true});
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      await page.screenshot({path:`output/remember-device-qa/login-${width}.png`,fullPage:true});
    }
    const key=fs.readFileSync(path.join(root,'owner.key'),'utf8').trim();
    await page.locator('#pilot-key').fill(key);await page.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await page.waitForURL('**/studio');
    const cookie=(await context.cookies()).find(c=>c.name==='zarya_pilot_session');
    assert(cookie.httpOnly && cookie.sameSite==='Strict' && cookie.expires>Date.now()/1000+80000);
    // Local QA invitation lasts only one day; the cookie must also respect it.
    assert(cookie.expires<=Date.now()/1000+86400);
    await page.request.post(base+'/access/logout',{headers:{'Origin':base,'X-Zarya-Access':'1'}});
    await page.goto(base+'/access/login');await page.locator('#pilot-remember').uncheck();
    await page.locator('#pilot-key').fill(key);await page.getByRole('button',{name:'Войти в ЗАРЮ'}).click();await page.waitForURL('**/studio');
    assert.equal((await context.cookies()).find(c=>c.name==='zarya_pilot_session').expires,-1);
    assert.deepEqual(errors,[]);
    console.log('PASS: checkbox default, real browser persistent/short cookies, key expiry cap, 320/390/1440px, no JS errors.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
