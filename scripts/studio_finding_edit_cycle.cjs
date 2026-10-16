// Called by verify_studio_finding_inputs.cjs --edit-cycle on its private server.
// After fixture setup, every mutation goes through visible Studio controls.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');

module.exports=async function editCycle({page,state,idle,before,root,draftFile,report,invalidCycle=false,parserCycle=false,linkCycle=false}) {
  const values=draft=>Object.fromEntries(draft.fields.map(row=>[row.key,row.value]));
  const finding=code=>page.locator('[data-finding-code="'+code+'"]');
  const open=async details=>{if(await details.getAttribute('open')===null)await details.locator(':scope > summary').click();};
  const enter=async(control,value)=>{
    if(await control.evaluate(element=>element.tagName)==='SELECT')await control.selectOption(value);
    else await control.fill(value);
  };
  const detail=async code=>{
    await page.locator('[data-action="readiness"]').click();
    await open(finding(code).locator('..'));
    const review=finding(code).locator(code==='K1-02'?'.riser-review':'.diagnostic-review');
    await open(review);
    if(code==='K1-02')return review;
    const service=review.locator('.diagnostic-group').filter({has:page.locator('summary').filter({hasText:'Линейное обслуживание'})});
    await open(service);return service;
  };
  const resultRow=(draft,code,id)=>code==='K1-02'
    ? draft.project_calculation.sewage_riser_review.risers.find(row=>row.riser_id===id)
    : draft.project_calculation.sewage_diagnostic_review.linear_service_checks.find(row=>row.section_id===id);
  const requests=[];
  page.on('request',request=>{
    if(!['GET','HEAD'].includes(request.method()))requests.push({method:request.method(),
      pathname:new URL(request.url()).pathname,body:request.postDataJSON()});
  });
  const cases=[
    {code:'K1-02',key:'sewage_risers',idField:'riser_id',id:values(before).sewage_risers[1].riser_id,
      column:'design_flow_lps',value:4.125,width:1440,height:1000,
      invalidColumn:'riser_id',invalidValue:values(before).sewage_risers[0].riser_id,errorText:'повторяется'},
    {code:'K1-05',key:'sewer_pipes',idField:'section_id',id:'К1-М1',
      column:'calculation_length_m',value:53,width:390,height:844,
      invalidColumn:'wall_thickness_mm',invalidValue:1000,errorText:'толщина стенки исключает проходное'},
  ];
  report.edit_cycles=[];
  report.invalid_cycles=[];
  report.stale_link_checked=false;
  let current=before;
  for(const c of cases) {
    await page.setViewportSize({width:c.width,height:c.height});
    const initial=current,oldResult=resultRow(initial,c.code,c.id),start=requests.length;
    const expected=structuredClone(values(initial));
    const row=expected[c.key].find(item=>item[c.idField]===c.id);
    assert(row);assert.notEqual(row[c.column],c.value);row[c.column]=c.value;
    const scope=await detail(c.code);
    await scope.locator('[data-action="finding-row"]').filter({hasText:'К строке '+c.id+' →'}).click();
    assert.equal(await page.evaluate(()=>document.activeElement.value),c.id);
    const editor=page.locator('#clarification-body [data-input="'+c.key+'"]');
    const rowIndex=values(initial)[c.key].findIndex(item=>item[c.idField]===c.id);
    const control=editor.locator('.route-row').nth(rowIndex).locator('[data-column="'+c.column+'"]');
    const collapsed=control.locator('xpath=ancestor::details[1]');
    if(await collapsed.count())await open(collapsed);
    await control.fill(String(c.value));
    assert.equal(await scope.isVisible(),false); // stale evidence disappears immediately
    assert.deepEqual(await state(),initial); // typing alone must not write
    assert.equal(requests.length,start);

    const invalidCases=invalidCycle?[c]:[];
    if(parserCycle) {
      const numeric=c.key==='sewage_risers'?'branch_dn_mm':'outer_diameter_mm';
      const integer=c.key==='sewage_risers'?'branch_dn_mm':'nominal_diameter_mm';
      invalidCases.push(
        {...c,invalidColumn:c.idField,invalidValue:'',errorText:'укажите'},
        {...c,invalidColumn:numeric,invalidValue:'oops',errorText:'число'},
        {...c,invalidColumn:numeric,invalidValue:'nan',errorText:'конечное число'},
        {...c,invalidColumn:integer,invalidValue:'110.5',errorText:'целое число'},
      );
    }
    if(linkCycle) {
      // Browser selects only real options. Invalid boolean types are API-tested;
      // the real UI negative case is the explicit "not set" option.
      invalidCases.push({...c,invalidColumn:c.key==='sewage_risers'?'has_toilet':'insulated',invalidValue:'',errorText:'укажите'});
      if(c.key==='sewage_risers')invalidCases.push({...c,invalidColumn:'riser_id',invalidValue:'К1-Нет-Такого',errorText:'не связана'});
    }
    for(const variant of invalidCases) {
      const c=variant,attempt=requests.length;
      const bytes=fs.readFileSync(draftFile);
      const invalidControl=()=>editor.locator('.route-row').nth(rowIndex).locator('[data-column="'+c.invalidColumn+'"]');
      const originalValue=values(initial)[c.key][rowIndex][c.invalidColumn];
      const parent=invalidControl().locator('xpath=ancestor::details[1]');
      if(await parent.count())await open(parent);
      await enter(invalidControl(),String(c.invalidValue));
      assert.deepEqual(await state(),initial);assert.equal(requests.length,attempt);
      const rejectedResponse=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
      await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
      const rejected=await rejectedResponse;
      assert.equal(rejected.status(),422);
      const rejection=await rejected.json();assert.equal(typeof rejection.detail,'string');
      assert(rejection.detail.includes(c.errorText));
      await idle();await page.locator('#error').waitFor({state:'visible'});
      assert.equal(rejection.input_issues.length,1);
      assert.equal(rejection.input_issues[0].registry,c.key);
      assert.equal(rejection.input_issues[0].row_index,rowIndex);
      assert.equal(rejection.input_issues[0].field,c.invalidColumn);
      assert((await page.locator('#error').innerText()).includes(rejection.input_message));
      assert(!(await page.locator('#error').innerText()).includes(c.key+'['));
      assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
      assert.equal(await page.locator('.riser-review-row:visible, .diagnostic-review-row:visible').count(),0);
      assert.deepEqual(await state(),initial,'422 must preserve revision, all inputs and the last server result');
      assert.deepEqual(fs.readFileSync(draftFile),bytes,'No partial writes on validation failure');
      assert.equal(requests.length,attempt+1,'No calculate or retry after 422');
      assert.deepEqual(Object.keys(requests[attempt].body.answers),[c.key]);
      assert.equal(requests[attempt].body.answers[c.key][rowIndex][c.invalidColumn],String(c.invalidValue));
      assert.equal(requests[attempt].body.answers[c.key][rowIndex][c.column],String(c.value));
      const shot=c.code+'-'+rejection.input_issues[0].code;
      await page.screenshot({path:path.join(root,'invalid-cycle-'+shot+'.png')});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      // Explicit structured-address return, not a fuzzy ID or message parser.
      await page.locator('#error [data-action="input-issue"]').focus();
      await page.keyboard.press('Enter');
      const focused=await page.evaluate(()=>({column:document.activeElement.dataset.column,
        value:document.activeElement.value,top:document.activeElement.getBoundingClientRect().top,
        bottom:document.activeElement.getBoundingClientRect().bottom,height:innerHeight}));
      assert.equal(focused.column,c.invalidColumn);assert.equal(focused.value,String(c.invalidValue));
      assert(focused.top>=0&&focused.bottom<=focused.height);
      assert.equal(requests.length,attempt+1,'Returning to the error must not save or retry');
      assert.equal(await invalidControl().inputValue(),String(c.invalidValue));
      assert.equal(await control.inputValue(),String(c.value));
      await page.screenshot({path:path.join(root,'invalid-return-'+shot+'.png')});
      await enter(invalidControl(),originalValue===null || originalValue===undefined?'':String(originalValue));
      assert.deepEqual(await state(),initial);assert.deepEqual(fs.readFileSync(draftFile),bytes);
      report.invalid_cycles.push({code:c.code,id:c.id,column:c.invalidColumn,rejected_value:c.invalidValue,
        http_status:rejected.status(),message:rejection.input_message,legacy_detail:rejection.detail,
        exact_field_return:true,server_state_and_bytes_unchanged:true,
        stale_results_hidden:true,unsaved_values_preserved:true});
    }

    const savedResponse=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await savedResponse;
    assert.equal(response.status(),200,await response.text());
    const saved=await response.json();
    assert.equal(saved.project_calculation,null);
    assert.deepEqual(values(saved),expected,'Only the explicitly edited property may change');
    await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
    await idle();
    assert.deepEqual(await state(),saved);
    const savedDisk=JSON.parse(fs.readFileSync(draftFile));
    assert.equal(savedDisk.project_calculation,null);
    assert.equal(await page.locator('.riser-review-row:visible, .diagnostic-review-row:visible').count(),0);

    const calculatedResponse=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const calculated=await calculatedResponse;
    assert.equal(calculated.status(),200,await calculated.text());
    current=await calculated.json();await idle();
    await page.waitForFunction(()=>!document.querySelector('#clarification-dialog').open);
    assert.equal(await page.locator('#error').isVisible(),false,'Successful recovery clears the validation error');
    assert.deepEqual(values(current),expected);
    assert.equal(current.project_calculation.can_release,false);
    const newResult=resultRow(current,c.code,c.id);
    assert.equal(newResult[c.column],c.value);
    assert.notEqual(newResult.note,oldResult.note,'The changed engineering reason must replace the old one');
    assert.equal(newResult.status,'fail');
    if(c.code==='K1-02') {
      assert.equal(newResult.capacity_ok,false);
      assert.deepEqual(current.project_calculation.sewage_riser_review.risers.filter(r=>r.riser_id!==c.id),
        initial.project_calculation.sewage_riser_review.risers.filter(r=>r.riser_id!==c.id));
    } else {
      assert.deepEqual(current.project_calculation.sewage_riser_review,initial.project_calculation.sewage_riser_review);
    }
    const changedFinding=current.project_calculation.quality.gates.flatMap(g=>g.findings).find(f=>f.code===c.code);
    assert.equal(changedFinding.state,'blocked');
    const checkUI=async()=>{
      const rendered=await detail(c.code);
      const card=rendered.locator(c.code==='K1-02'?'.riser-review-row':'.diagnostic-review-row')
        .filter({has:page.locator('[data-action="finding-row"]').filter({hasText:'К строке '+c.id+' →'})});
      const text=await card.innerText();
      assert(text.includes(newResult.note));assert(!text.includes(oldResult.note));
      assert(text.includes(String(c.value).replace('.',',')));
      assert(text.includes('Есть несоответствие'));
      assert((await finding(c.code).innerText()).includes(changedFinding.detail));
      await card.scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(root,'edit-cycle-'+c.code+'.png')});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    };
    await checkUI();
    assert.deepEqual(await state(),current);
    const bytes=fs.readFileSync(draftFile),writes=requests.length;
    assert.deepEqual(requests.slice(start).map(r=>[r.method,r.pathname]),[
      ...invalidCases.map(()=>['PATCH','/studio/api/answers']),
      ['PATCH','/studio/api/answers'],['PATCH','/studio/api/answers'],['POST','/studio/api/calculate'],
    ]);
    const savedIndex=start+invalidCases.length;
    assert.deepEqual(Object.keys(requests[savedIndex].body.answers),[c.key]);
    assert.deepEqual(requests[savedIndex+1].body.answers,{});
    await page.reload();await idle();await checkUI();
    assert.equal(requests.length,writes,'Reload/view must not calculate or save again');
    assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    report.edit_cycles.push({code:c.code,id:c.id,column:c.column,value:c.value,
      before_note:oldResult.note,after_note:newResult.note,status:newResult.status,
      can_release:current.project_calculation.can_release,writes:requests.length-start,
      other_inputs_unchanged:true,saved_result_revoked:true,reload_unchanged:true});
  }
  if(linkCycle) {
    // A real change to the OTHER registry must revoke the stored error address.
    const bytes=fs.readFileSync(draftFile),start=requests.length;
    const id=values(current).sewage_risers[1].riser_id;
    const scope=await detail('K1-02');
    await scope.locator('[data-action="finding-row"]').filter({hasText:'К строке '+id+' →'}).click();
    await page.locator('#clarification-body [data-input="sewage_risers"] .route-row').nth(1)
      .locator('[data-column="riser_id"]').fill('К1-Нет-Такого');
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body button[type="submit"]').click();
    const rejected=await pending;assert.equal(rejected.status(),422);
    assert.equal((await rejected.json()).input_issues[0].code,'unlinked_riser');await idle();
    await page.locator('[data-action="config"][data-config="connection"]').click();
    const pipes=page.locator('#clarification-body [data-input="sewer_pipes"]');
    await open(pipes.locator('xpath=ancestor::details[1]'));
    await pipes.locator('.route-row').first().locator('[data-column="room"]').fill('TEST-ONLY: изменено после проверки связи');
    await page.keyboard.press('Escape');
    await page.locator('#error [data-action="input-issue"]').click();
    assert((await page.locator('#error').innerText()).includes('Исходные после проверки изменились'));
    assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
    assert.equal(await page.locator('#error [data-action="input-issue"]').count(),0);
    assert.equal(requests.length,start+1,'Stale-address refusal must not write or retry');
    assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),bytes);
    await page.screenshot({path:path.join(root,'stale-link-address.png')});
    await page.reload();await idle();
    assert.equal(requests.length,start+1);assert.deepEqual(await state(),current);
    assert.deepEqual(fs.readFileSync(draftFile),bytes);
    report.stale_link_checked=true;
  }
  assert.equal(report.invalid_cycles.length,linkCycle?13:parserCycle?10:invalidCycle?2:0);
  const rejectedCount=report.invalid_cycles.length+(linkCycle?1:0);
  assert.equal(report.writes.length,6+rejectedCount);assert.deepEqual(report.errors,[]);
  assert.equal(report.expected_http_errors.length,rejectedCount);
  if(linkCycle)console.log('PASS: changed pipe registry revokes unlinked-riser error address; no save, no stale focus, unchanged server state after reload.');
  if(invalidCycle)console.log('PASS: '+report.invalid_cycles.length+' real 422 refusals, no partial save/revision/result changes, readable errors, unsaved values retained, recovery and recalculation through UI.');
  console.log('PASS: two UI edit/save/recalculate cycles, revoked old details, exact API reasons after reload, other inputs unchanged, release still blocked; no PDF requests.');
};
