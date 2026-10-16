// Real registry UI + HTTP, own disposable loopback server; no model substitution.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zarya-sewer-editor-'));
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
  // Basic building answers through the public API; registry itself is entered only through UI.
  const initial=await(await context.request.post('/studio/api/draft')).json();
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_network_input_boundary import ordinary_answers; print(json.dumps(ordinary_answers()))'],{encoding:'utf8'}));
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  await page.goto('/studio?view=project');await idle();
  const open=async()=>{
    await page.locator('[data-config="connection"]').click();
    const summary=page.getByText('Реальные участки К1/К2 · отдельный реестр',{exact:true});
    const details=summary.locator('..');
    if(!(await details.getAttribute('open')!==null)) await summary.click();
  };
  await open();
  const editor=page.locator('#clarification-body [data-input="sewer_pipes"]');
  await editor.getByRole('button',{name:'+ Добавить реальный участок К1/К2'}).click();
  assert.equal(await editor.locator('[data-column="length_m"]').inputValue(),'');
  assert.equal(await editor.locator('[data-column="system"]').inputValue(),'');
  const values={section_id:'К1-СтТест',purpose:'стояк К1',material:'ПП',standard:'Явный тестовый стандарт',
    outer_diameter_mm:'110',wall_thickness_mm:'3,4',length_m:'3,3',from_node:'К1-ВентТест',to_node:'К1-СтТест'};
  for(const [key,value] of Object.entries(values)) await editor.locator(`[data-column="${key}"]`).fill(value);
  await editor.locator('[data-column="system"]').selectOption('K1');
  await editor.locator('[data-column="insulated"]').selectOption('false');
  await editor.screenshot({path:path.join(root,'editor-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await editor.locator('[data-column="system"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'editor-mobile-top.png')});
  await editor.locator('[data-column="insulated"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'editor-mobile-bottom.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await editor.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await page.setViewportSize({width:1440,height:1000});
  await editor.locator('.sewer-pipe-options > summary').click();
  await editor.locator('[data-column="elevation_start_m"]').fill('0');
  await editor.locator('[data-column="elevation_end_m"]').fill('-3,3');
  await editor.locator('[data-column="pressure_rated"]').selectOption('false');
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  let saved=await state();
  const pipes=s=>s.fields.find(f=>f.key==='sewer_pipes').value;
  assert.equal(pipes(saved)[0].length_m,3.3);
  assert.equal(pipes(saved)[0].insulated,false);
  assert.equal(pipes(saved)[0].design_flow_lps,null);
  assert.equal(pipes(saved)[0].elevation_start_m,0);
  assert.equal(pipes(saved)[0].elevation_end_m,-3.3);
  assert.equal(pipes(saved)[0].pressure_rated,false);
  await page.reload();await idle();await open();
  assert.equal(await editor.locator('[data-column="length_m"]').inputValue(),'3.3');
  const before=JSON.stringify(saved);
  await editor.locator('[data-column="length_m"]').fill('');
  const failure=page.waitForResponse(r=>r.url().endsWith('/api/answers') && r.request().method()==='PATCH');
  await page.locator('[data-config-form] button[type="submit"]').click();
  assert.equal((await failure).status(),422);await idle();
  assert.equal(JSON.stringify(await state()),before);
  assert(await page.locator('#error').isVisible());
  await page.screenshot({path:path.join(root,'invalid-row.png')});
  // Existing Studio error flow closes the dialog; reopen without losing the draft edit.
  await open();
  assert.equal(await editor.locator('[data-column="length_m"]').inputValue(),'');
  await editor.locator('[data-column="length_m"]').fill('4');
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  saved=await state();assert.equal(pipes(saved)[0].length_m,4);
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:saved.revision}})).status(),200);
  saved=await state();assert.equal(saved.project_calculation.can_release,false);
  assert.equal(saved.project_calculation.sewer_scheme.ready,false);
  assert.notEqual(saved.project_calculation.sewer_scheme.presentation,'representative');
  await page.reload();await idle();await open();
  await editor.getByRole('button',{name:'Удалить участок К1/К2 1'}).click();
  await page.locator('[data-config-form] button[type="submit"]').click();await idle();
  assert.equal(pipes(await state()),null);
  assert.deepEqual(report.errors,[]);
  report.passed=true;
  console.log('PASS: blank row, UI save/reopen, atomic invalid edit, edit/delete, strict incomplete network, desktop/mobile.');
 } finally {
  if(browser)await browser.close();server.kill('SIGTERM');
  fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);
 }
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
