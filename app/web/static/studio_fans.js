/* Fan evidence is a nested record; unknown booleans stay null, not false. */
(() => {
  const key='wastewater_fan_ventilation';
  function rows(value, schema, escape) {
    return window.ZaryaSewerPipes.rows(Array.isArray(value)?value:(value?.terminals || []),schema.columns,escape,'fans');
  }
  function globals(value, escape) {
    const v=value?.external_ventilation_verified;
    const invalid=v!==undefined && v!==null && v!=='' && typeof v!=='boolean';
    const retained=invalid?`<option value="unsupported" selected data-fan-raw="${escape(JSON.stringify(v))}">Не поддерживается: ${escape(JSON.stringify(v))} — выберите явно</option>`:'';
    const ref=value?.external_ventilation_ref;
    const rawRef=ref!==undefined && typeof ref!=='string'?` data-preserved-raw="${escape(JSON.stringify(ref))}"`:'';
    return `<div class="pipe-option-fields"><label>Вентиляция наружной сети подтверждена<select class="field-control" data-fan-global="external_ventilation_verified"><option value="">Неизвестно</option>${retained}<option value="true"${v===true?' selected':''}>Да</option><option value="false"${v===false?' selected':''}>Нет</option></select></label><label>Основание подтверждения наружной сети<input class="field-control" data-fan-global="external_ventilation_ref"${rawRef} maxlength="200" value="${escape(ref ?? '')}" placeholder="Не задано"></label></div>`;
  }
  function control(row, prefix, schema, escape) {
    return `<div class="setup-field route-editor" data-input="${key}" data-hydraulic-editor="${key}"><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><p class="field-help">* Обязательны ID окончания и стояков К1. Остальные пробелы сохраняются как неизвестные. Не более ${schema.max_rows} окончаний. Удаление всех строк и очистка общих подтверждений очищают запись.</p><input type="hidden" id="${prefix}-${key}" name="${key}" value="${escape(JSON.stringify(row.value || null))}"><div data-fan-globals>${globals(row.value,escape)}</div><div data-route-rows>${rows(row.value,schema,escape)}</div><button type="button" class="text-button" data-action="add-section">+ Добавить фановое окончание</button></div>`;
  }
  function read(editor, terminals) {
    const control=editor.querySelector('[data-fan-global="external_ventilation_verified"]'),value=control.value;
    const ref=editor.querySelector('[data-fan-global="external_ventilation_ref"]');
    return {terminals,external_ventilation_verified:value==='unsupported'?JSON.parse(control.selectedOptions[0].dataset.fanRaw):value===''?null:value==='true',
      external_ventilation_ref:ref.dataset?.preservedRaw!==undefined?JSON.parse(ref.dataset.preservedRaw):ref.value.trim()};
  }
  window.ZaryaFanEditor={rows,control,read,globals};
})();
