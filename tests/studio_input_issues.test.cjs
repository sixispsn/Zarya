const {test}=require('node:test');
const assert=require('node:assert/strict');
const {resolve}=require('../app/web/static/studio_input_issues.js');
const issue={code:'duplicate_riser_id',registry:'sewage_risers',field:'riser_id',row_index:1};
const rows=[{riser_id:'same'},{riser_id:'same'}];
test('nested fan addresses validate schema, full object and position; globals cannot be row targets',()=>{
  const registry='wastewater_fan_ventilation';
  const value={terminals:[{terminal_id:'A'},{terminal_id:'B'}],external_ventilation_verified:null};
  const editors={[registry]:[{key:'terminal_id',label:'ID',kind:'text',required:true},
    {key:'riser_ids',label:'IDs',kind:'ids',required:true},{key:'height_m',label:'H',kind:'number'},
    {key:'cold_attic',label:'Чердак',kind:'boolean'},{key:'source_ref',label:'Источник',kind:'text'}]};
  for(const [code,field] of [['required_value','terminal_id'],['required_value','riser_ids'],
    ['invalid_number','height_m'],['nonfinite_number','height_m'],['boolean_required','cold_attic'],
    ['fan_text_value','source_ref'],['fan_ids_list','riser_ids']]) {
    const error={code,field,registry,row_index:1};
    assert.equal(resolve(error,value,structuredClone(value),true,editors).index,1);
    for(const current of [value.terminals,{terminals:value.terminals},
      {...value,external_ventilation_verified:false},{...value,terminals:value.terminals.toReversed()}])
      assert.equal(resolve(error,value,current,true,editors),null);
    assert.equal(resolve(error,value.terminals,value.terminals,true,editors),null);
    assert.equal(resolve(error,value,value,false,editors),null);
  }
  assert.equal(resolve({code:'fan_text_value',registry,field:'height_m',row_index:1},value,value,true,editors),null);
  assert.equal(resolve({code:'boolean_required',registry,field:'external_ventilation_verified',row_index:1},value,value,true,editors),null);
});
test('global fan targets require explicit global scope, exact field and unchanged whole object',()=>{
  const registry='wastewater_fan_ventilation';
  const value={terminals:[],external_ventilation_verified:'false',external_ventilation_ref:0};
  for(const [code,field] of [['fan_global_boolean','external_ventilation_verified'],['fan_global_text','external_ventilation_ref']]) {
    const issue={code,field,registry,scope:'global'};
    assert.equal(resolve(issue,value,structuredClone(value)).scope,'global');
    assert.equal(resolve(issue,value,value,false),null);
    for(const patch of [{scope:undefined},{scope:'terminal'},{row_index:0},{row_index:null},{field:'kind'},{registry:'sewer_elements'}])
      assert.equal(resolve({...issue,...patch},value,value),null);
    for(const current of [null,[],{...value,terminals:[{}]},{...value,external_ventilation_verified:false}])
      assert.equal(resolve(issue,value,current),null);
    assert(resolve(issue,{},{}));
  }
});
test('fan model row codes require correct schema and nested unchanged data',()=>{
  const registry='wastewater_fan_ventilation',value={terminals:[{},{}]};
  const editors={[registry]:[{key:'height_m',label:'Высота',kind:'number'},
    {key:'cold_attic',label:'Чердак',kind:'boolean'},{key:'source_ref',label:'Источник',kind:'text'}]};
  for(const [code,field] of [['fan_model_id','terminal_id'],['fan_model_duplicate_id','terminal_id'],
    ['fan_model_riser_ids','riser_ids'],['fan_model_kind','kind'],['fan_model_number','height_m'],
    ['fan_model_boolean','cold_attic'],['fan_model_reference','source_ref']]) {
    const issue={code,field,registry,row_index:1};
    assert.equal(resolve(issue,value,value,true,editors).index,1);
    assert.equal(resolve({...issue,scope:'global'},value,value,true,editors),null);
    assert.equal(resolve(issue,value,{terminals:[{}]},true,editors),null);
    assert.equal(resolve({...issue,field:'constructor'},value,value,true,editors),null);
  }
  assert.equal(resolve({code:'fan_model_number',field:'source_ref',registry,row_index:1},value,value,true,editors),null);
});
for(const code of ['fan_unlinked_riser','fan_repeated_riser'])test(code+' requires nested fan object and pipe context',()=>{
  const registry='wastewater_fan_ventilation',value={terminals:[{riser_ids:['X']}]};
  const error={code,registry,field:'riser_ids',row_index:0};
  const submitted={[registry]:value,sewer_pipes:[{section_id:'P'}]};
  assert(resolve(error,value,value,true,{}, {submitted,current:structuredClone(submitted)}));
  assert.equal(resolve(error,value,value),null);
  for(const current of [{[registry]:value},{...submitted,sewer_pipes:[]},
    {...submitted,[registry]:{...value,external_ventilation_ref:'changed'}}])
    assert.equal(resolve(error,value,value,true,{}, {submitted,current}),null);
});
test('duplicate IDs addressed by submitted position, not by first matching ID',()=>{
  const before=JSON.stringify(rows);
  assert.deepEqual(resolve(issue,rows,structuredClone(rows)),{
    key:'sewage_risers',field:'riser_id',index:1,label:'Обозначение стояка · строка 2'});
  assert.equal(JSON.stringify(rows),before);
});
test('rejects changed, reordered, shortened and missing snapshots',()=>{
  const original=[{riser_id:'A'},{riser_id:'B'}];
  for(const current of [null,[],original.slice(1),[...original].reverse(),[{riser_id:'A'},{riser_id:'C'}]])
    assert.equal(resolve(issue,original,current),null);
});
test('explicit code/key/field combinations; safe indices and editable mode',()=>{
  for(const patch of [{code:'constructor'},{code:'unknown'},{registry:'sewer_elements'},
    {field:'constructor'},{row_index:-1},{row_index:2},{row_index:1.5},{row_index:'1'}])
    assert.equal(resolve({...issue,...patch},rows,rows),null);
  assert.equal(resolve(null,rows,rows),null);
  assert.equal(resolve(issue,rows,rows,false),null);
  assert(resolve({code:'blocked_pipe_section',registry:'sewer_pipes',field:'wall_thickness_mm',row_index:0},[{}],[{}]));
});
for(const [code,field] of [['duplicate_element_id','element_id'],['element_quantity_positive','quantity'],
  ['element_typical_quantity_positive','typical_quantity'],['element_floor_order','floor_to'],
  ['element_dn_positive','dn_mm'],['element_slope_nonnegative','slope_per_mille'],
  ['element_layout_nonnegative','layout_column'],['element_chainage_nonnegative','service_chainage_m'],
  ['element_system_choice','system'],['element_kind_choice','kind'],['element_direction_choice','service_direction'],
  ['element_fitting_choice','service_fitting'],['element_spec_unit_required','unit']])
test(code+' resolves by submitted position and rejects changed registry or forged address',()=>{
  const rows=[{element_id:'same',floor_from:1},{element_id:'same',floor_from:2}];
  const issue={code,field,registry:'sewer_elements',row_index:1};
  const before=JSON.stringify(rows);
  assert.equal(resolve(issue,rows,structuredClone(rows)).index,1);
  for(const current of [rows.toReversed(),rows.slice(1),[{...rows[0]}, {...rows[1],floor_from:3}]])
    assert.equal(resolve(issue,rows,current),null);
  for(const patch of [{field:'constructor'},{registry:'sewer_pipes'},{row_index:-1},{row_index:2}])
    assert.equal(resolve({...issue,...patch},rows,rows),null);
  assert.equal(resolve(issue,rows,rows,false),null);
  assert.equal(JSON.stringify(rows),before);
});
for(const registry of ['sewage_risers','sewer_pipes','sewer_elements'])test(registry+' parser addresses require an actual compatible editor column',()=>{
  const columns=[{key:'id',label:'ID',kind:'text',required:true},
    {key:'flag',label:'Да/нет',kind:'boolean',required:true},
    {key:'n',label:'N',kind:'integer',required:false}, {key:'q',label:'Q',kind:'number',required:true}];
  const editors={[registry]:columns};
  const make=(code,field)=>({code,registry,field,row_index:0});
  for(const [code,field] of [['required_value','id'],['required_value','q'],['invalid_number','q'],
    ['nonfinite_number','n'],['integer_required','n'],['boolean_required','flag']]) {
    assert(resolve(make(code,field),[{}],[{}],true,editors));
    assert.equal(resolve(make(code,field),[{}],[{}]),null);
    assert.equal(resolve(make(code,field),[{}],[{}],false,editors),null);
  }
  for(const [code,field] of [['required_value','n'],['invalid_number','id'],['integer_required','q'],
    ['nonfinite_number','__proto__'],['invalid_number','absent'],['boolean_required','q']])
    assert.equal(resolve(make(code,field),[{}],[{}],true,editors),null);
  assert.equal(resolve(make('invalid_number','q'),[{}],[{}],true,{[registry]:[...columns,columns.at(-1)]}),null);
});
for(const [code,field] of [['unknown_element_section','section_id'],['element_section_system','section_id'],['unknown_element_connection','connects_to']])
test(code+' needs unchanged element and pipe snapshots',()=>{
  const rows=[{element_id:'A'},{element_id:'B'}];
  const issue={code,field,registry:'sewer_elements',row_index:1};
  const submitted={sewer_elements:rows,sewer_pipes:[{section_id:'P',from_node:'N'}]};
  const run=current=>resolve(issue,rows,rows,true,{}, {submitted,current});
  assert(run(structuredClone(submitted)));
  assert.equal(resolve(issue,rows,rows),null);
  for(const current of [{sewer_elements:rows},{...submitted,sewer_pipes:[]},
    {...submitted,sewer_pipes:[{section_id:'P',from_node:'changed'}]},
    {...submitted,sewer_elements:rows.toReversed()}])assert.equal(run(current),null);
  assert.equal(resolve({...issue,field:'name'},rows,rows,true,{}, {submitted,current:submitted}),null);
  assert.equal(resolve(issue,rows,rows,false,{}, {submitted,current:submitted}),null);
  const empty={sewer_elements:rows,sewer_pipes:null};
  assert(resolve(issue,rows,rows,true,{}, {submitted:empty,current:empty}));
});
test('unlinked riser requires unchanged snapshots of BOTH registries, including absent pipes',()=>{
  const row=[{riser_id:'unknown'}],pipes=[{section_id:'A'}];
  const error={code:'unlinked_riser',registry:'sewage_risers',field:'riser_id',row_index:0};
  const submitted={sewage_risers:row,sewer_pipes:pipes};
  const run=current=>resolve(error,row,row,true,{}, {submitted,current});
  assert(run(structuredClone(submitted)));
  assert.equal(resolve(error,row,row),null);
  for(const current of [{sewage_risers:row},{...submitted,sewer_pipes:[]},
    {...submitted,sewer_pipes:[{section_id:'B'}]}, {...submitted,sewage_risers:[{riser_id:'new'}]}])assert.equal(run(current),null);
  const empty={sewage_risers:row,sewer_pipes:null};
  assert(resolve(error,row,row,true,{}, {submitted:empty,current:empty}));
  assert.equal(resolve(error,row,row,false,{}, {submitted,current:submitted}),null);
});
