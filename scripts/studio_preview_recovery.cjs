// Explicit UI restoration, then lost delivery AFTER genuine PDF commits.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,root,report,values,expected,restoreRow,draftFile,
  editor,input,reveal,open,submit,calculate,capture,revoked,build})=>{
  const writes=[];
  const track=r=>{if(['POST','PATCH','DELETE'].includes(r.method()))writes.push({method:r.method(),url:r.url()});};
  page.on('request',track);
  const historical=report.lifecycle.slice();
  const selection=page.locator('.document-selection');
  await page.setViewportSize({width:1440,height:1000});await open();
  const add=editor('sewage_risers').locator('[data-action="add-section"]');await reveal(add);await add.click();
  const controls=editor('sewage_risers').locator('.route-row').nth(1).locator('[data-column]');
  for(let i=0;i<await controls.count();i++) {
    const control=controls.nth(i),key=await control.getAttribute('data-column');
    const value=restoreRow[key];if(value===undefined || value===null)continue;
    await reveal(control);
    if(await control.evaluate(el=>el.tagName==='SELECT'))await control.selectOption(String(value));
    else await control.fill(String(value));
  }
  assert.equal(writes.length,0); // local addition must not save or restore anything by itself
  expected.sewage_risers.push({...restoreRow});
  const restoredResponse=await submit();assert.equal(restoredResponse.status(),200,await restoredResponse.text());
  const restored=await restoredResponse.json();assert.deepEqual(values(restored),expected);
  assert.equal(restored.preview,null);assert.equal(restored.project_calculation,null);
  for(const entry of historical)await revoked(entry);
  const recalculated=await calculate();assert.equal(recalculated.project_calculation.sewer_scheme.ready,true);
  assert.equal(recalculated.project_calculation.can_release,false);assert.equal(recalculated.preview,null);
  const built=await build();const fourth=await capture(built,'restored');historical.push(fourth);
  assert.equal(fourth.documents.find(d=>d.kind==='wastewater_scheme_pdf').state,'ready');
  assert.equal(fourth.documents.find(d=>d.kind==='wastewater_package_pdf').state,'preliminary');
  assert.match(await selection.innerText(),/Предварительный документ/);
  assert.doesNotMatch(await selection.innerText(),/Неполный документ/);
  console.log('PASS: explicitly restored calculation row, fresh calculation and fourth real preview, no automatic data restoration/release.');
  report.previewRecovery=[];
  for(const kind of ['connection','server500','malformed200']) {
    // Descriptive provenance only, explicitly edited to revoke the prior preview.
    await open();const control=input('sewage_risers',1,'pressure_input_source');await reveal(control);
    const note='TEST-ONLY: preview recovery '+kind;await control.fill(note);
    expected.sewage_risers[1].pressure_input_source=note;
    const response=await submit();assert.equal(response.status(),200,await response.text());
    assert.deepEqual(values(await response.json()),expected);
    const before=await calculate();assert.equal(before.preview,null);
    assert.equal(before.project_calculation.sewer_scheme.ready,true);
    for(const entry of historical)await revoked(entry);
    let committed,serverStatus;
    const endpoint='**/studio/api/preview';
    const fault=async route=>{
      const actual=await route.fetch({timeout:120000});serverStatus=actual.status();
      assert.equal(serverStatus,200,await actual.text());committed=await actual.json();
      assert.equal(committed.revision,before.revision+1);
      if(kind==='connection')await route.abort('failed');
      else await route.fulfill({status:kind==='server500'?500:200,contentType:'text/html',body:'TEST-ONLY: lost preview response'});
    };
    const start=writes.length,posts=report.previewPosts;
    report.previewFaultActive=kind;
    await page.route(endpoint,fault,{times:1});
    try {
      await page.locator('[data-action="documents"][data-view="ios3"]').click();
      await page.locator('#error [data-action="reload"]').waitFor({timeout:120000});await idle();
      assert.equal(writes.length,start+1);assert.equal(report.previewPosts,posts+1);
      assert.match(await page.locator('#error').innerText(),kind==='connection'?/Связь с сервером прервалась/:kind==='server500'?/Ошибка на сервере/:/Сервер вернул неполный ответ/);
      assert.equal(await page.locator('#error [data-action="download-input-copy"]').count(),0);
      assert.equal(await page.locator('.document-selection a').count(),0);
      assert.deepEqual(await state(),committed);assert.deepEqual(values(committed),expected);
      const bytes=fs.readFileSync(draftFile);
      assert(await page.locator('[data-action="package"]').isDisabled());
      await page.locator('#error').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(root,'preview-error-'+kind+'.png')});
      await page.locator('#error [data-action="reload"]').click();await idle();
      assert.deepEqual(fs.readFileSync(draftFile),bytes);assert.deepEqual(await state(),committed);
      await page.locator('[data-action="documents"][data-view="ios3"]').click();
      assert.equal(writes.length,start+1);assert.equal(report.previewPosts,posts+1);
      const entry=await capture(committed,kind);historical.push(entry);
      assert.match(await selection.innerText(),/Предварительный документ/);
      assert.doesNotMatch(await selection.innerText(),/Неполный документ/);
      const url=entry.documents.find(d=>d.kind==='wastewater_package_pdf').url;
      assert.equal(await selection.locator('a').getAttribute('href'),url);
      for(const previous of historical.slice(0,-1))await revoked(previous);
      await page.reload();await idle();await page.locator('[data-action="documents"][data-view="ios3"]').click();
      assert.equal(writes.length,start+1);assert.equal(report.previewPosts,posts+1);
      assert.equal((await state()).preview.id,entry.id);assert.deepEqual(fs.readFileSync(draftFile),bytes);
      report.previewRecovery.push({kind,serverStatus,previewId:entry.id,noRetry:true,reloadReadOnly:true});
      console.log('PASS: '+kind+' after genuine PDF commit; explicit read recovers same preview without rebuild.');
    } finally {await page.unroute(endpoint,fault);delete report.previewFaultActive;}
  }
  for(const [label,size] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
    await page.setViewportSize(size);await selection.scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'preview-recovered-'+label+'.png')});
  }
  assert.equal(report.previewPosts,7);assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  assert.equal((await state()).project_calculation.can_release,false);
  report.recoveryWrites=writes;page.off('request',track);
};
