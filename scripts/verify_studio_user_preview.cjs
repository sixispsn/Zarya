// Ordinary explicit TEST-ONLY input; real preview through UI on a private server.
// No Project/handoff substitution; --atomicity injects one explicit server renderer failure.
// Does not exercise Chrome's native Save dialog.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn,execFileSync}=require('node:child_process');
const fs=require('node:fs'), path=require('node:path');
const {createHash}=require('node:crypto');
const assert=require('node:assert/strict');
const {setTimeout:delay}=require('node:timers/promises');
fs.mkdirSync('tmp/pdfs',{recursive:true});
const root=fs.mkdtempSync(path.resolve('tmp/pdfs/studio-browser-preview-'));
const python=path.resolve('venv/bin/python');
const persistence=process.argv.includes('--persistence');
const server=spawn(python,['-m','scripts.studio_file_smoke_server',root,'--empty',...(process.argv.includes('--atomicity')||persistence?['--preview-faults']:[])],{stdio:['ignore','pipe','pipe']});
let logs='';for(const stream of [server.stdout,server.stderr])stream.on('data',c=>{logs+=c;});
const hash=b=>createHash('sha256').update(b).digest('hex');
(async()=>{
 let browser;
 const report={root,errors:[],consoleErrors:[],previewPosts:0,passed:false};
 try {
  const file=path.join(root,'fixture.json');
  for(let i=0;i<200&&!fs.existsSync(file);i++){if(server.exitCode!==null)throw Error(logs);await delay(100);}
  const {base_url:base}=JSON.parse(fs.readFileSync(file));
  for(let i=0;i<100;i++){try{if((await fetch(base+'/studio')).ok)break;}catch{}if(i===99)throw Error(logs);await delay(100);}
  browser=await chromium.launch({headless:true,channel:'chrome'});
  const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:1000},reducedMotion:'reduce',extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
  const page=await context.newPage();page.setDefaultTimeout(30000);
  page.on('pageerror',e=>report.errors.push(e.message));
  page.on('console',m=>{if(m.type()==='error') {
    const injected=m.location().url.endsWith('/studio/api/preview') && (
      (report.previewFaultActive && /^Failed to load resource: (net::ERR_FAILED|the server responded with a status of 500 \(Internal Server Error\))$/.test(m.text()))
      || (report.previewAtomicStatus && m.text()===`Failed to load resource: the server responded with a status of ${report.previewAtomicStatus}`));
    if(injected)(report.expectedConsoleErrors ||= []).push(m.text());else report.consoleErrors.push(m.text());
  }});
  context.on('request',r=>{if(r.url().endsWith('/api/preview')&&r.method()==='POST')report.previewPosts++;});
  const state=async()=>await(await context.request.get('/studio/api/draft')).json();
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  const initial=await(await context.request.post('/studio/api/draft')).json();
  const answers=JSON.parse(execFileSync(python,['-c','import json; from tests.test_studio_risers import building_answers, rows as risers; from tests.test_studio_sewer_pipes import rows as pipes; from tests.test_studio_sewer_elements import rows as elements; from tests.test_studio_fans import evidence; print(json.dumps({**building_answers(), "object_name":"Контроль обычного ввода Studio · TEST-ONLY", "sewer_pipes":pipes(), "sewer_elements":elements(), "wastewater_fan_ventilation":evidence(), "sewage_risers":risers()}))'],{encoding:'utf8'}));
  assert.equal((await context.request.post('/studio/api/calculate',{data:{revision:initial.revision,answers}})).status(),200);
  await page.goto('/studio?view=project');await idle();
  const before=await state();assert.equal(before.preview,null);assert.equal(before.project_calculation.can_release,false);
  const release=page.locator('[data-action="package"]');assert(await release.isDisabled());
  const built=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST',{timeout:120000});
  await page.locator('[data-action="documents"][data-view="scheme"]').click();
  assert.equal((await built).status(),200);await idle();
  let saved=await state();assert.equal(saved.preview.documents.length,17);assert.equal(saved.project_calculation.can_release,false);
  report.previewId=saved.preview.id;report.projectId=saved.project_id;
  const scheme=saved.preview.documents.find(d=>d.kind==='wastewater_scheme_pdf');
  assert.equal(scheme.state,'ready');
  const select=page.locator('.document-selection');
  const readinessBox=await page.locator('.delivery > [data-action="readiness"]').boundingBox();
  const designBox=await page.locator('.delivery > [data-action="section-design"]').boundingBox();
  assert(designBox.x-readinessBox.x-readinessBox.width>=19);
  const link=select.getByRole('link',{name:'Принципиальная схема ИОС3 ↗',exact:true});
  const url=await link.getAttribute('href');report.schemeUrl=url;
  const responsePromise=context.waitForEvent('response',{predicate:r=>r.url()===base+url});
  const popupPromise=page.waitForEvent('popup');
  await link.click();const popup=await popupPromise;const response=await responsePromise;
  assert.equal(response.status(),200);assert.match(response.headers()['content-type'],/application\/pdf/);
  await popup.waitForLoadState('domcontentloaded');report.popupUrl=popup.url();
  assert.equal(report.popupUrl,base+url);await popup.close();
  // Download verification uses the exact rendered link and this browser's cookies.
  const downloaded=await context.request.get(url);const content=await downloaded.body();
  assert.equal(downloaded.status(),200);assert.equal(downloaded.headers()['x-zarya-preview'],'true');
  assert.equal(downloaded.headers()['cache-control'],'private, no-store');
  const disk=path.join(root,'studio',saved.project_id,'previews',saved.preview.id,scheme.name);
  assert.equal(hash(content),hash(fs.readFileSync(disk)));report.sha256=hash(content);
  report.schemePath=disk;
  await select.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'delivery-desktop.png')});
  await page.setViewportSize({width:390,height:844});await select.scrollIntoViewIfNeeded();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(root,'delivery-mobile.png')});
  await page.locator('[data-action="documents"][data-view="ios3"]').click();
  assert(await select.getByRole('link',{name:'Комплект ИОС3 К1, К2 и К3 ↗',exact:true}).isVisible());
  assert.match(await select.innerText(),/Предварительный просмотр/);
  await page.screenshot({path:path.join(root,'ios3-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.reload();await idle();
  assert.equal((await state()).preview.id,saved.preview.id);
  await page.locator('[data-action="documents"][data-view="scheme"]').click();
  assert.equal(await link.getAttribute('href'),url);assert.equal(report.previewPosts,1);
  assert.equal(hash(await(await context.request.get(url)).body()),report.sha256);
  if(process.argv.includes('--atomicity') || persistence) {
    await require('./studio_preview_atomicity.cjs')({page,context,state,idle,root,report,initial:saved,persistence});
  } else if(process.argv.includes('--lifecycle') || process.argv.includes('--recovery')) {
    const shared=await require('./studio_preview_lifecycle.cjs')({page,context,state,idle,root,report,initial:saved});
    if(process.argv.includes('--recovery'))await require('./studio_preview_recovery.cjs')({page,context,state,idle,root,report,...shared});
  } else {
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-config="connection"]').click();
  const summary=page.getByText('Расчётные стояки К1 · отдельный реестр',{exact:true});
  if(await summary.locator('..').getAttribute('open')===null)await summary.click();
  const editor=page.locator('#clarification-body [data-input="sewage_risers"]');
  await editor.getByRole('button',{name:'Удалить расчётный стояк К1 2'}).click();
  const edited=page.waitForResponse(r=>r.url().endsWith('/api/answers')&&r.request().method()==='PATCH');
  await page.locator('[data-config-form] button[type="submit"]').click();assert.equal((await edited).status(),200);await idle();
  saved=await state();assert.equal(saved.preview,null);assert.equal(saved.project_calculation,null);
  assert.equal(saved.fields.find(f=>f.key==='sewage_risers').value.length,1);
  assert.equal((await context.request.get(url)).status(),404);
  assert.equal(hash(fs.readFileSync(disk)),report.sha256);
  assert.equal(await page.locator('a[href="'+url+'"]').count(),0);
  await page.reload();await idle();assert.equal((await state()).preview,null);
  assert(await release.isDisabled());
  await page.screenshot({path:path.join(root,'revoked-desktop.png')});
  assert.equal(report.previewPosts,1);assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  }
  report.passed=true;console.log('PASS: real UI preview, PDF popup/bytes, reload reuse, mobile, UI edit revokes link, release blocked.');
 } catch(e) {report.failure=String(e);throw e;}
 finally {
  if(browser)await browser.close();server.kill('SIGTERM');
  fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(report,null,2));console.log('Evidence: '+root);
 }
})().catch(e=>{console.error(e,logs);process.exitCode=1;});
