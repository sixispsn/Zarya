// Real ordinary draft and audit. Navigation is UI-only and must write nothing.
// --edit-cycle additionally tests explicit UI saves/recalculations afterwards.
// --invalid-cycle adds rejected edits and recovery before those saves.
// --parser-cycle also checks required, malformed, non-finite and fractional inputs.
// --link-cycle additionally checks unset boolean selects and an unlinked riser.
// --element-cycle checks element parser/link errors and atomic recovery.
// --element-ranges-cycle also checks duplicate IDs, ranges and mixed refusals.
// --element-enum-cycle adds an explicitly seeded obsolete private draft.
// --fan-input-cycle checks nested terminal parser/links and full-context freshness.
// --fan-model-cycle adds model errors and an explicitly seeded obsolete fan fixture.
// --joint-input-cycle checks simultaneous registries and real two-tab recovery.
// --interrupted-input-cycle injects response delivery faults after genuine saves.
// --identity-cycle checks explicit joint rename and deletion without cascades.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'zarya-finding-inputs-'));
const python=path.resolve('venv/bin/python');
const server=spawn(python,['-m','scripts.studio_file_smoke_server',root,'--empty'],{stdio:['ignore','pipe','pipe']});
let logs='';for(const stream of [server.stdout,server.stderr])stream.on('data',c=>{logs+=c;});
(async()=>{
 let browser;
 const report={root,errors:[],writes:[],passed:false};
 try {
  const fixture=path.join(root,'fixture.json');
  for(let i=0;i<200&&!fs.existsSync(fixture);i++){if(server.exitCode!==null)throw Error(logs);await delay(100);}
  const {base_url:base}=JSON.parse(fs.readFileSync(fixture));
  for(let i=0;i<100;i++){try{if((await fetch(base+'/studio')).ok)break;}catch{}if(i===99)throw Error(logs);await delay(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:1000},reducedMotion:'reduce',extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
  const initial=await(await context.request.post('/studio/api/draft')).json();
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_risers import building_answers, rows as risers; from tests.test_studio_sewer_pipes import rows as pipes; from tests.test_studio_sewer_elements import rows as elements; from tests.test_studio_fans import evidence; print(json.dumps({**building_answers(), "object_name":"Навигация замечаний · TEST-ONLY", "sewer_pipes":pipes(), "sewer_elements":elements(), "wastewater_fan_ventilation":evidence(), "sewage_risers":risers()}))'],{encoding:'utf8'}));
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  const state=async()=>await(await context.request.get('/studio/api/draft')).json();
  const before=await state();assert.equal(before.project_calculation.can_release,false);
  const draftFile=path.join(root,'studio',before.project_id,'draft.json');const bytes=fs.readFileSync(draftFile);
  const findings=before.project_calculation.quality.gates.flatMap(g=>g.findings);
  for(const code of ['K1-02','K1-05'])assert.equal(findings.find(f=>f.code===code).state,'blocked');
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  report.expected_http_errors=[];
  report.expected_transport_errors=[];
  page.on('console',m=>{
    if(m.type()!=='error')return;
    if(process.argv.includes('--interrupted-input-cycle') && [base+'/studio/api/answers',base+'/studio/api/draft'].includes(m.location().url)
      && (/^Failed to load resource: net::ERR_FAILED$/.test(m.text())
        || /^Failed to load resource: the server responded with a status of 500\b/.test(m.text()))) {
      report.expected_transport_errors.push(m.text());return;
    }
    if(['--invalid-cycle','--parser-cycle','--link-cycle','--element-cycle','--element-ranges-cycle','--element-enum-cycle','--fan-input-cycle','--fan-model-cycle','--joint-input-cycle','--identity-cycle'].some(flag=>process.argv.includes(flag)) && m.location().url===base+'/studio/api/answers'
      && /^Failed to load resource: the server responded with a status of (422|409)\b/.test(m.text())) {
      report.expected_http_errors.push(m.text());return;
    }
    report.errors.push(m.text());
  });
  page.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))report.writes.push(r.method()+' '+r.url());});
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await page.goto('/studio?view=project');await idle();
  await page.locator('[data-action="readiness"]').click();
  const finding=code=>page.locator('[data-finding-code="'+code+'"]');
  // Expand the real section via its summary, never replace application state.
  const parent=finding('K1-02').locator('..');
  if(await parent.getAttribute('open')===null)await parent.locator(':scope > summary').click();
  for(const code of ['K1-02','K1-05'])assert((await finding(code).innerText()).includes(findings.find(f=>f.code===code).detail));
  const review=finding('K1-02').locator('.riser-review');
  assert.equal(await review.getAttribute('open'),null);
  await review.locator(':scope > summary').click();
  const result=before.project_calculation.sewage_riser_review;
  assert.equal(await review.locator('.riser-review-row').count(),result.risers.length);
  for(const [index,row] of result.risers.entries()) {
    const text=await review.locator('.riser-review-row').nth(index).innerText();
    assert(text.includes(row.riser_id));assert(text.includes(row.note));
    assert(text.includes(String(row.design_flow_lps).replace('.',',')));
    if(row.capacity_lps!==null)assert(text.includes(String(row.capacity_lps).replace('.',',')));
    assert(text.includes('Есть несоответствие'));
  }
  await review.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'riser-detail-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await review.locator(':scope > summary').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'riser-detail-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.setViewportSize({width:1440,height:1000});
  const navigateRow=async(scope,id,column,label)=>{
    const button=scope.locator('[data-action="finding-row"]').filter({hasText:'К строке '+id+' →'});
    await button.focus();await page.keyboard.press('Enter');
    const focused=await page.evaluate(()=>({value:document.activeElement.value,column:document.activeElement.dataset.column,
      top:document.activeElement.getBoundingClientRect().top,bottom:document.activeElement.getBoundingClientRect().bottom,height:innerHeight}));
    assert.equal(focused.value,id);assert.equal(focused.column,column);
    assert(focused.top>=0&&focused.bottom<=focused.height);
    await page.screenshot({path:path.join(root,'row-'+label+'.png')});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  };
  assert(result.risers.length>1);
  await navigateRow(review,result.risers[1].riser_id,'riser_id','riser-desktop');
  await page.setViewportSize({width:390,height:844});
  await navigateRow(review,result.risers[1].riser_id,'riser_id','riser-mobile');
  await page.setViewportSize({width:1440,height:1000});
  await review.locator(':scope > summary').click();
  await finding('K1-02').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'findings-desktop.png')});
  const diagnostic=finding('K1-05').locator('.diagnostic-review');
  assert.equal(await diagnostic.getAttribute('open'),null);
  await diagnostic.locator(':scope > summary').click();
  const service=diagnostic.locator('.diagnostic-group').filter({has:page.locator('summary').filter({hasText:'Линейное обслуживание'})});
  await service.locator(':scope > summary').click();
  const diagnosis=before.project_calculation.sewage_diagnostic_review;
  assert.equal(await service.locator('.diagnostic-review-row').count(),diagnosis.linear_service_checks.length);
  for(const [index,row] of diagnosis.linear_service_checks.entries()) {
    const text=await service.locator('.diagnostic-review-row').nth(index).innerText();
    assert(text.includes(row.section_id));assert(text.includes(row.note));
    if(row.calculation_length_m!==null)assert(text.includes(String(row.calculation_length_m).replace('.',',')));
    assert(text.includes('не нормативный предел'));
  }
  await service.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'diagnostic-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await service.locator(':scope > summary').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'diagnostic-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(diagnosis.linear_service_checks.length>1);
  const lastSection=diagnosis.linear_service_checks.at(-1).section_id;
  await navigateRow(service,lastSection,'section_id','pipe-mobile');
  await page.setViewportSize({width:1440,height:1000});
  await navigateRow(service,lastSection,'section_id','pipe-desktop');
  await page.setViewportSize({width:390,height:844});
  const warnings=diagnostic.locator('.diagnostic-group').filter({has:page.locator('summary').filter({hasText:'Предупреждения и недостающие данные'})});
  await warnings.locator(':scope > summary').click();
  const warningText=await warnings.innerText();
  for(const note of diagnosis.warnings)assert(warningText.includes(note));
  const hydraulics=diagnostic.locator('.diagnostic-group').filter({has:page.locator('summary').filter({hasText:'Гидравлика рассчитанных участков'})});
  await hydraulics.locator(':scope > summary').click();
  assert.equal(await hydraulics.locator('.diagnostic-review-row').count(),diagnosis.hydraulics.length);
  if(!diagnosis.hydraulics.length)assert((await hydraulics.innerText()).includes('Отсутствие строк не подтверждает'));
  await diagnostic.locator(':scope > summary').click();
  await page.setViewportSize({width:1440,height:1000});
  for(const [code,key] of [['K1-02','sewage_risers'],['K1-05','sewer_pipes'],['K1-05','sewer_elements'],['K1-05','sewage_risers']]) {
    const button=finding(code).locator('[data-action="finding-inputs"][data-finding-input="'+key+'"]');
    await button.click();
    const editor=page.locator('#clarification-body [data-input="'+key+'"]');
    assert(await editor.isVisible());
    const focused=await page.evaluate(()=>({tag:document.activeElement.tagName,text:document.activeElement.textContent}));
    assert.equal(focused.tag,'SUMMARY');
    assert(await editor.locator('..').isVisible());
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    if(key==='sewage_risers'&&code==='K1-02') {
      await page.setViewportSize({width:390,height:844});
      await page.screenshot({path:path.join(root,'target-mobile.png')});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    await page.keyboard.press('Escape');assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  }
  await finding('K1-05').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'findings-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  // Keyboard activation must reveal the same destination without a save.
  const button=finding('K1-02').locator('[data-action="finding-inputs"][data-finding-input="sewage_risers"]');
  await button.focus();await page.keyboard.press('Enter');
  assert(await page.locator('#clarification-body [data-input="sewage_risers"]').isVisible());
  await page.keyboard.press('Escape');
  // Real unsaved edits hide stale results. Reopening the normal editor must
  // preserve the backing form without resurrecting a result or saving it.
  await review.locator(':scope > summary').click();
  const oldId=result.risers[1].riser_id;
  const staleButton=review.locator('[data-action="finding-row"]').filter({hasText:'К строке '+oldId+' →'});
  const idInputs=()=>page.locator('#clarification-body [data-input="sewage_risers"] [data-column="riser_id"]');
  const openRegistry=()=>page.locator('[data-action="config"][data-config="connection"]').click();
  await button.click();await idInputs().nth(1).fill(oldId+'-edited');await page.keyboard.press('Escape');
  assert.equal(await staleButton.isVisible(),false);
  assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  await openRegistry();assert.equal(await idInputs().nth(1).inputValue(),oldId+'-edited');
  await idInputs().nth(1).fill(oldId);await idInputs().nth(0).fill(oldId);await page.keyboard.press('Escape');
  assert.equal(await staleButton.isVisible(),false);
  assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  await openRegistry();
  assert.equal(await idInputs().nth(0).inputValue(),oldId);
  assert.equal(await idInputs().nth(1).inputValue(),oldId);
  await page.keyboard.press('Escape');
  assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
  await page.reload();await idle();assert.deepEqual(await state(),before);
  assert.deepEqual(fs.readFileSync(draftFile),bytes);assert.deepEqual(report.writes,[]);assert.deepEqual(report.errors,[]);
  console.log('PASS: exact non-first riser/pipe destinations and viewport focus, canonical details, four registry destinations, stale results hidden after unsaved rename/duplicate without losing edits, mouse/keyboard/mobile, zero writes, unchanged gates/draft.');
  if(['--edit-cycle','--invalid-cycle','--parser-cycle','--link-cycle'].some(flag=>process.argv.includes(flag)))await require('./studio_finding_edit_cycle.cjs')({page,state,idle,before,root,draftFile,report,invalidCycle:['--invalid-cycle','--parser-cycle','--link-cycle'].some(flag=>process.argv.includes(flag)),parserCycle:process.argv.includes('--parser-cycle') || process.argv.includes('--link-cycle'),linkCycle:process.argv.includes('--link-cycle')});
  if(['--element-cycle','--element-ranges-cycle'].some(flag=>process.argv.includes(flag)))await require('./studio_element_edit_cycle.cjs')({page,state,idle,before:await state(),root,draftFile,report,rangesCycle:process.argv.includes('--element-ranges-cycle')});
  if(process.argv.includes('--element-enum-cycle'))await require('./studio_element_enum_cycle.cjs')({page,state,idle,root,draftFile,report});
  if(['--fan-input-cycle','--fan-model-cycle'].some(flag=>process.argv.includes(flag)))await require('./studio_fan_input_cycle.cjs')({page,state,idle,root,draftFile,report,modelCycle:process.argv.includes('--fan-model-cycle')});
  if(process.argv.includes('--fan-model-cycle'))await require('./studio_fan_model_cycle.cjs')({page,state,idle,root,draftFile,report});
  if(process.argv.includes('--joint-input-cycle'))await require('./studio_joint_input_cycle.cjs')({page,state,idle,root,draftFile,report});
  if(process.argv.includes('--interrupted-input-cycle'))await require('./studio_interrupted_input_cycle.cjs')({page,state,idle,root,draftFile,report});
  if(process.argv.includes('--identity-cycle'))await require('./studio_registry_identity_cycle.cjs')({page,state,idle,root,draftFile,report});
  report.passed=true;
 } catch(e){report.failure=String(e);throw e;}
 finally {if(browser)await browser.close();server.kill('SIGTERM');fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);}
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
