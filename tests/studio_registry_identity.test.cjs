const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const scope={window:{}};vm.runInNewContext(fs.readFileSync('app/web/static/studio_sewer_pipes.js','utf8'),scope);
const api=scope.window.ZaryaSewerPipes;
for(const [mode,system,noun] of [[false,'К1/К2','участок'],[true,'К1/К2','элемент'],['risers','К1','расчётный стояк'],['fans','К1','фановое окончание']]) {
  test('explicit labels and accessible remove names: '+noun,()=>{
    const html=api.rows([{},{}],[],String,mode);
    assert(html.includes(`data-registry-row-label="${system} · ${noun}"`));
    assert(html.includes(`data-registry-remove-label="Удалить ${noun} ${system}"`));
    const rows=[2,3].map(index=>{
      const legend={dataset:{registryRowLabel:`${system} · ${noun}`},textContent:'old '+index};
      const remove={dataset:{registryRemoveLabel:`Удалить ${noun} ${system}`},setAttribute(k,v){this[k]=v;}};
      return {legend,remove,raw:{value:'nan',kind:'obsolete',confirmed:false},details:{open:true},
        querySelector(s){return s==='[data-registry-row-label]'?legend:remove;}};
    });
    const before=JSON.stringify(rows.map(row=>[row.raw,row.details]));
    api.renumber({querySelectorAll:()=>rows});
    for(const [i,row] of rows.entries()) {
      assert.equal(row.legend.textContent,`${system} · ${noun} ${i+1}`);
      assert.equal(row.remove['aria-label'],`Удалить ${noun} ${system} ${i+1}`);
    }
    assert.equal(JSON.stringify(rows.map(row=>[row.raw,row.details])),before);
  });
}
test('empty and non-registry editors do not invent labels or rows',()=>{
  api.renumber({querySelectorAll:()=>[]});
  api.renumber({querySelectorAll:()=>[{querySelector:()=>null}]});
});
