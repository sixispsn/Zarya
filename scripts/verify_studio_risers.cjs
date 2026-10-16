// Disposable real HTTP/browser exercise. No handoff substitution or production writes.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zarya-riser-editor-'));
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
  // Existing explicit pipe fixture and building inputs through public API; calculation risers only via UI.
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_risers import building_answers; from tests.test_studio_sewer_pipes import rows; from tests.test_studio_sewer_elements import rows as elements; from tests.test_studio_fans import evidence; print(json.dumps({**building_answers(), "sewer_pipes":rows(), "sewer_elements":elements(), "wastewater_fan_ventilation":evidence()}))'],{encoding:'utf8'}));
  const data=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_risers import rows; print(json.dumps(rows()))'],{encoding:'utf8'}));
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  await page.goto('/studio?view=project');await idle();
  const open=async()=>{
    await page.locator('[data-config="connection"]').click();
    const summary=page.getByText('Расчётные стояки К1 · отдельный реестр',{exact:true});
    if(await summary.locator('..').getAttribute('open')===null) await summary.click();
  };
  const submit=async(status=200)=>{
    const response=page.waitForResponse(r=>r.url().endsWith('/api/answers') && r.request().method()==='PATCH');
    await page.locator('[data-config-form] button[type="submit"]').click();
    assert.equal((await response).status(),status);await idle();
  };
  await open();
  const editor=page.locator('#clarification-body [data-input="sewage_risers"]');
  const field=(key,index=0)=>editor.locator('.route-row').nth(index).locator('[data-column="'+key+'"]');
  for(const [index,row] of data.entries()) {
    await editor.getByRole('button',{name:'+ Добавить расчётный стояк К1'}).click();
    for(const key of ['design_flow_lps','material','ventilation','riser_dn_mm','branch_dn_mm','branch_angle_deg','has_toilet']) assert.equal(await field(key,index).inputValue(),'');
    for(const key of ['riser_id','design_flow_lps','riser_dn_mm','branch_dn_mm']) await field(key,index).fill(String(row[key]));
    for(const key of ['material','ventilation','branch_angle_deg','has_toilet']) await field(key,index).selectOption(String(row[key]));
  }
  await editor.locator('.route-row').first().screenshot({path:path.join(root,'editor-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await field('design_flow_lps').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-top.png')});
  await field('has_toilet').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'editor-mobile-bottom.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await editor.evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  await page.setViewportSize({width:1440,height:1000});await submit();
  const risers=s=>s.fields.find(f=>f.key==='sewage_risers').value;
  let saved=await state();
  assert.equal(risers(saved).length,2);
  assert.equal(risers(saved)[0].design_flow_lps,data[0].design_flow_lps);
  assert.equal(risers(saved)[0].has_toilet,true);
  assert.equal(risers(saved)[0].working_height_m,null);
  assert.equal(risers(saved)[0].air_valve_free_area_mm2,null);
  await page.reload();await idle();await open();
  assert.equal(await field('ventilation').inputValue(),'ventilated');
  assert.equal(await field('branch_angle_deg').inputValue(),'87.5');
  const before=JSON.stringify(saved);
  await field('design_flow_lps').fill('');await submit(422);
  assert.equal(JSON.stringify(await state()),before);assert(await page.locator('#error').isVisible());
  await page.screenshot({path:path.join(root,'missing-flow.png')});
  await open();assert.equal(await field('design_flow_lps').inputValue(),'');
  await field('design_flow_lps').fill(String(data[0].design_flow_lps));
  await field('riser_id').fill('Неизвестный стояк');await submit(422);
  assert.equal(JSON.stringify(await state()),before);
  await open();await field('riser_id').fill(data[0].riser_id);await submit();
  saved=await state();
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:saved.revision}})).status(),200);
  saved=await state();assert.equal(saved.project_calculation.can_release,false);
  assert.equal(saved.project_calculation.sewer_scheme.ready,true,JSON.stringify(saved.project_calculation.sewer_scheme.reasons));
  await page.reload();await idle();await open();
  await editor.getByRole('button',{name:'Удалить расчётный стояк К1 2'}).click();await submit();
  saved=await state();assert.equal(risers(saved).length,1);assert.equal(saved.project_calculation,null);
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:saved.revision}})).status(),200);
  saved=await state();assert.equal(saved.project_calculation.sewer_scheme.ready,false);
  assert(saved.project_calculation.sewer_scheme.reasons.some(r=>r.includes('Режим стояка')));
  assert.deepEqual(report.errors,[]);
  report.passed=true;console.log('PASS: blank risers, explicit UI input, save/reopen, flow/link errors, repair, graphic ready without overall release, deletion revokes ready, desktop/mobile.');
 } finally {
  if(browser)await browser.close();server.kill('SIGTERM');
  fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);
 }
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
