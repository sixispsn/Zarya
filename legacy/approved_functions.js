// Source fragments for the standalone working HTML. Archive is never rewritten.
// BEGIN getAlpha
function getAlpha(np) {
  if (!Number.isFinite(np)) throw new RangeError('NP должен быть конечным числом');
  if (np < B2[0][0]) return 0.2;
  if (np > B2[B2.length - 1][0]) throw new RangeError('NP выходит за таблицу Б.2; экстраполяция запрещена');
  const right = B2.findIndex(p => p[0] >= np);
  if (B2[right][0] === np) return B2[right][1];
  const [x0, y0] = B2[right - 1], [x1, y1] = B2[right];
  return y0 + (np - x0) / (x1 - x0) * (y1 - y0);
}
// END getAlpha

// BEGIN interpH
function interpH(curve, q) {
  if (!Number.isFinite(q) || q < curve[0].q || q > curve[curve.length - 1].q) return null;
  for (let i = 0; i < curve.length - 1; i++) {
    const a = curve[i], b = curve[i + 1];
    if (q >= a.q && q <= b.q) return a.h + (b.h - a.h) * (q - a.q) / (b.q - a.q);
  }
  return null;
}
// END interpH

// BEGIN findWorkingPoint
function findWorkingPoint(curve, H_stat, k_sys) {
  if (!Number.isFinite(H_stat) || !Number.isFinite(k_sys) || k_sys < 0) return null;
  const roots = [];
  let coincident = false;
  function add(q, a, b) {
    if (!Number.isFinite(q) || q < a.q - 1e-10 || q > b.q + 1e-10) return;
    q = Math.max(a.q, Math.min(b.q, q));
    const h = interpH(curve, q), h_sys = Math.max(0, H_stat + k_sys * q * q);
    if (h === null || Math.abs(h - h_sys) > 1e-8 || roots.some(p => Math.abs(p.q - q) < 1e-9)) return;
    roots.push({q, h, h_sys});
  }
  for (let i = 0; i < curve.length - 1; i++) {
    const a = curve[i], b = curve[i + 1], m = (b.h - a.h) / (b.q - a.q), c = a.h - m * a.q;
    add(a.q, a, b); add(b.q, a, b);
    if (m === 0 && ((k_sys === 0 && a.h === Math.max(0, H_stat)) ||
        (a.h === 0 && H_stat + k_sys * a.q * a.q < 0))) coincident = true;
    if (m !== 0) add(-c / m, a, b);
    if (k_sys === 0) {
      if (m !== 0) add((H_stat - c) / m, a, b);
    } else {
      const d = m * m - 4 * k_sys * (H_stat - c);
      if (d >= 0) {
        // Stable quadratic roots; do not lose a near-zero intersection.
        const numerator = (m + (m >= 0 ? 1 : -1) * Math.sqrt(d)) / 2;
        if (numerator !== 0) {
          add(numerator / k_sys, a, b);
          add((H_stat - c) / numerator, a, b);
        } else add(0, a, b);
      }
    }
  }
  return !coincident && roots.length === 1 ? roots[0] : null;
}
// END findWorkingPoint

// BEGIN pickMeter
function pickMeter(q_sr_hr) {
  if (!Number.isFinite(q_sr_hr) || q_sr_hr < 0) throw new RangeError('Недопустимый средний расход');
  for (const m of METERS) if (m.qexpl >= q_sr_hr) return m;
  throw new RangeError('Нет подходящего водомера: Qсред=' + q_sr_hr +
    ' м³/ч превышает Qэкспл=' + METERS[METERS.length - 1].qexpl +
    ' м³/ч. Максимальный DN не принимается автоматически.');
}
// END pickMeter

// BEGIN meterMinimum
function meterMinimum(dn, label) {
  const key = /вводе/.test(label) ? 'total' : /ГВС|нагревателем/.test(label) ? 'hot' : 'cold';
  const raw = name => String(document.getElementById('minimum_' + key + '_' + name)?.value || '').trim();
  const d = Number(raw('dn')), actual = Number(raw('flow')), passport = Number(raw('passport'));
  if (!raw('dn') || !raw('flow') || !raw('passport') || !raw('source') || !raw('basis') ||
      d !== dn || !Number.isInteger(d) || !Number.isFinite(actual) || actual < 0 ||
      !Number.isFinite(passport) || passport <= 0) return null;
  return passport <= actual;
}
// END meterMinimum

// BEGIN circulation
// L07: чистая циркуляция — отдельная пара Q/H, без повысительного баланса.
function circulationCandidates(q, head, basis, mode = '1', npsh = null) {
  if (!Number.isFinite(q) || q <= 0 || !Number.isFinite(head) || head <= 0 ||
      typeof basis !== 'string' || !basis.trim())
    throw new RangeError('Т4: задайте положительные Q циркуляции, напор по кольцу и основание расчёта.');
  if (!['1', '2p', '2s'].includes(mode)) throw new RangeError('Неизвестный режим насосов');
  if (npsh !== null && (!Number.isFinite(npsh) || npsh < 0))
    throw new RangeError('Недопустимый NPSHa циркуляционного насоса');
  const candidates = PUMP_CURVES.filter(p => p.type === 'circ').map(pump => {
    const curve = buildEffectiveCurve(pump.curve, mode);
    if (curve.length < 2 || curve.some((p, i) => !Number.isFinite(p.q) ||
        !Number.isFinite(p.h) || p.q < 0 || p.h < 0 || (i && curve[i - 1].q >= p.q))) return null;
    const h = interpH(curve, q);
    if (h === null || h < head - 1e-9) return null;
    const ratio = q / (pump.Q_opt * (mode === '2p' ? 2 : 1));
    const excess = (h - head) / head * 100;
    let score = 100;
    if (ratio >= .7 && ratio <= 1.1) score += 30;
    else if (ratio >= .6 && ratio <= 1.2) score += 15;
    else score -= 20;
    if (excess >= 5 && excess <= 20) score += 20;
    else if (excess >= 0 && excess <= 35) score += 5;
    else if (excess > 35) score -= 15;
    else score -= 30;
    score += 20; // тот же legacy-рейтинг при Q = Qрасч, не найденное пересечение
    const npsh_ok = npsh === null || pump.NPSHr == null ? null : npsh >= pump.NPSHr + .5;
    if (npsh_ok === false) score -= 50;
    return {pump, eff_curve: curve, q, head_at_design: h, score, npsh_ok};
  }).filter(Boolean).sort((a, b) => b.score - a.score).slice(0, 3);
  return {q_design: q, h_required: head, h_geom: null, h_stat: null, k_sys: null,
    curve_kind: 'duty_only', basis: basis.trim(), candidates};
}

function calcCirculationHead() {
  const box = document.getElementById('pump_rec_result');
  box.replaceChildren();
  document.getElementById('hp_result').textContent = 'Нужны данные Т4';
  document.getElementById('hp_formula').textContent = '';
  drawChart(null, null, null, null, null);
  const value = id => document.getElementById(id).value.trim();
  try {
    const result = circulationCandidates(
      value('circ_q') ? Number(value('circ_q')) : NaN,
      value('circ_head') ? Number(value('circ_head')) : NaN,
      value('circ_basis'), value('pump_count_sel'),
      value('circ_npsh') ? Number(value('circ_npsh')) : null,
    );
    document.getElementById('hp_result').textContent = result.h_required.toFixed(2) + ' м';
    document.getElementById('hp_formula').textContent = 'Напор по циркуляционному кольцу, не по этажности';
    const paragraph = text => {
      const p = document.createElement('p'); p.textContent = text; box.append(p);
    };
    paragraph('Предварительно по паре Q/H. Кривая системы и фактическая рабочая точка не определены. ' +
      'Пригодность материалов для питьевой горячей воды, температуру, статическое давление и регулирование проверить отдельно.');
    paragraph('Основание: ' + result.basis);
    if (!result.candidates.length) paragraph('Нет подходящего кандидата. Требуемые Q/H не уменьшаются под каталог.');
    result.candidates.forEach(r => {
      paragraph(r.pump.brand + ' ' + r.pump.model + ': Qрасч = ' + r.q.toFixed(3) +
        ' м³/ч; Hкат(Qрасч) = ' + r.head_at_design.toFixed(3) + ' м ≥ Hтреб = ' +
        result.h_required.toFixed(3) + ' м. NPSH: ' + (r.npsh_ok === null ? 'нет данных' :
        r.npsh_ok ? 'по введённому NPSHa и справочному NPSHr' : 'условие не выполнено') + '.');
    });
    if (result.candidates.length) drawCirculationChart(result);
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    box.textContent = error.message;
  }
}

function drawCirculationChart(result) {
  const curve = result.candidates[0].eff_curve;
  const qmax = curve.at(-1).q * 1.1;
  const hmax = Math.max(...curve.map(p => p.h), result.h_required) * 1.15;
  const sx = q => 55 + q / qmax * 520, sy = h => 270 - h / hmax * 245;
  let svg = '<rect x="55" y="25" width="520" height="245" fill="#fafafa" stroke="#999"/>';
  for (let i = 0; i <= 5; i++) {
    const q = qmax * i / 5, h = hmax * i / 5;
    svg += `<line x1="55" y1="${sy(h)}" x2="575" y2="${sy(h)}" stroke="#ddd"/>`;
    svg += `<text x="48" y="${sy(h) + 4}" text-anchor="end" font-size="11">${h.toFixed(1)}</text>`;
    svg += `<text x="${sx(q)}" y="290" text-anchor="middle" font-size="11">${q.toFixed(1)}</text>`;
  }
  svg += '<text x="15" y="20" font-size="12">H, м</text><text x="480" y="313" font-size="12">Q, м³/ч</text>';
  svg += `<polyline points="${curve.map(p => `${sx(p.q)},${sy(p.h)}`).join(' ')}" fill="none" stroke="#1a6aaa" stroke-width="2"/>`;
  svg += `<rect data-role="required-duty" x="${sx(result.q_design) - 4}" y="${sy(result.h_required) - 4}" width="8" height="8" fill="#b05b00"/>`;
  document.getElementById('pump_chart').innerHTML = svg;
}
// END circulation
// BEGIN npsha
// CNP CDM/CDMF catalogue, 24.11.2025, p. 18. Separate explicit-input method.
function calculateNpsha(data) {
  const d = {...data};
  const numbers = ['pressure_bar','atmospheric_pressure_bar','source_elevation_m',
    'pump_elevation_m','suction_losses_m','vapor_head_m','max_flow_m3h',
    'temperature_c','npshr_m','safety_margin_m'];
  if (d.safety_margin_m === undefined) d.safety_margin_m = 0.5;
  for (const key of numbers) {
    if (d[key] === undefined) d[key] = null;
    if (d[key] !== null && (typeof d[key] !== 'number' || !Number.isFinite(d[key])))
      throw new RangeError(key + ': требуется конечное число');
  }
  if (!['absolute','gauge',null,undefined].includes(d.pressure_kind))
    throw new RangeError('Укажите вид давления: absolute или gauge');
  for (const key of ['suction_losses_m','vapor_head_m','npshr_m'])
    if (d[key] !== null && d[key] < 0) throw new RangeError(key + ': значение не может быть отрицательным');
  for (const key of ['atmospheric_pressure_bar','max_flow_m3h'])
    if (d[key] !== null && d[key] <= 0) throw new RangeError(key + ': требуется положительное значение');
  if (d.safety_margin_m === null || d.safety_margin_m < 0.5)
    throw new RangeError('Запас Hs по CNP должен быть не менее 0,5 м');
  if (d.pressure_kind === 'absolute' && d.atmospheric_pressure_bar !== null)
    throw new RangeError('К абсолютному давлению атмосферное повторно не прибавляется');
  let pressure = d.pressure_bar;
  if (d.pressure_kind === 'gauge') pressure = pressure !== null && d.atmospheric_pressure_bar !== null
    ? pressure + d.atmospheric_pressure_bar : null;
  if (d.pressure_kind && pressure !== null && pressure <= 0)
    throw new RangeError('Абсолютное давление должно быть положительным');
  const required = ['pressure_kind','pressure_bar','source_elevation_m','pump_elevation_m',
    'suction_losses_m','vapor_head_m','max_flow_m3h','temperature_c'];
  if (d.pressure_kind === 'gauge') required.push('atmospheric_pressure_bar');
  const missing = required.filter(key => d[key] === null || d[key] === undefined);
  if (!(d.basis || '').trim()) missing.push('basis');
  const result = {status:'needs_data',available_m:null,required_m:null,margin_m:null,
    check_ok:null,absolute_pressure_bar:null,elevation_difference_m:null,missing,
    method:'cnp_cdm_cdmf_p18',formula:'NPSHa = 10.2·Pb(abs) + z_source - z_pump - Hf - Hv',
    source:'CNP CDM/CDMF, каталог 24.11.2025, с. 18'};
  if (missing.length) return result;
  const delta = d.source_elevation_m - d.pump_elevation_m;
  const available = 10.2 * pressure + delta - d.suction_losses_m - d.vapor_head_m;
  if (!Number.isFinite(available)) throw new RangeError('Переполнение расчёта NPSHa: проверьте исходные данные');
  Object.assign(result, {status:'available_only',available_m:available,
    absolute_pressure_bar:pressure,elevation_difference_m:delta});
  if (d.npshr_m === null) missing.push('npshr_m');
  if (!(d.npshr_basis || '').trim()) missing.push('npshr_basis');
  if (!missing.length) {
    result.required_m = d.npshr_m + d.safety_margin_m;
    result.margin_m = available - result.required_m;
    if (!Number.isFinite(result.required_m) || !Number.isFinite(result.margin_m))
      throw new RangeError('Переполнение сравнения NPSH: проверьте исходные данные');
    result.check_ok = available >= result.required_m;
    result.status = result.check_ok ? 'margin_satisfied' : 'insufficient_margin';
  }
  return result;
}

function renderNpshaBalance() {
  const box = document.getElementById('npsha_balance_result');
  box.textContent = ''; // No stale success on deleted/invalid inputs.
  const data = {}, names = {};
  for (const input of document.querySelectorAll('[data-npsha-field]')) {
    const key = input.dataset.npshaField;
    names[key] = input.dataset.label;
    data[key] = input.type === 'number'
      ? (input.value.trim() === '' ? null : Number(input.value)) : input.value;
    if (key === 'pressure_kind' && !input.value) data[key] = null;
  }
  const gauge = data.pressure_kind === 'gauge';
  document.getElementById('npsha_atmospheric_label').hidden = !gauge;
  if (!gauge) data.atmospheric_pressure_bar = null;
  try {
    const result = calculateNpsha(data);
    if (result.available_m === null) {
      box.textContent = 'Нужны данные: ' + result.missing.map(key => names[key] || key).join('; ');
      return;
    }
    box.textContent = 'NPSHa = ' + result.available_m.toFixed(3) + ' м. ';
    if (result.check_ok === null) box.textContent += 'Проверка не завершена: ' + result.missing.map(key => names[key] || key).join('; ');
    else box.textContent += (result.check_ok ? 'Условие NPSHa ≥ NPSHr + Hs выполнено' : 'Недостаточный запас NPSHa') +
      '; разность ' + result.margin_m.toFixed(3) + ' м. Только заданный режим; не разрешение пуска.';
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    box.textContent = error.message;
  }
}
// END npsha

