const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/web/static/studio.js','utf8');
const code=source.slice(source.indexOf('  function waterStationHeadBalance('), source.indexOf('  function waterStationReview('));
const context={escape:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
  format:v=>typeof v==='number'?v.toLocaleString('ru-RU',{maximumFractionDigits:3}):String(v??'')};
vm.createContext(context);vm.runInContext(code,context);
const render=context.waterStationHeadBalance;
const balance=()=>({status:'current',governing:'V1',method:'Текущий расчёт',local_loss_note:'Местные уже включены',
  coverage_note:'Новая обвязка не подтверждена',paths:[{code:'V1',label:'В1',components:[{label:'Hгеом',value_m:48.2}],
    required_head_m:75.63,guaranteed_head_m:30,pump_head_m:45.63,missing:[]}]});
test('read-only collapsed trace, no new parameters or approval',()=>{
  assert.equal(render(null),'');
  const html=render(balance());
  assert.match(html,/45,63 м/);assert.match(html,/Новая обвязка не подтверждена/);
  assert.doesNotMatch(html,/<input|<select|<details[^>]*\bopen\b/);
  assert.equal((html.match(/<table/g)||[]).length,(html.match(/<\/table>/g)||[]).length);
});
test('unknown head is not zero; stale cache warned',()=>{
  const b=balance();b.status='stale';b.paths[0].pump_head_m=null;b.paths[0].missing=['Нет Hгар'];
  const html=render(b);
  assert.match(html,/нет данных/);assert.match(html,/требует пересчёта/);assert.match(html,/Нет Hгар/);
  assert.doesNotMatch(html,/NaN|undefined/);
});
test('all report text is escaped',()=>{
  const b=balance();b.coverage_note='<script>bad</script>';b.paths[0].label='<img src=x>';
  b.paths[0].components[0].value_m='<svg>';
  const html=render(b);assert.doesNotMatch(html,/<script|<img|<svg/);assert.match(html,/&lt;script&gt;/);
});
