// Transport fault injection AFTER a real successful write. Never substitute calculations.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,root,draftFile,report})=>{
  const keys=['sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation'];
  const fields=['room','note','pressure_input_source','source_ref'];
  const rows=(data,key)=>key===keys[3]?data[key].terminals:data[key];
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const snapshot=()=>page.evaluate(keys=>Object.fromEntries(keys.map(key=>[key,JSON.parse(document.querySelector('#field-'+key).value)])),keys);
  const reveal=async input=>{
    const parents=input.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)
      await parents.nth(i).locator(':scope > summary').click();
  };
  report.interrupted_input_cycles=[];
  const start=report.writes.length;
  for(const [index,kind] of ['connection','server500','malformed200'].entries()) {
    const before=await state(),base=values(before);
    const canonical=JSON.parse(JSON.stringify(base));
    await page.setViewportSize(index%2?{width:390,height:844}:{width:1440,height:1000});
    await page.locator('[data-action="config"][data-config="connection"]').click();
    for(const [i,key] of keys.entries()) {
      const input=page.locator('#clarification-body [data-input="'+key+'"] .route-row').nth(1).locator('[data-column="'+fields[i]+'"]');
      await reveal(input);await input.fill('TEST-ONLY: '+kind+' registry '+(i+1));
      rows(canonical,key)[1][fields[i]]='TEST-ONLY: '+kind+' registry '+(i+1);
    }
    const expected=await snapshot();
    const endpoint='**/studio/api/answers';
    let committed;
    const fault=async route=>{
      // Forward the genuine UI payload first. Only delivery of the response fails.
      const response=await route.fetch();assert.equal(response.status(),200,await response.text());
      committed=await response.json();
      assert.equal(committed.revision,before.revision+1);
      if(kind==='connection')await route.abort('failed');
      else await route.fulfill({status:kind==='server500'?500:200,contentType:'text/html',body:'TEST-ONLY: interrupted gateway response'});
    };
    await page.route(endpoint,fault,{times:1});
    try {
      await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
      await page.locator('#error [data-action="download-input-copy"]').waitFor();await idle();
      const error=await page.locator('#error').innerText();
      assert(error.includes(kind==='connection'?'Связь с сервером прервалась':kind==='server500'?'Ошибка на сервере':'Сервер вернул неполный ответ'));
      assert.equal(await page.locator('#error [data-action="input-issue"]').count(),0);
      assert.deepEqual(await snapshot(),expected);
      assert.deepEqual(await state(),committed);
      assert.deepEqual(values(committed),canonical);
      const bytes=fs.readFileSync(draftFile);
      assert.equal(report.writes.length,start+index+1); // no automatic retry
      await page.locator('#error').scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(root,'interrupted-'+kind+'.png')});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      const pending=page.waitForEvent('download');await page.locator('[data-action="download-input-copy"]').click();
      const download=await pending,file=path.join(root,'interrupted-'+kind+'.json');await download.saveAs(file);
      const copy=JSON.parse(fs.readFileSync(file,'utf8'));
      assert.equal(copy.project_id,before.project_id);assert.equal(copy.base_revision,before.revision);
      assert.deepEqual(copy.answers,expected);
      for(const item of copy.base_fields)assert.deepEqual(item.value,base[item.key]);
      assert.equal(report.writes.length,start+index+1);
      page.once('dialog',dialog=>dialog.dismiss());await page.locator('#error [data-action="reload"]').click();
      assert.deepEqual(await snapshot(),expected);assert.deepEqual(fs.readFileSync(draftFile),bytes);
      if(kind==='connection') {
        // Even the recovery read may fail; do not clear the pending local form.
        const readFault=route=>route.abort('failed');
        await page.route('**/studio/api/draft',readFault,{times:1});
        try {
          page.once('dialog',dialog=>dialog.accept());await page.locator('#error [data-action="reload"]').click();
          await page.locator('#error [data-action="download-input-copy"]').waitFor();await idle();
          assert.deepEqual(await snapshot(),expected);assert.deepEqual(await state(),committed);
          assert.deepEqual(fs.readFileSync(draftFile),bytes);assert.equal(report.writes.length,start+index+1);
        } finally {await page.unroute('**/studio/api/draft',readFault);}
      }
      page.once('dialog',dialog=>dialog.accept());await page.locator('#error [data-action="reload"]').click();await idle();
      assert.deepEqual(await state(),committed);assert.deepEqual(fs.readFileSync(draftFile),bytes);
      assert.deepEqual(await snapshot(),Object.fromEntries(keys.map(key=>[key,canonical[key]])));
      assert.equal(await page.locator('#error [data-action="download-input-copy"]').count(),0);
      assert.equal(report.writes.length,start+index+1);
      assert.equal(committed.project_calculation,null); // invalidated by the real save, no fabricated success
      for(const [i,key] of keys.entries())assert.equal(rows(values(committed),key)[1][fields[i]],'TEST-ONLY: '+kind+' registry '+(i+1));
      report.interrupted_input_cycles.push({kind,real_server_commit:true,copy_base_revision:copy.base_revision,
        no_retry:true,reload_no_write:true,failed_reload_preserved:kind==='connection',all_four_registries_retained:true});
    } finally {await page.unroute(endpoint,fault);}
  }
  assert.deepEqual(report.errors,[]);
  console.log('PASS: lost connection, HTTP 500 and malformed success after genuine commit; local copies retain old baseline, no retry, read-only reload recovers saved inputs.');
};
