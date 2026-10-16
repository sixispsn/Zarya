/* Execute the actual startup script, including an asynchronously restored draft. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/web/static/studio.js', 'utf8');
function element() {
  const classes = new Set();
  return {hidden:false, dataset:{}, textContent:'', open:false, events:{}, attrs:{},
    classList:{add:v=>classes.add(v), remove:v=>classes.delete(v), contains:v=>classes.has(v),
      toggle:(v,on)=>on?classes.add(v):classes.delete(v)},
    setAttribute(k,v){this.attrs[k]=v;}, removeAttribute(k){delete this.attrs[k];},
    addEventListener(k,fn){this.events[k]=fn;}, replaceChildren(){}, close(){this.open=false;},
    focus(){}, scrollIntoView(){}, querySelectorAll(){return [];}};
}
const tick = async () => {for(let i=0;i<30;i++) await Promise.resolve();};
async function start(value, view='home', reject=false) {
  const nodes = new Map(), requests=[];
  const get = key => {if(!nodes.has(key)) nodes.set(key,element());return nodes.get(key);};
  const root = get('#studio'); root.dataset.view=view; root.querySelector=get;
  get('#workspace').hidden=true;get('#entry').hidden=view==='project';
  const location={pathname:'/studio',search:view==='project'?'?view=project':''};
  const window={location,matchMedia:()=>({matches:true}),addEventListener(){},
    ZaryaMotion:{change:async fn=>fn(),stop(){}},
    ZaryaTransport:{decode:async x=>x,presentation:e=>({message:e.message})}};
  vm.runInNewContext(source, {window, document:{getElementById:()=>root},
    fetch:async path=>{requests.push(path);if(reject)throw new Error('offline');return value;},
    setTimeout:()=>0,clearTimeout(){},AbortController,URLSearchParams,location,history:{},
    FormData:class {},console});
  await tick();return {get,root,requests};
}
for (const saved of [
  null,
  {revision:7,fields:[{key:'object_name',value:'Наш дом'}],documents:[]},
  {revision:11,fields:[],documents:[],study:{title:'Учебный дом'}},
]) test(`home remains home after async restore: ${saved?.revision ?? 'no draft'}`,async()=>{
  const h=await start(saved || {draft:null});
  assert.equal(h.get('#entry').hidden,false);
  assert.equal(h.get('#workspace').hidden,true);
  assert.equal(h.get('#busy').hidden,true);
  assert.equal(h.root.classList.contains('compact'),false);
  assert.equal(h.get('#resume-project').hidden,!saved);
  assert.equal(h.get('#studio').attrs['aria-busy'],'false');
  assert.deepEqual(h.requests,['/studio/api/draft']);
});
test('an explicit project URL without a draft offers the start, not an empty form',async()=>{
  const h=await start({draft:null},'project');
  assert.equal(h.get('#entry').hidden,false);
  assert.equal(h.get('#workspace').hidden,true);
  assert.equal(h.get('#resume-project').hidden,true);
});
test('primary UI never calls the copying handoff endpoint',()=>{
  assert.equal(source.includes("api('handoff'"),false);
  assert.equal(source.includes('data-action="handoff"'),false);
  assert.equal(source.includes('/wizard'),false);
});
