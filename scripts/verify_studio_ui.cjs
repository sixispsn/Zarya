/* Run against an isolated, enabled local studio. See docs/studio_preview.md. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname),'Local preview only');
const out = path.resolve('output/studio-preview/screenshots');
fs.mkdirSync(out,{recursive:true});

(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:1000}});
    const errors=[];
    page.on('pageerror',error=>errors.push(String(error)));
    await page.goto(base+'/studio');
    await page.getByRole('button',{name:'Начать без документов'}).waitFor();
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    await page.waitForTimeout(1700);
    await page.screenshot({path:out+'/01-start.png',fullPage:true});
    const pdf=execFileSync('venv/bin/python',['-c',
      'import sys; from weasyprint import HTML; sys.stdout.buffer.write(HTML(string="<html><meta charset=utf-8><body><h1>ТЗ и ТУ — тест интерфейса</h1><p>Число жителей: 20.</p><p>Этажность: 2.</p><p>Количество квартир: 8.</p><p>Общая высота здания: 6,6 м.</p><p>Пожарно-техническая высота: 4,8 м.</p><p>Гарантированный напор: 5 м.</p></body></html>").write_pdf())']);
    await page.locator('#file-input').setInputFiles({name:'Исходные.pdf',mimeType:'application/pdf',buffer:pdf});
    await page.locator('#field-residents').waitFor();
    assert.equal(await page.locator('#field-residents').inputValue(),'20');
    await page.locator('[data-input="residents"] .source-details summary').click();
    assert(await page.getByRole('link',{name:'Исходные.pdf · стр. 1 ↗',exact:true}).isVisible());
    const [sourcePage] = await Promise.all([
      page.waitForEvent('popup'),
      page.getByRole('link',{name:'Исходные.pdf · стр. 1 ↗',exact:true}).click()
    ]);
    await sourcePage.waitForLoadState('load');
    await sourcePage.waitForTimeout(1000);
    await sourcePage.screenshot({path:out+'/04-source-document.png'});
    await sourcePage.close();
    assert.equal(await page.locator('#field-consumer_code').inputValue(),'residential_full_bath');
    assert.equal(await page.locator('.widget[aria-label="Канализация"]').count(),0);
    await page.locator('[data-action="calculate"]').click();
    await page.locator('#calculation-title').waitFor();
    assert.equal(await page.locator('.flow-table tbody tr').first().locator('td').last().textContent(),'3,6');
    await page.screenshot({path:out+'/02-calculated.png',fullPage:true});
    assert.equal(await page.locator('#setup-details').getAttribute('open'),null);
    assert.equal(await page.locator('#calculation-details').getAttribute('open'),null);
    assert(await page.getByRole('button',{name:/Скачать комплект/}).isDisabled());
    assert.equal(await page.locator('#next-title').innerText(),'Напор: ввод и диктующий прибор');
    for (const [key,value] of Object.entries({h_geom_m:'6',hws_heater_in_scope:'no'})) {
      const input=page.locator('#next-'+key); await input.waitFor();
      if(key==='hws_heater_in_scope') await input.selectOption(value); else await input.fill(value);
    }
    await page.getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.locator('#next-pressure_loss_mode').selectOption('ready');
    await page.locator('#next-h_il_m').waitFor();
    for(const [key,value] of Object.entries({h_il_m:'3',h_vvod_m:'1',h_apartment_c_meter_m:'0.5',h_apartment_h_meter_m:'0.5'})) {
      await page.locator('#next-'+key).fill(value);
    }
    await page.getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.locator('#next-storm_city').waitFor();
    // Stored roof choice is not asked again. Losses are explicit QA values, not defaults.
    assert.equal(await page.locator('#next-roof_type').count(),0);
    await page.locator('#next-storm_city').selectOption('moscow');
    await page.locator('#next-storm_roof_area_m2').fill('252');
    await page.locator('#next-storm_walls_area_m2').fill('0');
    await page.getByRole('button',{name:'Продолжить',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#studio').getAttribute('aria-busy')==='false');
    await page.locator('#calculation-details > summary').click();
    assert(await page.getByText(/Hтр = 33,19/).isVisible());
    assert(await page.getByText('Q = 5,395 л/с',{exact:true}).isVisible());
    assert(await page.getByText(/ВПВ не требуется/).isVisible());
    await page.locator('#calculation-details > summary').click();
    await page.screenshot({path:out+'/05-project-calculated.png',fullPage:true});
    assert(await page.getByRole('button',{name:/Скачать комплект/}).isDisabled());
    await page.getByRole('button',{name:/Открыть ПЗ/}).click();
    await page.locator('#calculation .document-list a').first().waitFor({timeout:90000,state:'attached'});
    assert.equal(new URL(page.url()).pathname,'/studio');
    const state=await (await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(state.preview.state,'preview');
    assert.equal(state.package,null);
    assert(await page.locator('.document-selection').getByRole('link',{name:'Пояснительная записка ИОС3 ↗',exact:true}).isVisible());
    assert.equal(await page.request.get(base+'/studio/api/package/'+state.preview.id+'/download').then(r=>r.status()),404);
    await page.getByRole('button',{name:/Посмотреть схему/}).click();
    assert(await page.locator('.document-selection').getByText(/Каркас: нужны стояки/).isVisible());
    await page.screenshot({path:out+'/06-documents.png',fullPage:true});
    const doc=state.preview.documents.find(doc=>doc.label==='Расчётные обоснования В1 и Т3') || state.preview.documents[0];
    const documentResponse=await page.request.get(base+'/studio/api/preview/'+state.preview.id+'/files/'+encodeURIComponent(doc.name));
    assert.equal(documentResponse.status(),200);
    const documentBuffer=await documentResponse.body();
    assert.equal(documentBuffer.subarray(0,5).toString(),'%PDF-');
    fs.writeFileSync(path.resolve('output/studio-preview/verification-calculation.pdf'),documentBuffer);
    console.log(JSON.stringify({preview:state.preview,qaPdf:'output/studio-preview/verification-calculation.pdf'}));
    await page.goto(base+'/studio?view=project');
    await page.locator('#calculation-title').waitFor();
    assert.equal(await page.locator('.flow-table tbody tr').first().locator('td').last().textContent(),'3,6');
    const mobile=await browser.newPage({viewport:{width:320,height:950},reducedMotion:'reduce'});
    mobile.on('pageerror',error=>errors.push(String(error)));
    await mobile.goto(base+'/studio');
    await mobile.getByRole('button',{name:'Начать без документов'}).click();
    await mobile.locator('#field-residents').fill('500');
    await mobile.locator('#field-residents').press('Enter');
    assert.equal(await mobile.locator('#field-sewage_max_fixture_lps').isVisible(),false);
    await mobile.locator('#calculation-title').waitFor();
    assert.equal(await mobile.locator('.flow-table tbody tr').first().locator('td').last().textContent(),'90');
    assert.equal(await mobile.locator('#next-title').innerText(),'Параметры здания');
    // Choose a different next task, without pretending that head or building data is ready.
    await mobile.locator('[data-step="storm"]').click();
    await mobile.locator('#next-storm_city').selectOption('moscow');
    await mobile.locator('#next-storm_roof_area_m2').fill('252');
    await mobile.locator('#next-storm_walls_area_m2').fill('0');
    await mobile.getByRole('button',{name:'Продолжить',exact:true}).click();
    await mobile.locator('#next-floors').waitFor();
    assert(await mobile.getByRole('button',{name:/Открыть ПЗ/}).isDisabled());
    await mobile.reload();
    await mobile.locator('#next-floors').waitFor();
    const saved=await (await mobile.request.get(base+'/studio/api/draft')).json();
    assert.equal(saved.fields.find(row=>row.key==='storm_roof_area_m2').value,252);
    assert.equal(saved.fields.find(row=>row.key==='guaranteed_head_m').value,null);
    const geometry=await mobile.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(geometry.scroll<=geometry.width,JSON.stringify(geometry));
    await mobile.screenshot({path:out+'/03-mobile.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',checks:['upload with evidence','default 1.6 without question','real demand 20 residents','full project pipeline','head and storm','private PDF without leaving studio','reload','320px','500 residents = 90 m3/day'],geometry},null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
