const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render}=require('../app/web/static/studio_diagnostic_review.js');
const review=()=>({linear_service_checks:[{section_id:'К1-М1',calculation_length_m:52,
  maximum_gap_m:52,access_chainages_m:[0,52],status:'fail',note:'превышена достижимость прочистки на интервалах 0–52 м'}],
  turn_checks:[],hydraulics:[],errors:['К1-М1: ошибка'],warnings:['К1-М1: нужен расход'],
  pending_horizontal_flows:['К1-М1'],horizontal_flow_notes:{'К1-М1':'Нет N/L'}});
test('source intervals and status are displayed, gap is not a normative limit',()=>{
  const r=review(),before=JSON.stringify(r),html=render(r);
  assert.match(html,/0–52 м/);assert.match(html,/0; 52/);
  assert.match(html,/Максимальный интервал в расчёте: 52/);assert.match(html,/не нормативный предел/);
  assert.match(html,/Есть несоответствие/);assert.equal(JSON.stringify(r),before);
});
test('pending and unknown numbers are not zero or verified',()=>{
  const r=review();Object.assign(r.linear_service_checks[0],{status:'pending',calculation_length_m:null,maximum_gap_m:null,access_chainages_m:[]});
  const html=render(r);assert.match(html,/Недостаточно данных/);assert.match(html,/длина: не определено/);
  assert.match(html,/нет подтверждённых координат/);assert.doesNotMatch(html,/длина: 0/);
  r.linear_service_checks[0].status='other';assert.match(render(r),/Статус не определён/);
});
test('empty hydraulic list is not success; errors and warnings are independent',()=>{
  const html=render(review());assert.match(html,/Нет результатов этой проверки/);
  assert.match(html,/К1-М1: ошибка/);assert.match(html,/К1-М1: нужен расход/);assert.match(html,/К1-М1: Нет N\/L/);
  assert.match(render(null),/Повторите расчёт/);
});
test('hydraulic source verdict and null booleans are preserved without arithmetic',()=>{
  const r=review();r.hydraulics=[{section_id:'Г1',status:'fail',design_flow_lps:0,velocity_mps:1,
    fill_ratio:null,self_cleaning_ok:null,velocity_ok:true,minimum_fill_ok:false,
    note:'независимая причина',roughness_source:'Паспорт'}];
  const html=render(r);assert.match(html,/Расход: 0 л\/с/);assert.match(html,/h\/d: не определено/);
  assert.match(html,/самоочищения: не завершена; скорости: выполнена; минимального наполнения: не выполнена/);
  assert.match(html,/Г1 · Есть несоответствие/);assert.match(html,/независимая причина/);
});
test('lower turn preserves named access and missing access is explicit',()=>{
  const r=review();r.turn_checks=[{riser_id:'Ст1',outgoing_section_id:'М1',access_element_id:'Р1',status:'verified',note:'доступ'}];
  assert.match(render(r),/Элемент доступа: Р1/);
  r.turn_checks[0].access_element_id='';assert.match(render(r),/Элемент доступа: не подтверждён/);
});
test('all source strings escaped; details readonly and collapsed',()=>{
  const r=review();r.errors=['<script>x</script>'];r.linear_service_checks[0].note='<img src=x>';
  r.horizontal_flow_notes={'<b>ID</b>':'<i>note</i>'};
  const html=render(r);assert.doesNotMatch(html,/<script|<img|<b>|<i>|<input|<button|<details[^>]*\bopen\b/);
  assert.match(html,/&lt;img/);assert.match(html,/не разрешает работы или выпуск/);
});
