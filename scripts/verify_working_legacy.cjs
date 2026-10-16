// Isolated standalone-browser smoke test; never touches production/projects.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.stack || e.message));
    await page.goto('file://' + path.resolve('legacy/sp30_calculator.html'));
    assert.equal(await page.evaluate(() => getAlpha(63)), 17.39);
    const last = await page.evaluate(() => interpH(PUMP_CURVES[0].curve, PUMP_CURVES[0].curve.at(-1).q));
    assert.equal(last, await page.evaluate(() => PUMP_CURVES[0].curve.at(-1).h));
    await page.evaluate(() => {
      document.getElementById('k06_check').checked = true;
      calculate();
    });
    assert.equal(await page.locator('#err').innerText(), '');
    await page.evaluate(() => {
      for (const [id, value] of Object.entries({m_gvs_type:'central',m_T:24,m_q_sec_c:120,m_q_day_c:9600,m_q_hr_c:432}))
        document.getElementById(id).value = String(value);
      calcMeters();
    });
    assert.match(await page.locator('#meters_result').innerText(), /Нет подходящего водомера/);
    assert.doesNotMatch(await page.locator('#meters_result').innerText(), /Принят:|Кандидат;/);
    await page.evaluate(() => {
      document.getElementById('m_q_day_c').value = '9120';
      calcMeters();
    });
    assert.match(await page.locator('#meters_result').innerText(), /Нужны паспорт/);
    await page.evaluate(() => {
      for (const [key,value] of Object.entries({dn:250,flow:20,passport:15,source:'TEST ONLY',basis:'TEST ONLY'}))
        document.getElementById('minimum_cold_' + key).value = String(value);
      calcMeters();
    });
    assert.match(await page.locator('#meters_result').innerText(), /измеряет минимальные расходы/);
    await page.evaluate(() => {
      document.getElementById('h_losses').value = '';
      calcPumpHead();
    });
    assert.equal(await page.locator('#hp_result').innerText(), 'Нужны данные');
    // L08: empty and zero are distinct; invalid input cannot retain selection.
    assert.equal(await page.locator('#npsh_a').inputValue(), '');
    await page.evaluate(() => {
      document.querySelector('input[name="hgeom_mode"][value="manual"]').checked = true;
      for (const [id,value] of Object.entries({h_geom_manual:25,h_losses:5,h_pr:20,h_gar:20,q_design:5}))
        document.getElementById(id).value = String(value);
      calcPumpHead();
    });
    assert.match(await page.locator('#pump_rec_result').innerText(), /NPSHa не задан/);
    await page.fill('#npsh_a', '0');
    assert.match(await page.locator('#pump_rec_result').innerText(), /NPSHa=0м/);
    await page.fill('#npsh_a', '-1');
    assert.match(await page.locator('#pump_rec_result').innerText(), /неотрицательным/);
    assert.equal(await page.locator('#pump_chart polyline').count(), 0);
    await page.fill('#npsh_a', '');
    const balance = page.locator('details').filter({has:page.locator('#npsha_balance_result')});
    await balance.locator('summary').click();
    await page.selectOption('[data-npsha-field="pressure_kind"]', 'absolute');
    for (const [key,value] of Object.entries({pressure_bar:1,source_elevation_m:0,pump_elevation_m:2,
      suction_losses_m:1,vapor_head_m:.2,max_flow_m3h:12,temperature_c:20,npshr_m:2,
      basis:'Контрольная арифметика, не проектные значения',npshr_basis:'Контроль: 2 м при Qmax=12'}))
      await page.fill(`[data-npsha-field="${key}"]`, String(value));
    assert.match(await page.locator('#npsha_balance_result').innerText(), /NPSHa = 7.000 м/);
    assert.match(await page.locator('#npsha_balance_result').innerText(), /выполнено/);
    assert.equal(await page.locator('#npsh_a').inputValue(), ''); // no implicit transfer
    await page.selectOption('[data-npsha-field="pressure_kind"]', 'gauge');
    assert.match(await page.locator('#npsha_balance_result').innerText(), /Нужны данные/);
    await page.fill('[data-npsha-field="pressure_bar"]', '0');
    await page.fill('[data-npsha-field="atmospheric_pressure_bar"]', '1');
    assert.match(await page.locator('#npsha_balance_result').innerText(), /NPSHa = 7.000 м/);
    if (process.env.NPSHA_SCREENSHOT) await balance.screenshot({path:process.env.NPSHA_SCREENSHOT});
    await page.fill('[data-npsha-field="suction_losses_m"]', '');
    assert.match(await page.locator('#npsha_balance_result').innerText(), /Нужны данные/);
    assert.doesNotMatch(await page.locator('#npsha_balance_result').innerText(), /выполнено/);
    await page.fill('[data-npsha-field="suction_losses_m"]', '-1');
    assert.match(await page.locator('#npsha_balance_result').innerText(), /отрицательным/);
    await balance.locator('summary').click();
    await page.fill('#h_losses', ''); // keep original L07 setup
    await page.selectOption('#pump_sel_type', 'circ');
    assert.equal(await page.locator('#boost_head_inputs').isVisible(), false);
    assert.equal(await page.locator('#boost_q_inputs').isVisible(), false);
    assert.equal(await page.locator('#circ_inputs').isVisible(), true);
    assert.equal(await page.locator('#circ_q').inputValue(), '');
    assert.equal(await page.locator('#circ_head').inputValue(), '');
    assert.equal(await page.locator('#circ_npsh').inputValue(), '');
    assert.equal(await page.locator('#hp_result').innerText(), 'Нужны данные Т4');
    await page.fill('#circ_q', '1.8');
    await page.fill('#circ_head', '5');
    await page.fill('#circ_basis', 'ТЕСТ: потери кольца <img src=x onerror=alert(1)>');
    assert.equal(await page.locator('#hp_result').innerText(), '5.00 м');
    assert.match(await page.locator('#pump_rec_result').innerText(), /Hкат\(Qрасч\) = 8.060/);
    assert.match(await page.locator('#pump_rec_result').innerText(), /NPSH: нет данных/);
    assert.equal(await page.locator('#pump_rec_result img').count(), 0);
    assert.equal(await page.locator('#pump_chart polyline').count(), 1);
    assert.equal(await page.locator('#pump_chart [data-role="required-duty"]').count(), 1);
    const result = await page.locator('#pump_rec_result').innerText();
    await page.evaluate(() => {
      for (const [id, value] of Object.entries({h_geom_manual:46, h_gar:100, h_pr:90}))
        document.getElementById(id).value = String(value);
      calcPumpHead();
    });
    assert.equal(await page.locator('#pump_rec_result').innerText(), result);
    await page.fill('#circ_basis', '');
    assert.equal(await page.locator('#hp_result').innerText(), 'Нужны данные Т4');
    assert.doesNotMatch(await page.locator('#pump_rec_result').innerText(), /MAGNA3/);
    assert.equal(await page.locator('#pump_chart polyline').count(), 0);
    await page.fill('#circ_basis', 'ТЕСТ: кольцо, тепловой и гидравлический расчёт');
    await page.fill('#circ_q', '20');
    assert.match(await page.locator('#pump_rec_result').innerText(), /Нет подходящего кандидата/);
    assert.equal(await page.locator('#pump_chart polyline').count(), 0);
    await page.fill('#circ_q', '1.8');
    if (process.env.CIRCULATION_SCREENSHOT) {
      await page.locator('#circ_inputs').locator('xpath=ancestor::div[contains(@class,"card")]').screenshot({
        path: process.env.CIRCULATION_SCREENSHOT,
      });
    }
    await page.selectOption('#pump_sel_type', 'boost');
    assert.equal(await page.locator('#boost_head_inputs').isVisible(), true);
    assert.equal(await page.locator('#circ_inputs').isVisible(), false);
    assert.equal(await page.locator('#hp_result').innerText(), 'Нужны данные');
    assert.deepEqual(errors, []);
    console.log('PASS: standalone working HTML; L01–L05, L07, L08/NPSHa and meter minimum, no browser errors');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
