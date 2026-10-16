// Original calcBlock execution; the L01 correction is an explicit opt-in overlay.
// The archived HTML, TBL, calcBlock, flow and heat formulas remain untouched.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const input = JSON.parse(readFileSync(0, 'utf8'));
const html = readFileSync(new URL(input.working_copy ? '../legacy/sp30_calculator.html' :
  '../legacy/archive/sp30_calculator.pre-2026-09-21.html', import.meta.url), 'utf8');
if (input.working_copy && input.approved_l01_correction) throw Error('Working copy needs no overlay');
const start = html.indexOf('const TBL = [');
const end = html.indexOf('addGroup(17, 480);', start);
if (start < 0 || end < start) throw Error('Legacy demand block not found');
const context = vm.createContext({});
vm.runInContext(html.slice(start, end), context);
if (input.approved_l01_correction === true) {
  const fixture = JSON.parse(readFileSync(
    new URL('../tests/fixtures/sp30_b2_official.json', import.meta.url), 'utf8'));
  context.correctedTable = fixture.rows.map(([x, y]) => [Number(x), Number(y)]);
  vm.runInContext(`
    B2.splice(0, B2.length, ...correctedTable);
    getAlpha = function(np) {
      if (!Number.isFinite(np)) throw Error('NP must be finite');
      if (np < B2[0][0]) return 0.2;
      if (np > B2.at(-1)[0]) throw Error('NP exceeds B.2');
      const right = B2.findIndex(p => p[0] >= np);
      if (B2[right][0] === np) return B2[right][1];
      const [x0, y0] = B2[right - 1], [x1, y1] = B2[right];
      return y0 + (np - x0) / (x1 - x0) * (y1 - y0);
    };
  `, context);
}
context.cases = input.cases;
context.points = input.points || [];
const result = vm.runInContext(`({
  alpha: points.map(getAlpha),
  cases: cases.map(items => {
    const groups = items.map(g => {
      const c = TBL.find(c => c.label === g.label);
      if (!c) throw Error('Unknown consumer');
      return {c, U:g.count};
    });
    return {
      total:calcBlock(groups,c=>c.q_hr_tot,c=>c.q0_tot,c=>c.q0hr_tot,'total',[]),
      cold:calcBlock(groups,c=>c.q_hr_tot-c.q_hr_h,c=>c.q0_c,c=>c.q0hr_c,'cold',[]),
      hot:calcBlock(groups,c=>c.q_hr_h,c=>c.q0_h,c=>c.q0hr_h,'hot',[]),
    };
  }),
})`, context);
process.stdout.write(JSON.stringify({
  source_sha256:createHash('sha256').update(html).digest('hex'),
  approved_l01_correction:input.approved_l01_correction === true,
  ...result,
}));
