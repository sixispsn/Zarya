// Own loopback server + mkdtemp only. No external URL or existing project accepted.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const {spawn, execFileSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const {setTimeout: delay} = require('node:timers/promises');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'zarya-file-smoke-'));
const server = spawn(path.resolve('venv/bin/python'), ['-m', 'scripts.studio_file_smoke_server', root],
  {stdio:['ignore','pipe','pipe']});
let serverLog = '';
for (const stream of [server.stdout, server.stderr]) stream.on('data', chunk => {serverLog += chunk;});

(async () => {
  let browser;
  const result = {root, cases:[], errors:[], scope:'UI/transport; synthetic saved state, not PDF or engineering approval'};
  try {
    const manifestPath = path.join(root, 'fixture.json');
    for(let i=0; i<200 && !fs.existsSync(manifestPath); i++) {
      if(server.exitCode !== null) throw Error(serverLog);
      await delay(100);
    }
    const fixture = JSON.parse(fs.readFileSync(manifestPath));
    const base = fixture.base_url;
    for(let i=0;i<100;i++) {
      try {if((await fetch(base+'/studio')).ok) break;} catch {}
      if(i===99) throw Error('Fixture server did not start: '+serverLog);
      await delay(100);
    }
    browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'chrome'});
    for(const kind of ['preview','package']) {
      const f = fixture[kind];
      const context = await browser.newContext({baseURL:base,viewport:{width:1440,height:1000},
        reducedMotion:'reduce',extraHTTPHeaders:{'X-Zarya-Studio':'1'}});
      await context.addCookies([{name:'zarya_studio_draft',value:f.draft_id,url:base}]);
      const page = await context.newPage();
      page.on('pageerror', e => result.errors.push(e.message));
      const writes = [];
      page.on('request', req => {if(req.method()!=='GET') writes.push(req.method()+' '+req.url());});
      const baseline = fs.readFileSync(f.draft_file);
      const target = path.join(f.folder,'scheme.pdf');
      const healthy = fs.readFileSync(target);
      const api = '/studio/api/'+kind+'/'+f.identifier;
      async function load() {
        await page.goto('/studio?view=project');
        await page.locator('.delivery').waitFor();
        await page.waitForFunction(()=>document.querySelector('#studio')?.getAttribute('aria-busy')==='false');
      }
      async function snapshot(name) {
        await page.locator('.calculation-output').screenshot({path:path.join(root,name+'.png')});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      }
      await load();
      await page.locator('[data-action="documents"][data-view="pz"]').click();
      assert.equal(await page.locator('.document-selection a').count(),1);
      if(kind==='package') assert.equal(await page.locator('.release-status.ready').count(),1);
      await snapshot(kind+'-healthy');
      for(const damage of ['missing','empty']) {
        if(damage==='missing') fs.renameSync(target,target+'.held');
        else fs.writeFileSync(target,Buffer.alloc(0));
        try {
          await load();
          const state = await (await context.request.get('/studio/api/draft')).json();
          assert.equal(state.project_calculation.can_release,false);
          if(kind==='package') {
            assert.equal(state.package.state,'unavailable');
            assert.equal(await page.locator('.release-status.ready').count(),0);
            assert.equal(await page.locator('a[href$="/download"]').count(),0);
            assert(await page.locator('[data-action="package"]').isDisabled());
            assert(await page.getByText('Сохранённый комплект недоступен целиком',{exact:true}).isVisible());
            // Clicking documents must not secretly regenerate the release.
            await page.locator('[data-action="documents"][data-view="pz"]').click();
          } else {
            assert.equal(state.documents_need_refresh,true);
            assert(await page.getByText(/Часть файлов предпросмотра отсутствует или пуста/).isVisible());
            assert(await page.locator('[data-action="documents"][data-view="pz"]').isEnabled());
          }
          const links = await page.locator('.document-list a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
          assert(links.some(url=>url===api+'/files/pz.pdf'));
          assert(!links.some(url=>url.endsWith('/scheme.pdf')));
          await page.locator('.delivery > details > summary').click();
          assert(await page.getByText('Схема · тест доступности — файл недоступен',{exact:true}).isVisible());
          assert.equal((await context.request.get(api+'/files/scheme.pdf')).status(),404);
          const good = await context.request.get(api+'/files/pz.pdf');
          assert.equal(good.status(),200);
          assert.deepEqual(await good.body(),fs.readFileSync(path.join(f.folder,'pz.pdf')));
          if(kind==='package') assert.equal((await context.request.get(api+'/download')).status(),404);
          await snapshot(kind+'-'+damage+'-desktop');
          await page.setViewportSize({width:390,height:844});
          await snapshot(kind+'-'+damage+'-mobile');
          await page.setViewportSize({width:1440,height:1000});
          assert.deepEqual(fs.readFileSync(f.draft_file),baseline);
          result.cases.push(kind+'-'+damage);
        } finally {
          if(damage==='missing') fs.renameSync(target+'.held',target);
          else fs.writeFileSync(target,healthy);
        }
        await load();
        await page.locator('[data-action="documents"][data-view="scheme"]').click();
        assert.equal(await page.locator('.document-selection a').count(),1);
        assert.equal((await context.request.get(api+'/files/scheme.pdf')).status(),200);
        if(kind==='package') {
          assert.equal(await page.locator('.release-status.ready').count(),1);
          const [download] = await Promise.all([page.waitForEvent('download'),
            page.getByRole('link',{name:/Скачать комплект/}).click()]);
          const downloaded = path.join(root,'release-'+damage+'.zip');
          await download.saveAs(downloaded);
          assert(fs.readFileSync(downloaded).subarray(0,2).equals(Buffer.from('PK')));
          execFileSync('unzip',['-t',downloaded]);
          assert.deepEqual(execFileSync('unzip',['-Z1',downloaded],{encoding:'utf8'}).trim().split('\n'),
            ['scheme.pdf','pz.pdf']);
          for(const name of ['scheme.pdf','pz.pdf']) {
            assert.deepEqual(execFileSync('unzip',['-p',downloaded,name]),fs.readFileSync(path.join(f.folder,name)));
          }
        }
        assert.deepEqual(fs.readFileSync(f.draft_file),baseline);
        result.cases.push(kind+'-'+damage+'-recovered');
      }
      assert.deepEqual(writes,[],'Opening/recovering files must not submit writes');
      await context.close();
    }
    assert.deepEqual(result.errors,[]);
    result.passed=true;
    console.log('PASS '+result.cases.length+' browser transitions; desktop/mobile; no writes or JS errors.');
  } finally {
    if(browser) await browser.close();
    server.kill('SIGTERM');
    fs.writeFileSync(path.join(root,'browser-qa.json'),JSON.stringify(result,null,2));
    console.log('Evidence: '+root);
  }
})().catch(error=>{console.error(error,serverLog);process.exitCode=1;});
