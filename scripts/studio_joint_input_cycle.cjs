// Real four-registry edits and two browser tabs; no replacement of responses/DOM.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,root,draftFile,report})=>{
  const keys=['sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation'];
  const ids=['section_id','element_id','riser_id','terminal_id'];
  const notes=['room','note','pressure_input_source','source_ref'];
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const rows=(data,key)=>key===keys[3]?data[key].terminals:data[key];
  const before=await state(),base=values(before),bytes=fs.readFileSync(draftFile);
  const start=report.writes.length,errorsStart=report.expected_http_errors.length;
  const editor=(p,key)=>p.locator('#clarification-body [data-input="'+key+'"]');
  const control=(p,key,field)=>editor(p,key).locator('.route-row').nth(1).locator('[data-column="'+field+'"]');
  const global=p=>editor(p,keys[3]).locator('[data-fan-global="external_ventilation_ref"]');
  const reveal=async input=>{
    const parents=input.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)
      await parents.nth(i).locator(':scope > summary').click();
  };
  const open=p=>p.locator('[data-action="config"][data-config="connection"]').click();
  const waitIdle=p=>p.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
  const submit=async p=>{
    const pending=p.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await p.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await waitIdle(p);return response;
  };
  const snapshot=()=>page.evaluate(keys=>Object.fromEntries(keys.map(key=>[key,JSON.parse(document.querySelector('#field-'+key).value)])),keys);
  await page.setViewportSize({width:1440,height:1000});await open(page);
  const localNotes=notes.map((_,i)=>'TEST-ONLY: local registry '+(i+1));
  for(const [i,key] of keys.entries()) {
    await reveal(control(page,key,notes[i]));await control(page,key,notes[i]).fill(localNotes[i]);
    await reveal(control(page,key,ids[i]));await control(page,key,ids[i]).fill('');
  }
  await reveal(global(page));await global(page).fill('TEST-ONLY: local overlapping confirmation');
  const expected=await snapshot();
  for(const [i,key] of keys.entries()) {
    assert.equal(rows(expected,key)[1][ids[i]],'');
    assert.equal(rows(expected,key)[1][notes[i]],localNotes[i]);
  }
  report.joint_refusals=[];
  for(let attempt=0;attempt<4;attempt++) {
    await page.setViewportSize(attempt%2?{width:390,height:844}:{width:1440,height:1000});
    const response=await submit(page);assert.equal(response.status(),422,await response.text());
    const issue=(await response.json()).input_issues[0],i=keys.indexOf(issue.registry);
    assert(i>=0);assert.equal(issue.row_index,1);assert.equal(issue.field,ids[i]);
    assert(!report.joint_refusals.includes(issue.registry));
    assert.deepEqual(await snapshot(),expected);
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    await page.locator('#error [data-action="input-issue"]').first().focus();await page.keyboard.press('Enter');
    assert.equal(await control(page,issue.registry,issue.field).evaluate(e=>e===document.activeElement),true);
    assert.deepEqual(await snapshot(),expected);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'joint-return-'+issue.registry+'.png')});
    const original=rows(base,issue.registry)[1][issue.field];
    await control(page,issue.registry,issue.field).fill(original);
    rows(expected,issue.registry)[1][issue.field]=original;
    assert.deepEqual(await snapshot(),expected);
    report.joint_refusals.push(issue.registry);
  }
  assert.equal(report.writes.length-start,4);
  // A real second tab changes the same global field while the first keeps all edits.
  const remote=await page.context().newPage();
  remote.on('pageerror',e=>report.errors.push(e.message));
  remote.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
  remote.on('request',r=>{if(!['GET','HEAD'].includes(r.method()))report.writes.push(r.method()+' '+r.url());});
  await remote.goto('/studio?view=project');await waitIdle(remote);await open(remote);
  await reveal(global(remote));const remoteNote='TEST-ONLY: saved by second tab';await global(remote).fill(remoteNote);
  const remoteResponse=await submit(remote);assert.equal(remoteResponse.status(),200,await remoteResponse.text());
  const current=await remoteResponse.json(),currentBytes=fs.readFileSync(draftFile);
  assert.equal(current.revision,before.revision+1);assert.equal(values(current)[keys[3]].external_ventilation_ref,remoteNote);
  await remote.close();
  const response=await submit(page);assert.equal(response.status(),409,await response.text());
  assert.equal((await response.json()).input_issues,undefined);
  assert.equal(await page.locator('#error [data-action="input-issue"]').count(),0);
  assert.deepEqual(await snapshot(),expected);
  assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),currentBytes);
  assert.equal(report.writes.length-start,6);
  for(const [name,size] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
    await page.setViewportSize(size);await page.locator('#error').scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'joint-conflict-'+name+'.png')});
  }
  // A download is a local action, not a save or automatic retry.
  const downloadEvent=page.waitForEvent('download');
  await page.locator('[data-action="download-input-copy"]').click();
  const download=await downloadEvent;assert.equal(download.suggestedFilename(),'zarya-unsaved-input.json');
  const file=path.join(root,'joint-unsaved-input.json');await download.saveAs(file);
  const copy=JSON.parse(fs.readFileSync(file,'utf8'));
  assert.equal(copy.format,'zarya-unsaved-input');assert.equal(copy.base_revision,before.revision);
  assert.equal(copy.project_id,before.project_id);assert.deepEqual(copy.answers,expected);
  assert.deepEqual(copy.base_fields.map(r=>r.key).sort(),[...keys].sort());
  for(const field of copy.base_fields)assert.deepEqual(field.value,base[field.key]);
  assert.equal(copy.calculation,undefined);assert.equal(copy.documents,undefined);
  assert.equal(report.writes.length-start,6);assert.deepEqual(await snapshot(),expected);
  page.once('dialog',dialog=>dialog.dismiss());await page.locator('#error [data-action="reload"]').click();
  await idle();assert.deepEqual(await snapshot(),expected);assert.deepEqual(await state(),current);
  // An explicit repeated attempt remains stale; the UI must not adopt a new revision.
  await open(page);assert.deepEqual(await snapshot(),expected);
  assert.equal((await submit(page)).status(),409);
  assert.deepEqual(fs.readFileSync(draftFile),currentBytes);assert.equal(report.writes.length-start,7);
  page.once('dialog',dialog=>dialog.accept());await page.locator('#error [data-action="reload"]').click();await idle();
  assert.deepEqual(await snapshot(),Object.fromEntries(keys.map(key=>[key,values(current)[key]])));
  assert.equal(await page.locator('#error [data-action="download-input-copy"]').count(),0);
  assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),currentBytes);
  // Manually restore only the selected non-conflicting notes from the saved copy.
  // Keep the second tab's global value; no import or implicit merge is available.
  await open(page);
  for(const [i,key] of keys.entries()) {
    await reveal(control(page,key,notes[i]));
    await control(page,key,notes[i]).fill(rows(copy.answers,key)[1][notes[i]]);
  }
  assert.equal(await global(page).inputValue(),remoteNote);
  const recovered=await submit(page);assert.equal(recovered.status(),200,await recovered.text());
  const finalValues=values(current);
  for(const [i,key] of keys.entries())rows(finalValues,key)[1][notes[i]]=localNotes[i];
  assert.deepEqual(values(await recovered.json()),finalValues);
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const calculated=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
  await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
  const calculation=await calculated;assert.equal(calculation.status(),200,await calculation.text());await idle();
  const final=await calculation.json();assert.deepEqual(values(final),finalValues);
  assert.equal(final.project_calculation.can_release,false);
  await page.reload();await idle();assert.deepEqual(await state(),final);
  assert.equal(report.writes.length-start,10);assert.equal(report.expected_http_errors.length-errorsStart,6);
  assert.deepEqual(report.errors,[]);
  report.joint_recovery={tabs:2,registry_count:4,rejected_422:4,rejected_409:2,
    download_no_write:true,cancel_keeps_input:true,explicit_reload:true,manual_recovery_keeps_remote:true};
  console.log('PASS: four simultaneous registries, sequential 422, two-tab 409, local JSON copy, cancel/reload, explicit manual recovery and real recalculation.');
};
