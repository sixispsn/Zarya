// Disposable real HTTP/browser exercise. No handoff substitution or production writes.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zarya-sewer-elements-'));
const python=path.resolve('venv/bin/python');
const server=spawn(python,['-m','scripts.studio_file_smoke_server',root,'--empty'],{stdio:['ignore','pipe','pipe']});
let logs=''; for(const stream of [server.stdout,server.stderr]) stream.on('data',chunk=>{logs+=chunk;});
(async()=>{
 let browser;
 const report={root,errors:[],passed:false};
 try {
  const file=path.join(root,'fixture.json');
  for(let i=0;i<200 && !fs.existsSync(file);i++){if(server.exitCode!==null)throw Error(logs);await delay(100);}
  const {base_url:base}=JSON.parse(fs.readFileSync(file));
  for(let i=0;i<100;i++){try{if((await fetch(base+'/studio')).ok)break;}catch{} if(i===99)throw Error(logs);await delay(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:1000},reducedMotion:'reduce',
    extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
  const page=await context.newPage(); page.on('pageerror',e=>report.errors.push(e.message));
  const state=async()=>await(await context.request.get('/studio/api/draft')).json();
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  const initial=await(await context.request.post('/studio/api/draft')).json();
  // Existing explicit pipe fixture and building inputs through public API; elements only via UI.
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_network_input_boundary import ordinary_answers; from tests.test_studio_sewer_pipes import rows; print(json.dumps({**ordinary_answers(), "sewer_pipes":rows()}))'],{encoding:'utf8'}));
  const section=answers.sewer_pipes[0].section_id;
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  await page.goto('/studio?view=project');await idle();
  const open=async()=>{
    await page.locator('[data-config="connection"]').click();
    const summary=page.getByText('Элементы К1/К2 · отдельный реестр',{exact:true});
    if(await summary.locator('..').getAttribute('open')===null) await summary.click();
  };
  const submit=async(status=200)=>{
    const response=page.waitForResponse(r=>r.url().endsWith('/api/answers') && r.request().method()==='PATCH');
    await page.locator('[data-config-form] button[type="submit"]').click();
    assert.equal((await response).status(),status);await idle();
  };
  await open();
  const editor=page.locator('#clarification-body [data-input="sewer_elements"]');
  const field=key=>editor.locator(`[data-column="${key}"]`);
  await editor.getByRole('button',{name:'+ Добавить элемент реальной сети К1/К2'}).click();
  for(const key of ['quantity','floor_from','accessible','include_in_spec','kind','system']) assert.equal(await field(key).inputValue(),'');
  for(const [key,value] of Object.entries({element_id:'Р-Тест',name:'Тестовая ревизия',quantity:'2',floor_from:'0',section_id:section,connects_to:section})) await field(key).fill(value);
  for(const [key,value] of Object.entries({system:'K1',kind:'revision',accessible:'false',include_in_spec:'false'})) await field(key).selectOption(value);
  await editor.screenshot({path:path.join(root,'editor-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await field('element_id').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-top.png')});
  await field('accessible').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-bottom.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await editor.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await page.setViewportSize({width:1440,height:1000});
  await editor.locator('.sewer-pipe-options > summary').click();
  await field('typical_quantity').fill('1');await field('floor_to').fill('1');
  await field('elevation_m').fill('0');await field('service_chainage_m').fill('0');
  await submit();
  let saved=await state();
  const elements=s=>s.fields.find(f=>f.key==='sewer_elements').value;
  const row=elements(saved)[0];
  assert.equal(row.quantity,2);assert.equal(row.floor_from,0);assert.equal(row.accessible,false);
  assert.equal(row.typical_quantity,1);assert.equal(row.elevation_m,0);assert.equal(row.service_chainage_m,0);
  assert.equal(row.dn_mm,null);assert.equal(row.manufacturer,'');assert.equal(row.include_in_spec,false);
  await page.reload();await idle();await open();
  assert.equal(await field('quantity').inputValue(),'2');assert.equal(await field('accessible').inputValue(),'false');
  const before=JSON.stringify(saved);
  await field('connects_to').fill('Нет такого узла');await submit(422);
  assert.equal(JSON.stringify(await state()),before);assert(await page.locator('#error').isVisible());
  await page.screenshot({path:path.join(root,'invalid-link.png')});
  await open();assert.equal(await field('connects_to').inputValue(),'Нет такого узла');
  await field('connects_to').fill(section);await field('quantity').fill('3');await submit();
  saved=await state();assert.equal(elements(saved)[0].quantity,3);
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:saved.revision}})).status(),200);
  saved=await state();assert.equal(saved.project_calculation.can_release,false);assert.equal(saved.project_calculation.sewer_scheme.ready,false);
  await page.reload();await idle();await open();
  await editor.getByRole('button',{name:'Удалить элемент К1/К2 1'}).click();await submit();
  assert.equal(elements(await state()),null);assert.deepEqual(report.errors,[]);
  report.passed=true;console.log('PASS: explicit empty row, save/reopen, unknown link 422, repair/delete, incomplete network, desktop/mobile.');
 } finally {
  if(browser)await browser.close();server.kill('SIGTERM');
  fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);
 }
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
