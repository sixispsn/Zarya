// A clearly seeded obsolete private draft, then real UI-only validation/recovery.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process');
module.exports=async({page,state,idle,root,draftFile,report})=>{
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const original=await state(),row=values(original).sewer_elements[1];
  execFileSync(path.resolve('venv/bin/python'),['-m','scripts.seed_studio_enum_fixture',root,original.project_id]);
  const seeded=await state(),bytes=fs.readFileSync(draftFile),start=report.writes.length;
  const errorsStart=report.expected_http_errors.length;
  const unknown={system:'K3',kind:'legacy-kind',service_direction:'legacy-direction',
    service_fitting:'legacy"><img src=x onerror="boom">'};
  await page.setViewportSize({width:390,height:844});
  await page.reload();await idle();
  await page.locator('[data-action="config"][data-config="connection"]').click();
  const control=field=>page.locator('#clarification-body [data-input="sewer_elements"] .route-row').nth(1).locator('[data-column="'+field+'"]');
  const reveal=async field=>{
    const parents=control(field).locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)await parents.nth(i).locator(':scope > summary').click();
  };
  const checkUnknown=async()=>{
    for(const [field,value] of Object.entries(unknown)) {
      assert.equal(await control(field).inputValue(),value);
      const selected=control(field).locator('option:checked');
      assert((await selected.textContent()).includes('Не поддерживается:'),field+': '+await selected.evaluate(el=>el.outerHTML));
    }
    assert.equal(await page.locator('#clarification-body img').count(),0);
  };
  await checkUnknown();await reveal('service_fitting');
  await control('service_fitting').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'enum-unsupported-mobile.png')});
  await reveal('note');await control('note').fill('TEST-ONLY: соседний ввод сохранён');
  await checkUnknown();await page.keyboard.press('Escape');
  await page.locator('[data-action="config"][data-config="connection"]').click();
  await checkUnknown(); // reopening must not replace unknown enums by blank/default
  assert.deepEqual(await state(),seeded);assert.deepEqual(fs.readFileSync(draftFile),bytes);
  assert.equal(report.writes.length,start);
  report.element_enum_cycles=[];
  const attempts=[
    {fields:['system'],target:'system',value:row.system},
    {fields:['kind','service_direction','service_fitting','unit'],target:'kind',value:row.kind},
    {fields:['service_direction','service_fitting','unit'],target:'service_fitting',value:row.service_fitting},
    {fields:['service_direction','unit'],target:'service_direction',value:row.service_direction},
    {fields:['unit'],target:'unit',value:row.unit},
  ];
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  for(const [index,attempt] of attempts.entries()) {
    const response=await submit();assert.equal(response.status(),422);
    const error=await response.json();
    assert.deepEqual(error.input_issues.map(i=>i.field),attempt.fields);
    assert(error.input_issues.every(i=>i.registry==='sewer_elements'&&i.row_index===1));
    assert((await page.locator('#error').innerText()).includes(error.input_message));
    assert.deepEqual(await state(),seeded);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    assert.equal(report.writes.length,start+index+1);
    await page.screenshot({path:path.join(root,'enum-error-'+attempt.target+'.png')});
    await page.locator('#error [data-action="input-issue"]').nth(attempt.fields.indexOf(attempt.target)).focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.column),attempt.target);
    await checkUnknown();
    assert.equal(await control('note').inputValue(),'TEST-ONLY: соседний ввод сохранён');
    if(attempt.target==='unit')await control('unit').fill(attempt.value);
    else await control(attempt.target).selectOption(attempt.value);
    delete unknown[attempt.target];
    report.element_enum_cycles.push({target:attempt.target,fields:attempt.fields,unchanged_server:true,exact_return:true});
  }
  const response=await submit();assert.equal(response.status(),200,await response.text());
  const saved=await response.json(),expected=values(original);
  expected.sewer_elements[1].note='TEST-ONLY: соседний ввод сохранён';
  assert.deepEqual(values(saved),expected);assert.equal(saved.project_calculation,null);
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
  await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
  const calculated=await pending;assert.equal(calculated.status(),200,await calculated.text());
  const current=await calculated.json();await idle();
  assert.deepEqual(values(current),expected);assert.equal(current.project_calculation.can_release,false);
  const savedBytes=fs.readFileSync(draftFile);
  await page.reload();await idle();assert.deepEqual(await state(),current);
  assert.deepEqual(fs.readFileSync(draftFile),savedBytes);
  assert.equal(report.writes.length,start+8);assert.equal(report.expected_http_errors.length-errorsStart,5);
  assert.deepEqual(report.errors,[]);report.element_enum_fixture='explicit private obsolete draft, no API acceptance';
  console.log('PASS: obsolete enum fixture retained across adjacent edit/reopen, 5 real 422s, exact field return, explicit correction/recalculation, no default substitutions.');
};
