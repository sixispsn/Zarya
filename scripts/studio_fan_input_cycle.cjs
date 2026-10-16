// Real nested fan editor, no fixture mutation or fabricated select choices.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,root,draftFile,report,modelCycle=false})=>{
  const key='wastewater_fan_ventilation',index=1;
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const before=await state(),data=values(before)[key],bytes=fs.readFileSync(draftFile);
  const start=report.writes.length,errorsStart=report.expected_http_errors.length;
  const editor=()=>page.locator('#clarification-body [data-input="'+key+'"]');
  const control=field=>editor().locator('.route-row').nth(index).locator('[data-column="'+field+'"]');
  const global=()=>editor().locator('[data-fan-global="external_ventilation_ref"]');
  const open=async details=>{if(await details.getAttribute('open')===null)await details.locator(':scope > summary').click();};
  const reveal=async input=>{
    const parents=input.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)await open(parents.nth(i));
  };
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-action="config"][data-config="connection"]').click();
  await reveal(global());
  const note='TEST-ONLY: сохранность общего поля фановой вентиляции';
  await global().fill(note);
  const cases=[['terminal_id','','required_value'],['riser_ids','','fan_ids_list'],
    ['height_m','oops','invalid_number'],['height_m','nan','nonfinite_number'],
    ['riser_ids','Нет-стояка','fan_unlinked_riser'],
    ['riser_ids',data.terminals[0].riser_ids.join('\n'),'fan_repeated_riser']];
  if(modelCycle)cases.push(['terminal_id',data.terminals[0].terminal_id,'fan_model_duplicate_id'],
    ['riser_ids',[data.terminals[1].riser_ids[0],data.terminals[1].riser_ids[0]].join('\n'),'fan_model_riser_ids'],
    ...['height_m','diameter_mm','collector_diameter_mm','opening_distance_m'].map(field=>[field,'-0.01','fan_model_number']));
  report.fan_input_cycles=[];
  for(const [attempt,[field,value,code]] of cases.entries()) {
    await page.setViewportSize(attempt%2?{width:390,height:844}:{width:1440,height:1000});
    await reveal(control(field));await control(field).fill(value);
    const response=await submit();assert.equal(response.status(),422,await response.text());
    const error=await response.json(),issue=error.input_issues[0];
    assert.equal(error.input_issues.length,1);
    assert.deepEqual([issue.registry,issue.row_index,issue.field,issue.code],[key,index,field,code]);
    assert((await page.locator('#error').innerText()).includes(error.input_message));
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    assert.equal(report.writes.length,start+attempt+1);
    await page.screenshot({path:path.join(root,'fan-error-'+code+'.png')});
    await page.locator('#error [data-action="input-issue"]').focus();await page.keyboard.press('Enter');
    const focus=await page.evaluate(()=>({field:document.activeElement.dataset.column,value:document.activeElement.value,
      top:document.activeElement.getBoundingClientRect().top,bottom:document.activeElement.getBoundingClientRect().bottom,height:innerHeight}));
    assert.equal(focus.field,field);assert.equal(focus.value,value);
    assert(focus.top>=0&&focus.bottom<=focus.height);
    assert.equal(await global().inputValue(),note);
    assert.equal(await control('terminal_id').inputValue(),field==='terminal_id'?value:data.terminals[index].terminal_id);
    assert.equal(report.writes.length,start+attempt+1);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'fan-return-'+code+'.png')});
    const old=data.terminals[index][field];
    await control(field).fill(Array.isArray(old)?old.join('\n'):old===null?'':String(old));
    report.fan_input_cycles.push({field,code,exact_return:true,global_preserved:true,server_unchanged:true});
  }
  const response=await submit();assert.equal(response.status(),200,await response.text());
  const saved=await response.json(),expected=values(before);
  expected[key].external_ventilation_ref=note;
  assert.deepEqual(values(saved),expected);assert.equal(saved.project_calculation,null);
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
  await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
  const calculated=await pending;assert.equal(calculated.status(),200,await calculated.text());
  const current=await calculated.json();await idle();
  await page.waitForFunction(()=>!document.querySelector('#clarification-dialog').open);
  assert.deepEqual(values(current),expected);assert.equal(current.project_calculation.can_release,false);
  assert.deepEqual(current.project_calculation.sewage_diagnostic_review,before.project_calculation.sewage_diagnostic_review);
  const after=fs.readFileSync(draftFile);
  await page.reload();await idle();assert.deepEqual(await state(),current);
  report.fan_stale_contexts=[];
  for(const context of ['global','pipes']) {
    const writes=report.writes.length;
    await page.locator('[data-action="config"][data-config="connection"]').click();
    await reveal(control('riser_ids'));await control('riser_ids').fill('Нет-стояка');
    assert.equal((await submit()).status(),422);
    await page.locator('[data-action="config"][data-config="connection"]').click();
    if(context==='global') {
      await reveal(global());await global().fill('TEST-ONLY: изменено после проверки');
    } else {
      const pipe=page.locator('#clarification-body [data-input="sewer_pipes"] .route-row').first().locator('[data-column="room"]');
      await reveal(pipe);await pipe.fill('TEST-ONLY: изменено после проверки');
    }
    await page.keyboard.press('Escape');
    await page.locator('#error [data-action="input-issue"]').click();
    assert((await page.locator('#error').innerText()).includes('Исходные после проверки изменились'));
    assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
    assert.equal(await page.locator('#error [data-action="input-issue"]').count(),0);
    assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),after);
    assert.equal(report.writes.length,writes+1);
    await page.screenshot({path:path.join(root,'fan-stale-'+context+'.png')});
    await page.reload();await idle();assert.deepEqual(await state(),current);
    assert.deepEqual(fs.readFileSync(draftFile),after);
    report.fan_stale_contexts.push(context);
  }
  assert.equal(report.writes.length-start,cases.length+5);assert.equal(report.expected_http_errors.length-errorsStart,cases.length+2);
  assert.deepEqual(report.errors,[]);
  console.log('PASS: nested fan parser/links/model, '+cases.length+' exact returns, globals preserved, recovery/recalculation; stale globals and pipes revoke addresses.');
};
