/* Run only against an isolated local server with temporary Studio storage. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8768';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base + '/studio?view=project');
    const headers = {'X-Zarya-Studio':'1'};
    let state = await (await page.request.post(base + '/studio/api/draft', {headers})).json();
    const calculation = await page.request.post(base + '/studio/api/calculate', {headers,data:{revision:state.revision,answers:{
      residents:20,apartments:8,consumer_code:'residential_full_bath',floors:2,
      building_height_m:6.6,fire_height_m:4.8,hws_type:'central',inputs_count:2,
      guaranteed_head_m:5,h_geom_m:6,pressure_loss_mode:'ready',h_il_m:3,h_vvod_m:1,
      t3_loss_mode:'ready',h_il_hot_m:4,hws_heater_in_scope:'no'
    }}});
    assert.equal(calculation.status(),200);
    await page.reload();
    await page.getByText('Проверка всасывания · необязательно сейчас',{exact:true}).click();
    await page.locator('[data-action="suction-check"]').click();
    const dialog = page.locator('#suction-dialog');
    await dialog.locator('[data-route]').waitFor();
    assert.equal(await dialog.locator('[data-balance="max_flow_m3h"]').inputValue(),'');
    assert.equal(await dialog.locator('[data-balance="safety_margin_m"]').inputValue(),'0.5');
    await dialog.locator('[data-route]').selectOption({index:1});
    await dialog.locator('[data-path-basis]').fill('Синтетический тест явного последовательного режима');
    await dialog.getByText('Давление, отметки и паспортные данные',{exact:true}).click();
    await dialog.locator('[data-balance="pressure_kind"]').selectOption('absolute');
    for (const [key,value] of Object.entries({pressure_bar:'1',source_elevation_m:'0',pump_elevation_m:'2',
      vapor_head_m:'0,2',max_flow_m3h:'12',temperature_c:'10',npshr_m:'6',basis:'Синтетические исходные',npshr_basis:'Тест при 12 м³/ч'})) {
      await dialog.locator(`[data-balance="${key}"]`).fill(value);
    }
    await dialog.locator('[data-add-loss]').click();
    await dialog.getByText('Состав результата · отметить учтённые элементы и соединения',{exact:true}).click();
    for (const checkbox of await dialog.locator('[data-cover]').all()) await checkbox.check();
    for (const [key,value] of Object.entries({loss_m:'1',flow_m3h:'12',temperature_c:'10',basis:'Тест готового полного результата'})) {
      await dialog.locator(`[data-loss-field="${key}"]`).fill(value);
    }
    await dialog.getByRole('button',{name:'Сохранить и проверить'}).click();
    await dialog.getByText('Запас выполнен в заданном режиме',{exact:true}).waitFor();
    assert((await dialog.locator('[data-suction-result]').innerText()).includes('NPSHa: 7 м'));
    fs.mkdirSync('output/ui/studio-suction',{recursive:true});
    await page.screenshot({path:'output/ui/studio-suction/desktop.png'});
    await page.setViewportSize({width:390,height:844});
    assert(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    await dialog.evaluate(el => {el.scrollTop = 0;});
    await page.screenshot({path:'output/ui/studio-suction/mobile.png'});
    await dialog.locator('[data-balance="max_flow_m3h"]').fill('13');
    assert(!(await dialog.locator('[data-suction-result]').innerText()).includes('Запас выполнен'));
    await dialog.getByRole('button',{name:'Сохранить и проверить'}).click();
    await dialog.getByText('Нужны данные',{exact:true}).waitFor();
    await dialog.locator('[data-suction-close]').last().click();
    await page.reload();
    await page.getByText('Проверка всасывания · необязательно сейчас',{exact:true}).click();
    await page.locator('[data-action="suction-check"]').click();
    await dialog.getByText('Нужны данные',{exact:true}).waitFor();
    assert.equal(await dialog.locator('[data-balance="max_flow_m3h"]').inputValue(),'13');
    await dialog.locator('[data-suction-close]').last().click();
    state = await (await page.request.get(base + '/studio/api/draft')).json();
    const answer = await page.request.patch(base + '/studio/api/answer', {headers,data:{revision:state.revision,field:'h_vvod_m',value:2}});
    assert.equal(answer.status(),200);
    await page.locator('[data-action="suction-check"]').click();
    await dialog.locator('[data-reviewed]').waitFor();
    assert((await dialog.locator('[data-suction-result]').innerText()).includes('устарела'));
    await dialog.getByRole('button',{name:'Сохранить и проверить'}).click();
    await page.waitForFunction(() => document.querySelector('[data-suction-error]').textContent.includes('перепроверьте'));
    await dialog.locator('[data-reviewed]').check();
    await dialog.getByRole('button',{name:'Сохранить и проверить'}).click();
    await dialog.getByText('Нужны данные',{exact:true}).waitFor();
    await page.screenshot({path:'output/ui/studio-suction/incomplete.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('Studio suction: save/reload, mode mismatch, stale inputs and mobile checked.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
