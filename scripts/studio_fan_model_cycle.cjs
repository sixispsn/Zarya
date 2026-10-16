// Explicit obsolete private fixture, followed only by real visible UI edits.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process');
module.exports=async({page,state,idle,root,draftFile,report})=>{
  const key='wastewater_fan_ventilation',values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const original=await state(),originalData=values(original)[key];
  execFileSync(path.resolve('venv/bin/python'),['-m','scripts.seed_studio_fan_model_fixture',root,original.project_id]);
  const seeded=await state(),bytes=fs.readFileSync(draftFile),start=report.writes.length;
  const errorsStart=report.expected_http_errors.length;
  const editor=()=>page.locator('#clarification-body [data-input="'+key+'"]');
  const rowField=field=>editor().locator('.route-row').nth(1).locator('[data-column="'+field+'"]');
  const global=field=>editor().locator('[data-fan-global="'+field+'"]');
  const reveal=async input=>{
    const parents=input.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)await parents.nth(i).locator(':scope > summary').click();
  };
  await page.setViewportSize({width:390,height:844});await page.reload();await idle();
  await page.locator('[data-action="config"][data-config="connection"]').click();
  await reveal(global('external_ventilation_verified'));
  const check=async()=>{
    assert.equal(await global('external_ventilation_verified').inputValue(),'unsupported');
    assert.equal(await global('external_ventilation_ref').inputValue(),'0');
    assert.equal(await global('external_ventilation_ref').getAttribute('data-preserved-raw'),'0');
    assert.equal(await rowField('kind').inputValue(),'legacy"><img src=x onerror="boom">');
    assert.equal(await editor().locator('img').count(),0);
  };
  await check();await page.screenshot({path:path.join(root,'fan-model-obsolete-mobile.png')});
  const note='TEST-ONLY: сохранённое соседнее поле';
  await reveal(rowField('source_ref'));await rowField('source_ref').fill(note);await check();
  await page.keyboard.press('Escape');
  await page.locator('[data-action="config"][data-config="connection"]').click();await check();
  assert.deepEqual(await state(),seeded);assert.deepEqual(fs.readFileSync(draftFile),bytes);
  assert.equal(report.writes.length,start);
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  report.fan_model_fixture_cycles=[];
  const cases=[['external_ventilation_verified','fan_global_boolean'],['external_ventilation_ref','fan_global_text'],['kind','fan_model_kind']];
  for(const [index,[field,code]] of cases.entries()) {
    const response=await submit();assert.equal(response.status(),422,await response.text());
    const error=await response.json(),issue=error.input_issues[0];
    assert.equal(error.input_issues.length,1);
    assert.equal(issue.code,code);assert.equal(issue.field,field);
    if(field==='kind')assert.equal(issue.row_index,1);
    else {assert.equal(issue.scope,'global');assert(!Object.hasOwn(issue,'row_index'));}
    assert((await page.locator('#error').innerText()).includes(error.input_message));
    assert.deepEqual(await state(),seeded);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    await page.screenshot({path:path.join(root,'fan-model-error-'+field+'.png')});
    await page.locator('#error [data-action="input-issue"]').focus();await page.keyboard.press('Enter');
    const focused=await page.evaluate(()=>({field:document.activeElement.dataset.fanGlobal || document.activeElement.dataset.column,
      top:document.activeElement.getBoundingClientRect().top,bottom:document.activeElement.getBoundingClientRect().bottom,height:innerHeight}));
    assert.equal(focused.field,field);assert(focused.top>=0&&focused.bottom<=focused.height);
    assert.equal(await rowField('source_ref').inputValue(),note);
    assert.equal(report.writes.length,start+index+1);
    await page.screenshot({path:path.join(root,'fan-model-return-'+field+'.png')});
    if(field==='kind')await rowField(field).selectOption(originalData.terminals[1].kind);
    else if(field==='external_ventilation_verified')await global(field).selectOption(originalData[field]===null?'':String(originalData[field]));
    else await global(field).fill(originalData[field]);
    report.fan_model_fixture_cycles.push({field,code,exact_return:true,server_unchanged:true});
  }
  const response=await submit();assert.equal(response.status(),200,await response.text());
  const saved=await response.json(),expected=values(original);expected[key].terminals[1].source_ref=note;
  assert.deepEqual(values(saved),expected);assert.equal(saved.project_calculation,null);
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
  await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
  const calculated=await pending;assert.equal(calculated.status(),200,await calculated.text());
  const current=await calculated.json();await idle();
  assert.deepEqual(values(current),expected);assert.equal(current.project_calculation.can_release,false);
  const after=fs.readFileSync(draftFile);await page.reload();await idle();
  assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),after);
  assert.equal(report.writes.length-start,6);assert.equal(report.expected_http_errors.length-errorsStart,3);
  assert.deepEqual(report.errors,[]);
  report.fan_model_fixture='explicit obsolete private data; original types preserved, no API acceptance';
  console.log('PASS: obsolete fan kind and global types retained across adjacent edits/reopen, 3 exact returns including globals, explicit correction/recalculation.');
};
