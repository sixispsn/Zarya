/* Read-only diagnostic evidence. No interval reconstruction or status arithmetic. */
(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,
    c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=value=>typeof value==='number'&&Number.isFinite(value)?String(value).replace('.',','):'не определено';
  const check=value=>value===true?'выполнена':value===false?'не выполнена':'не завершена';
  const labels=Object.freeze({verified:'Проверка выполнена',fail:'Есть несоответствие',
    pending:'Недостаточно данных',missing:'Недостаточно данных',stage_r:'Требуется уточнение стадии Р'});
  const status=value=>Object.hasOwn(labels,value)?labels[value]:'Статус не определён';
  const list=(values,empty)=>Array.isArray(values)&&values.length
    ? `<ul>${values.map(value=>`<li>${escape(value)}</li>`).join('')}</ul>` : `<p>${empty}</p>`;
  const group=(title,rows,draw)=>`<details class="diagnostic-group"><summary>${title} · ${Array.isArray(rows)?rows.length:0}</summary>${Array.isArray(rows)&&rows.length?rows.map(draw).join(''):'<p>Нет результатов этой проверки. Отсутствие строк не подтверждает её выполнение.</p>'}</details>`;
  const row=(title,item,body)=>`<article class="diagnostic-review-row"><h4>${escape(title)} · ${status(item.status)}</h4>${body}<p>${escape(item.note)}</p></article>`;
  function render(review, {rowAction=()=>''}={}) {
    if(!review) return '<p class="field-help">Подробная диагностика отсутствует. Повторите расчёт текущих исходных; старые результаты не восстанавливаются автоматически.</p>';
    const service=group('Линейное обслуживание',review.linear_service_checks,item=>row(item.section_id,item,
      `<p>Расчётная длина: ${number(item.calculation_length_m)} м. Максимальный интервал в расчёте: ${number(item.maximum_gap_m)} м (не нормативный предел).</p><p>Координаты учтённых точек доступа вдоль участка, м: ${item.access_chainages_m?.length?item.access_chainages_m.map(number).join('; '):'нет подтверждённых координат в результате'}.</p>${rowAction(item.section_id)}`));
    const turns=group('Нижние повороты стояков',review.turn_checks,item=>row(item.riser_id,item,
      `<p>Выходящий участок: ${escape(item.outgoing_section_id || 'не определён')}. Элемент доступа: ${escape(item.access_element_id || 'не подтверждён')}.</p>`));
    const hydraulics=group('Гидравлика рассчитанных участков',review.hydraulics,item=>row(item.section_id,item,
      `<p>Расход: ${number(item.design_flow_lps)} л/с; внутренний диаметр: ${number(item.inner_diameter_mm)} мм; уклон: ${number(item.slope_per_mille)} ‰.</p><p>Шероховатость n: ${number(item.manning_n)}. Источник: ${escape(item.roughness_source || 'не указан')}.</p><p>Скорость: ${number(item.velocity_mps)} м/с; наполнение h/d: ${number(item.fill_ratio)}; максимальная пропускная способность из расчёта: ${number(item.maximum_capacity_lps)} л/с.</p><p>Проверка самоочищения: ${check(item.self_cleaning_ok)}; скорости: ${check(item.velocity_ok)}; минимального наполнения: ${check(item.minimum_fill_ok)}.</p>`));
    const notes=Object.entries(review.horizontal_flow_notes || {}).map(([id,note])=>`${id}: ${note}`);
    return `<details class="diagnostic-review"><summary>Диагностика по участкам и обслуживанию</summary>
<details class="diagnostic-group"><summary>Ошибки диагностики</summary>${list(review.errors,'Ошибки в результате не перечислены. Это не допуск к выпуску.')}</details>
<details class="diagnostic-group"><summary>Предупреждения и недостающие данные</summary>${list(review.warnings,'Предупреждения в результате не перечислены.')}<p>Участки без подтверждённого горизонтального расхода:</p>${list(review.pending_horizontal_flows,'В этом списке нет участков. Полнота остальных проверок оценивается отдельно.')}</details>
${service}${turns}${hydraulics}<details class="diagnostic-group"><summary>Основания расходов участков К1</summary>${list(notes,'Основания расходов в результате не приведены.')}</details>
<p class="field-help">Показаны результаты существующей диагностики без повторного расчёта. Пустые поля не означают ноль или успешную проверку. Интервалы берутся из исходной причины, не восстанавливаются по рисунку. Проверка не назначает новые точки обслуживания и не разрешает работы или выпуск комплекта.</p></details>`;
  }
  const api=Object.freeze({render});
  if(typeof window!=='undefined')window.ZaryaDiagnosticReview=api;
  if(typeof module!=='undefined')module.exports=api;
})();
