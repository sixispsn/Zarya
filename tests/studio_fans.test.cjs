const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};
for(const file of ['studio_sewer_pipes.js','studio_fans.js']) vm.runInNewContext(fs.readFileSync('app/web/static/'+file,'utf8'),context);
const escape=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const schema={max_rows:200,columns:[
  {key:'terminal_id',label:'ID',kind:'text',primary:true},
  {key:'riser_ids',label:'Стояки',kind:'ids',primary:true},
  {key:'kind',label:'Тип',kind:'text',primary:true,options:[['roof','Кровля'],['unknown','Не определён']]},
  {key:'height_m',label:'Высота',kind:'number',primary:false},
  {key:'open_end_confirmed',label:'Устье',kind:'boolean',primary:false},
]};
test('fan blank row never assigns dimensions, confirmations or riser membership',()=>{
  const html=context.window.ZaryaFanEditor.rows([{}],schema,escape);
  assert(!html.includes(' selected'));
  assert(html.includes('data-id-list'));
  assert(html.includes('Удалить фановое окончание К1 1'));
  assert(!html.includes('К1/К2'));
});
test('nested evidence keeps false/zero and escapes ID lists and source refs',()=>{
  const value={terminals:[{terminal_id:'Ф1',riser_ids:['К1-1','<img>'],kind:'roof',height_m:0,open_end_confirmed:false}],
    external_ventilation_verified:false,external_ventilation_ref:'<script>'};
  const html=context.window.ZaryaFanEditor.control({label:'Вентиляция',help:'',value},'next',schema,escape);
  assert(html.includes('К1-1\n&lt;img>'));
  assert(!html.includes('<img>'));assert(!html.includes('<script>'));
  assert(html.includes('value="0"'));assert(html.includes('value="false" selected'));
});
test('global unknown stays null; explicit false survives; no terminal rows are invented',()=>{
  const editor=value=>({querySelector:selector=>({value:selector.includes('verified')?value:' источник '})});
  assert.equal(context.window.ZaryaFanEditor.read(editor(''),[]).external_ventilation_verified,null);
  const value=context.window.ZaryaFanEditor.read(editor('false'),[]);
  assert.equal(value.external_ventilation_verified,false);
  assert.equal(value.external_ventilation_ref,'источник');
  assert.equal(value.terminals.length,0);
});
test('unknown fan kind is retained and escaped, never replaced by unknown mode',()=>{
  const value={terminals:[{kind:'legacy"><img src=x>'}]};
  const before=JSON.stringify(value),html=context.window.ZaryaFanEditor.rows(value,schema,escape);
  assert(html.includes('selected data-unsupported'));
  assert(html.includes('Не поддерживается:'));
  assert(!html.includes('<img'));
  assert.equal(JSON.stringify(value),before);
});
for(const raw of ['true','false',0,1,[],{}])test('global invalid boolean preserves original type: '+JSON.stringify(raw),()=>{
  const html=context.window.ZaryaFanEditor.globals({external_ventilation_verified:raw},escape);
  assert(html.includes('value="unsupported" selected data-fan-raw='));
  const control={value:'unsupported',selectedOptions:[{dataset:{fanRaw:JSON.stringify(raw)}}]};
  const editor={querySelector:s=>s.includes('verified')?control:{value:'',dataset:{}}};
  assert.equal(JSON.stringify(context.window.ZaryaFanEditor.read(editor,[]).external_ventilation_verified),JSON.stringify(raw));
  control.value='false';
  assert.equal(context.window.ZaryaFanEditor.read(editor,[]).external_ventilation_verified,false);
});
for(const raw of [null,0,{},[]])test('global non-string reference remains raw until explicit input: '+JSON.stringify(raw),()=>{
  const html=context.window.ZaryaFanEditor.globals({external_ventilation_ref:raw},escape);
  assert(html.includes('data-preserved-raw='));
  const ref={value:'display',dataset:{preservedRaw:JSON.stringify(raw)}};
  const editor={querySelector:s=>s.includes('verified')?{value:''}:ref};
  assert.equal(JSON.stringify(context.window.ZaryaFanEditor.read(editor,[]).external_ventilation_ref),JSON.stringify(raw));
  delete ref.dataset.preservedRaw;ref.value=' explicit ';
  assert.equal(context.window.ZaryaFanEditor.read(editor,[]).external_ventilation_ref,'explicit');
});
