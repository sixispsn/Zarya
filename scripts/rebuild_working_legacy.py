#!/usr/bin/env python3
"""Reproduce the working HTML from the immutable archive and approved deltas.

This is a mechanical build, not a second formula oracle. --check never writes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'legacy/archive/sp30_calculator.pre-2026-09-21.html'
WORKING = ROOT / 'legacy/sp30_calculator.html'
ARCHIVE_SHA = 'ace54b14e2f30fadaec768ec06aa5a326553709b9a869263208ef8ee58df3788'


def build() -> str:
    raw = ARCHIVE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError('Immutable legacy archive fingerprint changed')
    text = raw.decode('utf-8')
    fragments = (ROOT / 'legacy/approved_functions.js').read_text()

    def fragment(name):
        return fragments.split('// BEGIN ' + name + '\n', 1)[1].split('// END ' + name, 1)[0].strip()

    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError('Unexpected legacy anchor: ' + old[:80])
        text = text.replace(old, new, 1)

    def replace_function(name):
        nonlocal text
        text, count = re.subn(r'function ' + name + r'\([^\n]*\) \{[\s\S]*?\n\}',
                              lambda _: fragment(name), text, count=1)
        if count != 1:
            raise ValueError('Missing function ' + name)

    rows = json.loads((ROOT / 'tests/fixtures/sp30_b2_official.json').read_text())['rows']
    table = 'const B2 = [\n' + '\n'.join('  [' + str(x) + ', ' + str(y) + '],'
                                              for x, y, _ in rows) + '\n];'
    text, count = re.subn(r'const B2 = \[[\s\S]*?\n\];', lambda _: table, text, count=1)
    if count != 1:
        raise ValueError('Missing B2')
    for name in ('getAlpha', 'pickMeter', 'interpH', 'findWorkingPoint'):
        replace_function(name)

    # Earlier approved meter corrections: use the actual DN65 coefficient and
    # independent minimum evidence. No peak-flow proxy or invented passport.
    replace('METERS[6].S  = 81   * 1e-5;   // 0.00081',
            'METERS[6].S  = 810  * 1e-5;   // 0.0081 — approved DN65 correction')
    replace('function checkMeter(', fragment('meterMinimum') + '\n\nfunction checkMeter(')
    replace('const ok_v = m.qthr <= q_hr;', 'const ok_v = meterMinimum(m.d, label);')
    replace('result.need_combo = ok_a && !ok_v && m.d > 15;',
            'result.need_combo = ok_a && ok_v === false && m.d > 15;')
    replace('Принят: <b>∅${r.m.d} мм</b>',
            '${r.ok_a && r.ok_v === true ? "Подобран по выполненным проверкам" : "Кандидат; проверка не завершена"}: <b>∅${r.m.d} мм</b>')
    replace('> ${r.h_limit_a} м ✗ → принят больший диаметр',
            '> ${r.h_limit_a} м ✗ → водомер не подходит по потерям')
    replace("html += `✦ Проверка в): q<sub>min</sub> счётчика = ${r.m.qthr} м³/ч `;",
            "html += `✦ Проверка в): паспортный минимум ≤ минимального расчётного часового расхода: `;")
    replace('if (r.ok_v) {', '''if (r.ok_v === null) {
    html += 'Нужны паспорт выбранного DN и обоснование минимального расхода. Максимальный расход не заменяет минимум.';
  } else if (r.ok_v) {''')

    # Atomic UI failure: do not leave the last accepted selection on screen.
    replace('function calcMeters() {', '''function calcMeters() {
  const box = document.getElementById('meters_result');
  box.innerHTML = '';
  try { return calculateMetersApproved(); }
  catch (error) {
    if (!(error instanceof RangeError)) throw error;
    box.textContent = error.message;
    box.style.display = 'block';
  }
}
function calculateMetersApproved() {''')
    replace("const T         = +document.getElementById('m_T').value || 24;",
            "const T = Number(document.getElementById('m_T').value);\n  if (!Number.isFinite(T) || T <= 0) throw new RangeError('Нужен положительный период водопотребления T');")
    ui = ['<details style="margin:1rem 0"><summary>Паспортная проверка минимальных расходов (п. 12.16в)</summary>',
          '<p>Заполняется для окончательно выбранного DN. Без подтверждения — только кандидат, не готовый подбор.</p>']
    for key, label in (('total', 'Общий ввод'), ('cold', 'ХВС'), ('hot', 'ГВС')):
        ui.append('<fieldset><legend>' + label + '</legend>')
        for name, title, kind in (('dn', 'DN паспорта', 'number'), ('flow', 'Минимальный расчётный расход, м³/ч', 'number'),
                                  ('passport', 'Минимальный паспортный расход, м³/ч', 'number'),
                                  ('source', 'Модель и ссылка на паспорт', 'text'), ('basis', 'Основание расчётного минимума', 'text')):
            ui.append(f'<label style="display:block">{title} <input id="minimum_{key}_{name}" type="{kind}" '
                      'step="any" oninput="calcMeters()"></label>')
        ui.append('</fieldset>')
    ui.append('</details>')
    replace('<div id="meters_result"', '\n'.join(ui) + '\n<div id="meters_result"')

    # Approved L02–L04, including the chart and insufficient-input path.
    start = text.index('  // Кривая системы: H_сист')
    end = text.index('  // Подбор насосов', start)
    text = text[:start] + '''  // L02: оценочная кривая, согласованная с балансом напора.
  const H_stat = H_geom + H_pr - H_gar;
  const k_sys = H_l / Q_des / Q_des;
  if (Hp <= 0) {
    document.getElementById('pump_rec_result').textContent = 'Гарантированного напора достаточно; повысительный насос не требуется.';
    drawChart(null, null, null, null, null);
    return;
  }

''' + text[end:]
    replace('if (wp.q < Q_des * 0.85) return null;\n    if (interpH(eff_curve, 0) < Hp_display * 0.9) return null;',
            'const atDuty = interpH(eff_curve, Q_des);\n    if (atDuty === null || atDuty < Hp_display - 1e-9) return null;')
    replace('const h = H_stat + k_sys * q * q;', 'const h = Math.max(0, H_stat + k_sys * q * q);')
    replace('function calcPumpHead() {', '''function calcPumpHead() {
  const required = ['h_losses', 'h_pr', 'h_gar', 'q_design'];
  if (document.querySelector('input[name="hgeom_mode"]:checked').value === 'manual') required.push('h_geom_manual');
  const bad = required.some(id => {
    const value = document.getElementById(id).value;
    return String(value).trim() === '' || !Number.isFinite(Number(value)) ||
      (id !== 'h_geom_manual' && Number(value) < 0) || (id === 'q_design' && Number(value) <= 0);
  });
  if (bad) {
    document.getElementById('hp_result').textContent = 'Нужны данные';
    document.getElementById('hp_formula').textContent = '';
    document.getElementById('pump_rec_result').textContent = 'Задайте геометрию, потери, свободный и гарантированный напор и положительный расчётный расход.';
    drawChart(null, null, null, null, null);
    return;
  }''')
    replace("const H_pr  = +document.getElementById('h_pr').value     || 20;",
            "const H_pr = Number(document.getElementById('h_pr').value);")
    replace('value="5" step="0.5" min="0" oninput="calcPumpHead()"',
            'value="" placeholder="Введите рассчитанные потери" step="0.5" min="0" oninput="calcPumpHead()"')
    replace('Скорректируйте параметры или добавьте насосы через импорт CSV.',
            'Не уменьшайте потребность под каталог; нужен подтверждённый подходящий насос.')
    replace('Рекомендации — Top-3', 'Предварительные кандидаты — Top-3 (оценочная кривая)')

    # L08 (15.10.2026): unknown NPSHa is not 8 m and is not a successful check.
    replace('id="npsh_a" value="8"', 'id="npsh_a" value="" placeholder="Не задан — проверка не завершена"')
    replace("const npsh_a = +document.getElementById('npsh_a').value || 8;", '''const npshRaw = document.getElementById('npsh_a').value.trim();
  const npsh_a = npshRaw === '' ? null : Number(npshRaw);
  if (npsh_a !== null && (!Number.isFinite(npsh_a) || npsh_a < 0)) {
    document.getElementById('hp_result').textContent = 'Ошибка исходных данных';
    document.getElementById('hp_formula').textContent = '';
    document.getElementById('pump_rec_result').textContent = 'NPSHa должен быть конечным неотрицательным числом или оставаться пустым.';
    drawChart(null, null, null, null, null);
    return;
  }''')
    replace('const npsh_ok = npsh_a >= pump.NPSHr + 0.5;',
            'const npsh_ok = npsh_a === null ? null : npsh_a >= pump.NPSHr + 0.5;')
    replace('if (!npsh_ok) score -= 50;', 'if (npsh_ok === false) score -= 50;')
    replace('    if (!npsh_ok)\n      reasons.push(`✗ КАВИТАЦИЯ:',
            "    if (npsh_ok === null) reasons.push('⚠ NPSHa не задан; проверка кавитационного запаса не завершена');\n    else if (npsh_ok === false)\n      reasons.push(`✗ КАВИТАЦИЯ:")
    replace('function calcPumpHead() {', fragment('npsha') + '\n\nfunction calcPumpHead() {')
    npsha_ui = (ROOT / 'legacy/npsha_inputs.html').read_text()
    replace('      <!-- H_geom - два режима -->', npsha_ui + '\n      <!-- H_geom - два режима -->')

    # L07: separate blank inputs prevent reuse of booster/draw-off defaults.
    replace('      <!-- H_geom - два режима -->', '<div id="boost_head_inputs">\n      <!-- H_geom - два режима -->')
    replace('      <div style="background:#fff;border-radius:6px;padding:.6rem .875rem;border:2px solid #90c8f0">',
            '</div>\n' + (ROOT / 'legacy/circulation_inputs.html').read_text() +
            '\n      <div style="background:#fff;border-radius:6px;padding:.6rem .875rem;border:2px solid #90c8f0">')
    replace('      <div style="font-size:12px;font-weight:600;color:#444;margin-bottom:.75rem">\n        Hp =',
            '      <div id="boost_formula" style="font-size:12px;font-weight:600;color:#444;margin-bottom:.75rem">\n        Hp =')
    replace('      <div style="margin-bottom:8px">\n        <div style="font-size:11px;color:#888;margin-bottom:2px">Расчётный расход Q, м³/ч</div>',
            '      <div id="boost_q_inputs" style="margin-bottom:8px">\n        <div style="font-size:11px;color:#888;margin-bottom:2px">Расчётный расход Q, м³/ч</div>')
    replace('      <div style="margin-bottom:6px">\n        <div style="font-size:11px;color:#888;margin-bottom:2px">NPSH_a',
            '      <div id="boost_npsh_inputs" style="margin-bottom:6px">\n        <div style="font-size:11px;color:#888;margin-bottom:2px">NPSH_a')
    replace('Количество насосов в установке', 'Одновременно работающие насосы (резерв не суммируется)')
    replace('Подбор насоса по рабочей точке (СП 30.13330, методика Grundfos)',
            'Предварительный подбор насоса: повысительный режим / циркуляция')
    replace('График Q-H: кривая насоса и характеристика системы', 'График Q-H')
    replace('<span><span style="color:#1a6aaa">●</span> Кривая насоса</span>',
            '<span id="boost_chart_legend"><span><span style="color:#1a6aaa">●</span> Кривая насоса</span>')
    replace('<span><span style="color:#f39c12">■</span> Зона BEP (0.7-1.1×Q_opt)</span>',
            '<span><span style="color:#f39c12">■</span> Зона BEP (0.7-1.1×Q_opt)</span></span>'
            '<span id="circ_chart_legend" style="display:none">Синяя линия — каталог; квадрат — требуемая пара Q/H, не рабочая точка</span>')
    replace('function calcPumpHead() {', fragment('circulation') + '''

function calcPumpHead() {
  const circ = document.getElementById('pump_sel_type').value === 'circ';
  for (const id of ['boost_head_inputs', 'boost_formula', 'boost_q_inputs', 'boost_npsh_inputs', 'boost_chart_legend'])
    document.getElementById(id).style.display = circ ? 'none' : '';
  for (const id of ['circ_inputs', 'circ_chart_legend'])
    document.getElementById(id).style.display = circ ? '' : 'none';
  if (circ) return calcCirculationHead();''')

    # Historical JS-only crash already recorded in the audit: move declaration,
    # without modifying coefficient applicability or the calculation itself.
    replace("  if (k06 < 1) log.push(", "  const log = [];\n  if (k06 < 1) log.push(")
    replace("\n  const log = [];\n  log.push('<b>═══ 1.", "\n  log.push('<b>═══ 1.")
    # UI-only startup defect: result cards are siblings of input rows, but do
    # not contain .dn-sel/.t-inp. Never change calcGvs/calcHvs arithmetic here.
    for system in ('gvs', 'hvs'):
        replace(f"document.querySelectorAll('#{system}_rows > div')",
                f"document.querySelectorAll('#{system}_rows > div[id^=\"{system}_\"]')")
    replace('function calculate() {', '''function calculate() {
  document.getElementById('meters_result').innerHTML = '';
  try { return calculateApproved(); }
  catch (error) {
    if (!(error instanceof RangeError)) throw error;
    document.getElementById('err').textContent = error.message;
    document.getElementById('results').style.display = 'none';
  }
}
function calculateApproved() {''')
    # Visible scope prevents a corrected legacy file being presented as a
    # replacement for the current application's normative checks (notably В2).
    notice = '''<aside style="padding:12px;border:1px solid #d6bb79;background:#fff9eb;margin:12px">
<b>Рабочий legacy · 15.10.2026</b> — исправлены L01–L05, L07 (чистая циркуляция), L08 (нет подстановки NPSHa=8 м), DN65 и проверка минимума водомера.
Это автономный расчётник, не полный актуальный нормативный контур ЗАРИ.
В2 и остальные непроверенные ветви требуют проверки в приложении; учебные исходные не являются данными ТУ.
<a href="archive/sp30_calculator.pre-2026-09-21.html">Неизменённый архив</a>.</aside>'''
    text, count = re.subn(r'(<body[^>]*>)', lambda m: m[1] + '\n' + notice, text, count=1)
    if not count:  # original is an HTML fragment
        text = notice + '\n' + text
    return text


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = build()
    if args.check:
        if WORKING.read_text() != result:
            raise SystemExit('Working legacy is not reproducible; rebuild it')
    else:
        WORKING.write_text(result)
    print('Working legacy: approved deltas; archive SHA-256 verified')
