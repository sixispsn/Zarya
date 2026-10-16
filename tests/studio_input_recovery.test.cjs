const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const scope={window:{}};
vm.runInNewContext(fs.readFileSync('app/web/static/studio_input_recovery.js','utf8'),scope);
const create=(d,p)=>JSON.parse(JSON.stringify(scope.window.ZaryaInputRecovery.create(d,p)));
const draft=()=>({project_id:'private-project',revision:7,documents:[{secret:'not exported'}],
  calculation:{secret:'not exported'},fields:[
    {key:'sewer_pipes',value:[{section_id:'A',insulated:false}],status:'confirmed'},
    {key:'wastewater_fan_ventilation',value:null,status:'missing'},
    {key:'object_name',value:'Saved title',status:'confirmed'}]});
test('local copy contains only changed inputs and baseline, never docs or results',()=>{
  const d=draft(),p={revision:7,answers:{sewer_pipes:[{section_id:'',insulated:false,length_m:'nan'}],
    wastewater_fan_ventilation:{terminals:[{kind:'<img onerror="bad">'}],external_ventilation_verified:'false',external_ventilation_ref:0}},preset_keys:[]};
  const before=JSON.stringify({d,p}),copy=create(d,p);
  assert.equal(copy.format,'zarya-unsaved-input');assert.equal(copy.version,1);
  assert.equal(copy.base_revision,7);assert.equal(copy.project_id,d.project_id);
  assert.deepEqual(copy.answers,p.answers);assert.deepEqual(copy.base_fields,d.fields.slice(0,2));
  assert(!('documents' in copy));assert(!('calculation' in copy));
  assert(!JSON.stringify(copy).includes('not exported'));assert(!JSON.stringify(copy).includes('Saved title'));
  assert.equal(JSON.stringify({d,p}),before);
  copy.answers.sewer_pipes[0].section_id='detached';assert.equal(p.answers.sewer_pipes[0].section_id,'');
  assert.match(copy.notice,/Не проект/);
});
for(const value of [null,false,0,'','false',[],{unknown:'unchanged'}])test('raw value retained: '+JSON.stringify(value),()=>{
  assert.deepEqual(create(draft(),{revision:7,answers:{wastewater_fan_ventilation:value}}).answers.wastewater_fan_ventilation,value);
});
for(const patch of [{revision:8},{revision:'7'},{answers:[]},{answers:null},{answers:{unknown:3}},
  {preset_keys:['unknown']},{preset_keys:'bad'}])test('reject inconsistent recovery payload '+JSON.stringify(patch),()=>{
  assert.throws(()=>create(draft(),{revision:7,answers:{sewer_pipes:[]},...patch}));
});
test('preset provenance and missing baseline survive without adopting defaults',()=>{
  const d=draft();d.fields[1].value=null;
  const copy=create(d,{revision:7,answers:{wastewater_fan_ventilation:null},preset_keys:['wastewater_fan_ventilation']});
  assert.deepEqual(copy.preset_keys,['wastewater_fan_ventilation']);assert.equal(copy.base_fields[0].status,'missing');
});
