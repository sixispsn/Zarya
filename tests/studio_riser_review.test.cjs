const {test}=require('node:test');
const assert=require('node:assert/strict');
const {render}=require('../app/web/static/studio_riser_review.js');
const row=()=>({riser_id:'К1-Ст1',design_flow_lps:2.758,capacity_lps:3.2,reserve_lps:.442,
  status:'fail',capacity_ok:true,diameter_ok:true,minimum_dn_mm:100,
  material_label:'ПП',ventilation_label:'Вентилируемый',riser_dn_mm:110,
  branch_dn_mm:110,branch_angle_deg:87.5,table:'К.1',note:'нагрузка отдельного стояка превышает общий расчётный расход системы К1'});
const review=r=>({total:{q_sewage_lps:2.293},risers:[r]});
test('independent failure is preserved despite passing capacity and diameter',()=>{
  const r=review(row()),before=JSON.stringify(r),html=render(r);
  assert.match(html,/Есть несоответствие/);assert.match(html,/нагрузка отдельного стояка превышает/);
  assert.match(html,/2,758/);assert.match(html,/3,2/);assert.match(html,/2,293/);
  assert.match(html,/пропускной способности: выполнена/);assert.equal(JSON.stringify(r),before);
});
test('unknown capacity is not zero; missing and stage R stay distinct',()=>{
  for(const [status,label] of [['missing','Недостаточно данных'],['stage_r','Требуется уточнение стадии Р']]) {
    const html=render(review({...row(),status,capacity_lps:null,capacity_ok:null,reserve_lps:null}));
    assert.match(html,new RegExp(label));assert.match(html,/способность: не определён/);
    assert.match(html,/способности: не завершена/);assert.doesNotMatch(html,/способность: 0/);
  }
});
test('uses source status, zero and negative values without new arithmetic',()=>{
  const html=render(review({...row(),status:'verified',reserve_lps:0,capacity_lps:1,design_flow_lps:2}));
  assert.match(html,/Проверка стояка выполнена/);assert.match(html,/Разность по таблице: 0/);
  assert.match(render(review({...row(),reserve_lps:-.5})),/Разность по таблице: -0,5/);
});
test('legacy absent summary and empty registry are not a successful result',()=>{
  assert.match(render(undefined),/Повторите расчёт/);assert.match(render({risers:[]}),/не заданы/);
  assert.match(render(review({...row(),status:'other'})),/Статус не определён/);
});
test('source text is escaped and the detail is read-only and collapsed',()=>{
  const html=render(review({...row(),riser_id:'<img src=x>',note:'<script>alert(1)</script>',table:'<b>fake</b>'}));
  assert.doesNotMatch(html,/<img|<script|<b>|<input|<button|<details[^>]*\bopen\b/);
  assert.match(html,/&lt;script&gt;/);assert.match(html,/не означает готовность всего выпуска/);
});
