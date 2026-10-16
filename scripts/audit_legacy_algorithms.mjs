// Read-only diagnostic probes, NOT approval tests or corrected algorithms.
// Execute original legacy functions verbatim. Only DOM/presentation are stubbed.
// Run: node scripts/audit_legacy_algorithms.mjs
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const html = readFileSync(new URL('../legacy/archive/sp30_calculator.pre-2026-09-21.html', import.meta.url), 'utf8');
function block(startToken, endToken) {
  const start = html.indexOf(startToken);
  const end = html.indexOf(endToken, start);
  if (start < 0 || end <= start) throw Error(`Legacy block not found: ${startToken}`);
  return html.slice(start, end);
}
function sandbox() {
  const elements = new Map();
  const context = vm.createContext({
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {
          value: '', checked: false, textContent: '', innerHTML: '', style: {}, children: [],
        });
        return elements.get(id);
      },
      querySelector() { return { value: 'manual' }; },
    },
  });
  return { context, elements, run: source => vm.runInContext(source, context) };
}

const flow = sandbox();
flow.run(block('const TBL = [', 'addGroup(17, 480);'));
const alpha = flow.run(`({
  below_boundary: getAlpha(62.999), at_boundary: getAlpha(63),
  above_boundary: getAlpha(63.001), stored_boundary: B2.at(-1),
  stored_12: B2.find(p => p[0] === 12), calculated_70: getAlpha(70),
})`);
const residential = [500, 1629, 1630, 5865, 5866].map(residents => {
  const total = flow.run(`calcBlock([{c:TBL[0],U:${residents}}],
    c=>c.q_hr_tot, c=>c.q0_tot, c=>c.q0hr_tot, 'total', [])`);
  return { residents, ...total, day_m3: residents * flow.run('TBL[0].qu_tot') / 1000 };
});
flow.context.document.getElementById('k06_check').checked = true;
flow.context.document.getElementById('groups').children = [{
  querySelector(selector) { return { value: selector === 'select' ? '17' : '480' }; },
}];
let coefficient06Error = null;
try { flow.run('calculate()'); } catch (error) { coefficient06Error = `${error.name}: ${error.message}`; }

const pump = sandbox();
pump.run(block('const PUMP_CURVES = [', 'function renderTop3('));
// Capture results before presentation, without replacing the selection logic.
pump.run(`
  var captured;
  function drawChart(curve, hstat, k, wp, selected) {
    captured = {curve, hstat, k, wp, selected};
  }
  function renderTop3(results, hp, q) {
    captured.results = results;
    captured.hp = hp;
    captured.q = q;
  }
`);
const pumpCases = [
  { name: 'system_curve', geom: 25, loss: 5, gar: 40, q: 5 },
  { name: 'undersized_candidate', geom: 6, loss: 5, gar: 5, q: 10 },
  { name: 'baseline', geom: 25, loss: 5, gar: 20, q: 5 },
].map(c => {
  const values = {
    h_geom_manual: c.geom, h_losses: c.loss, h_pr: 20, h_gar: c.gar,
    q_design: c.q, pump_sel_type: 'boost', pump_count_sel: '1', npsh_a: 8,
  };
  for (const [id, value] of Object.entries(values)) {
    pump.context.document.getElementById(id).value = String(value);
  }
  pump.run('captured = null; calcPumpHead();');
  const actual = pump.run(`({
    hp: captured.hp, hstat: captured.hstat, k: captured.k,
    system_at_design: captured.hstat + captured.k * captured.q ** 2,
    candidates: captured.results.map(r => ({
      model:r.pump.model, wp:r.wp, score:r.score,
      head_at_design:interpH(r.eff_curve, captured.q), reasons:r.reasons,
    })),
  })`);
  return { input: c, actual };
});
const curveEndpoints = pump.run(`PUMP_CURVES.map(p => ({
  model:p.model, stored:p.curve.at(-1),
  calculated:interpH(p.curve, p.curve.at(-1).q),
}))`);
const nonexistentIntersection = pump.run(`findWorkingPoint(
  PUMP_CURVES[1].curve, 140, 0.1)`);

const meter = sandbox();
meter.run(block('const METERS = [', '</script>'));
const meterOverflow = meter.run(`(() => {
  const m = pickMeter(400);
  const r = checkMeter(m, 120, 0, 432, 'audit', false);
  return {q_average:400, q_expl:m.qexpl, dn:m.d, h:r.h_a,
    pass_normal:r.ok_a, pass_sensitivity:r.ok_v, need_combo:r.need_combo};
})()`);

process.stdout.write(JSON.stringify({
  mode: 'audit_only_no_corrections',
  source_sha256: createHash('sha256').update(html).digest('hex'),
  alpha, residential, pump_cases: pumpCases, curve_endpoints: curveEndpoints,
  nonexistent_intersection: nonexistentIntersection,
  meter_overflow: meterOverflow,
  previously_known_coefficient06_error: coefficient06Error,
}, null, 2) + '\n');
