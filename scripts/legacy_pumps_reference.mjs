// Archive stays unchanged. Each approved audit correction is an explicit overlay.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';
const input = JSON.parse(readFileSync(0, 'utf8'));
const html = readFileSync(new URL(input.working_copy ? '../legacy/sp30_calculator.html' :
  '../legacy/archive/sp30_calculator.pre-2026-09-21.html', import.meta.url), 'utf8');
if (input.working_copy && (input.approved_l02_correction || input.approved_l03_correction || input.approved_l04_correction)) throw Error('Working copy needs no overlay');
let source = html.slice(html.indexOf('const PUMP_CURVES = ['), html.indexOf('function renderTop3('));
if (input.approved_l02_correction) {
  const old = /const H_stat = H_gar > 0 \? H_gar : 0;[\s\S]*?: 0\.1;/;
  if (!old.test(source)) throw Error('Legacy L02 block changed');
  source = source.replace(old, 'const H_stat = H_geom + H_pr - H_gar; const k_sys = H_l / Q_des / Q_des;');
  source = source.replace('const h_sys = H_stat + k_sys * q * q;',
    'const h_sys = Math.max(0, H_stat + k_sys * q * q);');
}
if (input.approved_l03_correction) {
  const old = /if \(wp\.q < Q_des \* 0\.85\) return null;\s*if \(interpH\(eff_curve, 0\) < Hp_display \* 0\.9\) return null;/;
  if (!old.test(source)) throw Error('Legacy L03 admission block changed');
  source = source.replace(old,
    `if (Q_des < eff_curve[0].q || Q_des ${input.approved_l04_correction ? '>' : '>='} eff_curve[eff_curve.length-1].q || interpH(eff_curve, Q_des) < Hp_display - 1e-9) return null;`);
}
if (input.approved_l04_correction) {
  const oldInterp = /function interpH\(curve, q\) \{[\s\S]*?\n\}/;
  const oldFind = /function findWorkingPoint\(curve, H_stat, k_sys, pump_mode\) \{[\s\S]*?\n\}/;
  if (!oldInterp.test(source) || !oldFind.test(source)) throw Error('Legacy L04 functions changed');
  source = source.replace(oldInterp, `function interpH(curve, q) {
    if (q < curve[0].q || q > curve[curve.length-1].q) return null;
    for (let i=0; i<curve.length-1; i++) {
      const a=curve[i], b=curve[i+1];
      if (q >= a.q && q <= b.q) return a.h+(b.h-a.h)*(q-a.q)/(b.q-a.q);
    }
    return null;
  }`);
  // Independent algebraic oracle. Python brackets monotonic residual intervals.
  source = source.replace(oldFind, `function findWorkingPoint(curve, H_stat, k_sys) {
    const roots=[];
    let coincident=false;
    function add(q,a,b) {
      if (!Number.isFinite(q) || q < a.q-1e-10 || q > b.q+1e-10) return;
      q=Math.max(a.q,Math.min(b.q,q));
      const h=interpH(curve,q), h_sys=Math.max(0,H_stat+k_sys*q*q);
      if (Math.abs(h-h_sys)>1e-8 || roots.some(p=>Math.abs(p.q-q)<1e-9)) return;
      roots.push({q,h,h_sys});
    }
    for (let i=0; i<curve.length-1; i++) {
      const a=curve[i], b=curve[i+1], m=(b.h-a.h)/(b.q-a.q), c=a.h-m*a.q;
      add(a.q,a,b); add(b.q,a,b);
      if (m===0 && ((k_sys===0 && a.h===Math.max(0,H_stat)) ||
          (a.h===0 && H_stat+k_sys*a.q*a.q<0))) coincident=true;
      if (m!==0) add(-c/m,a,b); // inactive/clamped system curve
      if (k_sys===0) {
        if (m!==0) add((H_stat-c)/m,a,b);
      } else {
        const d=m*m-4*k_sys*(H_stat-c);
        if (d>=0) {
          add((m+Math.sqrt(d))/(2*k_sys),a,b);
          add((m-Math.sqrt(d))/(2*k_sys),a,b);
        }
      }
    }
    return !coincident && roots.length===1 ? roots[0] : null;
  }`);
}
const elements = new Map();
const context = vm.createContext({document:{
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, {value:'',style:{},innerHTML:'',textContent:''});
    return elements.get(id);
  },
  querySelector() { return {value:'manual'}; },
}});
vm.runInContext(source, context);
vm.runInContext(`
var captured;
function drawChart(curve,hstat,k,wp) {captured = {hstat,k,wp,candidates:[]};}
function renderTop3(results,hp,q) {
  captured.hp=hp; captured.q=q;
  captured.candidates=results.map(r=>({model:r.pump.model,wp:r.wp,score:r.score,npsh_ok:r.npsh_ok,reasons:r.reasons}));
}
`, context);
const cases = input.cases.map(c => {
  for (const [id,value] of Object.entries({
    h_geom_manual:c.geom,h_losses:c.loss,h_pr:20,h_gar:c.gar,
    q_design:c.q,pump_sel_type:'boost',pump_count_sel:c.mode||'1',
    npsh_a:Object.hasOwn(c,'npsh_a') ? c.npsh_a : 8,
  })) context.document.getElementById(id).value=value === null ? '' : String(value);
  vm.runInContext('captured=null; calcPumpHead();',context);
  const result = vm.runInContext('captured',context);
  if (input.capture_ui) result.ui = {
    result:context.document.getElementById('hp_result').textContent,
    formula:context.document.getElementById('hp_formula').textContent,
    recommendation:context.document.getElementById('pump_rec_result').textContent,
  };
  return result;
});
const probes = (input.probes || []).map(p => {
  context.probe = p;
  return vm.runInContext('findWorkingPoint(probe.curve, probe.hstat, probe.k)', context);
});
const npsha = (input.npsha || []).map(data => {
  context.npshaInput = data;
  try { return vm.runInContext('calculateNpsha(npshaInput)', context); }
  catch (error) { return {error:error.message}; }
});
process.stdout.write(JSON.stringify({
  source_sha256:createHash('sha256').update(html).digest('hex'),
  approved_l02_correction:Boolean(input.approved_l02_correction),cases,
  approved_l03_correction:Boolean(input.approved_l03_correction),
  approved_l04_correction:Boolean(input.approved_l04_correction), probes, npsha,
}));
