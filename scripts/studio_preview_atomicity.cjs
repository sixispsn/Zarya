// Genuine server failure before commit and a second real browser tab; no response substitution.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const hash=b=>createHash('sha256').update(b).digest('hex');
module.exports=async({page,context,state,idle,root,report,initial,persistence=false})=>{
  const file=path.join(root,'studio',initial.project_id,'draft.json'),folders=path.join(path.dirname(file),'previews');
  const capture=async(saved,stage)=>{
    const documents=[];
    for(const doc of saved.preview.documents) {
      const url='/studio/api/preview/'+saved.preview.id+'/files/'+encodeURIComponent(doc.name);
      const response=await context.request.get(url);assert.equal(response.status(),200);
      const p=path.join(folders,saved.preview.id,doc.name),bytes=fs.readFileSync(p);
      assert.equal(hash(await response.body()),hash(bytes));assert.equal(response.headers()['x-zarya-preview'],'true');
      assert.equal(response.headers()['cache-control'],'private, no-store');
      documents.push({...doc,path:p,url,sha256:hash(bytes)});
    }
    return {stage,id:saved.preview.id,documents};
  };
  report.lifecycle=[await capture(initial,'initial')];
  await page.setViewportSize({width:1440,height:1000});await page.locator('[data-config="connection"]').click();
  const input=page.locator('#clarification-body [data-input="sewage_risers"] .route-row').nth(1).locator('[data-column="pressure_input_source"]');
  const parents=input.locator('xpath=ancestor::details');
  for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)await parents.nth(i).locator(':scope > summary').click();
  await input.fill(persistence?'TEST-ONLY: disk persistence':'TEST-ONLY: renderer atomicity');
  const save=page.waitForResponse(r=>r.url().endsWith('/api/answers')&&r.request().method()==='PATCH');
  await page.locator('[data-config-form] button[type="submit"]').click();assert.equal((await save).status(),200);await idle();
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const calc=page.waitForResponse(r=>r.url().endsWith('/api/calculate')&&r.request().method()==='POST');
  await page.locator('[data-config-form] button[type="submit"]').click();assert.equal((await calc).status(),200);await idle();
  const before=await state(),bytes=fs.readFileSync(file),oldFolders=fs.readdirSync(folders).sort();
  assert.equal(before.preview,null);assert.equal(before.project_calculation.can_release,false);
  const second=await context.newPage();second.on('pageerror',e=>report.errors.push(e.message));
  second.on('console',m=>{if(m.type()==='error')report.consoleErrors.push(m.text());});
  const idleSecond=()=>second.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  await second.goto('/studio?view=project');await idleSecond();
  fs.writeFileSync(path.join(root,persistence?'fail-next-preview-save':'fail-next-preview'),'TEST-ONLY: one failure');
  report.previewAtomicStatus=persistence?'503 (Service Unavailable)':'422 (Unprocessable Entity)';
  const failed=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST',{timeout:120000});
  await page.locator('[data-action="documents"][data-view="ios3"]').click();
  assert.equal((await failed).status(),persistence?503:422);await idle();
  assert.match(await page.locator('#error').innerText(),persistence?/Не удалось подтвердить сохранение предпросмотра/:/Предпросмотр PDF не сформирован; выпуск не выполнен/);
  assert.equal(await page.locator('.document-selection a').count(),0);
  assert.equal(report.previewPosts,2);assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(file),bytes);
  assert.deepEqual(fs.readdirSync(folders).sort(),oldFolders);
  const failure=JSON.parse(fs.readFileSync(path.join(root,persistence?'persistence-failure.json':'renderer-failure.json')));
  assert(failure.failure_before_commit);assert.equal(fs.existsSync(failure.folder),false);
  if(persistence) {
    assert.equal(failure.documents.length,17);assert(failure.documents.every(d=>d.pages>0));
    assert(!fs.readdirSync(path.dirname(file)).some(n=>n.endsWith('.tmp')));
    for(const doc of failure.documents)assert.equal((await context.request.get('/studio/api/preview/'+path.basename(failure.folder)+'/files/'+encodeURIComponent(doc.name))).status(),404);
  } else assert(failure.pages>0);
  await page.screenshot({path:path.join(root,persistence?'persistence-failure-desktop.png':'renderer-failure-desktop.png')});
  delete report.previewAtomicStatus;
  // Second tab still has the same valid revision: failed generation did not consume it.
  const built=second.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST',{timeout:120000});
  await second.locator('[data-action="documents"][data-view="ios3"]').click();
  assert.equal((await built).status(),200);await idleSecond();
  const saved=await state();assert.equal(saved.revision,before.revision+1);assert.equal(saved.project_calculation.can_release,false);
  report.lifecycle.push(await capture(saved,'after_failure'));
  const committed=fs.readFileSync(file),currentFolders=fs.readdirSync(folders).sort();
  report.previewAtomicStatus='409 (Conflict)';
  const stale=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST');
  await page.locator('[data-action="documents"][data-view="ios3"]').click();
  assert.equal((await stale).status(),409);await idle();
  assert.match(await page.locator('#error').innerText(),/другой вкладке/);
  assert.deepEqual(fs.readFileSync(file),committed);assert.deepEqual(await state(),saved);
  assert.deepEqual(fs.readdirSync(folders).sort(),currentFolders);assert.equal(report.previewPosts,4);
  await page.setViewportSize({width:390,height:844});await page.locator('#error').scrollIntoViewIfNeeded();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(root,'preview-conflict-mobile.png')});
  delete report.previewAtomicStatus;
  await page.locator('#error [data-action="reload"]').click();await idle();
  await page.locator('[data-action="documents"][data-view="ios3"]').click();
  assert.equal(report.previewPosts,4);assert.deepEqual(fs.readFileSync(file),committed);
  const doc=saved.preview.documents.find(d=>d.kind==='wastewater_package_pdf');
  assert.equal(await page.locator('.document-selection a').getAttribute('href'),'/studio/api/preview/'+saved.preview.id+'/files/'+encodeURIComponent(doc.name));
  assert(await page.locator('[data-action="package"]').isDisabled());
  for(const doc of report.lifecycle[0].documents) {
    assert.equal((await context.request.get(doc.url)).status(),404);
    assert.equal(hash(fs.readFileSync(doc.path)),doc.sha256);
  }
  report[persistence?'previewPersistence':'previewAtomicity']={failure,failedStatus:persistence?503:422,staleStatus:409,successfulBuilds:2,noRetry:true,readOnlyRecovery:true};
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  await second.close();
  console.log('PASS: '+(persistence?'genuine persistence failure after17 PDFs':'genuine renderer exception after real PZ')+', rollback/cleanup, second tab builds at unchanged revision, stale first tab gets409, read-only recovery.');
};
