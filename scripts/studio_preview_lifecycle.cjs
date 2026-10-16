// Genuine private PDF builds and explicit UI changes, never a release or renderer stub.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const hash=b=>createHash('sha256').update(b).digest('hex');
module.exports=async({page,context,state,idle,root,report,initial})=>{
  const values=d=>Object.fromEntries(d.fields.map(r=>[r.key,r.value]));
  const base=values(initial),old=base.sewage_risers[1].riser_id,next='К1-Новый-ID';
  const expected=JSON.parse(JSON.stringify(base));
  const draftFile=path.join(root,'studio',initial.project_id,'draft.json');
  const editor=key=>page.locator('#clarification-body [data-input="'+key+'"]');
  const input=(key,index,field)=>editor(key).locator('.route-row').nth(index).locator('[data-column="'+field+'"]');
  const reveal=async control=>{
    const parents=control.locator('xpath=ancestor::details');
    for(let i=0;i<await parents.count();i++)if(await parents.nth(i).getAttribute('open')===null)
      await parents.nth(i).locator(':scope > summary').click();
  };
  const open=()=>page.locator('[data-config="connection"]').click();
  const submit=async()=>{
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/answers')&&r.request().method()==='PATCH');
    await page.locator('[data-config-form] button[type="submit"]').click();
    const response=await pending;await idle();return response;
  };
  const calculate=async()=>{
    await page.waitForFunction(()=>document.querySelector('#next-title')?.textContent==='Потребители');
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/calculate')&&r.request().method()==='POST');
    await page.locator('[data-config-form] button[type="submit"]').click();
    const response=await pending;assert.equal(response.status(),200,await response.text());await idle();return response.json();
  };
  const capture=async(saved,stage)=>{
    assert.equal(saved.preview.state,'preview');assert.equal(saved.project_calculation.can_release,false);
    const folder=path.join(root,'studio',saved.project_id,'previews',saved.preview.id);
    const documents=[];
    for(const doc of saved.preview.documents) {
      const url='/studio/api/preview/'+saved.preview.id+'/files/'+encodeURIComponent(doc.name);
      const response=await context.request.get(url);assert.equal(response.status(),200,url);
      assert.equal(response.headers()['x-zarya-preview'],'true');assert.equal(response.headers()['cache-control'],'private, no-store');
      const file=path.join(folder,doc.name),bytes=fs.readFileSync(file);
      assert.equal(hash(await response.body()),hash(bytes));assert(bytes.subarray(0,5).equals(Buffer.from('%PDF-')));
      documents.push({...doc,url,path:file,sha256:hash(bytes)});
    }
    for(const kind of ['wastewater_pz_pdf','wastewater_balance_pdf','wastewater_scheme_pdf','wastewater_package_pdf'])
      assert(documents.some(doc=>doc.kind===kind),kind);
    const entry={stage,id:saved.preview.id,revision:saved.revision,documents,
      gost_blockers:saved.project_calculation.gost_blockers,scheme:saved.project_calculation.sewer_scheme};
    report.lifecycle.push(entry);return entry;
  };
  const revoked=async entry=>{
    const before=fs.readFileSync(draftFile);
    for(const doc of entry.documents) {
      assert.equal((await context.request.get(doc.url)).status(),404,doc.url);
      assert.equal(hash(fs.readFileSync(doc.path)),doc.sha256); // revoke access, retain historical bytes
      assert.equal(await page.locator('a[href="'+doc.url+'"]').count(),0);
    }
    assert.deepEqual(fs.readFileSync(draftFile),before); // GET must not rewrite the draft
  };
  const build=async()=>{
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST',{timeout:120000});
    await page.locator('[data-action="documents"][data-view="ios3"]').click();
    const response=await pending;assert.equal(response.status(),200,await response.text());await idle();return state();
  };
  report.lifecycle=[];
  const first=await capture(initial,'initial');
  await page.setViewportSize({width:1440,height:1000});await open();
  for(const [key,fields] of [['sewer_pipes',['section_id','from_node','to_node']],['sewer_elements',['section_id','connects_to']],['sewage_risers',['riser_id']]]) {
    for(const [i,row] of base[key].entries())for(const field of fields)if(row[field]===old) {
      await reveal(input(key,i,field));await input(key,i,field).fill(next);expected[key][i][field]=next;
    }
  }
  for(const [i,row] of base.wastewater_fan_ventilation.terminals.entries())if(row.riser_ids.includes(old)) {
    const changed=row.riser_ids.map(id=>id===old?next:id);
    await reveal(input('wastewater_fan_ventilation',i,'riser_ids'));await input('wastewater_fan_ventilation',i,'riser_ids').fill(changed.join('\n'));
    expected.wastewater_fan_ventilation.terminals[i].riser_ids=changed;
  }
  assert.equal(await page.locator('.document-selection').isVisible(),false);
  const savedResponse=await submit();assert.equal(savedResponse.status(),200,await savedResponse.text());
  const saved=await savedResponse.json();assert.deepEqual(values(saved),expected);assert.equal(saved.preview,null);
  await revoked(first);
  const recalculated=await calculate();assert.deepEqual(values(recalculated),expected);assert.equal(recalculated.preview,null);
  await revoked(first);
  const renamed=await build();assert.deepEqual(values(renamed),expected);assert.notEqual(renamed.preview.id,first.id);
  const second=await capture(renamed,'renamed');
  assert.equal(second.documents.find(d=>d.kind==='wastewater_scheme_pdf').state,'ready');
  assert.notEqual(second.documents.find(d=>d.kind==='wastewater_scheme_pdf').sha256,first.documents.find(d=>d.kind==='wastewater_scheme_pdf').sha256);
  await revoked(first);
  await open();const remove=editor('sewage_risers').locator('.route-row').nth(1).locator('[data-action="remove-section"]');
  await reveal(remove);await remove.click();
  const removedResponse=await submit();assert.equal(removedResponse.status(),200,await removedResponse.text());
  const removed=await removedResponse.json();expected.sewage_risers=expected.sewage_risers.slice(0,1);
  assert.deepEqual(values(removed),expected);assert.equal(removed.preview,null);await revoked(second);
  const incomplete=await calculate();assert.equal(incomplete.project_calculation.sewer_scheme.ready,false);
  assert.equal(incomplete.project_calculation.can_release,false);await revoked(second);
  const rebuilt=await build();assert.deepEqual(values(rebuilt),expected);
  const third=await capture(rebuilt,'incomplete');assert.notEqual(third.id,second.id);
  for(const kind of ['wastewater_scheme_pdf','wastewater_package_pdf']) {
    const doc=third.documents.find(d=>d.kind===kind);
    assert.equal(doc.state,'incomplete');assert(doc.state_note);
  }
  assert.equal(rebuilt.project_calculation.sewer_scheme.ready,false);
  assert(await page.locator('[data-action="package"]').isDisabled());
  const selection=page.locator('.document-selection');assert.match(await selection.innerText(),/Неполный документ/);
  for(const [label,size] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
    await page.setViewportSize(size);await selection.scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(root,'lifecycle-incomplete-'+label+'.png')});
  }
  await revoked(first);await revoked(second);
  const bytes=fs.readFileSync(draftFile);await page.reload();await idle();
  assert.equal((await state()).preview.id,third.id);assert.deepEqual(fs.readFileSync(draftFile),bytes);
  await page.locator('[data-action="documents"][data-view="ios3"]').click();
  assert.equal(report.previewPosts,3);assert.match(await selection.innerText(),/Неполный документ/);
  assert.equal((await state()).project_calculation.can_release,false);
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.consoleErrors,[]);
  console.log('PASS: three real preview builds, all historical URLs revoked after saves/rebuilds, archived bytes retained, incomplete replacement and release blocked.');
  return {values,expected,restoreRow:values(renamed).sewage_risers[1],draftFile,editor,input,reveal,open,submit,calculate,capture,revoked,build};
};
