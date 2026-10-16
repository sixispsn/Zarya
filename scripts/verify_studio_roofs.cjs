/* Roof profiles, legacy placeholders and fixed-study safety; isolated cookie. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
const out=path.resolve('output/studio-preview/screenshots');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const idle=()=>page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
  const state=async()=>await (await page.request.get(base+'/studio/api/draft')).json();
  await page.goto(base+'/studio'); await idle();
  await page.getByRole('button',{name:'Начать без документов'}).click();
  await page.locator('#field-roof_type').waitFor();
  const choices=['single_slope','gable','complex','flat_accessible','flat_non_accessible'];
  assert.deepEqual(await page.locator('#field-roof_type option').evaluateAll(items=>items.map(i=>i.value)),['',...choices]);
  assert.equal(await page.locator('#field-roof_type').inputValue(),'flat_non_accessible');
  await page.locator('#field-residents').fill('20');
  for(const choice of choices) {
   await page.locator('#field-roof_type').selectOption(choice);
   assert.match(await page.locator('#field-roof_type-hint').innerText(),choice==='complex'?/нужны участки/:choice==='flat_accessible'?/минимум 3 м/:/минимум 0,2 м/);
   assert.equal(await page.locator('#field-roof_type-profile [data-roof-profile]').getAttribute('data-roof-profile'),choice);
   await page.locator('[data-action="calculate"]').click(); await idle();
   assert.equal((await state()).fields.find(f=>f.key==='roof_type').value,choice);
   await page.locator('#setup-details > summary').click();
  }
  await page.screenshot({path:out+'/roof-choices-desktop.png',fullPage:true});
  // An old generic flat roof must not turn into a precise choice on page load.
  for(const oldValue of ['flat','sloped']) {
   const draft=await state();
   const legacy=await page.request.patch(base+'/studio/api/answer',{headers:{'X-Zarya-Studio':'1'},data:{revision:draft.revision,field:'roof_type',value:oldValue}});
   assert.equal(legacy.status(),200);
   await page.reload(); await idle();
   if(await page.locator('#setup-details').count()) await page.locator('#setup-details > summary').click();
   assert.equal(await page.locator('#field-roof_type').inputValue(),'');
   assert.equal(await page.locator('#field-roof_type option[value="flat"], #field-roof_type option[value="sloped"]').count(),0);
   assert.match(await page.locator('#field-roof_type-hint').innerText(),/Уточните|Ранее указана/);
   await page.locator('#field-residents').fill('21');
   await page.locator('[data-action="calculate"]').click(); await idle();
   assert.equal((await state()).fields.find(f=>f.key==='roof_type').value,oldValue);
   await page.locator('#setup-details > summary').click();
  }
  await page.locator('#field-roof_type').selectOption('gable');
  await page.setViewportSize({width:320,height:950});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:out+'/roof-choices-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Попробовать на примере →'}).filter({visible:true}).click();
  await page.locator('[data-kind="two"]').click(); await idle();
  assert.equal(await page.locator('#field-roof_type').inputValue(),'flat_non_accessible');
  await page.locator('#field-roof_type').selectOption('gable');
  await page.locator('[data-action="calculate"]').click(); await idle();
  assert(await page.locator('.delivery .field-error').isVisible());
  assert.match(await page.locator('.delivery .field-error').innerText(),/новая геометрия/);
  assert(await page.getByRole('button',{name:'Схема К1 + К2'}).isDisabled());
  await page.locator('#field-roof_type').selectOption('flat_non_accessible');
  await page.locator('[data-action="calculate"]').click(); await idle();
  assert(await page.getByRole('button',{name:'Схема К1 + К2'}).isEnabled());
  const editor=await browser.newPage({viewport:{width:1280,height:1000}});
  editor.on('pageerror',e=>errors.push(String(e)));
  await editor.goto(base+'/wizard');
  await editor.locator('[name="wastewater_roof_kind"]').evaluate(el=>{
   let ancestor=el.parentElement;
   while(ancestor) {if(ancestor.tagName==='DETAILS') ancestor.open=true; ancestor=ancestor.parentElement;}
  });
  let lastPath;
  for(const choice of choices) {
   await editor.locator('[name="wastewater_roof_kind"]').selectOption(choice);
   const preview=editor.locator('[data-roof-profile-control] [data-roof-profile]');
   assert.equal(await preview.getAttribute('data-roof-profile'),choice);
   const drawing=await preview.locator('path').getAttribute('d');
   assert.notEqual(drawing,lastPath); lastPath=drawing;
   if(choice==='complex') {
    assert(await editor.locator('#wizard-roof-note').isVisible());
    assert.equal(await editor.locator('[data-completeness-for="wastewater_roof_kind"]').evaluate(el=>el.classList.contains('is-complete')),false);
   }
  }
  await editor.locator('[name="wastewater_roof_kind"]').selectOption('gable');
  await editor.locator('.roof-control-group').screenshot({path:out+'/roof-editor-gable.png'});
  assert.deepEqual(errors,[]);
  console.log('PASS: five profiles, no legacy options, old values preserved on unrelated saves, complex roof pending, Studio/full-editor silhouettes, 320px layout, study guards');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
