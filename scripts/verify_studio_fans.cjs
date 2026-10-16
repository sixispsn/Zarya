// Disposable real HTTP/browser exercise. No handoff substitution or production writes.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zarya-fan-editor-'));
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
  // Existing explicit pipe fixture and building inputs through public API; fan endings only via UI.
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_network_input_boundary import ordinary_answers; from tests.test_studio_sewer_pipes import rows; from tests.test_studio_sewer_elements import rows as elements; print(json.dumps({**ordinary_answers(), "sewer_pipes":rows(), "sewer_elements":elements()}))'],{encoding:'utf8'}));
  const rid=answers.sewer_pipes[0].section_id;
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  await page.goto('/studio?view=project');await idle();
  const open=async()=>{
    await page.locator('[data-config="connection"]').click();
    const summary=page.getByText('Фановые окончания · реальная сеть К1',{exact:true});
    if(await summary.locator('..').getAttribute('open')===null) await summary.click();
  };
  const submit=async(status=200)=>{
    const response=page.waitForResponse(r=>r.url().endsWith('/api/answers') && r.request().method()==='PATCH');
    await page.locator('[data-config-form] button[type="submit"]').click();
    assert.equal((await response).status(),status);await idle();
  };
  await open();
  const editor=page.locator('#clarification-body [data-input="wastewater_fan_ventilation"]');
  const field=key=>editor.locator('[data-column="'+key+'"]');
  const global=key=>editor.locator('[data-fan-global="'+key+'"]');
  await editor.getByRole('button',{name:'+ Добавить фановое окончание'}).click();
  for(const key of ['kind','height_m','open_end_confirmed','riser_ids']) assert.equal(await field(key).inputValue(),'');
  await field('terminal_id').fill('Ф-Тест');await field('riser_ids').fill(rid);
  await field('kind').selectOption('roof');
  await field('source_ref').fill('Явные TEST-ONLY данные АР, лист 1');
  await global('external_ventilation_verified').selectOption('false');
  await global('external_ventilation_ref').fill('Тест: наружная сеть не подтверждена');
  await editor.screenshot({path:path.join(root,'editor-desktop.png')});
  await editor.locator('.sewer-pipe-options > summary').click();
  await field('height_m').fill('0');await field('opening_distance_m').fill('4,5');
  await field('open_end_confirmed').selectOption('false');
  await page.setViewportSize({width:390,height:844});
  await field('riser_ids').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-top.png')});
  await field('open_end_confirmed').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-details.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await editor.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await page.setViewportSize({width:1440,height:1000});await submit();
  const evidence=s=>s.fields.find(f=>f.key==='wastewater_fan_ventilation').value;
  let saved=await state(), data=evidence(saved);
  assert.equal(data.terminals[0].height_m,0);assert.equal(data.terminals[0].opening_distance_m,4.5);
  assert.equal(data.terminals[0].open_end_confirmed,false);assert.equal(data.terminals[0].diameter_mm,null);
  assert.equal(data.external_ventilation_verified,false);
  await page.reload();await idle();await open();
  assert.equal(await field('riser_ids').inputValue(),rid);
  assert.equal(await global('external_ventilation_verified').inputValue(),'false');
  const before=JSON.stringify(saved);
  await field('riser_ids').fill('Нет такого стояка');await submit(422);
  assert.equal(JSON.stringify(await state()),before);assert(await page.locator('#error').isVisible());
  await page.screenshot({path:path.join(root,'invalid-link.png')});
  await open();assert.equal(await field('riser_ids').inputValue(),'Нет такого стояка');
  assert.equal(await global('external_ventilation_verified').inputValue(),'false');
  await field('riser_ids').fill(rid);await field('source_ref').fill('Исправленный источник, лист 2');await submit();
  saved=await state();
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:saved.revision}})).status(),200);
  saved=await state();assert.equal(saved.project_calculation.can_release,false);assert.equal(saved.project_calculation.sewer_scheme.ready,false);
  assert(saved.project_calculation.sewer_scheme.reasons.some(r=>r.includes('Режим стояка')));
  await page.reload();await idle();await open();
  await editor.getByRole('button',{name:'Удалить фановое окончание К1 1'}).click();
  await global('external_ventilation_verified').selectOption('');
  await global('external_ventilation_ref').fill('');await submit();
  assert.equal(evidence(await state()),null);assert.deepEqual(report.errors,[]);
  report.passed=true;console.log('PASS: fan blank/unknown fields, UI save/reopen, external evidence, invalid link/repair, delete, pending modes, desktop/mobile.');
 } finally {
  if(browser)await browser.close();server.kill('SIGTERM');
  fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);
 }
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
