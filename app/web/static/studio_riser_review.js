/* Read-only presentation of SewageSystemResult; never recompute a verdict. */
(() => {
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,
    c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=value=>typeof value==='number'&&Number.isFinite(value)
    ? String(value).replace('.',',') : 'не определён';
  const check=value=>value===true?'выполнена':value===false?'не выполнена':'не завершена';
  const statuses=Object.freeze({verified:'Проверка стояка выполнена',fail:'Есть несоответствие',
    missing:'Недостаточно данных',stage_r:'Требуется уточнение стадии Р'});
  function render(review, {rowAction=()=>''}={}) {
    if(!review || !Array.isArray(review.risers)) return '<p class="field-help">Подробный результат стояков отсутствует. Повторите расчёт текущих исходных; старые числа не восстанавливаются автоматически.</p>';
    if(!review.risers.length) return '<p class="field-help">Расчётные стояки не заданы.</p>';
    const rows=review.risers.map(row=>`<article class="riser-review-row"><h4>${escape(row.riser_id)} · ${Object.hasOwn(statuses,row.status)?statuses[row.status]:'Статус не определён'}</h4>
<p>Нагрузка стояка: ${number(row.design_flow_lps)} л/с. Табличная пропускная способность: ${number(row.capacity_lps)} л/с. Разность по таблице: ${number(row.reserve_lps)} л/с.</p>
<p>Материал: ${escape(row.material_label)}. Вентиляция: ${escape(row.ventilation_label)}. Размеры для расчётной таблицы: стояк ${number(row.riser_dn_mm)} мм, отвод ${number(row.branch_dn_mm)} мм; угол ${number(row.branch_angle_deg)}°.</p>
<p>Проверка диаметра: ${check(row.diameter_ok)} (минимум из расчёта ${number(row.minimum_dn_mm)} мм). Проверка табличной пропускной способности: ${check(row.capacity_ok)}.</p>
<p>Основание расчёта: ${escape(row.table)}.</p><p>${escape(row.note)}</p>${rowAction(row.riser_id)}</article>`).join('');
    return `<details class="riser-review"><summary>Результаты по стоякам · ${review.risers.length}</summary><p>Общий расчётный расход системы К1: ${number(review.total?.q_sewage_lps)} л/с. Это не назначенная нагрузка каждого стояка.</p>${rows}<p class="field-help">Статусы и числа переданы из расчётного ядра без повторного сравнения округлённых значений. Проверка стояка не означает готовность всего выпуска. Размеры расчётной таблицы не заменяют номинальный DN вытяжки или внутренний диаметр трубы.</p></details>`;
  }
  const api=Object.freeze({render});
  if(typeof window!=='undefined')window.ZaryaRiserReview=api;
  if(typeof module!=='undefined')module.exports=api;
})();
