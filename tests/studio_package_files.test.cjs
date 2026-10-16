const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/web/static/studio.js'), 'utf8');
const functions = source.slice(source.indexOf('  function documentKind('),
                               source.indexOf('  function sectionReview('));
function view(state, documents, canRelease = false) {
  const draft = {
    package:{state, run_id:'saved', documents, availability_note:'Недоступен <файл>'},
    preview:{id:'preview', documents:[{name:'preview.pdf',label:'Черновик'}]},
    project_calculation:{can_release:canRelease},
  };
  return new Function('draft', 'escape', 'documentView', 'window', 'sectionReview',
    `${functions}; return deliverables();`
  )(draft, value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;'), 'all', {}, ()=>'');
}
test('unavailable release keeps healthy archive links, but no ZIP or green ready', () => {
  const html = view('unavailable', [
    {name:'pz.pdf',label:'ПЗ'},
    {name:'scheme.pdf',label:'Схема',file_missing:true,state:'incomplete',state_note:'Нет файла'},
  ], true); // UI also guards against an inconsistent cached can_release.
  assert.ok(html.includes('/package/saved/files/pz.pdf'));
  assert.ok(!html.includes('/files/scheme.pdf'));
  assert.ok(!html.includes('/preview/'));
  assert.ok(!html.includes('/download'));
  assert.ok(!html.includes('release-status ready'));
  assert.ok(html.includes('data-action="package" disabled'));
  assert.ok(html.includes('Сохранённый комплект недоступен целиком'));
  assert.ok(html.includes('Можно открыть сохранившиеся документы выпуска'));
  assert.ok(html.includes('Недоступен &lt;файл&gt;'));
  assert.ok(!html.includes('Открыть черновик ПЗ'));
});
test('healthy release retains ZIP and ready status', () => {
  const html = view('ready', [{name:'pz.pdf',label:'ПЗ'}]);
  assert.ok(html.includes('/package/saved/download'));
  assert.ok(html.includes('release-status ready'));
  assert.ok(!html.includes('Недоступен &lt;файл&gt;'));
});
test('invalid empty manifest renders an unavailable release without links', () => {
  const html = view('unavailable', []);
  assert.ok(html.includes('Сохранённый комплект недоступен целиком'));
  assert.ok(!html.includes('/files/'));
  assert.ok(!html.includes('/download'));
});
