// Visible controls only; isolated ordinary draft from the parent harness.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,before,root,draftFile,report,rangesCycle=false})=>{
  const values=draft=>Object.fromEntries(draft.fields.map(row=>[row.key,row.value]));
  const initial=values(before),index=1,key='sewer_elements';
  const bytes=fs.readFileSync(draftFile),start=report.writes.length,startErrors=report.expected_http_errors.length;
  const open=async details=>{if(await details.getAttribute('open')===null)await details.locator(':scope > summary').click();};
  const control=field=>page.locator('#clarification-body [data-input="sewer_elements"] .route-row').nth(index).locator('[data-column="'+field+'"]');
  const enter=async(field,value)=>{
    const input=control(field),parents=input.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)await open(parents.nth(i));
    if(await input.evaluate(el=>el.tagName)==='SELECT')await input.selectOption(value);
    else await input.fill(value);
  };
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-action="readiness"]').click();
  const finding=page.locator('[data-finding-code="K1-05"]');
  await open(finding.locator('..'));
  await finding.locator('[data-action="finding-inputs"][data-finding-input="sewer_elements"]').click();
  assert.equal(await control('element_id').inputValue(),initial[key][index].element_id);
  const note='TEST-ONLY: сохранённый ввод элемента';
  await enter('room_name',note);
  const wrongSystem=initial.sewer_pipes.find(p=>p.system!==initial[key][index].system).section_id;
  const cases=[['name','','required_value'],['dn_mm','oops','invalid_number'],
    ['elevation_m','nan','nonfinite_number'],['quantity','1.5','integer_required'],
    ['accessible','','required_value'],['include_in_spec','','required_value'],
    ['section_id','Нет-такого-участка','unknown_element_section'],
    ['section_id',wrongSystem,'element_section_system'],
    ['connects_to','Нет-такого-узла','unknown_element_connection']];
  if(rangesCycle)cases.push(
    ['element_id',initial[key][0].element_id,'duplicate_element_id'],
    ['quantity','0','element_quantity_positive'],
    ['typical_quantity','0','element_typical_quantity_positive'],
    ['floor_to',String(initial[key][index].floor_from-1),'element_floor_order'],
    ['dn_mm','0','element_dn_positive'],
    ['slope_per_mille','-0.001','element_slope_nonnegative'],
    ['layout_column','-1','element_layout_nonnegative'],
    ['service_chainage_m','-0.001','element_chainage_nonnegative']);
  report.element_cycles=[];
  for(const [attempt,[field,value,code]] of cases.entries()) {
    await page.setViewportSize(attempt%2?{width:390,height:844}:{width:1440,height:1000});
    await enter(field,value);
    const response=await submit();assert.equal(response.status(),422);
    const error=await response.json();
    assert.equal(error.input_issues.length,1);
    assert.deepEqual([error.input_issues[0].registry,error.input_issues[0].row_index,error.input_issues[0].field,error.input_issues[0].code],
      [key,index,field,code]);
    assert((await page.locator('#error').innerText()).includes(error.input_message));
    assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    assert.equal(report.writes.length,start+attempt+1);
    await page.screenshot({path:path.join(root,'element-error-'+field+'-'+code+'.png')});
    await page.locator('#error [data-action="input-issue"]').focus();await page.keyboard.press('Enter');
    const focused=await page.evaluate(()=>({field:document.activeElement.dataset.column,value:document.activeElement.value,
      top:document.activeElement.getBoundingClientRect().top,bottom:document.activeElement.getBoundingClientRect().bottom,height:innerHeight}));
    assert.equal(focused.field,field);assert.equal(focused.value,value);
    assert(focused.top>=0&&focused.bottom<=focused.height);
    assert.equal(await control('room_name').inputValue(),note);
    assert.equal(await control('element_id').inputValue(),field==='element_id'?value:initial[key][index].element_id);
    assert.equal(report.writes.length,start+attempt+1);
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'element-return-'+field+'-'+code+'.png')});
    await enter(field,initial[key][index][field]===null?'':String(initial[key][index][field]));
    report.element_cycles.push({field,code,exact_return:true,unsaved_values_preserved:true,server_unchanged:true});
  }
  report.element_multi_errors=[];
  if(rangesCycle)for(const mixed of [false,true]) {
    const writes=report.writes.length;
    await enter('quantity','0');await enter('dn_mm','0');
    if(mixed)await enter('unit','');
    const response=await submit();assert.equal(response.status(),422);
    const error=await response.json();
    assert.deepEqual(error.input_issues.map(i=>[i.row_index,i.field]),[[index,'quantity'],[index,'dn_mm'],...(mixed?[[index,'unit']]:[])]);
    assert.equal(typeof error.input_message,'string');
    const errorText=await page.locator('#error').innerText();
    assert(errorText.includes(error.input_message));
    if(mixed)assert(errorText.includes('единицу измерения'));
    assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    await page.screenshot({path:path.join(root,'element-multiple-'+mixed+'.png')});
    await page.locator('#error [data-action="input-issue"]').nth(1).focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.column),'dn_mm');
    assert.equal(await control('quantity').inputValue(),'0');
    assert.equal(await control('dn_mm').inputValue(),'0');
    assert.equal(await control('room_name').inputValue(),note);
    assert.equal(report.writes.length,writes+1);
    for(const field of ['quantity','dn_mm','unit'])await enter(field,String(initial[key][index][field]));
    report.element_multi_errors.push({mixed,second_address_exact:true,server_unchanged:true});
  }
  const rejectedCount=cases.length+report.element_multi_errors.length;
  const savedResponse=await submit();assert.equal(savedResponse.status(),200,await savedResponse.text());
  const saved=await savedResponse.json(),expected=structuredClone(initial);
  expected[key][index].room_name=note;
  assert.deepEqual(values(saved),expected);assert.equal(saved.project_calculation,null);
  await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
  const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
  await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
  const calculated=await pending;assert.equal(calculated.status(),200,await calculated.text());
  const current=await calculated.json();await idle();
  await page.waitForFunction(()=>!document.querySelector('#clarification-dialog').open);
  assert.deepEqual(values(current),expected);assert.equal(current.project_calculation.can_release,false);
  // Room identity is engineering input: splitting a fixture from the original
  // room must produce the existing mixed-room branch diagnostic after recalc.
  const diagnostic=current.project_calculation.sewage_diagnostic_review;
  const roomError=initial[key][index].section_id+': одно ответвление содержит приборы разных помещений; разделите участки';
  assert(!before.project_calculation.sewage_diagnostic_review.errors.includes(roomError));
  assert(diagnostic.errors.includes(roomError));
  assert.deepEqual(diagnostic.linear_service_checks,before.project_calculation.sewage_diagnostic_review.linear_service_checks);
  assert.equal(report.writes.length,start+rejectedCount+3);
  const afterBytes=fs.readFileSync(draftFile);
  await page.reload();await idle();assert.deepEqual(await state(),current);
  assert.deepEqual(fs.readFileSync(draftFile),afterBytes);
  // An unsaved change to a pipe invalidates the earlier element-link address.
  await page.locator('[data-action="config"][data-config="connection"]').click();
  await enter('section_id','Нет-такого-участка');
  assert.equal((await submit()).status(),422);
  await page.locator('[data-action="config"][data-config="connection"]').click();
  const pipes=page.locator('#clarification-body [data-input="sewer_pipes"]');
  await open(pipes.locator('xpath=ancestor::details[1]'));
  await pipes.locator('.route-row').first().locator('[data-column="room"]').fill('TEST-ONLY: изменено после проверки');
  await page.keyboard.press('Escape');
  await page.locator('#error [data-action="input-issue"]').click();
  assert((await page.locator('#error').innerText()).includes('Исходные после проверки изменились'));
  assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  assert.equal(await page.locator('#error [data-action="input-issue"]').count(),0);
  await page.screenshot({path:path.join(root,'element-stale-link.png')});
  assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),afterBytes);
  await page.reload();await idle();assert.deepEqual(await state(),current);
  assert.deepEqual(fs.readFileSync(draftFile),afterBytes);
  assert.equal(report.writes.length,start+rejectedCount+4);assert.deepEqual(report.errors,[]);
  assert.equal(report.expected_http_errors.length-startErrors,rejectedCount+1);
  report.element_stale_link_checked=true;report.element_recovery_checked=true;
  console.log('PASS: '+rejectedCount+' element refusals with exact return, atomic recovery/recalculation, unrelated inputs unchanged, release blocked, stale pipe context rejected without writes.');
};
