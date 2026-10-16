// All identity/link changes use existing visible inputs; no automatic cascades.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
module.exports=async({page,state,idle,root,draftFile,report})=>{
  const keys=['sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation'];
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const before=await state(),base=values(before),bytes=fs.readFileSync(draftFile);
  const old=base.sewage_risers[1].riser_id,next='К1-Переименован-TEST';
  const expected=JSON.parse(JSON.stringify(base));
  const start=report.writes.length;
  const editor=key=>page.locator('#clarification-body [data-input="'+key+'"]');
  const input=(key,index,field)=>editor(key).locator('.route-row').nth(index).locator('[data-column="'+field+'"]');
  const reveal=async control=>{
    const parents=control.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)
      await parents.nth(i).locator(':scope > summary').click();
  };
  const open=()=>page.locator('[data-action="config"][data-config="connection"]').click();
  const snapshot=()=>page.evaluate(keys=>Object.fromEntries(keys.map(key=>[key,JSON.parse(document.querySelector('#field-'+key).value)])),keys);
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.request().method()==='PATCH'&&new URL(r.url()).pathname==='/studio/api/answers');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  const calculate=async()=>{
    await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
    const pending=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/studio/api/calculate');
    await page.locator('#clarification-body [data-config-form] button[type="submit"]').click();
    const response=await pending;assert.equal(response.status(),200,await response.text());await idle();return response.json();
  };
  await page.setViewportSize({width:1440,height:1000});await open();
  const pi=base.sewer_pipes.findIndex(r=>r.section_id===old);assert(pi>=0);
  await reveal(input('sewer_pipes',pi,'section_id'));await input('sewer_pipes',pi,'section_id').fill(next);
  const pending=await snapshot();
  for(const key of keys.slice(1))assert.deepEqual(pending[key],base[key]);
  assert.equal(await page.locator('.calculation-output').isVisible(),false);
  const refused=await submit();assert.equal(refused.status(),422,await refused.text());
  assert.deepEqual(await state(),before);assert.deepEqual(fs.readFileSync(draftFile),bytes);
  const issue=(await refused.json()).input_issues[0];assert.equal(issue.registry,'sewer_elements');
  await page.locator('#error [data-action="input-issue"]').first().click();
  assert.equal(await input(issue.registry,issue.row_index,issue.field).evaluate(e=>e===document.activeElement),true);
  assert.deepEqual(await snapshot(),pending);
  // Change every matching reference explicitly through its own control.
  for(const [key,fields] of [['sewer_pipes',['section_id','from_node','to_node']],['sewer_elements',['section_id','connects_to']],['sewage_risers',['riser_id']]]) {
    for(const [i,row] of base[key].entries())for(const field of fields)if(row[field]===old) {
      await reveal(input(key,i,field));
      assert.equal(await input(key,i,field).inputValue(),key==='sewer_pipes'&&i===pi&&field==='section_id'?next:old);
      await input(key,i,field).fill(next);expected[key][i][field]=next;
    }
  }
  for(const [i,row] of base[keys[3]].terminals.entries())if(row.riser_ids.includes(old)) {
    const changed=row.riser_ids.map(id=>id===old?next:id);
    await reveal(input(keys[3],i,'riser_ids'));await input(keys[3],i,'riser_ids').fill(changed.join('\n'));
    expected[keys[3]].terminals[i].riser_ids=changed;
  }
  const saved=await submit();assert.equal(saved.status(),200,await saved.text());
  const renamed=await saved.json();assert.deepEqual(values(renamed),expected);assert.equal(renamed.project_calculation,null);
  const current=await calculate();assert.deepEqual(values(current),expected);assert.deepEqual(current.calculation,before.calculation);
  assert.equal(current.project_calculation.can_release,false);
  const ids=current.project_calculation.sewage_riser_review.risers.map(r=>r.riser_id);
  assert(ids.includes(next));assert(!ids.includes(old));
  await page.reload();await idle();assert.deepEqual(await state(),current);
  await page.locator('[data-action="readiness"]').click();
  const finding=page.locator('[data-finding-code="K1-02"]');
  await reveal(finding.locator('.riser-review > summary'));
  const detail=finding.locator('.riser-review');if(await detail.getAttribute('open')===null)await detail.locator(':scope > summary').click();
  assert((await detail.innerText()).includes(next));assert(!(await detail.innerText()).includes(old));
  await detail.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(root,'identity-renamed-review.png')});
  // A prior row-2 error must not point to a different position after deletion.
  await open();await reveal(input(keys[3],1,'height_m'));await input(keys[3],1,'height_m').fill('-1');
  assert.equal((await submit()).status(),422);
  const deletionBytes=fs.readFileSync(draftFile);
  await open();const rows=editor(keys[3]).locator('.route-row');
  await reveal(rows.first().locator('[data-action="remove-section"]'));
  await rows.first().locator('[data-action="remove-section"]').click();
  assert.equal(await rows.count(),base[keys[3]].terminals.length-1);
  assert.equal(await rows.first().locator('legend').innerText(),'К1 · фановое окончание 1');
  assert.equal(await rows.first().locator('[data-action="remove-section"]').getAttribute('aria-label'),'Удалить фановое окончание К1 1');
  assert.equal(await input(keys[3],0,'height_m').inputValue(),'-1');
  await page.keyboard.press('Escape');await page.locator('#error [data-action="input-issue"]').click();
  assert((await page.locator('#error').innerText()).includes('Исходные после проверки изменились'));
  assert.equal(await page.locator('#clarification-dialog').getAttribute('open'),null);
  assert.deepEqual(await state(),current);assert.deepEqual(fs.readFileSync(draftFile),deletionBytes);
  await open();await reveal(input(keys[3],0,'height_m'));
  await input(keys[3],0,'height_m').fill(String(base[keys[3]].terminals[1].height_m));
  await page.setViewportSize({width:390,height:844});await rows.first().locator('legend').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'identity-deletion-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const removed=await submit();assert.equal(removed.status(),200,await removed.text());
  expected[keys[3]].terminals=expected[keys[3]].terminals.slice(1);
  assert.deepEqual(values(await removed.json()),expected);
  const final=await calculate();assert.deepEqual(values(final),expected);
  assert.equal(final.project_calculation.sewer_scheme.ready,false);assert.equal(final.project_calculation.can_release,false);
  await page.reload();await idle();assert.deepEqual(await state(),final);
  // Deletion itself never saves or cascades. Check all four active editors,
  // including the now-single fan row (focus returns to Add on an empty registry).
  const finalBytes=fs.readFileSync(draftFile),finalValues=values(final);
  for(const [i,key] of keys.entries()) {
    await open();const activeRows=editor(key).locator('.route-row');
    const original=key===keys[3]?finalValues[key].terminals:finalValues[key];
    const id=['section_id','element_id','riser_id','terminal_id'][i];
    await reveal(activeRows.first().locator('[data-action="remove-section"]'));
    await activeRows.first().locator('[data-action="remove-section"]').click();
    assert.equal(await activeRows.count(),original.length-1);
    for(let index=0;index<original.length-1;index++) {
      assert((await activeRows.nth(index).locator('legend').innerText()).endsWith(' '+(index+1)));
      assert((await activeRows.nth(index).locator('[data-action="remove-section"]').getAttribute('aria-label')).endsWith(' '+(index+1)));
      assert.equal(await input(key,index,id).inputValue(),original[index+1][id]);
    }
    const focus=original.length>1?activeRows.first().locator('input,select,textarea').first():editor(key).locator('[data-action="add-section"]');
    assert.equal(await focus.evaluate(e=>e===document.activeElement),true);
    const unsaved=await snapshot();
    for(const other of keys.filter(other=>other!==key))assert.deepEqual(unsaved[other],finalValues[other]);
    if(key===keys[3]) {
      assert.deepEqual(unsaved[key].terminals,[]);
      assert.equal(unsaved[key].external_ventilation_ref,finalValues[key].external_ventilation_ref);
      assert.equal(unsaved[key].external_ventilation_verified,finalValues[key].external_ventilation_verified);
    }
    await page.keyboard.press('Escape');await open();assert.deepEqual(await snapshot(),unsaved);
    assert.deepEqual(await state(),final);assert.deepEqual(fs.readFileSync(draftFile),finalBytes);
    await page.keyboard.press('Escape');
    const discard=dialog=>dialog.accept();page.on('dialog',discard);
    try {await page.reload();await idle();} finally {page.off('dialog',discard);}
    assert.deepEqual(await state(),final);assert.deepEqual(fs.readFileSync(draftFile),finalBytes);
  }
  assert.equal(report.writes.length-start,8);assert.deepEqual(report.errors,[]);
  report.identity_cycle={partial_rename_refused:true,explicit_four_registry_rename:true,arithmetic_unchanged:true,
    new_ids_in_review:true,deleted_row_renumbered:true,stale_address_revoked:true,no_cascade:true,incomplete_after_delete:true,
    all_four_editors_delete_without_write:true,neighbor_and_empty_focus:true};
  console.log('PASS: partial rename refused, explicit four-registry rename, refreshed IDs, row deletion/renumbering, stale address revocation and incomplete recalculated result.');
};
