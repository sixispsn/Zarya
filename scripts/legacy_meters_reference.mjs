// Execute the original meter table, checks and central/local branching verbatim.
// Input: {cases:[{hws_type, period_hours, q_sec_c, ...}]} on stdin.
// Parity with this oracle does NOT establish compliance with SP 30.
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const input = JSON.parse(readFileSync(0, 'utf8'));
const html = readFileSync(new URL(input.working_copy ? '../legacy/sp30_calculator.html' :
  '../legacy/archive/sp30_calculator.pre-2026-09-21.html', import.meta.url), 'utf8');
if (input.working_copy && (input.approved_dn65_correction || input.approved_l05_correction)) throw Error('Working copy needs no overlay');
const start = html.indexOf('const METERS = [');
const end = html.indexOf('</script>', start);
const source = html.slice(start, end);
if (start < 0 || end < 0 || !source.includes('function calcMeters()')) {
  throw Error('Legacy meter block not found');
}
const elements = new Map();
const collected = [];
const context = vm.createContext({
  collected,
  document: {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', style: {}});
    return elements.get(id);
  }},
});
vm.runInContext(source, context);
// Explicit, opt-in approved normative delta. The archived HTML remains untouched.
// All branch logic and arithmetic below are still executed from the original JS.
if (input.approved_dn65_correction === true) {
  vm.runInContext('METERS[6].S = 810 * 1e-5', context);
}
if (input.approved_l05_correction === true) {
  // Only the explicitly approved exhausted-catalog fallback changes. The
  // original archive and normal selection/check arithmetic remain untouched.
  const match = source.match(/function pickMeter\(q_sr_hr\) \{[\s\S]*?\n\}/);
  if (!match || !match[0].includes('return METERS[METERS.length-1]')) {
    throw Error('Legacy pickMeter fallback changed');
  }
  vm.runInContext(match[0].replace('return METERS[METERS.length-1]',
    'throw new Error("L05_NO_METER")'), context);
}
// Capture calculator results before presentation; all arithmetic stays original.
vm.runInContext('renderMeter = function(result) { collected.push(result); return ""; }', context);
const cases = (input.cases ?? []).map(c => {
  collected.length = 0;
  const fields = {
    m_gvs_type: c.hws_type ?? 'central', m_T: c.period_hours ?? 24,
    m_qfire: c.q_fire_l_per_s ?? 0, m_vvods: c.inputs_count ?? 1,
    m_bldg: c.is_individual_house ? 'individual' : 'other',
  };
  for (const key of ['q_sec_tot', 'q_sec_c', 'q_sec_h', 'q_day_tot', 'q_day_c', 'q_day_h', 'q_hr_c', 'q_hr_h']) {
    fields[`m_${key}`] = c[key] ?? 0;
  }
  for (const [id, value] of Object.entries(fields)) {
    context.document.getElementById(id).value = String(value);
  }
  for (const key of ['total','cold','hot']) {
    const evidence = c.minimum_checks?.[key] || {};
    for (const [name, field] of Object.entries({dn:'dn_mm',flow:'q_min_hourly_m3h',passport:'q_min_passport_m3h',source:'passport_reference',basis:'flow_reference'})) {
      context.document.getElementById(`minimum_${key}_${name}`).value = String(evidence[field] ?? '');
    }
  }
  context.document.getElementById('meters_result').innerHTML = '';
  try {
    vm.runInContext(input.working_copy ? 'calculateMetersApproved()' : 'calcMeters()', context);
  } catch (error) {
    if ((input.approved_l05_correction && error.message === 'L05_NO_METER') ||
        (input.working_copy && error.message.startsWith('Нет подходящего водомера'))) {
      return {unavailable:true, meters:[]};
    }
    throw error;
  }
  return {
    meters: collected.map(r => ({
      dn: r.m.d, s: r.m.S, h_normal: Number(r.h_a.toFixed(3)),
      h_limit_normal: r.h_limit_a, pass_normal: r.ok_a,
      h_fire: r.h_b === null ? null : Number(r.h_b.toFixed(3)),
      h_limit_fire: r.h_b === null ? null : r.h_limit_b,
      pass_fire: r.h_b === null ? null : r.ok_b,
      need_bypass: r.need_bypass, pass_sensitivity: r.ok_v, need_combo: r.need_combo,
    })),
    one_input_bypass_note: elements.get('meters_result').innerHTML.includes('При одном вводе'),
  };
});
process.stdout.write(JSON.stringify({
  approved_dn65_correction: input.approved_dn65_correction === true,
  approved_l05_correction: input.approved_l05_correction === true,
  source_sha256: createHash('sha256').update(source).digest('hex'),
  table: vm.runInContext('METERS', context), cases,
}));
