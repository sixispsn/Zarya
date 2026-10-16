const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};
vm.runInNewContext(fs.readFileSync('app/web/static/studio_sewer_pipes.js','utf8'),context);
const columns=[{key:'system',label:'Система',kind:'text',primary:true,required:true},
  {key:'length_m',label:'Длина',kind:'number',primary:true,required:true},
  {key:'insulated',label:'Изоляция',kind:'boolean',primary:true,required:true},
  {key:'flow_source',label:'Основание',kind:'text',primary:false}];
const render=rows=>context.window.ZaryaSewerPipes.rows(rows,columns,v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'));
for(const key of ['system','kind','service_direction','service_fitting'])test('unsupported element '+key+' retained, escaped and not accepted as a normal option',()=>{
  const cols=[{key,label:key,kind:'text',primary:true,options:[['revision','Ревизия']]}];
  const escape=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
  const item={[key]:'old"><img src=x onerror="boom">'},original=JSON.stringify(item);
  const html=context.window.ZaryaSewerPipes.rows([item],cols,escape,true);
  assert(html.includes('selected data-unsupported'));
  assert(html.includes('Не поддерживается: old&quot;&gt;') || html.includes('Не поддерживается: old&quot;>'));
  assert(!html.includes('<img'));assert(html.includes('&lt;img'));
  assert.equal(JSON.stringify(item),original);
  const valid=key==='system'?'K1':'revision';
  for(const value of ['',null,valid]) {
    const normal=context.window.ZaryaSewerPipes.rows([{[key]:value}],cols,escape,true);
    assert(!normal.includes('data-unsupported'));
  }
  for(const mode of [false,'risers',...(key==='kind'?[]:['fans'])])assert(!context.window.ZaryaSewerPipes.rows([item],cols,escape,mode).includes('data-unsupported'));
});
test('new row does not assign system, dimensions or insulation',()=>{
  const html=render([{}]);
  assert(!html.includes(' selected'));
  assert(html.includes('value="" inputmode="decimal"'));
  assert(html.includes('Не задано'));
  assert(!render([]).includes('fieldset'));
});
test('explicit false and zero survive; source text escaped',()=>{
  const html=render([{system:'K1',insulated:false,length_m:0,flow_source:'<img src=x onerror="boom">'}]);
  assert(html.includes('value="false" selected'));
  assert(html.includes('value="0"'));
  assert(!html.includes('<img'));
  assert(html.includes('&lt;img'));
});
test('element controls have no silent quantity, floor or accessibility choices',()=>{
  const fields=[{key:'quantity',label:'Количество',kind:'integer',primary:true},
    {key:'floor_from',label:'Этаж',kind:'integer',primary:true},
    {key:'accessible',label:'Доступность',kind:'boolean',primary:true},
    {key:'kind',label:'Вид',kind:'text',primary:true,options:[['revision','Ревизия']]}];
  const renderElement=items=>context.window.ZaryaSewerPipes.rows(items,fields,String,true);
  const blank=renderElement([{}]);
  assert(!blank.includes(' selected'));
  assert(blank.includes('Нет / не подтверждена'));
  assert(blank.includes('Удалить элемент К1/К2 1'));
  const saved=renderElement([{quantity:2,floor_from:0,accessible:false,kind:'revision'}]);
  assert(saved.includes('value="0"'));
  assert(saved.includes('value="false" selected'));
  assert(saved.includes('value="revision" selected'));
});
test('calculation riser starts without flow, ventilation or toilet confirmation',()=>{
  const fields=[{key:'design_flow_lps',label:'Расход',kind:'number',primary:true},
    {key:'ventilation',label:'Вентиляция',kind:'text',primary:true,options:[['ventilated','Вентилируемый']]},
    {key:'branch_angle_deg',label:'Угол',kind:'number',primary:true,options:[['87.5','87,5']]},
    {key:'has_toilet',label:'Унитаз',kind:'boolean',primary:true}];
  const renderRiser=items=>context.window.ZaryaSewerPipes.rows(items,fields,String,'risers');
  assert(!renderRiser([{}]).includes(' selected'));
  assert(renderRiser([{}]).includes('Удалить расчётный стояк К1 1'));
  const html=renderRiser([{design_flow_lps:1.2,ventilation:'ventilated',branch_angle_deg:87.5,has_toilet:false}]);
  assert(html.includes('value="1.2"'));
  assert(html.includes('value="87.5" selected'));
  assert(html.includes('value="false" selected'));
});
