// Execute the working HTML's JavaScript, not a second implementation of it.
// Rain block is unchanged; demand now includes the explicitly approved L01.
// Input: {cases:[{city,roof,walls,period}], residents:[20,...]} on stdin.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const html = readFileSync(new URL('../legacy/sp30_calculator.html', import.meta.url), 'utf8');
const input = JSON.parse(readFileSync(0, 'utf8'));
const start = html.indexOf('const CITIES =');
const rainSource = html.slice(start, html.indexOf('</script>', start));
if (start < 0 || !rainSource.includes('function calcStorm()')) throw Error('legacy rain block not found');
const elements = new Map();
const context = vm.createContext({ document: {
  addEventListener() {},
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', style: {}});
    return elements.get(id);
  },
}});
vm.runInContext(rainSource, context);
const cases = (input.cases ?? []).map(c => {
  for (const [id, value] of Object.entries({storm_F_roof:c.roof, storm_F_walls:c.walls ?? 0, storm_P:c.period ?? 1})) {
    context.document.getElementById(id).value = String(value);
  }
  vm.runInContext(`selectCity(${JSON.stringify(c.city)})`, context);
  const rendered = elements.get('storm_result').innerHTML;
  const q = rendered.match(/\/ 10000 = ([\d.]+) л\/с/);
  const q5 = rendered.match(/q₅ = .*?<b>([\d.]+) л\//);
  const f = rendered.match(/<b>([\d.]+) м²/);
  if (!q || !q5 || !f) throw Error('legacy DOM output not recognized');
  return {flow_lps:Number(q[1]), q5:Number(q5[1]), area:Number(f[1])};
});

// Source tables/functions are extracted verbatim. No copied arithmetic oracle.
const table = name => {
  const from = html.indexOf(`const ${name} = [`);
  return html.slice(from, html.indexOf('];', from)+2);
};
const alphaStart = html.indexOf('function getAlpha(');
const alpha = html.slice(alphaStart, html.indexOf('// ============================================================', alphaStart));
const blockStart = html.indexOf('function calcBlock(');
const block = html.slice(blockStart, html.indexOf('function calculate()', blockStart));
const formatter = html.match(/function f\(v, n=3\).*$/m)?.[0];
if (!formatter) throw Error('legacy formatter missing');
vm.runInContext([table('TBL'), table('B2'), alpha, formatter, block].join('\n'), context);
const residents = (input.residents ?? []).map(count => {
  if (!Number.isInteger(count) || count <= 0) throw Error('invalid resident count');
  const result = vm.runInContext(`calcBlock([{c:TBL[0],U:${count}}], c=>c.q_hr_tot, c=>c.q0_tot, c=>c.q0hr_tot, 'total', [])`, context);
  return {raw_total_lps:result.q_sec, total_lps:Number(result.q_sec.toFixed(3)),
    sewage_lps:Number((result.q_sec+1.6).toFixed(3)), hourly_m3:Number(result.q_hr.toFixed(3))};
});
process.stdout.write(JSON.stringify({cases, residents,
  rain_sha256:createHash('sha256').update(rainSource).digest('hex'),
  cities:vm.runInContext('CITIES', context), gamma:vm.runInContext('GAMMA', context)}));
