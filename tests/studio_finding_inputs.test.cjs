const {test}=require('node:test');
const assert=require('node:assert/strict');
const {targets,resolve,render,exactIndex,resolveRow,renderRow}=require('../app/web/static/studio_finding_inputs.js');
const item=(code,state='blocked')=>({code,state,detail:'К1-Ст1: исходные отсутствуют'});
test('K1-02 opens only explicit calculation risers',()=>{
  assert.deepEqual(targets(item('K1-02')),['sewage_risers']);
  assert.deepEqual(resolve(item('K1-02'),'sewage_risers'),{group:'connection',key:'sewage_risers'});
  assert.equal(resolve(item('K1-02'),'sewer_pipes'),null);
});
test('K1-05 offers existing diagnostic inputs, not inferred fan evidence',()=>{
  assert.deepEqual(targets(item('K1-05')),['sewer_pipes','sewer_elements','sewage_risers']);
  assert.equal(resolve(item('K1-05'),'wastewater_fan_ventilation'),null);
});
test('conditional findings can be completed; ready, unknown and frozen cannot edit',()=>{
  assert(targets(item('K1-02','conditional')).length);
  for(const state of ['ready','unknown',null])assert.equal(render(item('K1-02',state)),'');
  assert.equal(render(item('K1-05'),{editable:false}),'');
  assert.equal(resolve(item('K1-05'),'sewer_pipes',false),null);
});
test('unknown codes/keys and markup cannot create navigation',()=>{
  for(const code of ['K1-03','__proto__','constructor','K1-02" onclick="bad'])assert.equal(render(item(code)),'');
  assert.equal(resolve(item('K1-02'),'sewage_risers" onclick="bad'),null);
  assert.deepEqual(targets(null),[]);
});
test('render neither mutates source nor supplies audit outcomes or input values',()=>{
  const r=item('K1-05');const before=JSON.stringify(r);const html=render(r);
  assert.equal(JSON.stringify(r),before);
  assert.match(html,/не снимает замечание/);
  assert.match(html,/data-finding-input="sewer_elements"/);
  assert.doesNotMatch(html,/<input|<form|confirmed|<script/);
  const keys=targets(r);keys.length=0;assert.equal(targets(r).length,3);
});
const routes=[
  ['K1-02','sewage_risers','riser_id','sewage_riser_review','risers'],
  ['K1-05','sewer_pipes','section_id','sewage_diagnostic_review','linear_service_checks'],
];
for(const [code,key,field,review,list] of routes) {
  test(code+' row navigation is exact, unique, non-mutating and escaped',()=>{
    const id='К1-[2] "<&\' →';
    const rows=[{[field]:'first'},{[field]:id}];
    const calculation={[review]:{[list]:structuredClone(rows)}};
    const before=JSON.stringify({rows,calculation});
    assert.deepEqual(resolveRow(item(code),key,id,calculation,rows),{group:'connection',key,field,id});
    assert.equal(exactIndex(rows,field,id),1);
    const html=renderRow(item(code),key,id,calculation,rows);
    assert.match(html,/data-action="finding-row"/);
    assert.match(html,/&quot;&lt;&amp;&#39;/);
    assert.doesNotMatch(html,/<input|<script/);
    assert.equal(JSON.stringify({rows,calculation}),before);
  });
  test(code+' refuses missing, duplicate, fuzzy, stale, readonly and wrong targets',()=>{
    const id='К1-2',rows=[{[field]:id}],calculation={[review]:{[list]:rows}};
    for(const absent of ['',null,2,'к1-2','К1-2 ','К1-20'])assert.equal(resolveRow(item(code),key,absent,calculation,rows),null);
    for(const invalid of [null,[],[...rows,...rows],[{note:id}]]) {
      assert.equal(resolveRow(item(code),key,id,calculation,invalid),null);
      assert.equal(resolveRow(item(code),key,id,{[review]:{[list]:invalid}},rows),null);
    }
    assert.equal(resolveRow(item(code),key,id,null,rows),null);
    assert.equal(resolveRow(item(code),key,id,calculation,rows,false),null);
    assert.equal(resolveRow(item(code,'ready'),key,id,calculation,rows),null);
    assert.equal(resolveRow(item(code),'sewer_elements',id,calculation,rows),null);
    assert.equal(renderRow(item(code),key,id,calculation,rows,false),'');
    assert.match(renderRow(item(code),key,id,calculation,[]),/нет единственного совпадения/);
    assert.doesNotMatch(renderRow(item(code),key,id,calculation,[]),/<button/);
  });
}
test('detail renderers enable only explicitly provided row actions in intended groups',()=>{
  const riser=require('../app/web/static/studio_riser_review.js');
  const diagnostic=require('../app/web/static/studio_diagnostic_review.js');
  const called=[];const rowAction=id=>{called.push(id);return '<button>Navigate</button>';};
  assert.match(riser.render({risers:[{riser_id:'R2'}]},{rowAction}),/<button/);
  assert.match(diagnostic.render({linear_service_checks:[{section_id:'P2'}],turn_checks:[{riser_id:'R3'}],hydraulics:[{section_id:'P3'}]},{rowAction}),/<button/);
  assert.deepEqual(called,['R2','P2']);
});
