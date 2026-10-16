const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const context={window:{}};
vm.runInNewContext(fs.readFileSync('app/web/static/studio_questions.js','utf8'),context);
const steps=draft=>JSON.parse(JSON.stringify(context.window.ZaryaQuestions.steps(draft)));
const base={fields:[],documents:[],next_question:null,calculation:null};

test('no attention for an empty result, a study, or optional missing metadata',()=>{
  assert.deepEqual(steps(null),[]);
  assert.deepEqual(steps({...base,study:{},next_question:'residents'}),[]);
  assert.deepEqual(steps({...base,fields:[{key:'cipher',status:'missing'},{key:'v1_sections',status:'missing'}]}),[]);
});
test('first calculation asks the server blocker, not the whole manual form',()=>{
  assert.deepEqual(steps({...base,next_question:'residents'})[0].fields,['residents']);
});
test('document confirmation contains at most three unresolved fields',()=>{
  const fields=[{key:'accepted',status:'confirmed'},...['a','b','c','d'].map(key=>({key,status:'review'})),{key:'conflict',status:'conflict'}];
  assert.deepEqual(steps({...base,fields,documents:[{}]})[0].fields,['a','b','c']);
  fields.slice(1,4).forEach(row=>row.status='confirmed');
  assert.deepEqual(steps({...base,fields,documents:[{}]})[0].fields,['d','conflict']);
});
test('after calculation exactly the server queue is shown; no extra head-route question',()=>{
  const queue=[{id:'building',fields:['building_height_m']},{id:'storm',fields:['storm_city']}];
  const draft={...base,calculation:{total:3.6},next_steps:queue,head_missing:['v1_sections','t3_sections']};
  assert.deepEqual(steps(draft),queue);
  assert.deepEqual(steps({...draft,next_steps:[]}),[]);
});
