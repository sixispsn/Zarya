/* Navigation only: no inferred values, audit decisions or automatic saves. */
(() => {
  'use strict';
  const destinations=Object.freeze({
    'K1-02':['sewage_risers'],
    'K1-05':['sewer_pipes','sewer_elements','sewage_risers'],
  });
  const labels=Object.freeze({
    sewage_risers:'Расчётные стояки К1',
    sewer_pipes:'Трубы К1/К2',
    sewer_elements:'Элементы и доступ для обслуживания',
  });
  function targets(item, editable=true) {
    if(!editable || !item || !['blocked','conditional'].includes(item.state)) return [];
    return Object.hasOwn(destinations,item.code) ? [...destinations[item.code]] : [];
  }
  function resolve(item, key, editable=true) {
    return targets(item,editable).includes(key) ? {group:'connection',key} : null;
  }
  const rowDestinations=Object.freeze({
    'K1-02':{key:'sewage_risers',field:'riser_id',review:'sewage_riser_review',rows:'risers'},
    'K1-05':{key:'sewer_pipes',field:'section_id',review:'sewage_diagnostic_review',rows:'linear_service_checks'},
  });
  const escape=value=>String(value).replace(/[&<>"']/g,
    c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function exactIndex(rows, field, id) {
    if(!Array.isArray(rows) || typeof id!=='string' || !id.trim()) return -1;
    const matches=rows.map((row,index)=>row?.[field]===id?index:-1).filter(index=>index>=0);
    return matches.length===1?matches[0]:-1;
  }
  function resolveRow(item,key,id,calculation,rows,editable=true) {
    const target=resolve(item,key,editable);
    const spec=item && Object.hasOwn(rowDestinations,item.code)?rowDestinations[item.code]:null;
    if(!target || spec?.key!==key || exactIndex(calculation?.[spec.review]?.[spec.rows],spec.field,id)<0
      || exactIndex(rows,spec.field,id)<0) return null;
    return {...target,field:spec.field,id};
  }
  function renderRow(item,key,id,calculation,rows,editable=true) {
    if(!resolve(item,key,editable)) return '';
    if(!resolveRow(item,key,id,calculation,rows,editable)) return '<p class="field-help">Точный переход недоступен: нет единственного совпадения ID в результате и реестре. Проверьте исходные в реестре.</p>';
    return `<button type="button" class="text-button" data-action="finding-row" data-finding="${item.code}" data-finding-input="${key}" data-finding-row="${escape(id)}">К строке ${escape(id)} →</button>`;
  }
  function render(item, {editable=true}={}) {
    const keys=targets(item,editable);
    if(!keys.length) return '';
    return `<div class="finding-input-actions">${keys.map(key=>`<button type="button" class="text-button" data-action="finding-inputs" data-finding="${item.code}" data-finding-input="${key}">${labels[key]} →</button>`).join('')}</div><p class="field-help">Открытие реестра не изменяет исходные и не снимает замечание. После правки нужен повторный расчёт.</p>`;
  }
  const api=Object.freeze({targets,resolve,render,exactIndex,resolveRow,renderRow});
  if(typeof window!=='undefined') window.ZaryaFindingInputs=api;
  if(typeof module!=='undefined') module.exports=api;
})();
