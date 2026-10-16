const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/web/static/studio.js'), 'utf8');
const functions = source.slice(source.indexOf('  function documentList('),
                               source.indexOf('  function deliverableContent('));
function view(draft, documents) {
  return new Function('draft', 'documents', 'escape', 'deliverableContent', 'window',
    `${functions}; return {list:documentList(documents,'preview'),note:deliverables()};`
  )(draft, documents, value=>String(value).replaceAll('<','&lt;').replaceAll('>','&gt;'),
    ()=>'content', {});
}
test('missing file is not linked; existing incomplete package remains downloadable', () => {
  const output = view({preview:{id:'abc'}, documents_need_refresh:true,
                       documents_missing_files:['scheme.pdf']}, [
    {name:'scheme.pdf', label:'<Схема>', file_missing:true, state:'incomplete', state_note:'Недоступен'},
    {name:'package.pdf', label:'Комплект', state:'incomplete', state_note:'Часть комплекта недоступна'},
  ]);
  assert.ok(!output.list.includes('/files/scheme.pdf'));
  assert.ok(output.list.includes('/files/package.pdf'));
  assert.ok(output.list.includes('&lt;Схема&gt; — файл недоступен'));
  assert.ok(output.note.includes('отсутствует или пуста'));
  assert.ok(!output.note.includes('Генератор документов обновлён'));
});
test('renderer upgrade keeps its own message and healthy preview has no warning', () => {
  assert.ok(view({preview:{id:'abc'},documents_need_refresh:true}, []).note.includes('Генератор документов обновлён'));
  assert.equal(view({preview:{id:'abc'},documents_need_refresh:false}, []).note, 'content');
});
for(const [state,label] of [['incomplete','Неполный документ'],['preliminary','Предварительный документ']]) {
  test(`${state}: explicit status independent of reason wording, optional reason escaped`, () => {
    for(const reason of [undefined,'','Режим должен соответствовать <roof>']) {
      const output=view({preview:{id:'abc'}},[{name:'a.pdf',label:'Комплект',state,state_note:reason}]);
      assert.ok(output.list.includes(label));
      assert.ok(output.list.includes('/files/a.pdf'));
      assert.ok(!output.list.includes('undefined'));
      assert.ok(!output.list.includes('<roof>'));
      if(reason) assert.ok(output.list.includes('Режим должен соответствовать &lt;roof&gt;'));
    }
  });
}
test('ready document is not relabelled incomplete or preliminary', () => {
  const output=view({preview:{id:'abc'}},[{name:'a.pdf',label:'Схема',state:'ready'}]);
  assert.ok(!output.list.includes('Неполный документ'));
  assert.ok(!output.list.includes('Предварительный документ'));
});
