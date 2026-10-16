const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render}=require('../app/web/static/studio_spec_review.js');
const review=()=>({scope:'ios2',state:'reviewed',counts:{positions:114,assigned:78,estimated:8,missing:36,invalid:0,requirements:0},
  notice:'Не допуск к закупке',groups:[{title:'В1',count:1,items:[{position:'17',name:'Кран',detail:'Число стояков не задано'}]}],
  actions:[{id:'risers',title:'Стояки',note:'Только количества'}]});
test('collapsed by default; estimates separate; not a release signal',()=>{
  const html=render(review());
  assert.match(html,/без количества: 36/);
  assert.match(html,/Количество указано: <b>78/);
  assert.match(html,/Из них оценочных: <b>8/);
  assert.match(html,/Поз. 17 · Кран/);
  assert.match(html,/data-spec-input="risers"/);
  assert.doesNotMatch(html,/<details[^>]*\bopen\b|class="[^"]*confirmed|к закупке готов/);
});
test('frozen example cannot show edit buttons',()=>{
  const html=render(review(),{editable:false});
  assert.doesNotMatch(html,/data-action="spec-quantity-inputs"/);
  assert.match(html,/Кран/);
});
test('area question opens only the existing estimate input, not a network measurement',()=>{
  const r=review();
  r.actions.push({id:'area',title:'Общая площадь',note:'Только предварительная оценка'});
  assert.match(render(r),/data-spec-input="area"/);
  assert.doesNotMatch(render(r,{editable:false}),/data-spec-input="area"/);
});
test('sectional quantities open optional layout fields; frozen case stays read-only',()=>{
  const r=review();
  r.actions.push({id:'sectional_valves',title:'Секционные краны В1',note:'По компоновке'});
  assert.match(render(r),/data-spec-input="sectional_valves"/);
  assert.doesNotMatch(render(r,{editable:false}),/data-spec-input="sectional_valves"/);
});
test('all document text escaped, unknown action ignored',()=>{
  const r=review();
  r.groups[0].title='<img src=x onerror=alert(1)>';
  r.groups[0].items[0].detail='<script>bad</script>';
  r.actions.push({id:'evil" onclick="bad',title:'evil'});
  const html=render(r);
  assert.doesNotMatch(html,/<img|<script|onclick=/);
  assert.match(html,/&lt;script&gt;/);
});
test('service and balancing layouts remain optional and frozen case cannot edit them',()=>{
  const r=review();
  r.actions.push(...['service_nodes','balancing'].map(id=>({id,title:id,note:'По компоновке'})));
  assert.match(render(r),/data-spec-input="service_nodes"/);
  assert.match(render(r),/data-spec-input="balancing"/);
  assert.doesNotMatch(render(r,{editable:false}),/data-spec-input=/);
});
test('zero missing is not approval, absent/unavailable data not success',()=>{
  assert.equal(render(null),'');assert.equal(render({...review(),scope:'ios3'}),'');
  const r=review();r.counts.missing=0;r.groups=[];r.actions=[];
  assert.match(render(r),/количества заполнены/);
  assert.match(render(r),/Не допуск к закупке/);
  const html=render({scope:'ios2',state:'unavailable',notice:'Ошибка'});
  assert.match(html,/проверка не выполнена/);assert.doesNotMatch(html,/количества заполнены/);
});
