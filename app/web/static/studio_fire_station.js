/* Optional expert import; no dimensions or engineering defaults are generated. */
(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const describe = model => model ? `${model.network?.runs?.length || 0} участков · ${model.network?.risers?.length || 0} расчётных ПК · ${model.supplies?.length || 0} вводов. ${model.basis || ''}` : 'Модель не задана. Для обычного предварительного комплекта она не обязательна.';
  function control(row, prefix) {
    const id = `${prefix}-${row.key}`, model = row.value || null;
    return `<div class="setup-field setup-field-wide" data-input="${row.key}" data-fire-station-editor>
      <input type="hidden" id="${id}" name="${row.key}" value="${escape(JSON.stringify(model))}">
      <label for="${id}-file">Модель пожарной насосной · экспертный импорт</label>
      <p class="field-help">${escape(row.help)} Раздельная В2, одна зона, стальные ВГП трубы. Все длины и сопротивления задаются явно. В модели версии 3 обвязка считается отдельно; в версиях 1–2 она включена в расчётные пути. Необязательный блок location содержит номер помещения и отметки по АР, без измерения плана.</p>
      <input id="${id}-file" type="file" accept=".json,application/json" class="field-control" data-fire-station-import aria-describedby="${id}-status">
      <p id="${id}-status" class="field-help" data-fire-station-status aria-live="polite">${escape(describe(model))}</p>
      <div class="fire-station-actions"><button type="button" class="text-button" data-action="fire-station-export"${model?'':' disabled'}>Скачать модель</button>
      <button type="button" class="text-button" data-action="fire-station-remove"${model?'':' disabled'}>Убрать модель</button></div>
      <label class="field-help"><input type="checkbox" data-fire-station-adopt${model?.pressure_review?.document_use==='preliminary_project'?' checked':''}${model?.pressure_review?'':' disabled'}>
      Использовать проверенный вариант насоса и диафрагм в предварительном комплекте</label>
      <p class="field-help">Доступно для модели версии 2 или 3. Версия 3 задаёт отдельную обвязку. Перед сборкой проверка повторяется; при нарушениях вариант не принимается. Это не допуск к реальному выпуску.</p>
    </div>`;
  }
  function set(editor, model, notify=true) {
    const hidden = editor.querySelector('input[type="hidden"]');
    hidden.value = JSON.stringify(model);
    editor.querySelector('[data-fire-station-status]').textContent = describe(model);
    editor.querySelectorAll('button').forEach(button => {button.disabled = !model;});
    const adoption = editor.querySelector('[data-fire-station-adopt]');
    adoption.disabled = !model?.pressure_review;
    adoption.checked = model?.pressure_review?.document_use === 'preliminary_project';
    if(notify) hidden.dispatchEvent(new Event('input', {bubbles:true}));
  }
  const refresh = editor => set(editor,JSON.parse(editor.querySelector('input[type="hidden"]').value || 'null'),false);
  function adopt(input) {
    const editor = input.closest('[data-fire-station-editor]');
    const model = JSON.parse(editor.querySelector('input[type="hidden"]').value);
    if(!model?.pressure_review) return;
    model.pressure_review.document_use = input.checked ? 'preliminary_project' : 'review_only';
    set(editor, model);
  }
  async function importFile(input) {
    const file = input.files[0];
    if(!file) return;
    try {
      if(file.size > 100000) throw new Error('Модель В2: файл должен быть не больше 100 КБ.');
      let model;
      try {model = JSON.parse(await file.text());}
      catch {throw new Error('Не удалось прочитать JSON модели В2. Исходные данные не изменены.');}
      if(!model || ![1,2,3].includes(model.schema_version) || !model.network || !Array.isArray(model.supplies)) throw new Error('Нужна модель В2 schema_version = 1, 2 или 3, с сетью и вводами. Это не загрузка планов PDF.');
      set(input.closest('[data-fire-station-editor]'), model);
    } finally {input.value = '';}
  }
  function action(name, button) {
    const editor = button.closest('[data-fire-station-editor]');
    if(name === 'fire-station-remove') {set(editor, null);return;}
    const model = JSON.parse(editor.querySelector('input[type="hidden"]').value);
    const url = URL.createObjectURL(new Blob([JSON.stringify(model,null,2)], {type:'application/json'}));
    const link = document.createElement('a');
    link.href = url;link.download = 'fire-station-model.json';link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function result(station, format) {
    if(!station) return '';
    if(station.state !== 'preliminary') return `<p class="result-note">${escape(station.note)}</p>${reviewResult(station.pressure_review)}`;
    const pump = station.pump;
    if(station.adopted) return `<details class="section-details result-details" id="fire-station-results" open><summary>Пожарная насосная · единый предварительный вариант</summary>
      <p>${escape(pump.model)} · 1 рабочий + 1 резервный.</p>
      <p>Контрольный режим: Q = ${format(pump.wp_q)} м³/ч · H насоса = ${format(pump.wp_h)} м.</p>
      <p class="field-help">Те же насос и отверстия переданы в ПЗ, лист узлов и спецификацию.</p>
      ${station.location ? `<p>Помещение ${escape(station.location.room_number)} · ${escape(station.location.room_name)}. Пол ${format(station.location.floor_elevation_m)} м; отметки проходок перенесены на схему. Монтажные проходы не проверены.</p>` : ''}
      ${station.pump_geometry ? `<details class="section-details"><summary>Присоединения выбранного насоса</summary><p class="field-help">${escape(station.pump_geometry.note)}</p></details>` : ''}
      ${station.pipework ? `<p>Потери обвязки в этом режиме: всасывание ${format(station.pipework.losses_m.suction)} м · напор ${format(station.pipework.losses_m.discharge)} м. Учтены отдельно, без удвоения резерва.</p>` : ''}${reviewResult(station.pressure_review)}</details>`;
    const candidate = !station.pump_needed ? 'Повышение напора в проверенном сценарии не требуется.' : pump?.model ? `${escape(pump.model)} · 1 рабочий + 1 резервный. Каталожный кандидат по Q/H, не подтверждённая фактическая рабочая точка.` : 'Каталог не дал кандидата по расчётной потребности.';
    return `<details class="section-details result-details" id="fire-station-results" open><summary>Пожарная насосная · предварительный расчёт</summary>
      <p>Q = ${format(station.flow_lps)} л/с · H насоса = ${format(station.pump_head_m)} м</p><p>${candidate}</p>
      <dl><div><dt>Отметка оси насоса</dt><dd>${format(station.pump_axis_m)} м</dd></div><div><dt>Минимальный напор до насоса</dt><dd>${format(station.minimum_suction_head_m)} м</dd></div><div><dt>Требуется на выходе станции</dt><dd>${format(station.required_header_head_m)} м</dd></div></dl>
      <div class="hydraulic-scroll" tabindex="0" aria-label="Проверка вводов пожарной станции"><table class="flow-table"><thead><tr><th>Ввод</th><th>Q, л/с</th><th>Потери, м</th><th>До насоса, м</th></tr></thead><tbody>${station.supplies.map(s=>`<tr><th>${escape(s.name)}</th><td>${format(s.flow_lps)}</td><td>${format(s.loss_m)}</td><td>${format(s.suction_head_m)}</td></tr>`).join('')}</tbody></table></div>
      <p class="field-help">${escape(station.basis)}</p><p class="result-note">${escape(station.note)}</p>${reviewResult(station.pressure_review)}</details>`;
  }
  function reviewResult(r) {
    if(!r) return '';
    if(r.error) return `<p class="result-note">Проверка диафрагм и отключений: ${escape(r.error)}</p>`;
    const status = ok => ok ? 'проходит в модели' : 'есть нарушения или недостаточно данных';
    return `<section class="fire-pressure-review"><h4>Диафрагмы и отключения · исследовательская проверка</h4>
      <p>${r.adoption?.state==='preliminary' ? 'Принят предварительно' : 'Проверяемый насос'}: ${escape(r.pump.pump_model)}.</p>
      ${r.adoption?.state==='rejected' ? `<p class="fire-review-failure">Не принят в комплект: ${escape(r.adoption.reason)}. Другой насос автоматически не подставлен.</p>` : ''}
      <p>Решено ${r.solved_count} из ${r.scenario_count} режимов. Минимумы обеспечены в ${r.minimum_pass_count}.</p>
      ${r.all_model_minima_met ? '' : `<p class="fire-review-failure">В ${r.scenario_count-r.minimum_pass_count} режимах недостаточны расход/напор либо не найдено решение.</p>`}
      <p>Ограничение максимального давления при расходе: ${status(r.all_model_dynamic_limits_met)}. Статика: ${status(r.all_model_static_limits_met)}.</p>
      <p class="field-help">${escape(r.note)} Подробности и исходные — в отдельном расчётном приложении.</p></section>`;
  }
  window.ZaryaFireStation = Object.freeze({control, importFile, action, result, refresh, adopt});
})();
