/* Run only against the isolated local preview, never a production project store. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.STUDIO_URL || 'http://127.0.0.1:8766';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname), 'Local preview only');
const out = path.resolve('output/studio-preview/site');
fs.mkdirSync(out, {recursive:true});

(async () => {
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1050}});
    // The new white shell must not accidentally inherit the former dark setting.
    await context.addInitScript(() => localStorage.setItem('zarya-theme','dark'));
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto(base + '/');
    assert.equal(new URL(page.url()).pathname, '/studio');
    await page.waitForFunction(() => document.querySelector('#studio')?.getAttribute('aria-busy') === 'false');
    await page.waitForTimeout(1100);
    assert.equal(await page.locator('.site-nav > a').count(), 2);
    assert.equal(await page.locator('.site-tools').getAttribute('open'), null);
    await page.screenshot({path:out+'/01-home.png',fullPage:true});
    await page.locator('.site-tools summary').click();
    await page.locator('[data-site-radar]').waitFor();
    assert.equal(await page.locator('[data-studio-handoff]').count(),0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.site-tools').getAttribute('open'), null);
    await page.getByRole('button',{name:'Начать без документов'}).click();
    assert.equal(await page.locator('#field-consumer_code').inputValue(),'residential_full_bath');
    assert.equal(await page.locator('#field-roof_type').inputValue(),'flat_non_accessible');
    assert.equal(await page.locator('#field-hws_type').inputValue(),'central');
    assert.equal(await page.locator('#manual-entry').getAttribute('open'),null);
    assert.equal(await page.locator('#field-sewage_max_fixture_lps').isVisible(),false);
    await page.screenshot({path:out+'/quick-start.png',fullPage:true});
    await page.locator('#field-residents').fill('20');
    await page.locator('#field-residents').press('Enter');
    await page.locator('#calculation-title').waitFor();
    assert.equal(await page.locator('.flow-table tbody tr').first().locator('td').last().textContent(),'3,6');
    const before = await (await page.request.get(base+'/studio/api/draft')).json();
    await page.getByRole('link',{name:'Мои проекты',exact:true}).click();
    await page.locator('.library-current').waitFor();
    await page.screenshot({path:out+'/02-projects.png',fullPage:true});
    await page.getByRole('link',{name:'Продолжить →',exact:true}).click();
    await page.locator('#calculation-title').waitFor();
    const after = await (await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(before.revision,after.revision);
    assert.deepEqual(before.calculation,after.calculation);
    await page.screenshot({path:out+'/03-workspace.png',fullPage:true});
    // Logo goes home, not into a restored form. Resume is explicit and read-only.
    await page.locator('.site-brand').click();
    await page.waitForFunction(() => document.querySelector('#studio')?.getAttribute('aria-busy') === 'false');
    assert.equal(await page.locator('#entry').isVisible(),true);
    assert.equal(await page.locator('#workspace').isVisible(),false);
    await page.reload();
    await page.locator('#resume-project').waitFor();
    assert.equal(await page.locator('#workspace').isVisible(),false);
    await page.locator('[data-action="resume"]').click();
    await page.locator('#calculation-title').waitFor();
    const resumed=await (await page.request.get(base+'/studio/api/draft')).json();
    assert.equal(resumed.revision,before.revision);
    assert.deepEqual(resumed.calculation,before.calculation);
    const pages = [
      ['/wizard','04-editor'], ['/wizard/building-model','05-building'],
      ['/wizard/architecture','06-plans'], ['/wizard/analyze','07-analysis'],
      ['/wizard/normatives','08-normatives'],
    ];
    for (const [url,name] of pages) {
      const response = await page.goto(base+url);
      assert.equal(response.status(),200,url);
      assert.equal(await page.locator('.site-header').count(),1);
      assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor),'rgb(255, 255, 255)',url);
      await page.screenshot({path:out+'/'+name+'.png',fullPage:true});
    }
    for (const width of [320,768]) {
      await page.setViewportSize({width,height:950});
      for (const url of ['/studio','/studio?view=project','/studio/projects',...pages.map(row=>row[0])]) {
        await page.goto(base+url);
        if (url==='/studio?view=project') await page.locator('#calculation-title').waitFor();
        const geometry = await page.evaluate(() => ({width:innerWidth,scroll:document.documentElement.scrollWidth}));
        assert(geometry.scroll<=geometry.width, url+' @'+width+': '+JSON.stringify(geometry));
        await page.locator('.site-tools summary').click();
        const menu = await page.locator('.site-tools-panel').boundingBox();
        assert(menu.x>=0 && menu.x+menu.width<=width, 'menu outside viewport');
        await page.keyboard.press('Escape');
        if (width===320) await page.screenshot({path:out+'/mobile-'+url.split('/').pop()+'.png',fullPage:true});
      }
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({result:'PASS',checks:['stable home and logo','explicit resume','20 residents calculation','draft survives navigation','no editor handoff','archive retained','white despite old preference','320/768/1440px']},null,2));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
