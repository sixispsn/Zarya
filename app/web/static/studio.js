/* Residential intake UI. Engineering decisions and arithmetic stay on the server. */
(() => {
  'use strict';
  const root = document.getElementById('studio');
  const $ = selector => root.querySelector(selector);
  const fileInput = $('#file-input');
  const motion = window.ZaryaMotion;
  // A saved project and the currently visible screen are independent states.
  let workspaceOpen = root.dataset.view === 'project';
  const visibleScreen = () => $('#workspace:not([hidden]), #entry:not([hidden]), #busy:not([hidden])');
  const scrollTo = (element, block = 'nearest') => element?.scrollIntoView({block, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  let draft = null;
  let working = false;
  let manualOpen = false;
  let setupExpanded = false;
  let selectedStep = null;
  let documentView = null;
  let dirty = false;
  let dragDepth = 0;
  let deletingDocument = null;
  let configStep = null;
  let configExpanded = new Set();
  const touchedFields = new Set();
  let inputIssueTargets=[];
  const config = window.ZaryaConfigurator;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const format = value => typeof value === 'number' ? value.toLocaleString('ru-RU', {maximumFractionDigits: 3}) : String(value ?? '');
  const field = key => draft?.fields.find(row => row.key === key);
  const accepted = row => ['confirmed','default'].includes(row.status);
  const issueEditors=()=>({sewage_risers:draft?.riser_editor?.columns,sewer_pipes:draft?.sewer_pipe_editor?.columns,
    sewer_elements:draft?.sewer_element_editor?.columns,wastewater_fan_ventilation:draft?.fan_editor?.columns});
  function issueSnapshot() {
    return Object.fromEntries(['sewage_risers','sewer_pipes','sewer_elements','wastewater_fan_ventilation'].map(key=>{
      try {return [key,JSON.parse($('#field-'+key)?.value || 'null')];} catch {return [key,undefined];}
    }));
  }
  const say = text => { $('#announcement').textContent = text; };
  function showError(message, reload = false) {
    inputIssueTargets=[];
    if (message) motion.stop();
    if(message && $('#example-picker').open) $('#example-picker').close();
    if(message && $('#clarification-dialog').open) $('#clarification-dialog').close();
    $('#error').textContent = message;
    $('#error').hidden = !message;
    if(message) { $('#error').focus(); $('#error').scrollIntoView({block:'nearest'}); }
    if (reload) {
      const button = document.createElement('button');
      button.type = 'button'; button.dataset.action = 'reload'; button.textContent = 'Обновить черновик';
      $('#error').append(button);
    }
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    try {
      let response;
      try {
        response = await fetch('/studio/api/' + path, {
          credentials: 'same-origin', ...options, signal: controller.signal,
          headers: {'X-Zarya-Studio': '1', ...(draft?.project_id && options.method && options.method !== 'GET' ? {'X-Zarya-Draft':draft.project_id} : {}), ...(options.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options.headers}
        });
      } catch (cause) {
        throw window.ZaryaTransport.interrupted(cause);
      }
      return await window.ZaryaTransport.decode(response);
    } finally { clearTimeout(timeout); }
  }
  function failure(error, submitted=null) {
    const result = window.ZaryaTransport.presentation(error);
    const issues=error.status===422 && Array.isArray(error.inputIssues)?error.inputIssues:[];
    showError(issues.length && error.inputMessage?error.inputMessage:result.message, result.reload);
    if(result.reload && dirty && draft && !draft.study) {
      const note=document.createElement('p');
      note.textContent='Ввод остаётся в этой вкладке. Перед обновлением можно скачать копию полей, подготовленных к отправке, для ручной сверки. Копия не является сохранённым проектом; автоматического переноса в новую версию нет.';
      const button=document.createElement('button');button.type='button';button.className='text-button';
      button.dataset.action='download-input-copy';button.textContent='Скачать несохранённый ввод (JSON)';
      $('#error').append(note,button);
    }
    for(const issue of issues) {
      const rows=submitted?.[issue.registry];
      // The resolver whitelists keys before any selector is constructed.
      const candidate=window.ZaryaInputIssues?.resolve(issue,rows,rows,!draft?.study,issueEditors(),{submitted,current:submitted});
      if(!candidate)continue;
      let current;
      try {current=JSON.parse($('#field-'+candidate.key)?.value || 'null');} catch {continue;}
      const target=window.ZaryaInputIssues.resolve(issue,rows,current,!draft?.study,issueEditors(),{submitted,current:issueSnapshot()});
      if(!target)continue;
      const button=document.createElement('button');button.type='button';button.className='text-button';
      button.dataset.action='input-issue';button.dataset.issueIndex=String(inputIssueTargets.length);
      button.textContent='Исправить: '+target.label+' →';
      const wrapper=document.createElement('p');wrapper.append(button);$('#error').append(wrapper);
      inputIssueTargets.push({issue,rows,submitted});
    }
  }
  function setWorking(value, title = '') {
    working = value;
    root.setAttribute('aria-busy', String(value));
    root.querySelectorAll('button, input, select, textarea').forEach(button => {
      if (value) { button.dataset.wasDisabled = String(button.disabled); button.disabled = true; }
      else if ('wasDisabled' in button.dataset) { button.disabled = button.dataset.wasDisabled === 'true'; delete button.dataset.wasDisabled; }
    });
    if (title) say(title);
  }
  async function ensureDraft() {
    if (!draft) draft = await api('draft', {method:'POST'});
    return draft;
  }
  function sourceLinks(row) {
    if (row.source?.kind === 'core_default') return '<p class="source-label">Принятое значение рабочего расчётного ядра · можно изменить</p>';
    const sources = row.source?.evidence || row.candidates;
    if (!sources?.length) return row.status === 'confirmed' ? '<p class="source-label">Введено пользователем</p>' : '';
    return sources.map(item => {
      const doc = draft.documents.find(doc => doc.id === item.document_id);
      if (!doc) return '';
      return `<div class="evidence"><a href="/studio/api/files/${encodeURIComponent(doc.id)}#page=${item.page}" target="_blank" rel="noopener">${escape(doc.name)} · стр. ${item.page} ↗</a><blockquote>${escape(item.quote)}</blockquote></div>`;
    }).join('');
  }
  const basicKeys = ['residents','floors','apartments','consumer_code','hws_type','roof_type'];
  const labels = {residents:'Жителей',floors:'Надземных этажей',apartments:'Квартир всего',consumer_code:'Приборы в квартирах',hws_type:'Горячая вода',roof_type:'Кровля',h_geom_m:'Высота прибора над вводом, м',storm_roof_area_m2:'Площадь водосбора кровли, м²'};
  const routeColumns = [['section_id','Участок'],['role','Назначение'],['length_m','Длина, м'],['inner_diameter_mm','d внутренний, мм'],['roughness_mm','Шероховатость, мм'],['flow_lps','Расход, л/с'],['material','Материал / серия']];
  function routeRows(rows, key='v1_sections') {
    if(key==='wastewater_fan_ventilation') return window.ZaryaFanEditor.rows(rows,draft.fan_editor,escape);
    if(key==='sewage_risers') return window.ZaryaSewerPipes.rows(rows,draft.riser_editor.columns,escape,'risers');
    if(key==='sewer_elements') return window.ZaryaSewerPipes.rows(rows,draft.sewer_element_editor.columns,escape,true);
    if(key==='sewer_pipes') return window.ZaryaSewerPipes.rows(rows,draft.sewer_pipe_editor.columns,escape);
    if(key==='t3_sections') return hotRouteRows(rows);
    return rows.map((row,index)=>`<fieldset class="route-row"><legend>Участок ${index+1}</legend>${routeColumns.map(([key,label])=>`<label${key==='role'?' class="route-role"':''}>${label}${key==='role'?`<select data-column="role" class="field-control"><option value="input"${row.role==='input'?' selected':''}>Ввод</option><option value="internal"${row.role!=='input'?' selected':''}>Внутренняя сеть</option></select>`:`<input data-column="${key}" class="field-control" value="${escape(row[key])}" ${['section_id','material'].includes(key)?'maxlength="120"':'inputmode="decimal"'} placeholder="${key==='flow_lps' && row.role==='input'?'Авто':'—'}">`}</label>`).join('')}<button type="button" class="text-button" data-action="remove-section" aria-label="Удалить участок ${index+1}">Удалить</button></fieldset>`).join('');
  }
  function routeControl(row,prefix) {
    if(row.kind==='fan_evidence') return window.ZaryaFanEditor.control(row,prefix,draft.fan_editor,escape);
    const rows=accepted(row)?row.value:[];
    if(row.key==='sewage_risers') return `<div class="setup-field route-editor" data-input="sewage_risers" data-hydraulic-editor="sewage_risers"><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><p class="field-help">* Обязательные данные каждой введённой строки. Без них строка не сохраняется; исправные сохранённые данные не заменяются. Не более ${draft.riser_editor.max_rows} строк.</p><input type="hidden" id="${prefix}-sewage_risers" name="sewage_risers" value="${escape(JSON.stringify(rows))}"><div data-route-rows>${routeRows(rows,'sewage_risers')}</div><button type="button" class="text-button" data-action="add-section">+ Добавить расчётный стояк К1</button></div>`;
    if(row.key==='sewer_elements') return `<div class="setup-field route-editor" data-input="sewer_elements" data-hydraulic-editor="sewer_elements"><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><p class="field-help">* Обязательные данные каждой введённой строки. Без них строка не сохраняется; исправные сохранённые данные не заменяются. Не более ${draft.sewer_element_editor.max_rows} строк.</p><input type="hidden" id="${prefix}-sewer_elements" name="sewer_elements" value="${escape(JSON.stringify(rows))}"><div data-route-rows>${routeRows(rows,'sewer_elements')}</div><button type="button" class="text-button" data-action="add-section">+ Добавить элемент реальной сети К1/К2</button></div>`;
    if(row.key==='sewer_pipes') return `<div class="setup-field route-editor" data-input="sewer_pipes" data-hydraulic-editor="sewer_pipes"><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><p class="field-help">* Обязательные данные каждой введённой строки. Без них строка не сохраняется; исправные сохранённые данные не заменяются. Не более ${draft.sewer_pipe_editor.max_rows} строк.</p><input type="hidden" id="${prefix}-sewer_pipes" name="sewer_pipes" value="${escape(JSON.stringify(rows))}"><div data-route-rows>${routeRows(rows,'sewer_pipes')}</div><button type="button" class="text-button" data-action="add-section">+ Добавить реальный участок К1/К2</button></div>`;
    if(row.key==='t3_sections') return `<div class="setup-field route-editor" data-input="t3_sections" data-hot-only data-t3-mode="sections" data-hydraulic-editor="t3_sections"><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><input type="hidden" id="${prefix}-t3_sections" name="t3_sections" value="${escape(JSON.stringify(rows))}"><div data-route-rows>${hotRouteRows(rows)}</div><button type="button" class="text-button" data-action="add-section">+ Добавить участок Т3</button><p class="field-help">Предел скорости задайте по п. 8.26 и приложению И. qcir — только из отдельного расчёта циркуляции; без него итоговый напор не подтверждается. Между точками таблицы Г автоматическая интерполяция не выполняется.</p></div>`;
    return `<div class="setup-field route-editor" data-input="v1_sections" data-loss-mode="sections" data-hydraulic-editor><h4>${escape(row.label)}</h4><p class="field-help">${escape(row.help)}</p><input type="hidden" id="${prefix}-v1_sections" name="v1_sections" value="${escape(JSON.stringify(rows))}"><div data-route-rows>${routeRows(rows)}</div><button type="button" class="text-button" data-action="add-section">+ Добавить участок</button><p class="field-help">На вводе пустой расход означает автоматический расчёт по текущим потребителям. На внутренних участках нужен расход именно участка — общий расход дома туда не подставляется. Шероховатость задаётся отдельно, а не угадывается по названию материала.</p></div>`;
  }
  function hotRouteRows(rows) {
    const cols=[['section_id','Участок'],['length_m','Длина, м'],['inner_diameter_mm','d внутренний, мм'],['roughness_mm','Шероховатость, мм'],['flow_lps','Расход участка, л/с'],['circulation_flow_lps','qcir участка, л/с'],['velocity_limit_mps','Допустимая скорость, м/с'],['material','Материал / серия'],['basis','Источник расхода / обоснование']];
    const modes=[['unknown','Уточнить учёт циркуляции'],['none','Система без циркуляции'],['terminal','Вне поправки по п. 10.11'],['main','Начальный участок — учесть qcir'],['corrected','Расход уже скорректирован']];
    return rows.map((row,index)=>`<fieldset class="route-row"><legend>Т3 · участок ${index+1}</legend><label class="route-role">Учёт циркуляции<select class="field-control" data-column="flow_mode">${modes.map(([v,t])=>`<option value="${v}"${(row.flow_mode||'unknown')===v?' selected':''}>${t}</option>`).join('')}</select></label>${cols.map(([k,label])=>`<label${k==='circulation_flow_lps' && row.flow_mode!=='main'?' hidden':''}>${label}<input class="field-control" data-column="${k}" value="${escape(row[k])}" ${k==='circulation_flow_lps' && row.flow_mode!=='main'?'disabled':''} ${['section_id','material','basis'].includes(k)?'maxlength="240"':'inputmode="decimal"'} placeholder="—"></label>`).join('')}<button type="button" class="text-button" data-action="remove-section" aria-label="Удалить участок Т3 ${index+1}">Удалить</button></fieldset>`).join('');
  }
  function readRoute(editor) {
    return Array.from(editor.querySelectorAll('.route-row')).map(row=>Object.fromEntries(Array.from(row.querySelectorAll('[data-column]:not(:disabled)')).map(input=>[input.dataset.column,input.hasAttribute('data-id-list') ? input.value.split('\n').map(x=>x.trim()).filter(Boolean) : input.hasAttribute('data-pipe-boolean') && input.value!=='' ? input.value==='true' : input.value.trim()])));
  }
  function syncRoute(editor) {
    const key=editor.dataset.hydraulicEditor || 'v1_sections';
    const hidden=editor.querySelector(`[name="${key}"]`);
    hidden.value=JSON.stringify(key==='wastewater_fan_ventilation'?window.ZaryaFanEditor.read(editor,readRoute(editor)):readRoute(editor));
    root.querySelectorAll('[data-hydraulic-editor]').forEach(other=>{
      if(other===editor || (other.dataset.hydraulicEditor || 'v1_sections')!==key)return;
      other.querySelector(`[name="${key}"]`).value=hidden.value;
      other.querySelector('[data-route-rows]').innerHTML=routeRows(JSON.parse(hidden.value),key);
      if(key==='wastewater_fan_ventilation') other.querySelector('[data-fan-globals]').innerHTML=window.ZaryaFanEditor.globals(JSON.parse(hidden.value),escape);
    });
    hidden.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function syncLossMode() {
    const stageP=$('#field-hws_stage_p_enabled')?.value==='yes';
    ['water_towel_rails','circulation_zones','delta_t_c','loss_percent','hot_temp_c','cold_temp_c'].forEach(key=>{
      root.querySelectorAll(`[data-input="hws_${key}"]`).forEach(item=>{item.hidden=!stageP;});
    });
    const mode=$('#field-pressure_loss_mode')?.value || field('pressure_loss_mode')?.value;
    const hot=$('#field-hws_type')?.value !== 'none';
    root.querySelectorAll('[data-loss-mode]').forEach(item=>{item.hidden=item.dataset.lossMode!==mode || (item.hasAttribute('data-hot-only') && !hot);});
    const t3mode=$('#field-t3_loss_mode')?.value || field('t3_loss_mode')?.value;
    root.querySelectorAll('[data-hot-only]:not([data-loss-mode])').forEach(item=>{item.hidden=!hot || (item.dataset.t3Mode && item.dataset.t3Mode!==t3mode);});
    const heater=$('#field-hws_heater_in_scope')?.value==='yes';
    root.querySelectorAll('[data-heater-only]').forEach(item=>{item.hidden=!hot || !heater;});
    const basement=$('#field-basement_kind')?.value;
    root.querySelectorAll('[data-input="basement_floor_m"]').forEach(item=>{item.hidden=!['basement','subfloor'].includes(basement);});
    const fanValues=Object.fromEntries(['section_fan_mode','section_fan_plastic_exposed',
      'section_k1_flow_basis','section_k1_design_flow_lps','section_k1_flow_source',
      'section_k1_q_hour_max_m3h','section_k1_fixture_max_lps','section_k1_fixtures_count','section_k1_receiving_length_m',
      'sewer_service_k1_metering_enabled','sewer_service_sump_enabled','sewer_service_sump_room','sewer_service_sump_reserve_location']
      .map(key=>[key,$('#field-'+key)?.value]));
    root.querySelectorAll('[data-input^="section_fan_"], [data-input^="section_k1_"], [data-input^="sewer_service_"]').forEach(item=>{
      const key=item.dataset.input;
      item.hidden=!window.ZaryaConfigurator.fanFieldVisible(key,fanValues);
    });
    const disposal=$('#field-wastewater_disposal_mode')?.value;
    root.querySelectorAll('[data-input^="wastewater_tu_"]').forEach(item=>{item.hidden=disposal!=='centralized';});
    const technology=$('#field-technology_presence')?.value;
    root.querySelectorAll('[data-input="technology_note"]').forEach(item=>{item.hidden=technology!=='yes';});
    const rainwater=$('#field-rainwater_enabled')?.value==='yes';
    const rainPurpose=$('#field-rainwater_purpose')?.value;
    root.querySelectorAll('[data-rainwater-active]').forEach(item=>{item.hidden=!rainwater;});
    root.querySelectorAll('[data-input^="rainwater_"]').forEach(item=>{
      if(item.dataset.input==='rainwater_enabled') return;
      item.hidden=!rainwater || (item.dataset.input==='rainwater_technical_use' && rainPurpose!=='other');
    });
    const pumpSetup=$('#field-rainwater_pump_setup')?.value;
    const hoseChoice=$('#field-rainwater_hose_choice')?.value;
    root.querySelectorAll('[data-input^="rainwater_pump_"], [data-input="rainwater_outlets_count"], [data-input^="rainwater_hose_"]').forEach(item=>{
      const key=item.dataset.input;
      item.hidden=!rainwater || (key!=='rainwater_pump_setup' && !pumpSetup) || (key.startsWith('rainwater_hose_') && key!=='rainwater_hose_choice' && hoseChoice!=='custom');
    });
    const treatment=$('#field-rainwater_treatment_setup')?.value;
    root.querySelectorAll('[data-input^="rainwater_treatment_"]').forEach(item=>{
      item.hidden=!rainwater || (item.dataset.input!=='rainwater_treatment_setup' && !treatment);
    });
    if(treatment) root.querySelectorAll('[data-input="rainwater_pump_treatment_loss_m"]').forEach(item=>{item.hidden=true;});
  }
  function control(row, prefix='field') {
    if(row.kind==='fire_station') return window.ZaryaFireStation.control(row,prefix);
    if(['sections','t3_sections','sewer_pipes','sewer_elements','sewage_risers','fan_evidence'].includes(row.kind)) return routeControl(row,prefix);
    const proposed = row.status === 'missing' && Object.hasOwn(draft.quick_start_presets || {},row.key);
    const candidate = row.status === 'review' ? row.candidates[0]?.value : '';
    const value = accepted(row) ? row.value : proposed ? draft.quick_start_presets[row.key] : candidate ?? '';
    const options = draft.options[row.key];
    const legacyRoof = row.key === 'roof_type' && ['flat','sloped'].includes(value);
    const optionLabel = item => row.key === 'consumer_code' && item.value === 'residential_full_bath' ? 'Ванна ≥ 1500 мм' : item.label;
    const id=`${prefix}-${row.key}`;
    if(['vu_per_inlet','russian_equipment_only','sewer_service_k1_metering_enabled','sewer_service_sump_enabled'].includes(row.key)) return `<div class="setup-field setup-field-wide" data-input="${row.key}"><label class="equipment-origin-toggle" for="${id}"><input type="checkbox" id="${id}" name="${row.key}" value="${value==='yes'?'yes':'no'}"${value==='yes'?' checked':''}>${escape(row.label)}</label><p class="field-help">${escape(row.help)}</p></div>`;
    if(row.kind==='design_note') return `<div class="setup-field setup-field-wide" data-input="${row.key}"><label for="${id}">${escape(row.label)}</label><textarea id="${id}" name="${row.key}" class="field-control design-note" rows="4" maxlength="1200">${escape(value)}</textarea><p class="field-help">${escape(row.help)}</p></div>`;
    if(row.key==='rainwater_enabled') return `<div class="setup-field" data-input="rainwater_enabled"><label for="${id}">${escape(row.label)}</label><select id="${id}" name="rainwater_enabled" class="field-control"><option value="no"${value!=='yes'?' selected':''}>Нет</option><option value="yes"${value==='yes'?' selected':''}>Да</option></select></div>`;
    if(row.kind==='rain_profile') return `<div class="setup-field setup-field-wide" data-input="${row.key}"><label for="${id}">${escape(row.label)}</label><textarea id="${id}" name="${row.key}" class="field-control rain-profile" rows="4" maxlength="150000" placeholder="2026-06-01; 8; 1,2&#10;2026-06-02; 0; 1,2">${escape(value)}</textarea><p class="field-help">${escape(row.help)}</p></div>`;
    const vuEmptyLabels={vu_orientation:'Горизонтально → · по умолчанию',vu_technology:'По расчёту',vu_telemetry:'Без дополнительных требований',vu_leak_monitoring:'Нет',vu_tamper_monitoring:'Нет',vu_valve_feedback:'Без дополнительных требований',vu_assembly:'По проекту',vu_magnetic_filter:'Нет',vu_power:'По выбранному оборудованию'};
    Object.assign(vuEmptyLabels,{vu_cold_orientation:'Как по умолчанию',vu_hot_orientation:'Как по умолчанию',vu_filter_layout:'На оси узла',vu_maintenance_layout:'Существующая компоновка'});
    ['inlet','outlet','bypass','bypass_after'].forEach(k=>vuEmptyLabels['vu_support_'+k]='Не назначена');
    const emptyLabel=vuEmptyLabels[row.key] || (row.key==='vu_drawing_scale'?'Авто · 1:5':row.key==='rainwater_enabled'?'Нет':row.key==='roof_type'?'Выберите вид кровли':'Не задано');
    const input = options ? `<select id="${id}" name="${row.key}" class="field-control"${row.key==='roof_type'?` aria-describedby="${id}-hint"`:''}${legacyRoof?' data-preserved-roof="true"':''}><option value=""${legacyRoof?' selected':''}>${emptyLabel}</option>${options.map(item=>`<option value="${escape(item.value)}"${item.value===value?' selected':''}>${escape(optionLabel(item))}</option>`).join('')}</select>` : `<input id="${id}" name="${row.key}" class="field-control" value="${escape(value)}" inputmode="${row.kind==='integer'?'numeric':row.kind==='number'?'decimal':'text'}" ${row.kind==='text'?'maxlength="200"':''} placeholder="${basicKeys.includes(row.key)?'—':'Не задано'}" autocomplete="off">`;
    const needsReview = ['review','conflict'].includes(row.status);
    const roofHint = row.key==='roof_type'?`<p id="${id}-hint" class="field-help" aria-live="polite">${escape(draft.roof_rules?.[value]?.note || '')}</p>`:'';
    const automatic = row.source?.kind==='apartment_estimate' ? `<p class="field-help">Авто · DN${escape(row.source.dn)} · ${format(row.source.flow_lps)} л/с · предварительно</p>` : '';
    return `<div class="setup-field ${(row.key==='consumer_code' || row.key.endsWith('_source_ref'))?'setup-field-wide':''}" data-input="${row.key}"${['h_il_m','h_vvod_m'].includes(row.key)?' data-loss-mode="ready"':row.key==='h_il_hot_m'?' data-t3-mode="ready" data-hot-only':row.key==='h_tepl_m'?' data-heater-only': ['t3_loss_mode','h_apartment_h_meter_m','hws_heater_in_scope'].includes(row.key)?' data-hot-only':''}><label for="${id}">${escape(labels[row.key] || row.label)}${row.unit && !labels[row.key]?', '+escape(row.unit):''}</label>${input}${automatic}${roofHint}${row.status==='conflict'?'<p class="field-error">Источники расходятся — выберите значение.</p>':''}${needsReview?`<details class="source-details"><summary>${row.status==='conflict'?'Сравнить источники':'Из документа · проверить'}</summary>${sourceLinks(row)}</details>`:''}${!basicKeys.includes(row.key) && row.help?`<p class="field-help">${escape(row.help)}</p>`:''}${equipmentCards(row.key,value)}</div>`;
  }
  function equipmentCards(key,value) {
    const products=draft.metering_catalogue?.choices?.[key]?.[value] || [];
    if(!products.length) return '';
    return `<details class="equipment-cards"><summary>Оборудование и условия · ${products.length}</summary>${products.map(p=>`<article><strong>${escape(p.manufacturer)} · ${escape(p.model)}</strong>${p.article?`<small>Артикул ${escape(p.article)}</small>`:''}<p>${p.facts.map(escape).join(' ')}</p><p>${p.requirements.map(escape).join(' ')}</p>${p.sources.map(s=>`<a href="${escape(s.url)}" target="_blank" rel="noopener noreferrer">${escape(s.title)} ↗</a>`).join('')}<small>Проверено ${escape(p.checked_on || draft.metering_catalogue.checked_on)}.</small></article>`).join('')}<small>Наличие уточняется при заказе.</small></details>`;
  }
  function setup() {
    if(draft.study?.kind==='samara') return `<section class="setup-panel"><h3>Проверенные исходные секции 3.2</h3><p>16 этажей · 143 квартиры · 350 жителей. Гарантированный напор 30 м в точке подключения.</p><p class="field-help">Фиксированный контрольный пример по согласованным исходным. Обвязка и диафрагмы проверены только для этой модели. Для нового здания вернитесь к своему проекту.</p></section>`;
    if(draft.study) {
      return `<form id="setup-form" class="setup-panel" data-setup><div class="manual-fields">${['residents','storm_city','storm_roof_area_m2','roof_type'].map(key=>control(field(key))).join('')}</div><p class="field-help">Ванна ≥1500 мм и централизованное ГВС. Водосборы разделены поровну; стены не добавлены. Геометрия — выбранный учебный вариант.</p><div class="setup-footer"><p id="save-state">После изменения пересчитайте: прежние PDF будут отозваны.</p><button type="submit" class="soft-button" data-action="calculate">Обновить расчёт</button></div></form>`;
    }
    const cards=config.groups.map((group,index)=>{
      const state=config.state(group,draft);
      const status=state.review?`Проверить по документам: ${state.review}`:`Заполнено ${state.filled} из ${state.total}`;
      return `<button type="button" class="config-card" data-action="config" data-config="${group.id}" aria-haspopup="dialog"><span class="config-card-top"><span class="config-index">0${index+1}</span>${configIcon(group.id)}</span><strong>${escape(group.title)}</strong><span>${escape(group.caption)}</span><small class="config-status" data-state="${state.kind}">${status}</small></button>`;
    }).join('');
    // One backing form retains unsaved edits across dialog pages. It is never
    // itself submitted wholesale; only visible/touched fields are adopted.
    return `<div class="config-cards" aria-label="Три блока исходных данных">${cards}</div><div class="config-toolbar"><p id="save-state">Три коротких шага. Всё можно уточнить позже.</p><button type="button" class="soft-button calculation-button" data-action="config-start">${draft.calculation?'Проверить исходные':'Настроить проект'} →</button></div><form id="setup-form" data-setup hidden>${draft.fields.map(row=>control(row)).join('')}</form>`;
  }
  function configIcon(id) {
    const shapes={building:'<path d="M6 27V7h20v20M3 27h26M11 12h3m4 0h3m-10 5h3m4 0h3m-10 5h3m4 0h3"/>',connection:'<path d="M4 10h24M10 5v10m12-10v10M4 23h9a6 6 0 0 0 6-6v-2m0 8h9"/><circle cx="6" cy="23" r="2"/>',consumers:'<circle cx="11" cy="10" r="4"/><circle cx="23" cy="12" r="3"/><path d="M3 27v-3a8 8 0 0 1 16 0v3m2-9a6 6 0 0 1 8 6v3"/>'};
    return `<svg class="config-icon" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[id]}</svg>`;
  }
  function openConfig(id='building', keys=[]) {
    configStep=config.groups.find(group=>group.id===id)?.id || 'building';
    const group=config.groups.find(group=>group.id===configStep);
    group.sections.forEach((section,index)=>{if(section[1].some(key=>keys.includes(key) || ['review','conflict'].includes(field(key)?.status))) configExpanded.add(`${group.id}-${index}`);});
    populateConfig(); motion.stop();
    if(!$('#clarification-dialog').open) $('#clarification-dialog').showModal();
    const focus=keys.map(key=>$('#next-'+key)).find(Boolean) || $('#clarification-body input, #clarification-body select');
    focus?.focus({preventScroll:true});
  }
  function populateConfig() {
    const index=config.groups.findIndex(group=>group.id===configStep),group=config.groups[index];
    if(!group) return;
    const progress=config.groups.map((item,i)=>`<li${i===index?' aria-current="step"':''}><span>${i+1}</span><small>${escape(item.title)}</small></li>`).join('');
    const extras=group.sections.map(([title,keys],i)=>{
      if(keys[0]?.startsWith('section_k2_') && field('section_drainage')?.value==='external') return '';
      const vu=title==='Водомерный узел';
      const count=vu?keys.filter(key=>{const value=$('#field-'+key)?.value;return value && value!=='no';}).length:0;
      const rain=keys[0]==='rainwater_enabled';
      const rainBase=['enabled','purpose','location','demand_m3_day','technical_use'].map(k=>'rainwater_'+k);
      const rainBalance=['useful_volume_m3','collection_area_m2','collection_factor','profile','source'].map(k=>'rainwater_'+k);
      const rainTreatment=keys.filter(k=>k.startsWith('rainwater_treatment_'));
      const rainDesign=keys.filter(k=>k.startsWith('rainwater_design_'));
      const rainPump=keys.filter(k=>!rainBase.includes(k) && !rainBalance.includes(k) && !rainTreatment.includes(k) && !rainDesign.includes(k));
      const controls=rain?`<div class="manual-fields">${rainBase.map(key=>control(field(key),'next')).join('')}</div><details class="config-extra" data-rainwater-active><summary>Проверка объёма по осадкам · ручной ввод</summary><p class="field-help">Если данных пока нет, их можно добавить позже. Ёмкость и экономию воды не будем придумывать.</p><div class="manual-fields">${rainBalance.map(key=>control(field(key),'next')).join('')}</div></details><details class="config-extra" data-rainwater-active><summary>Насос, обвязка и шланг</summary><p class="field-help">Для полива из бака. Каталог проверяется по расчётной точке и паспортным ограничениям. Обвязка — выбранный предварительный состав, не монтажная спецификация.</p><div class="manual-fields">${rainPump.map(key=>control(field(key),'next')).join('')}</div></details>`:`<div class="manual-fields">${keys.map(key=>control(field(key),'next')).join('')}</div>`;
      const treatmentControls=rain?`<details class="config-extra" data-rainwater-active><summary>Очистка · жилая терраса</summary><p class="field-help">Один типовой вариант для полива. Гейзер Джамбо 20 и УФ ЛЕНА — кандидаты; качество воды и рабочая производительность требуют подтверждения. Город не заменяет анализ воды.</p><div class="manual-fields">${rainTreatment.slice(0,2).map(key=>control(field(key),'next')).join('')}</div><details class="config-extra"><summary>Данные изготовителей · ручное уточнение</summary><p class="field-help">Потери фильтра и УФ складываются один раз вместо прежней общей потери очистки. Не включайте их повторно в потери труб и арматуры.</p><div class="manual-fields">${rainTreatment.slice(2).map(key=>control(field(key),'next')).join('')}</div></details></details>`:'';
      const designControls=rain?`<details class="config-extra" data-rainwater-active><summary>Паспорт решения · перед выпуском</summary><p class="field-help">Заполните после проработки системы. Укажите принятое решение и шифр документа/ревизию; это не автоматический расчёт очистки. Проверка проектировщика доступна в результатах после сохранения.</p><div class="manual-fields">${rainDesign.map(key=>control(field(key),'next')).join('')}</div></details>`:'';
      const service=keys[0]?.startsWith('sewer_service_');
      return `<details class="config-extra${vu?' metering-options':''}" data-config-extra="${group.id}-${i}"${configExpanded.has(`${group.id}-${i}`)?' open':''}><summary>${escape(title)}${vu?` <small>${count?'выбрано: '+count:'необязательно'}</small>`:''}</summary>${vu?'<p class="field-help">Компоновка и дополнительные опции. Изделия проверяются по паспортам; выбор положения не подтверждает готовность узла к монтажу.</p>':''}${controls}${service?'<p class="field-help">Настройки сохраняются в проект и ПЗ как требования. Расчёт, деталировка и оборудование пока не назначаются.</p>':''}${treatmentControls}${designControls}</details>`;
    }).join('');
    $('#clarification-body').innerHTML=`<section class="next-step config-step"><ol class="config-progress" aria-label="Порядок заполнения">${progress}</ol><p class="config-kicker">ШАГ ${index+1} ИЗ 3</p><h3 id="next-title">${escape(group.title)}</h3><p id="next-description">${escape(group.description)}</p><form data-config-form><div class="manual-fields">${group.primary.map(key=>control(field(key),'next')).join('')}</div>${extras}<p id="step-save-state" class="field-help">Пустое поле не означает ноль. Найденное в PDF подтверждается только после просмотра.</p><div class="step-footer"><button type="button" class="text-button" data-action="config-back">${index?'← Назад':'Позже'}</button><button type="submit" class="soft-button">${index===2?'Рассчитать':'Далее →'}</button></div></form></section>`;
    $('#clarification-body').querySelectorAll('[name]').forEach(input=>{const original=$('#field-'+input.name);if(original) {input.value=original.value;if(input.type==='checkbox')input.checked=original.checked;}});
    $('#clarification-body').querySelectorAll('[data-fire-station-editor]').forEach(window.ZaryaFireStation.refresh);
    $('#clarification-body').querySelectorAll('[data-hydraulic-editor]').forEach(editor=>{
      const key=editor.dataset.hydraulicEditor || 'v1_sections';
      const value=JSON.parse(editor.querySelector('[name]').value || 'null');
      editor.querySelector('[data-route-rows]').innerHTML=routeRows(value,key);
      if(key==='wastewater_fan_ventilation') editor.querySelector('[data-fan-globals]').innerHTML=window.ZaryaFanEditor.globals(value,escape);
    });
    syncLossMode();
    if(group.id==='building') {
      const button=document.createElement('button');button.type='button';button.className='location-entry';button.dataset.action='site-location';
      button.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2.5"/></svg><span><strong>Место строительства</strong><small data-location-summary></small></span>';
      $('[data-config-form]').querySelector('.manual-fields').after(button);
      locationSummary();
    }
  }
  function locationSummary() {
    const summary=$('[data-location-summary]'), place=draft?.site_location;
    if(summary) summary.textContent=place?((place.label || `${place.latitude.toFixed(6)}, ${place.longitude.toFixed(6)}`)+(place.elevation?.status==='available'?` · рельеф ≈ ${Math.round(place.elevation.metres)} м, справочно`:'')):'Выбрать на карте · необязательно, справочно';
  }
  async function continueConfig() {
    const index=config.groups.findIndex(group=>group.id===configStep);
    if(!(await saveForm(false))) return;
    if(index<2) {openConfig(config.groups[index+1].id);return;}
    if(!draft.can_calculate) {
      $('#step-save-state').textContent='Для расчёта укажите жителей и подтвердите выбор приборов. Остальные исходные можно уточнить позже.';
      $('#next-'+draft.next_question)?.focus();return;
    }
    setWorking(true);
    try {
      draft=await api('calculate',{method:'POST',body:JSON.stringify({revision:draft.revision})});
      $('#clarification-dialog').close();configStep=null;await render();say('Расчёт обновлён.');scrollTo($('#calculation'),'start');
    } catch(error) {failure(error);} finally {setWorking(false);}
  }
  function formPayload(adoptVisible=true) {
    const answers={}, preset_keys=[];
    const prompted=adoptVisible && $('#clarification-dialog').open
      ? new Set(Array.from($('#clarification-body').querySelectorAll('[name]')).filter(input=>!configStep || (!input.closest('[hidden]') && !input.closest('details:not([open])'))).map(input=>input.name)) : null;
    $('#setup-form').querySelectorAll('[name]').forEach(input=>{
      if(!draft.study && !touchedFields.has(input.name) && (!prompted || !prompted.has(input.name))) return;
      if(input.closest('[data-loss-mode],[data-hot-only],[data-heater-only]')?.hidden) return;
      if(['v1_sections','t3_sections','sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation','fire_station_model'].includes(input.name)) {
        const empty=['fire_station_model','wastewater_fan_ventilation'].includes(input.name)?null:[];
        const rows=input.value?JSON.parse(input.value):empty;
        const current=field(input.name).value || empty;
        if(JSON.stringify(rows)!==JSON.stringify(current)) answers[input.name]=rows;
        return;
      }
      const row=field(input.name), raw=input.value.trim(), value=raw || null;
      if(prompted && !touchedFields.has(row.key) && ['review','conflict'].includes(row.status) && !prompted.has(row.key)) return;
      // A placeholder for an old ambiguous roof is not an instruction to erase it.
      if(input.dataset.preservedRoof && value===null) return;
      const same=accepted(row) && (['integer','number'].includes(row.kind) ? value!==null && Number(raw.replace(',','.'))===row.value : value===row.value);
      if (same || (value===null && row.status==='missing' && !Object.hasOwn(draft.quick_start_presets || {},row.key))) return;
      answers[row.key]=value;
      if (row.status==='missing' && value!==null && draft.quick_start_presets?.[row.key]===value) preset_keys.push(row.key);
    });
    return {revision:draft.revision,answers,preset_keys};
  }
  function openManual(keys=[]) {
    if(!draft.study) {openConfig(config.groupFor(keys[0]).id,keys);return;}
    setupExpanded=true; if($('#setup-details')) $('#setup-details').open=true;
    if(!keys.length || keys.some(key=>!basicKeys.includes(key))) {manualOpen=true; $('#manual-entry').open=true;}
    const input=keys.map(key=>$('#field-'+key)).find(Boolean);
    if(input) input.focus(); else scrollTo($('#manual-entry'));
  }
  async function saveForm(calculate=false,adoptVisible=true) {
    const body=JSON.stringify(formPayload(adoptVisible));
    const submitted={...issueSnapshot(),...JSON.parse(body).answers};
    const reviewing=calculate && $('#clarification-dialog').open && !draft.calculation;
    setWorking(true); showError('');
    try {
      draft=await api(calculate && !reviewing?'calculate':'answers',{method:calculate && !reviewing?'POST':'PATCH',body});
      if(reviewing && draft.can_calculate && !draft.fields.some(row=>['review','conflict'].includes(row.status))) {
        draft=await api('calculate',{method:'POST',body:JSON.stringify({revision:draft.revision})});
      }
      dirty=false;touchedFields.clear(); if(calculate) {setupExpanded=false;manualOpen=false;selectedStep=null;} await render(); say(calculate && draft.calculation?'Расчёт обновлён.':'Изменения сохранены.');
      if(calculate) {
        if(questionSteps().length) openQuestions();
        else scrollTo($('#calculation'));
      }
      return true;
    } catch(error) {failure(error,submitted); return false;}
    finally {setWorking(false);}
  }
  function renderCalculation() {
    const result = draft.calculation;
    $('#calculation').hidden = !result;
    if (!result) { $('#calculation').replaceChildren(); return; }
const norm = draft.norms.find(norm => norm.value === field('consumer_code').value);
$('#calculation').innerHTML = `<h2 id="calculation-title">Результат</h2><p class="status confirmed demand-state">Расходы жилой группы · ${escape(field('residents').value)} жителей · ${format(norm.daily_litres)} л/(жит.·сут)</p><p class="demand-summary">Вода: <strong>${format(result.total.q_day)} м³/сут</strong> · К1, максимум за час: <strong>${format(result.total.q_hr)} м³/ч</strong></p>${calculationProgress()}<div class="calculation-output">${deliverables()}<details class="section-details result-details" id="calculation-details"><summary>Расчёты и проверки</summary><table class="flow-table"><thead><tr><th scope="col">Поток</th><th scope="col">л/с</th><th scope="col">м³/ч</th><th scope="col">м³/сут</th></tr></thead><tbody>${[['total','Всего'],['cold','Холодная вода'],['hot','Горячая вода']].map(([key,label]) => `<tr><th scope="row">${label}</th><td>${format(result[key].q_sec)}</td><td>${format(result[key].q_hr)}</td><td>${format(result[key].q_day)}</td></tr>`).join('')}</tbody></table><p>К1 по формуле для стояков (5): ${format(result.sewage_flow)} л/с, справочно для заданных потребителей. Это не расход выпуска. Горизонтальные участки рассчитываются по п. 5.7 с учётом подключённых приборов и длины L.</p>${projectResults()}</details></div>`;
    $('#calculation').insertAdjacentHTML('beforeend',rainwaterResults());
    $('#calculation').insertAdjacentHTML('beforeend',wastewaterServiceResults());
    if(!draft.study && draft.project_calculation?.water_station_review?.supported) {
      $('#calculation').insertAdjacentHTML('beforeend','<details class="section-details"><summary>Проверка всасывания · необязательно сейчас</summary><p>Один явно заданный путь и максимальный режим. Значения сохраняются отдельно в черновике.</p><button type="button" class="text-button" data-action="suction-check">Открыть проверку NPSHa →</button></details>');
    }
    $('.rainwater-result')?.insertAdjacentHTML('beforeend',rainTreatmentResult(draft.rainwater_reuse?.treatment));
    $('.rainwater-result')?.insertAdjacentHTML('beforeend',rainDesignResult(draft.rainwater_reuse?.design));
    syncLossMode();
  }
  function wastewaterServiceResults() {
    const service=draft.wastewater_service;
    if(!service) return '';
    return [service.meter,service.sump].filter(item=>item?.enabled).map(item=>
      `<details class="section-details wastewater-service-result"><summary>${escape(item.title)} · ${item.status==='invalid'?'проверьте настройки':'требуется проработка'}</summary><dl>${item.settings.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>${item.errors.map(error=>`<p role="alert">${escape(error)}</p>`).join('')}<ul>${item.requirements.map(note=>`<li>${escape(note)}</li>`).join('')}</ul><p class="field-help">${escape(item.reference)}</p><button type="button" class="text-button" data-action="wastewater-service-inputs" data-service="${item===service.meter?'k1_metering':'sump'}">Изменить настройки →</button></details>`
    ).join('');
  }
  function rainDesignResult(r) {
    if(!r || r.status==='disabled') return '';
    const label=r.confirmed?'Проверено проектировщиком':r.status==='stale'?'Проверка устарела':r.ready_for_review?'Готово к проверке проектировщиком':'Нужны проектные решения';
    return `<details class="section-details rain-design"><summary>Паспорт дождевой системы · ${label}</summary><ul>${r.rows.map(row=>`<li><strong>${row.ready?(row.kind==='document'?'Указано':'Проверено'):'Нужно'}: ${escape(row.title)}</strong><p class="field-help">${escape(row.note)}</p></li>`).join('')}</ul><p class="field-help">${escape(r.notice)}</p>${r.confirmed?`<p>${escape(r.review.reviewer)} · ${escape(r.review.reviewed_at)}</p>`:r.ready_for_review?`<label for="rain-reviewer">Проверил(а)</label><input id="rain-reviewer" class="field-control" maxlength="200" autocomplete="name" placeholder="ФИО проектировщика"><button type="button" class="soft-button" data-action="rain-review">Подтвердить проверку решения</button>`:`<button type="button" class="text-button" data-action="rain-design-inputs">Дополнить паспорт →</button>`}</details>`;
  }
  function rainwaterResults() {
    const r=draft.rainwater_reuse;
    if(!r?.enabled) return '';
    const t=r.totals;
    return `<details class="section-details result-details rainwater-result"><summary>Дождевая вода · ${t?'баланс рассчитан':'нужны данные'}</summary><p>${escape(r.purpose)} · ${escape(r.location)}. Отдельная сеть технической воды.</p>${t?`<dl><div><dt>Собрано за ${r.days.length} суток</dt><dd>${format(t.inflow_m3)} м³</dd></div><div><dt>Использовано</dt><dd>${format(t.supplied_m3)} м³</dd></div><div><dt>Не покрыто дождевой водой</dt><dd>${format(t.deficit_m3)} м³</dd></div><div><dt>Перелив</dt><dd>${format(t.overflow_m3)} м³</dd></div><div><dt>Покрытие за этот период</dt><dd>${t.coverage_percent===null?'Нет водоразбора':format(t.coverage_percent)+'%'}</dd></div></dl>`:`<p>Нужно задать: ${escape([...(r.missing||[]),...(r.errors||[])].join('; '))}.</p>`}${rainPumpResult(r.pump)}<p>${escape(r.limitations)}</p><p>${escape(r.storage_rule||'')}</p><p class="field-help">Для завершения системы нужны очистка, перелив и обоснование применения. Подбор насоса не подтверждает всю систему.</p></details>`;
  }
  function rainPumpResult(p) {
    if(!p || p.status==='not_configured') return '';
    const status={preliminary:'Кандидат по Q/H',no_match:'Подходящего насоса нет',needs_data:'Нужны данные для насоса',invalid:'Проверьте условия насоса',not_required:'Добавочный напор не требуется'};
    return `<h4>${escape(status[p.status]||p.status)}</h4>${p.duty?`<p>Q = ${format(p.duty.q_m3h)} м³/ч · H = ${format(p.duty.h_m)} м. Шланг: ${format(p.duty.hose_m)} м потерь.</p>`:''}${p.selected?`<p><strong>${escape(p.selected.model)}</strong> · ${format(p.selected.power_kw)} кВт. Напор по кривой ${format(p.selected.nominal_head_m)} м; с допуском −15%: ${format(p.selected.lower_head_m)} м.</p>`:''}<p>${escape([...p.missing,...p.errors].join('; '))}</p>${p.status==='no_match'?p.candidates.map(c=>`<p>${escape(c.model)}: ${escape(c.reasons.join(' '))}</p>`).join(''):''}<details class="section-details"><summary>Паспортные ограничения и монтаж</summary><p class="field-help">${escape(p.method)}</p><ul class="field-help">${p.pending.map(note=>`<li>${escape(note)}</li>`).join('')}</ul></details>`;
  }
  function rainTreatmentResult(t) {
    if(!t || t.status==='not_configured') return '';
    const status={preliminary:'Потери подготовки учтены по листу подбора',needs_data:'Подготовка воды · нужны данные',out_of_scope:'Водосбор вне типового варианта',no_match:'Оборудование подготовки не подходит',invalid:'Проверьте данные подготовки'};
    return `<h4>${escape(status[t.status]||t.status)}</h4>${t.candidates.map(c=>`<p>${escape(c.model)} · ${escape(c.connection)}<br><small>${escape(c.rating_note)}</small></p>`).join('')}${t.head_loss_m!==null?`<p>Фильтр + УФ: ${format(t.head_loss_m)} м потерь. Качество воды этим расчётом не подтверждено.</p>`:''}<p>${escape([...t.missing,...t.errors].join('; '))}</p>`;
  }
  function calculationProgress() {
    if(draft.study) return '';
    const p=draft.project_calculation;
    const keys=[...new Set([...(draft.handoff_missing||[]),...(draft.head_missing||[])])];
    const pending=[];
    if(keys.some(key=>(draft.handoff_missing||[]).includes(key))) pending.push('параметры здания');
    if(keys.some(key=>['guaranteed_head_m','h_geom_m','hws_heater_in_scope'].includes(key))) pending.push('данные ввода и отметки');
    if(keys.some(key=>['v1_sections','t3_sections','h_il_m','h_vvod_m','h_il_hot_m'].includes(key))) pending.push('расчётная трасса');
    if(keys.some(key=>['h_apartment_c_meter_m','h_apartment_h_meter_m','h_tepl_m'].includes(key))) pending.push('уточнение оборудования в ручных настройках');
    const text=p?.head?.ready
      ? `${p.head.preliminary?'Предварительный напор':'Напор'}: ${format(p.head.required_m)} м. ${p.head.pump_needed?'Повышение насосом: '+format(p.head.pump_m)+' м.':'Повышение напора не требуется.'}`
      : `Напор можно уточнить позже: ${pending.join('; ') || 'проверить расчётные пути'}. ${p?.can_preview?'Черновик ПЗ уже доступен; напор и насос в нём не подтверждены.':'Остальные расчёты можно продолжать.'}`;
    const estimate=draft.apartment_meters;
    return `<div class="calculation-progress"><p>${text}</p>${!p?.head?.ready?'<button type="button" class="text-button" data-action="head">Уточнить напор — необязательно сейчас →</button>':''}${estimate?`<details class="section-details"><summary>Квартирные счётчики рассчитаны автоматически</summary><p>${escape(estimate.basis)}</p><p>${Object.entries(estimate.rows).map(([key,row])=>`${key.includes('_c_')?'ХВС':'ГВС'}: DN${row.dn}, ${format(row.flow_lps)} л/с → ${format(row.loss_m)} м`).join(' · ')}</p><button type="button" class="text-button" data-action="apartment-settings">Изменить в ручных настройках →</button></details>`:''}</div>`;
  }
  function questionSteps() {
    return window.ZaryaQuestions.steps(draft);
  }
  function renderQuestions() {
    if(!draft.study) {
      $('#next-step').replaceChildren();
      if(configStep && $('#clarification-dialog').open) populateConfig();
      return;
    }
    const steps=questionSteps();
    const step=steps.find(row=>row.id===selectedStep) || steps[0];
    $('#next-step').innerHTML=step?`<button type="button" class="clarification-trigger" data-action="questions" aria-haspopup="dialog"><span class="step-dot" aria-hidden="true"></span><span><strong>Нужно уточнить</strong><small>${escape(step.title)}</small></span><span class="clarification-trigger-arrow" aria-hidden="true">↗</span></button>`:'';
    if(!step) $('#clarification-dialog').close();
    else if($('#clarification-dialog').open) populateQuestions();
  }
  function populateQuestions() {
    $('#clarification-body').innerHTML=nextStep();
    // Closing/reopening never discards unsaved typing: the ordinary form is
    // the same source for both presentations, not a second draft.
    $('#clarification-body').querySelectorAll('[name]').forEach(input=>{
      const original=$('#field-'+input.name);
      if(original) {input.value=original.value;if(input.type==='checkbox')input.checked=original.checked;}
    });
    if(dirty && $('#step-save-state')) $('#step-save-state').textContent='Изменения ещё не применены. Нажмите «Продолжить».';
    syncLossMode();
  }
  function openQuestions() {
    if(!draft.study) {openConfig('building');return;}
    if(!questionSteps().length) return;
    populateQuestions();
    if(!$('#clarification-dialog').open) $('#clarification-dialog').showModal();
    $('#clarification-body input, #clarification-body select')?.focus({preventScroll:true});
  }
  function nextStep() {
    const steps=questionSteps();
    const step=steps.find(row=>row.id===selectedStep) || steps[0];
    if(!step) return '';
    selectedStep=step.id;
    const keys=step.fields;
    return `<section class="next-step"><p class="step-kicker"><span class="step-dot" aria-hidden="true"></span>НУЖНО УТОЧНИТЬ</p><h3 id="next-title">${escape(step.title)}</h3><p id="next-description">${escape(step.description)}</p><form data-next-step><div class="manual-fields">${keys.map(key=>control(field(key),'next')).join('')}</div><p class="field-help" id="step-save-state">Только недостающие исходные. Можно вернуться позже.</p><div class="step-footer"><button type="button" class="text-button" data-action="close-questions">Позже</button><button class="soft-button" type="submit">Продолжить <span aria-hidden="true">→</span></button></div></form>${steps.length>1?`<div class="step-alternatives"><span>Другой раздел:</span>${steps.filter(row=>row.id!==step.id).map(row=>`<button class="text-button" type="button" data-action="step" data-step="${row.id}">${escape(row.title)}</button>`).join('')}</div>`:''}</section>`;
  }
  function documentKind(doc) {
    if(['pz_pdf','wastewater_pz_pdf'].includes(doc.kind) || /^Пояснительная записка/.test(doc.label)) return 'pz';
    if(/scheme_pdf$/.test(doc.kind || '') || /схема|^Схема/.test(doc.label)) return 'scheme';
    return 'other';
  }
  function documentList(documents, collection) {
    const released=collection==='package';
    const id=released?draft.package.run_id:draft.preview.id;
return `<ul class="document-list">${documents.map(doc=>`<li>${doc.file_missing?`<span>${escape(doc.label)} — файл недоступен</span>`:`<a target="_blank" rel="noopener" href="/studio/api/${collection}/${encodeURIComponent(id)}/files/${encodeURIComponent(doc.name)}">${escape(doc.label)} ↗</a>`}${['incomplete','preliminary'].includes(doc.state)?`<small class="field-help">${doc.state==='incomplete'?'Неполный документ':'Предварительный документ'}${doc.state_note?`: ${escape(doc.state_note)}`:'.'}</small>`:''}</li>`).join('')}</ul>`;
  }
  function deliverables() {
    const refresh=draft.documents_need_refresh
      ? `<p class="field-help" role="status">${draft.documents_missing_files?.length?'Часть файлов предпросмотра отсутствует или пуста. Повторно сформируйте предпросмотр. Расчётные данные сохранены.':'Генератор документов обновлён. Откройте схему или ПЗ — ЗАРЯ пересоберёт PDF. Исходные данные сохранены.'}</p>` : '';
    const packageNotice=draft.package?.state==='unavailable'
      ? `<p class="field-error" role="status">${escape(draft.package.availability_note)}</p>` : '';
    return refresh+packageNotice+deliverableContent()+(window.ZaryaSpecReview?.render(
      draft.project_calculation?.spec_quantity_review,{editable:!draft.study}) || '');
  }
  function deliverableContent() {
    const p=draft.project_calculation;
    const released=draft.package?.state==='ready';
    const unavailable=draft.package?.state==='unavailable';
    const collection=released || unavailable?'package':'preview';
    const docs=(released || unavailable?draft.package:draft.preview)?.documents || [];
    const ready=released || unavailable || p?.can_preview;
    const sectionKinds={ios2:'water_package_pdf',ios3:'wastewater_package_pdf'};
    const viewed=docs.filter(doc=>documentView==='all' || (sectionKinds[documentView]?doc.kind===sectionKinds[documentView]:documentKind(doc)===documentView));
    if(draft.study?.kind==='samara') return `<section class="delivery" aria-label="Контрольный комплект ИОС2 и ИОС3"><div class="delivery-heading"><h3>ИОС2 + ИОС3</h3><span class="release-status">Контрольный пример · не для выпуска</span></div>${p?.state==='blocked'?`<p class="field-error">${escape(p.issues.map(item=>item.message).join(' '))}</p>`:''}<div class="deliverables">${[['scheme','Схемы воды и канализации'],['pz','ПЗ ИОС2 и ИОС3'],['all','Общий PDF и приложения']].map(([view,label])=>`<button type="button" class="deliverable" data-action="documents" data-view="${view}" ${ready?'':'disabled'}><span>${label}</span><small>Одна версия исходных · PDF</small><b aria-hidden="true">↗</b></button>`).join('')}</div>${documentView && docs.length?`<div class="document-selection" tabindex="-1">${documentList(viewed,collection)}</div>`:''}<p class="field-help">Расчёты, баланс, схемы и спецификации из одной модели. Разрез К1/К2 условный: реальные трассы и длины труб ещё не подтверждены.</p></section>`;
    if(draft.study) return `<section class="delivery" aria-label="Документы учебного примера"><div class="delivery-heading"><h3>Посмотреть результат</h3><span class="release-status">Учебный пример · не для выпуска</span></div>${p?.state==='blocked'?`<p class="field-error" role="status">${escape(p.issues.map(item=>item.message).join(' '))}</p>`:''}<div class="deliverables">${[['scheme','Схема К1 + К2'],['pz','ПЗ ИОС3'],['all','Расчёты и баланс']].map(([view,label])=>`<button type="button" class="deliverable" data-action="documents" data-view="${view}" ${ready?'':'disabled'}><span>${label}</span><small>Текущие исходные · PDF</small><b aria-hidden="true">↗</b></button>`).join('')}</div>${documentView && docs.length?`<div class="document-selection" tabindex="-1">${documentList(viewed,collection)}</div>`:''}<p class="field-help">Схема, расчёты и ПЗ из одной версии модели. Состав ИОС3 ещё требует проектных исходных; выпуск заблокирован.</p></section>`;
    const action=(id,title,note)=>`<button type="button" class="deliverable" data-action="documents" data-view="${id}" ${ready?'':'disabled'}><span>${title}</span><small>${note}</small><b aria-hidden="true">↗</b></button>`;
    const schemeIncomplete=p?.sewer_scheme?.ready===false && !p?.sewer_scheme?.representative?.ready;
    const schemeNote=schemeIncomplete?'Уточните этажи, подвал и водосток':p?.sewer_scheme?.representative?.ready && !p.sewer_scheme.ready?'Условный разрез · PDF':ready?'Текущая версия · PDF':'После основных данных здания';
    const sectionState=p?.sewer_scheme?.representative;
    const sectionNeeded=[...(sectionState?.missing || []).map(key=>field(key).label), ...(sectionState?.limitations || [])];
    const schemeHelp=documentView==='scheme' && schemeIncomplete?`<div class="field-help"><p>Для разреза канализации: ${escape(sectionNeeded.join('; '))}.</p><button type="button" class="text-button" data-action="section-inputs">Уточнить параметры разреза →</button></div>`:documentView==='scheme' && sectionState?.ready?'<button type="button" class="text-button" data-action="section-design">Диаметры, уклоны и выпуски →</button>':'';
    const status=unavailable?'Сохранённый комплект недоступен целиком':released?'Комплект сформирован':p?.can_release?'Проверки пройдены — можно собрать комплект':'Комплект пока не готов к выпуску';
    const sectionDownloads=`<div class="step-alternatives" aria-label="PDF по разделам">${[['ios2','ИОС2 одним PDF'],['ios3','ИОС3 одним PDF']].map(([view,label])=>`<button type="button" class="text-button" data-action="documents" data-view="${view}" ${ready?'':'disabled'}>${label} ↗</button>`).join('')}</div>`;
return `<section class="delivery" aria-label="Документы проекта"><div class="delivery-heading"><h3>Документы</h3><span class="release-status ${released?'ready':''}">${status}</span></div><div class="deliverables">${action('scheme','Посмотреть схему',schemeNote)}${action('pz',released || unavailable?'Открыть ПЗ':'Открыть черновик ПЗ',ready?'ИОС2 и ИОС3 · PDF':'После основных данных здания')}${released?`<a class="deliverable" href="/studio/api/package/${encodeURIComponent(draft.package.run_id)}/download"><span>Скачать комплект</span><small>Все PDF одним архивом</small><b aria-hidden="true">↓</b></a>`:`<button type="button" class="deliverable" data-action="package" ${!unavailable && p?.can_release?'':'disabled'}><span>Скачать комплект</span><small>После проверки готовности</small><b aria-hidden="true">↓</b></button>`}</div>
${sectionDownloads}<p class="field-help">${unavailable?'Можно открыть сохранившиеся документы выпуска. Весь комплект недоступен; архивный снимок не изменён.':released?'Документы собраны через проверку готовности.':ready?'Можно открыть предварительные PDF по разделам. Замечания канализации не мешают посмотреть воду и наоборот; допуск к выпуску остаётся общим.':'Расходы уже рассчитаны. Для черновика PDF подтвердите основные данные здания.'}</p>${!released?`<button type="button" class="text-button" data-action="readiness">Что осталось для комплекта?</button>`:''}${draft.package?.errors?`<p class="field-error">${escape(draft.package.errors.join(' '))}</p>`:''}${schemeHelp}
${documentView && docs.length?`<div class="document-selection" tabindex="-1"><h4>${documentView==='scheme'?'Схемы':documentView==='pz'?'Пояснительные записки':documentView==='ios2'?'ИОС2 · Водоснабжение':documentView==='ios3'?'ИОС3 · Водоотведение':'Все документы'}</h4>${viewed.length?documentList(viewed,collection):'<p>Документы этого типа ещё не сформированы. Проверьте замечания раздела.</p>'}${['scheme','ios3'].includes(documentView)?sectionReview():''}</div>`:''}${docs.length?`<details class="section-details"><summary>Все документы · ${docs.length}</summary>${documentList(docs,collection)}</details>`:''}</section>`;
  }
  function sectionReview() {
    const r=draft.section_review;
    if(!r) return '';
    const labels={needs_pdf:'нужен текущий PDF',unreviewed:'ещё не просмотрен',reviewed:'просмотр сохранён',stale:'просмотр устарел'};
    const states={supplied:'Данные указаны',needs_input:'Нужны данные',drawing_work:'Доработка листа',manual_check:'Проверка проектировщика'};
    const pdf=r.current;
    return `<details class="section-details" id="section-review"><summary>Разрез ИОС3 · ${labels[r.state]}</summary><p class="field-help">${escape(r.notice)}</p>${r.state==='stale'?'<p class="field-error">После прошлого просмотра изменились исходные, версия программы или PDF. Нужна повторная проверка текущего листа.</p>':''}${r.checklist.map(row=>`<div class="readiness-item"><strong>${escape(row.title)}</strong><p>${states[row.state]} · ${escape(row.note)}</p></div>`).join('')}${r.record?`<p class="field-help">${r.state==='reviewed'?'Просмотрел(а)':'Предыдущий просмотр'}: ${escape(r.record.reviewer)} · ${escape(r.record.reviewed_at)}<br>АР: ${escape(r.record.architecture_ref)}</p>`:''}${r.can_record && r.state!=='reviewed'?`<p><a target="_blank" rel="noopener" href="/studio/api/preview/${encodeURIComponent(pdf.preview_id)}/files/${encodeURIComponent(pdf.filename)}">Открыть проверяемый PDF ↗</a></p><div class="manual-fields"><label class="field-row">Просмотрел(а)<input id="section-reviewer" class="field-control" maxlength="200" autocomplete="name" placeholder="ФИО проектировщика"></label><label class="field-row">Сверено с листами АР<input id="section-review-ar" class="field-control" maxlength="500" placeholder="Шифр, листы и версия"></label></div><p class="field-help">Отметка фиксирует просмотр с перечисленными ограничениями, а не соответствие всего листа ГОСТ.</p><button type="button" class="soft-button" data-action="section-review">Сохранить просмотр с ограничениями</button>`:''}</details>`;
  }
  function designBasis() {
    const basis=draft.design_basis;
    if(!basis || draft.study) return '';
    return `<details class="section-details" id="design-basis"><summary>Основания для ПЗ · заполнено ${basis.filled} из ${basis.total}</summary><p class="field-help">${escape(basis.notice)}</p>${basis.rows.filter(row=>row.applicable).map(row=>`<div class="readiness-item"><strong>${escape(row.title)}</strong><p>${row.filled?'Реквизиты указаны':'Нужно дополнить'} · <button type="button" class="text-button" data-action="basis-inputs" data-basis="${escape(row.code)}">${row.filled?'Проверить':'Заполнить'} →</button></p></div>`).join('')}</details>`;
  }
  function projectResults() {
    const p = draft.project_calculation;
    if(p?.ios2 && p?.fire_station) return `<p>${escape(p.fire_station.model)} · 1 рабочий + 1 резервный.</p><p>Qмин ${format(p.fire_station.q_min_m3h)} м³/ч · Hтреб ${format(p.fire_station.head_m)} м. Потери принятой обвязки ${format(p.fire_station.pipework_loss_m)} м.</p>${p.wastewater?`<p>К1 по ф.(5), не расход выпуска: ${format(p.wastewater.q_k1_lps)} л/с · К2: ${format(p.wastewater.q_k2_lps)} л/с. Суточный баланс: ${format(p.wastewater.q_day_m3)} м³/сут.</p>`:''}<p>Предварительное решение только для этого контрольного примера. Не подтверждает заводскую станцию или готовность к экспертизе.</p>`;
    if(p?.state==='study') return `<p>Дождевые воды К2: ${format(p.storm.q_total_l_per_s)} л/с. Версия модели: ${escape(p.model_hash.slice(0,12))}.</p><p>Учебная схема не подтверждает реальные трассы, точки сброса и возможность обслуживания. Напор и подбор насосов этим примером не проверяются.</p>`;
    if (!p || p.state === 'needs_inputs') return '<p class="result-note">Для напоров, проверки В2 и комплекта документов нужны параметры здания. Они показаны в карточке выше.</p>';
    if (p.state === 'blocked') return `<div class="result-note">${p.issues.map(item => `<p>${escape(item.message)}</p>`).join('')}</div>`;
    const tile = (title, status, body, action='') => {
      const options=title==='Водомерные узлы' && p.metering_options?.length;
      const equipment=p.metering_equipment;
      const extras=options?`<details class="equipment-cards"><summary>Дополнительное оборудование</summary>${equipment?.items?.length?`<p>${equipment.items.map(row=>`${escape(row.manufacturer)} ${escape(row.model)} — ${row.qty} шт.`).join('<br>')}</p><p>На одну водомерную. Предварительный состав добавлен в спецификацию; подключение и монтаж уточнить.</p>`:'<p>Выбраны пожелания или кандидаты; количество ещё не назначено.</p>'}${(equipment?.issues || []).map(note=>`<p class="field-error">${escape(note)}</p>`).join('')}<p>DN и потери выше относятся к базовому расчёту.</p></details>`:'';
      const layout=title==='Водомерные узлы'?meteringLayoutResult(p.metering_layout):'';
      const station=title==='Насосная установка'?waterStationReview(p.water_station_review):'';
      return `<section class="result-tile"><h3>${title}</h3><div class="status ${status}"><div class="result-body">${body}</div></div>${layout}${station}${extras}${action ? `<button class="text-button" data-action="${action}">Ручной ввод →</button>` : ''}</section>`;
    };
    const coldPath = p.head.paths.find(path=>path.code==='V1');
    const head = p.head.ready ? `${p.head.preliminary?'Предварительно: ':''}Hтр = ${format(p.head.required_m)} м; повышение напора ${format(p.head.pump_m)} м` : coldPath?.complete ? `В1: Hтр = ${format(coldPath.head.h_required_m)} м. Общий подбор ожидает данных остальных путей.` : 'Нужны отметки и потери; условные значения не подставляем';
    const pump = !p.head.ready ? 'Подбор ожидает расчёт напора' : p.head.pump_needed === false ? 'Повышение напора не требуется' : p.pumps?.model ? `${escape(p.pumps.model)}<br>Предварительная точка: ${format(p.pumps.wp_q)} м³/ч · ${format(p.pumps.wp_h)} м<br>Пригодность насоса требует завершения проверки${p.pumps.top3?.[0]?.archived ? '<br>Архивная кривая — требуется подтверждение производителя' : ''}` : 'Каталог не дал подтверждённого подбора';
    const metersReady = !p.meter_error && p.meters.length && p.meters.every(row => row.ok_average === true && row.ok_a && (row.ok_b || row.need_bypass) && row.ok_v === true && !row.product?.errors?.length && !row.product?.pending?.length);
    const meterPassports = p.meters.filter(row=>row.product?.id || row.product?.errors?.length).map(row=>{
      const product=row.product;
      return `<article><strong>${escape(row.label)}</strong><p>${escape(product.name || 'Модель не подтверждена')}${product.automatic?' · предложение каталога':''}</p>${product.id?`<p>Qmin ${format(product.qmin_m3h,3)} · Qmax ${format(product.qmax_m3h)} м³/ч · корпус ${format(product.body_length_mm,0)} мм</p><p>${escape(product.hydraulic_basis || '')}</p>${product.hydraulic_evidence?`<p>${escape(product.hydraulic_evidence.note)}</p>`:''}`:''}<p>${escape(product.minimum_note)}</p>${product.pending.map(note=>`<p>${escape(note)}</p>`).join('')}${product.sources.map(source=>`<a href="${escape(source.url)}" target="_blank" rel="noopener noreferrer">Паспорт изготовителя ↗</a>`).join('')}</article>`;
    }).join('');
    const meters = p.meter_error ? escape(p.meter_error) : p.meters.length ? `<span>${p.meters.map(row => `${escape(row.label.split('(')[0].trim())}: DN${row.dn}, потери ${format(row.h_a)} м`).join('<br>')}${p.meters.some(row => row.ok_average !== true) ? '<br><small>Требуется пересчёт проверки среднего расхода.</small>' : ''}${p.meters.some(row => row.ok_v !== true) ? '<br><small>Проверка минимального расхода здания пока не завершена.</small>' : ''}</span>${meterPassports?`<details class="equipment-cards"><summary>Модели и паспорта</summary>${meterPassports}</details>`:''}` : 'Не определены';
    const fire = p.fire.required ? `${p.fire.streams} × ${format(p.fire.q_per_stream)} л/с · ${escape(p.fire.normative_note)}` : `ВПВ не требуется · ${escape(p.fire.normative_note)}`;
    const storm = p.storm ? `Q = ${format(p.storm.q_total_l_per_s)} л/с` : 'Нужны кровля, город и водосборная площадь';
    const findings = p.quality.gates.flatMap(gate => gate.findings).filter(item => item.state !== 'ready' && item.source !== 'quality_gates');
    const findingCodes = new Set(findings.map(item => item.code));
    findings.push(...(p.gost_blockers || []).filter(row => !findingCodes.has(row.rule_id)).map(row => ({code:row.rule_id,state:'blocked',title:row.title,detail:row.evidence,action:'Дополнить исходные данные перед выпуском.',reference:row.reference})));
    const sections=p.review_sections || [{id:'common',title:'Замечания комплекта',findings}];
    const groupedCodes=new Set(sections.flatMap(section=>section.findings.map(item=>item.code)));
    const ungrouped=findings.filter(item=>!groupedCodes.has(item.code));
    const displayed=ungrouped.length?[...sections,{id:'additional',title:'Дополнительные проверки',findings:ungrouped}]:sections;
    const rowAction=(item,key)=>id=>window.ZaryaFindingInputs?.renderRow(item,key,id,p,field(key)?.value,!draft.study) || '';
    const findingHTML=item=>`<div class="readiness-item" data-finding-code="${escape(item.code)}"><h3>${escape(item.title)}</h3><p>${escape(item.detail)}</p><p>${escape(item.action)}</p>${item.reference?`<small>${escape(item.reference)}</small>`:''}${item.code==='K1-02'?window.ZaryaRiserReview?.render(p.sewage_riser_review,{rowAction:rowAction(item,'sewage_risers')}) || '':''}${item.code==='K1-05'?window.ZaryaDiagnosticReview?.render(p.sewage_diagnostic_review,{rowAction:rowAction(item,'sewer_pipes')}) || '':''}${window.ZaryaFindingInputs?.render(item,{editable:!draft.study}) || ''}</div>`;
    const sectionHTML=section=>{
      const blockers=section.findings.filter(item=>item.state==='blocked');
      const notes=section.findings.filter(item=>item.state!=='blocked');
      return `<details class="section-details" data-review-section="${escape(section.id)}"><summary>${escape(section.title)} · к выпуску: ${blockers.length} · уточнения: ${notes.length}</summary>${blockers.length?`<h3>Нужно закрыть перед выпуском</h3>${blockers.map(findingHTML).join('')}`:''}${notes.length?`<h3>Проверки и ограничения · не блокируют выпуск сами по себе</h3>${notes.map(findingHTML).join('')}`:''}${!section.findings.length?'<p>Замечаний этой группы нет. Это не самостоятельный допуск раздела к выпуску.</p>':''}</details>`;
    };
    return `<div class="result-grid">${tile('Напор В1 / Т3',p.head.ready?'confirmed':'review',head,p.head.ready?'':'head')}${tile('Насосная установка',p.head.ready && (!p.head.pump_needed || p.pumps?.model)?'confirmed':'review',pump)}${tile('Водомерные узлы',metersReady?'confirmed':'review',meters)}${tile('Пожарный водопровод В2','confirmed',fire)}${tile('Дождевые воды К2',p.storm?'confirmed':'review',storm,p.storm?'':'storm')}${tile('ГВС и циркуляция','review',hwsCirculationBody(p))}</div>
      ${window.ZaryaFireStation.result(p.fire_station,format)}${hydraulicResults(p.hydraulics)}<details class="section-details result-details"><summary>Составляющие напора и расчётные пути</summary>${p.head.paths.map(path=>`<h3>${escape(path.label)}</h3><p>${path.complete ? 'Слагаемые рассчитаны' : 'Расчёт неполный'}${path.missing.length ? ': '+escape(path.missing.join(', ')) : ''}</p><dl>${path.head.components.map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${value===null?'не задано':format(value)+' м'}</dd></div>`).join('')}</dl>`).join('') || '<p>Пути пока не определены.</p>'}</details>
      ${originResults(p.equipment_origin)}${designBasis()}<details class="section-details result-details" id="release-readiness"><summary>Что осталось для выпуска · ${findings.length} замечаний</summary><p>${escape(p.quality.release_status)}</p>${displayed.map(sectionHTML).join('')}<p>Разделение списка не отменяет общих проверок. Недостающие данные не заменяются выдуманными решениями.</p></details>`;
  }
  function meteringLayoutResult(layout) {
    if(!layout) return '';
    const counts=layout.connections;
    const hot=layout.hot_drawing;
    const hotSummary=(hot?`<p>${escape(hot.title)}: ${hot.available?'отдельные листы доступны':'компоновка требует уточнения'}.</p>${(hot.issues||[]).map(note=>`<p class="field-error">${escape(note)}</p>`).join('')}`:'')+meteringSupportsResult(layout.supports);
    const filterLabel=layout.filter_layout==='valtec_vt386'?'Фильтр VT.386 на оси узла.':layout.filter_layout==='valtec_vt192_vtr090'?'Горизонтальный фильтр + два отвода.':'';
    return `<details class="equipment-cards" data-metering-layout><summary>Компоновка · ${escape(layout.label)}</summary><p>${layout.drawing_available?'Габаритная схема основного ввода доступна':'Габаритная схема требует уточнения'} · М 1:${escape(layout.scale)}</p>${(layout.nodes||[]).map(n=>`<p>${escape(n.title)}: ${escape(n.label)}</p>`).join('')}${hotSummary}${filterLabel?`<p>${escape(filterLabel)} Исполнение проверяется по текущему DN.</p>`:''}${layout.issues.map(note=>`<p class="field-error">${escape(note)}</p>`).join('')}<p>Соединения основного узла: согласованы типы — ${counts.ports_match}; уточнить — ${counts.unresolved}; несовместимы — ${counts.incompatible}.</p>${layout.unselected_connectors?`<p>Соединительные детали без подтверждённой модели: ${layout.unselected_connectors}.</p>`:''}<p class="field-help">${escape(layout.notice)}</p>${meteringMaintenanceResult(layout.maintenance,'Основной узел')}${meteringMaintenanceResult(hot?.maintenance,'Узел ГВС')}<button type="button" class="text-button" data-action="metering-layout">Изменить компоновку →</button></details>`;
  }
  function meteringSupportsResult(report) {
    if(!report?.rows?.length) return '';
    return `<details class="section-details" data-metering-supports><summary>Постоянные опоры · точек: ${report.rows.length}</summary><p class="field-help">Предварительный состав. Расстояния, нагрузки и крепление к конструкциям требуют привязки; устойчивость при разборке не подтверждена.</p>${report.rows.map(r=>`<details><summary>${escape(r.mark)} · ${escape(r.title)} · ${r.active?'предварительно':'выбор несовместим'}</summary><p>${escape(r.product?.title||'Изделие не найдено')} · всего: ${r.quantity??'не определено'}</p>${r.errors.map(t=>`<p class="field-error">${escape(t)}</p>`).join('')}${r.pending.map(t=>`<p>${escape(t)}</p>`).join('')}</details>`).join('')}</details>`;
  }
  function meteringMaintenanceResult(report,title) {
    if(!report) return '';
    const labels={checked:'проверено по модели',needs_data:'нужны данные',blocked:'не обеспечено в модели'};
    const modes=report.operating_modes;
    const modeHtml=modes?`<details class="section-details" data-metering-modes><summary>Режимы арматуры · ВУ Г.1</summary><p>${escape(modes.notice)}</p><p>О — открыто; З — закрыто; ? — не задано; М — измерение. Метки совпадают со схемой.</p>${modes.modes.map(row=>`<details data-vu-mode="${escape(row.id)}"><summary>${escape(row.title)} · ${escape(row.status_label)}</summary><p>${escape(row.position_text)}</p>${row.notes.map(text=>`<p>${escape(text)}</p>`).join('')}${row.checks?`<p>Путь к заданным выходам: ${row.checks.supplied?'есть':'не подтверждён'}. Расход и напор этим не подтверждены.</p>`:''}${row.checks?.crossfeed_paths?.length?'<p>Есть связь вводов до счётчика: проверить давления и ТУ.</p>':''}${row.checks?.failures?.length?'<p class="field-error">В этом состоянии выявлено нарушение; см. проверку путей/обслуживания в выдаче.</p>':''}</details>`).join('')}<details><summary>Обозначения на схеме</summary>${modes.valves.map(v=>`<p>${escape(v.mark)} — ${escape(v.title)}</p>`).join('')}</details><details><summary>Недопустимые сочетания</summary>${modes.forbidden.map(t=>`<p>${escape(t)}</p>`).join('')}</details></details>`:'';
    return `${modeHtml}<details class="section-details" data-metering-maintenance><summary>Обслуживание · ${escape(title)}</summary><p class="field-help">${escape(report.notice)}</p>${report.scenarios.map(row=>`<details class="section-details" data-maintenance-target="${escape(row.target)}"><summary>${escape(row.operating_mark||'')} ${escape(row.title)} · ${escape(row.status_label)}</summary><p>Отсечение: ${escape(labels[row.isolation])} · Сброс давления: ${escape(labels[row.pressure_relief])} · Слив: ${escape(labels[row.drainage])} · Впуск воздуха: ${escape(labels[row.air_admission])}</p><p>Границы отсечения по модели: ${row.close_titles.map(escape).join(', ')||'не найдены'}.</p>${row.messages.map(message=>`<p>${escape(message)}</p>`).join('')}</details>`).join('')}</details>`;
  }

  function waterStationHeadBalance(balance) {
    if(!balance) return '';
    const metres=value=>value==null?'нет данных':`${escape(format(value))} м`;
    return `<details data-station-head-balance><summary>Из чего складывается напор</summary>
      ${balance.status==='stale'?'<p class="field-error">Исходные изменились: сохранённый подбор требует пересчёта.</p>':''}
      ${balance.paths.map(p=>`<p><b>${escape(p.label)}</b>${p.code===balance.governing?' · диктующий':''}</p>
        <table class="flow-table"><thead><tr><th>Составляющая</th><th>Напор</th></tr></thead><tbody>
        ${p.components.map(c=>`<tr><td>${escape(c.label)}</td><td>${metres(c.value_m)}</td></tr>`).join('')}
        <tr><th>Требуемый напор в точке подключения</th><td>${metres(p.required_head_m)}</td></tr>
        <tr><th>Гарантированный напор</th><td>${metres(p.guaranteed_head_m)}</td></tr>
        <tr><th>Требуемая добавка насоса</th><td>${metres(p.pump_head_m)}</td></tr></tbody></table>
        ${p.missing.map(m=>`<p class="field-error">${escape(m)}</p>`).join('')}`).join('')}
      <p>${escape(balance.local_loss_note)}</p><p>${escape(balance.coverage_note)}</p>
      <p class="field-help">${escape(balance.method)}</p></details>`;
  }
  function waterStationReview(report) {
    if(!report) return '';
    const access=waterStationHeadBalance(report.head_balance)+(report.access_requirements||[]).map(a=>`<p data-station-access-requirement="${escape(a.id)}"><b>${escape(a.mark)}* — ${escape(a.location)}.</b> ${escape(a.requirement)} ${escape(a.scope)}</p>`).join('');
    return `<details class="section-details" data-water-station-review><summary>Насосная В1 · увязка и обслуживание</summary><p>${escape(report.notice)}</p>${report.unsupported_note?`<p>${escape(report.unsupported_note)}</p>`:''}${report.scenarios.map(s=>`<p>${escape(s.title)}: отсечки ${s.close_tags.map(escape).join(', ')}; ${escape(s.active)} — ${s.delivery_path_exists?'путь подачи есть, Q/H требуют проверки':'путь подачи не подтверждён'}. Это не разрешает ремонт при работающей станции.</p><p>${escape(s.body_service||'')} ${escape(s.pocket_note||'')}</p>`).join('')}${report.service?`<p>${escape(report.service.summary)}</p><p>${escape(report.service.maintenance)}</p><p class="field-help">${escape(report.service.source)}</p>`:''}${access}<details><summary>Расчёт и ограничения</summary>${report.hydraulic.map(h=>`<p><b>${escape(h.title)}:</b> ${escape(h.value)}. ${escape(h.note)}</p>`).join('')}</details><details><summary>Задание автоматчикам</summary>${report.automation.map(a=>`<p><b>${escape(a.title)}:</b> ${escape(a.action)}</p>`).join('')}</details></details>`;
  }
  function originResults(report) {
    if(!report?.enabled) return '';
    const missing=report.rows.filter(row=>!row.ready);
    return `<details class="section-details"><summary>Российское оборудование · ${missing.length?'не подтверждено: '+missing.length:'проверено'}</summary><p>${escape(report.notice)}</p>${report.rows.map(row=>`<p>${row.ready?'✓':'!'} ${escape(row.name)} — ${row.ready?'Россия, по данным изготовителя':'страна / модель не подтверждена'}</p>`).join('')}</details>`;
  }
  function hwsCirculationBody(p) {
    if(field('hws_type').value==='none') return 'ГВС отсутствует по исходным данным';
    const h=p.hws_circulation;
    const edit='<button type="button" class="text-button" data-action="hws-circulation">Циркуляция · стадия П →</button>';
    const scope='<p class="field-help">Оценка общего расхода. Напор насоса, расходы ветвей и настройки балансиров не определены.</p>';
    if(!h || h.status==='not_requested') return `<p>Мощность нагрева без теплопотерь: ${format(p.flows.heat_max_kw)} кВт (65/5 °C).</p>${edit}`;
    if(h.status!=='preliminary') return `<p>${[...(h.missing||[]),...(h.notes||[])].map(escape).join(' ')}</p>${edit}`;
    const range=(xs,units)=>`${format(xs[0],3)}–${format(xs[1],3)} ${units}`;
    const selected=h.selected_flow_lps!==null;
    return `<div data-hws-stage-p><p><strong>Циркуляция · укрупнённо, стадия П</strong></p><p>${selected?`Принято ${format(h.inputs.loss_percent)}%: ${format(h.selected_flow_lps,3)} л/с · ${format(h.selected_flow_m3h,3)} м³/ч`:`Диапазон ${h.percent_range[0]}–${h.percent_range[1]}%: ${range(h.flow_range_lps,'л/с')} · ${range(h.flow_range_m3h,'м³/ч')}`}</p><p>Теплопотери: ${selected?format(h.selected_heat_loss_kw)+' кВт':range(h.heat_loss_range_kw,'кВт')}. Δt = ${format(h.inputs.delta_t_c)} °C.</p><details><summary>Как рассчитано</summary><p>qч ГВС = ${format(h.hot_hour_m3h,3)} м³/ч; температуры ${format(h.inputs.hot_temp_c)}/${format(h.inputs.cold_temp_c)} °C.</p><p>Qнагрев = 1,16 × qч × (tгор − tхол) = ${format(h.base_heat_kw)} кВт;<br>Qпот = k × Qнагрев;<br>qцир = Qпот / (4,2 × Δt).</p><p>${escape(h.method)}</p><p>МКД с водяными полотенцесушителями в ГВС. Зон: ${h.inputs.zones}. При выборе двух зон оценка общая, не распределение по зонам.</p></details>${scope}${edit}</div>`;
  }
  function hydraulicResults(h) {
    return v1HydraulicResults(h)+hotHydraulicResults(draft.project_calculation?.hot_hydraulics);
  }
  function hotHydraulicResults(h) {
    if(!h)return '';
    return `<details class="section-details result-details" id="hot-hydraulic-results"><summary>Потери по пути Т3 · ${h.total_loss_m===null?'нужны данные':format(h.total_loss_m)+' м'}</summary><p>${escape(h.method)}. Расчёт по формуле (15) при опорных 10 °C. kₗ = 0,30; водомеры и теплообменник не включены.</p>${h.missing.map(item=>`<p class="field-error">${escape(item)}</p>`).join('')}<div class="hydraulic-scroll" tabindex="0" aria-label="Расчёт участков Т3"><table class="flow-table"><thead><tr><th>Участок</th><th>q исходный</th><th>kcir</th><th>q расч., л/с</th><th>v, м/с</th><th>Потери, м</th></tr></thead><tbody>${h.sections.filter(row=>!row.missing).map(row=>`<tr><th>${escape(row.section_id)}</th><td>${format(row.original_flow_lps)}</td><td>${format(row.circulation_factor)}</td><td>${format(row.flow_lps)}</td><td>${format(row.velocity_mps)}${row.velocity_ok?'':' · выше допустимой'}</td><td>${format(row.total_loss_m)}</td></tr>`).join('')}</tbody></table></div><p class="field-help">${escape(h.scope)}. Для режима «уже скорректирован» поправка повторно не применяется.</p></details>`;
  }
  function v1HydraulicResults(h) {
    if(!h)return '';
    return `<details class="section-details result-details" id="hydraulic-results"><summary>Потери по участкам В1 · ${format(h.total_loss_m)} м</summary><p>Ввод: ${format(h.input_loss_m)} м · Внутренняя сеть: ${format(h.internal_loss_m)} м. Местные потери уже включены.</p><div class="hydraulic-scroll" tabindex="0" aria-label="Расчёт участков В1"><table class="flow-table"><thead><tr><th>Участок</th><th>q, л/с</th><th>v, м/с</th><th>Линейные, м</th><th>kₗ</th><th>Всего, м</th></tr></thead><tbody>${h.sections.map(row=>`<tr><th>${escape(row.section_id)}</th><td>${format(row.flow_lps)}</td><td>${format(row.velocity_mps)}${row.velocity_ok?'':' · выше допустимой'}</td><td>${format(row.linear_loss_m)}</td><td>${format(row.local_loss_factor)}</td><td>${format(row.total_loss_m)}</td></tr>`).join('')}</tbody></table></div><p class="field-help">Показан заданный последовательный путь В1, не вся сеть здания. Трассу Т3 необходимо проверять отдельно.</p></details>`;
  }
  function render(animate = true) {
    return motion.change(renderContent, visibleScreen, animate);
  }
  function openProject() {
    workspaceOpen = true;
    if (new URLSearchParams(location.search).get('view') !== 'project') {
      history.pushState(null, '', '/studio?view=project');
    }
  }
  function renderContent() {
    const inProject = workspaceOpen && !!draft;
    root.classList.toggle('compact', inProject);
    if (inProject) root.classList.remove('intro');
    $('#entry').hidden = inProject;
    $('#workspace').hidden = !inProject;
    $('#busy').hidden = true;
    const nav = root.querySelector('[data-site-page="studio"]');
    if (inProject) nav.setAttribute('aria-current', 'page');
    else nav.removeAttribute('aria-current');
    if (!inProject) {
      $('#next-step').replaceChildren();$('#clarification-dialog').close();
      $('#resume-project').hidden = !draft;
      $('#resume-title').textContent = draft?.study ? 'Учебный пример сохранён' : field('object_name')?.value || 'Ваш проект сохранён';
      $('#entry [data-action="manual"]').textContent = draft ? 'Продолжить без загрузки →' : 'Начать без документов →';
      $('#entry-context').textContent = draft?.study ? 'Открыт учебный пример. Чтобы добавить документы, сначала вернитесь к своему проекту.' : draft ? 'Документы добавятся к вашему сохранённому проекту.' : 'PDF сохраняются на сервере проекта. Без отправки во внешние ИИ-сервисы.';
      return;
    }
    $('#project-title').textContent = field('object_name')?.status === 'confirmed' && field('object_name').value ? field('object_name').value : 'Жилой дом';
    $('#study-banner').innerHTML=draft.study?`<section class="study-banner"><div><strong>Учебный пример · ${escape(draft.study.title)}</strong><p>${escape(draft.study.description)}</p></div><div><button type="button" class="text-button" data-action="examples">Другой пример</button><button type="button" class="text-button" data-action="exit-study">Вернуться к своему проекту →</button></div></section>`:`<button type="button" class="text-button" data-action="examples">Попробовать на примере →</button>`;
    $('.workspace-heading [data-action="choose"]').hidden=!!draft.study;
    $('#documents').innerHTML = draft.documents.map(doc => `<span class="document-chip"><a href="/studio/api/files/${encodeURIComponent(doc.id)}" target="_blank" rel="noopener">${escape(doc.name)} ↗</a>${doc.status !== 'text' ? `<small>${doc.status === 'scan' ? 'нет текстового слоя · просмотр' : 'частично прочитан'}</small>` : ''}${draft.study ? '' : `<button type="button" class="document-remove" data-action="delete-document" data-document-id="${escape(doc.id)}" aria-label="Удалить ${escape(doc.name)}" title="Удалить из проекта">×</button>`}</span>`).join('');
    $('#documents').hidden=!draft.documents.length;
    $('#widgets').innerHTML = setup();
    if($('#pilot-archive-actions')) $('#pilot-archive-actions').hidden=!!draft.study;
    const archiveState = $('#pilot-auto-state');
    if (archiveState) {
      const saved = draft.pilot_archive;
      archiveState.textContent = draft.study || !saved ? '' : saved.state === 'saved' ? `В архиве пилота сохранена версия ${saved.version}. При изменении исходных пересчитайте проект.` : saved.message;
      archiveState.style.color = saved?.state === 'failed' ? '#ac253a' : '#68766e';
    }
    renderCalculation();
    renderQuestions();
    syncLossMode();
  }
  async function manual() {
    if (working) return;
    setWorking(true); showError('');
    try { await ensureDraft(); openProject(); await render(); say('Проект открыт.'); $('#project-title')?.focus(); if(!draft.study && !draft.calculation) openConfig('building'); }
    catch(error) { failure(error); }
    finally { setWorking(false); }
  }
  async function upload(files) {
    if (working || !files.length) return;
    if (files.length > 10 || files.some(file => !/\.pdf$/i.test(file.name) || !file.size || file.size > 10*1024*1024) || files.reduce((size,file)=>size+file.size,0) > 40*1024*1024) {
      showError('Выберите от 1 до 10 непустых PDF до 10 МБ каждый и до 40 МБ суммарно.'); return;
    }
    if(dirty && !(await saveForm(false))) return;
    setWorking(true, 'Читаем документы.'); showError('');
    try {
      await ensureDraft();
      openProject();
      await motion.change(() => {
        root.classList.add('compact'); root.classList.remove('intro');
        $('#entry').hidden=true; $('#workspace').hidden=true; $('#busy').hidden=false;
        $('#busy-title').textContent='Читаем документы';
        $('#busy-description').textContent='Извлекаем текстовый слой и ищем исходные значения.';
      }, visibleScreen);
      const body=new FormData(); body.append('revision', String(draft.revision));
      files.forEach(file => body.append('files',file));
      draft=await api('files',{method:'POST',body});
      await render(); say('Документы прочитаны. Найденные значения нужно подтвердить.');
      openQuestions();
    } catch(error) { await render(false); failure(error); }
    finally { setWorking(false); }
  }
  root.addEventListener('click', async event => {
    const button=event.target.closest('button');
    const link=event.target.closest('a[href]');
    const normalClick=!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
    if(working && (button || link)) {event.preventDefault();return;}
    if(link && draft && dirty && normalClick && !link.target && !link.getAttribute('href').startsWith('#')) {
      event.preventDefault();
      if(await saveForm(false)) window.location.assign(link.href);
      return;
    }
    if(!button) return;
    const action=button.dataset.action;
    if(action==='download-input-copy') {
      if(!draft || draft.study || !dirty)return;
      try {
        const copy=window.ZaryaInputRecovery.create(draft,formPayload(false));
        const url=URL.createObjectURL(new Blob([JSON.stringify(copy,null,2)+'\n'],{type:'application/json;charset=utf-8'}));
        const link=document.createElement('a');link.href=url;link.download='zarya-unsaved-input.json';
        document.body.append(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
        say('Копия ввода передана браузеру для скачивания. Серверный проект и версия не изменены.');
      } catch {say('Не удалось подготовить копию. Ввод остаётся в этой вкладке; не обновляйте её до ручного сохранения данных.');}
      return;
    }
    if(action==='input-issue') {
      const saved=inputIssueTargets[Number(button.dataset.issueIndex)];if(!saved)return;
      const candidate=window.ZaryaInputIssues.resolve(saved.issue,saved.rows,saved.rows,!draft.study,issueEditors(),{submitted:saved.submitted,current:saved.submitted});
      if(!candidate)return;
      let rows;
      try {rows=JSON.parse($('#field-'+candidate.key)?.value || 'null');} catch {rows=null;}
      const target=window.ZaryaInputIssues.resolve(saved.issue,saved.rows,rows,!draft.study,issueEditors(),{submitted:saved.submitted,current:issueSnapshot()});
      if(!target) {showError('Исходные после проверки изменились. Откройте реестр и повторите сохранение; прежний адрес ошибки больше не применяется.');return;}
      openConfig('connection',[target.key]);
      const editor=$('#clarification-body [data-input="'+target.key+'"]');
      const row=editor?.querySelectorAll('.route-row')[target.index];
      const input=target.scope==='global'?editor?.querySelector('[data-fan-global="'+target.field+'"]')
        :row?.querySelector('[data-column="'+target.field+'"]');
      if(!input) {showError('Поле не найдено. Проверьте исходные в реестре.');return;}
      for(let parent=input.parentElement;parent && parent!==$('#clarification-body');parent=parent.parentElement) {
        if(parent.tagName==='DETAILS')parent.open=true;
      }
      showError('');
      input.focus({preventScroll:true});input.scrollIntoView({block:'center',behavior:'instant'});
      say('Открыто поле: '+target.label+'. Изменения ещё не сохранены.');return;
    }
    if(action==='finding-row') {
      const navigation=window.ZaryaFindingInputs;
      const item=draft.project_calculation?.quality?.gates.flatMap(gate=>gate.findings)
        .find(row=>row.code===button.dataset.finding);
      const allowed=navigation?.resolve(item,button.dataset.findingInput,!draft.study);
      if(!allowed) return;
      // Read current unsaved backing values too; never restore a deleted/renamed row.
      let rows;
      try {rows=JSON.parse($('#field-'+allowed.key)?.value || 'null');} catch {rows=null;}
      const target=navigation.resolveRow(item,allowed.key,button.dataset.findingRow,draft.project_calculation,rows,!draft.study);
      const missing=()=>showError('Точный переход недоступен: нет единственного совпадения ID в результате и текущем реестре. Проверьте исходные в реестре; строки автоматически не создаются.');
      if(!target) {missing();return;}
      openConfig(target.group,[target.key]);
      const editor=$('#clarification-body [data-input="'+target.key+'"]');
      const inputs=Array.from(editor?.querySelectorAll('[data-column="'+target.field+'"]') || []);
      const index=navigation.exactIndex(inputs.map(input=>({[target.field]:input.value})),target.field,target.id);
      if(index<0) {missing();return;}
      const section=editor.closest('details');if(section)section.open=true;
      inputs[index].focus({preventScroll:true});inputs[index].scrollIntoView({block:'center',behavior:'instant'});
      say('Открыта строка '+target.id+'. Исходные не изменены.');
      return;
    }
    if(action==='finding-inputs') {
      const item=draft.project_calculation?.quality?.gates.flatMap(gate=>gate.findings)
        .find(row=>row.code===button.dataset.finding);
      const target=window.ZaryaFindingInputs?.resolve(item,button.dataset.findingInput,!draft.study);
      if(!target) return;
      openConfig(target.group,[target.key]);
      const editor=$('#clarification-body [data-input="'+target.key+'"]');
      const section=editor?.closest('details');
      if(section) {
        section.open=true;
        const summary=section.querySelector('summary');
        summary?.focus({preventScroll:true});summary?.scrollIntoView({block:'start'});
      }
      return;
    }
    if(action==='suction-check') {
      if(dirty && !(await saveForm(false))) return;
      window.ZaryaSuction.open({api,projectId:draft.project_id,onSaved:async()=>{draft=await api('draft');await render(false);say('Проверка всасывания сохранена в черновике.');}});return;
    }
    if(action==='basis-inputs') {
      const row=draft.design_basis?.rows.find(item=>item.code===button.dataset.basis);
      if(row) openConfig(row.group,row.fields);return;
    }
    if(action==='site-location') {
      window.ZaryaLocation.open({draft,api,onSaved:result=>{draft={...draft,...result};locationSummary();say('Место сохранено. Расчётные исходные не изменены.');}});return;
    }
    if(action==='pilot-snapshot') {
      if(dirty && !(await saveForm(false,false))) return;
      await window.ZaryaPilotObjects?.open();return;
    }
    if(action==='config' || action==='config-start') {openConfig(button.dataset.config || 'building');return;}
    if(action==='metering-layout') {openConfig('connection',['vu_orientation','vu_drawing_scale']);return;}
    if(action==='spec-quantity-inputs') {
      if(draft.study) return;
      const target=draft.project_calculation?.spec_quantity_review?.actions.find(
        item=>item.id===button.dataset.specInput);
      if(target) openConfig(target.id==='area' ? 'building' : 'consumers',target.fields);
      return;
    }
    if(action==='config-back') {
      const index=config.groups.findIndex(group=>group.id===configStep);
      if(!(await saveForm(false,false))) return;
      if(index>0) openConfig(config.groups[index-1].id);else $('#clarification-dialog').close();
      return;
    }
    if(action==='delete-document') {
      const doc=draft.documents.find(item=>item.id===button.dataset.documentId);
      if(!doc) return;
      if(dirty && !(await saveForm(false))) return;
      deletingDocument=doc.id;
      $('#delete-document-name').textContent=doc.name;
      motion.stop(); // A transition snapshot must not cover a native modal.
      $('#delete-document-dialog').showModal(); return;
    }
    if(action==='cancel-delete-document') {$('#delete-document-dialog').close();deletingDocument=null;return;}
    if(action==='confirm-delete-document' && deletingDocument) {
      setWorking(true);showError('');
      try {
        draft=await api('files/delete',{method:'POST',body:JSON.stringify({revision:draft.revision,document_id:deletingDocument})});
        $('#delete-document-dialog').close();deletingDocument=null;documentView=null;
        await render();say('Документ удалён. Проверьте исходные данные и повторите расчёт.');
        $('#project-title').focus();
      } catch(error) {$('#delete-document-dialog').close();failure(error);} finally {setWorking(false);}
      return;
    }
    if(action==='questions') {openQuestions();return;}
    if(action==='hws-circulation') {openConfig('consumers',['hws_stage_p_enabled']);return;}
    if(['fire-station-export','fire-station-remove'].includes(action)) {window.ZaryaFireStation.action(action,button);return;}
    if(action==='close-questions') {$('#clarification-dialog').close();return;}
    if(action==='examples') {$('#example-picker').showModal();return;}
    if(action==='close-examples') {$('#example-picker').close();return;}
    if(action==='study' || action==='exit-study') {
      if(dirty && !(await saveForm(false))) return;
      setWorking(true);showError('');
      try {
        await ensureDraft();
        draft=await api(action==='study'?'study':'study/exit',{method:'POST',body:JSON.stringify({revision:draft.revision,...(action==='study'?{kind:button.dataset.kind}:{})})});
        dirty=false;documentView=null;selectedStep=null;$('#example-picker').close();openProject();await render();
        $('#project-title').scrollIntoView({block:'start'});
        say(action==='study'?'Учебный пример открыт. Ваш проект сохранён.':'Вы вернулись к своему проекту.');
      } catch(error) {failure(error);} finally {setWorking(false);}
      return;
    }
    if(action==='calculate') return; // One form submission accepts the visible values.
    if(action==='wastewater-service-inputs') {
      openConfig('connection', ['sewer_service_'+button.dataset.service+'_enabled']);
      return;
    }
    if(action==='rain-design-inputs') {
      openConfig('consumers', ['rainwater_design_basis']);
      const input=$('#next-rainwater_design_basis');
      if(input) {input.closest('details').open=true;input.focus();}
      return;
    }
    if(action==='rain-review') {
      if(dirty) {showError('Сначала сохраните изменённые исходные данные.');return;}
      const reviewer=$('#rain-reviewer')?.value.trim();
      if(!reviewer) {showError('Укажите ФИО проверившего проектировщика.');return;}
      if(!confirm('Подтверждаю проверку указанных расчётов, паспортов и проектных листов для текущих исходных. Это не электронная подпись и не заключение экспертизы.')) return;
      setWorking(true);showError('');
      try {draft=await api('rainwater/review',{method:'POST',body:JSON.stringify({revision:draft.revision,reviewer,confirm:true})});await render();say('Проверка дождевого решения сохранена. Остальные проверки комплекта остаются обязательными.');}
      catch(error) {failure(error);} finally {setWorking(false);}
      return;
    }
    if(action==='section-review') {
      if(dirty) {showError('Сначала сохраните изменённые исходные данные.');return;}
      const reviewer=$('#section-reviewer')?.value.trim();
      const architecture_ref=$('#section-review-ar')?.value.trim();
      if(!reviewer || !architecture_ref) {showError('Укажите проверившего проектировщика и листы АР.');return;}
      setWorking(true);showError('');
      try {
        draft=await api('section/review',{method:'POST',body:JSON.stringify({revision:draft.revision,reviewer,architecture_ref,confirm:true,fingerprint:draft.section_review.current.fingerprint})});
        await render();$('#section-review').open=true;
        say('Просмотр этой версии разреза сохранён. Замечания и ограничения выпуска остаются.');
      } catch(error) {failure(error);} finally {setWorking(false);}
      return;
    }
    if(['add-section','remove-section'].includes(action)) {
      const editor=button.closest('[data-hydraulic-editor]');
      const registry=['sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation'].includes(editor.dataset.hydraulicEditor);
      const removedIndex=action==='remove-section'?Array.from(editor.querySelectorAll('.route-row')).indexOf(button.closest('.route-row')):-1;
      if(action==='remove-section') {
        button.closest('.route-row').remove();
        if(registry)window.ZaryaSewerPipes.renumber(editor);
      }
      else {
        const rows=readRoute(editor);
        const key=editor.dataset.hydraulicEditor || 'v1_sections';
        const max=key==='sewage_risers'?draft.riser_editor.max_rows:key==='wastewater_fan_ventilation'?draft.fan_editor.max_rows:key==='sewer_elements'?draft.sewer_element_editor.max_rows:key==='sewer_pipes'?draft.sewer_pipe_editor.max_rows:30;
        if(rows.length>=max){showError(`В этом редакторе не более ${max} участков.`);return;}
        let next=1; while(rows.some(row=>row.section_id===`У${next}`))next++;
        rows.push(['sewer_pipes','sewer_elements','sewage_risers','wastewater_fan_ventilation'].includes(key)?{}:key==='t3_sections'?{section_id:`У${next}`,flow_mode:'unknown'}:{section_id:`У${next}`,role:rows.length?'internal':'input'});
        editor.querySelector('[data-route-rows]').innerHTML=routeRows(rows,key);
      }
      syncRoute(editor);
      if(registry && removedIndex>=0) {
        const rows=editor.querySelectorAll('.route-row');
        const next=rows[Math.min(removedIndex,rows.length-1)]?.querySelector('input,select,textarea')
          || editor.querySelector('[data-action="add-section"]');
        next?.focus();
      } else editor.querySelector('.route-row:last-child input')?.focus();
      return;
    }
    if(action==='choose') {fileInput.click();return;}
    if(action==='manual' || action==='resume') {await manual();return;}
    if(action==='save') {await saveForm(false);return;}
    if(action==='apartment-settings') {openManual(['apartment_design_residents']);return;}
    if(action==='section-design') {
      openManual(['section_k1_dn_mm','section_k1_slope','section_k1_outlet_invert_m','section_k1_discharge_point','section_k1_source_ref']); return;
    }
    if(action==='section-inputs') {
      selectedStep='section';
      if(questionSteps().some(step=>step.id==='section')) openQuestions();
      else openManual(['roof_type','floor_height_m','basement_kind']);
      return;
    }
    if(action==='step') {
      const targetStep=button.dataset.step;
      if(dirty && !(await saveForm(true))) return;
      selectedStep=targetStep;
      motion.reveal(populateQuestions, () => $('#clarification-body'));
      $('#clarification-body input, #clarification-body select')?.focus({preventScroll:true}); return;
    }
    if(action==='readiness') {
      if($('#release-readiness')) {
        $('#calculation-details').open=true; $('#release-readiness').open=true;
        scrollTo($('#release-readiness'), 'start');
      } else scrollTo($('#next-step'), 'start');
      return;
    }
    if(['project','head','storm'].includes(action)) {
      openManual(action==='head'?draft.head_missing:action==='storm'?draft.storm_missing:draft.handoff_missing);return;
    }
    if(action==='documents') {
      documentView=button.dataset.view;
      if((draft.preview && !draft.documents_need_refresh) || ['ready','unavailable'].includes(draft.package?.state)) {
        motion.reveal(renderCalculation, () => $('.document-selection')); $('.document-selection')?.focus(); return;
      }
    }
    if(!['reload','package','preview','documents'].includes(action)) return;
    if(action==='reload' && dirty && !confirm('Отбросить несохранённые изменения и загрузить черновик?')) return;
    setWorking(true);showError('');
    try {
      if(action!=='reload') {
        const endpoint=action==='documents'?'preview':action;
        say(endpoint==='preview'?'Собираем PDF для просмотра.':'Формируем и проверяем комплект.');
        draft=await api(endpoint,{method:'POST',body:JSON.stringify({revision:draft.revision})});
        await render(); say(endpoint==='preview'?'PDF для просмотра готовы.':draft.package?.state==='ready'?'Документы готовы.':'Выпуск требует устранения замечаний.');
        $('.document-selection')?.focus();
        if(endpoint==='package' && draft.package?.state==='ready') {
          window.location.assign('/studio/api/package/'+encodeURIComponent(draft.package.run_id)+'/download');
        }
      } else {
        const value=await api('draft');draft=value.draft===null?null:value;dirty=false;touchedFields.clear();await render();
      }
    } catch(error) {failure(error);}
    finally {setWorking(false);}
  });
  root.addEventListener('submit', async event => {
    if(event.target.matches('[data-config-form]')) {event.preventDefault();if(!working) await continueConfig();return;}
    if(!event.target.matches('[data-setup], [data-next-step]')) return;
    event.preventDefault();
    if(event.target.matches('[data-setup]') && draft.next_question && !$('#field-'+draft.next_question)?.value.trim()) {
      openQuestions();return;
    }
    if(event.target.matches('[data-next-step]')) {
      const missing=Array.from(event.target.querySelectorAll('[name]')).find(input=>!input.closest('[data-loss-mode],[data-hot-only]')?.hidden && !input.value.trim());
      if(missing) {
        missing.setCustomValidity('Укажите значение. Если пока неизвестно, нажмите «Позже».');
        missing.reportValidity(); return;
      }
    }
    if(!working) await saveForm(true);
  });
  $('#delete-document-dialog').addEventListener('cancel', event => {if(working) event.preventDefault();});
  root.addEventListener('input', event => {
    if(['vu_per_inlet','russian_equipment_only','sewer_service_k1_metering_enabled','sewer_service_sump_enabled'].includes(event.target.name)) {
      const checked=event.target.checked;
      root.querySelectorAll(`[name="${event.target.name}"]`).forEach(input=>{input.checked=checked;input.value=checked?'yes':'no';});
    }
    if(event.target.matches('[data-fire-station-adopt]')) {window.ZaryaFireStation.adopt(event.target);return;}
    if(event.target.matches('[data-fire-station-import]')) return;
    if(event.target.matches('[data-fan-global]')) {
      delete event.target.dataset.preservedRaw;
      syncRoute(event.target.closest('[data-hydraulic-editor]'));return;
    }
    if(event.target.matches('[data-column]')) {
      const editor=event.target.closest('[data-hydraulic-editor]');
      if(event.target.dataset.column==='role') {
        const row=event.target.closest('.route-row');
        row.querySelector('[data-column="flow_lps"]').placeholder=event.target.value==='input'?'Авто':'—';
      }
      if(event.target.dataset.column==='flow_mode') {
        const input=event.target.closest('.route-row').querySelector('[data-column="circulation_flow_lps"]');
        input.disabled=event.target.value!=='main';
        input.closest('label').hidden=input.disabled;
        if(input.disabled)input.value='';
      }
      syncRoute(editor);return;
    }
    const contextual=event.target.closest('[data-next-step], [data-config-form]');
    if(!event.target.closest('[data-setup]') && !contextual) return;
    touchedFields.add(event.target.name);
    event.target.setCustomValidity('');
    if(event.target.name.startsWith('vu_')) {
      const wrapper=event.target.closest('.setup-field');
      wrapper.querySelector('.equipment-cards')?.remove();
      wrapper.insertAdjacentHTML('beforeend',equipmentCards(event.target.name,event.target.value));
    }
    if(['pressure_loss_mode','t3_loss_mode','hws_heater_in_scope'].includes(event.target.name)) {
      root.querySelectorAll(`[name="${event.target.name}"]`).forEach(input=>{input.value=event.target.value;});
      syncLossMode();
    }
    if(event.target.name==='roof_type') {
      document.querySelectorAll('[name="roof_type"]').forEach(input=>{
        delete input.dataset.preservedRoof;
        input.value=event.target.value;
        const hint=document.getElementById(input.id+'-hint');
        if(hint) hint.textContent=draft.roof_rules?.[event.target.value]?.note || '';
      });
    }
    if(contextual) {
      $('#field-'+event.target.name).value=event.target.value;
      $('.rainwater-result')?.setAttribute('hidden','');
      root.querySelectorAll('.wastewater-service-result').forEach(item=>{item.hidden=true;});
      if($('.calculation-output')) $('.calculation-output').hidden=true;
      $('.calculation-progress')?.setAttribute('hidden','');
      $('#step-save-state').textContent=configStep?'Ответы сохранятся при переходе к следующему шагу.':'Изменения ещё не применены. Нажмите «Продолжить».';
    } else $('#calculation').hidden=true;
    syncLossMode();
    dirty=true;
    $('#save-state').textContent='Изменения ещё не применены.';
    if($('[data-action="calculate"]')) $('[data-action="calculate"]').textContent='Рассчитать';
  });
  root.addEventListener('toggle', event => {
    if(event.target.dataset.configExtra) {if(event.target.open) configExpanded.add(event.target.dataset.configExtra);else configExpanded.delete(event.target.dataset.configExtra);}
    if(event.target.id==='manual-entry') manualOpen=event.target.open;
    if(event.target.id==='setup-details') setupExpanded=event.target.open;
  },true);
  $('#clarification-dialog').addEventListener('cancel', event=>{
    if(working) event.preventDefault();
  });
  $('#clarification-dialog').addEventListener('close', ()=>{
    if($('#error').hidden) $('[data-action="questions"]')?.focus({preventScroll:true});
  });
  window.addEventListener('beforeunload', event => {
    if(dirty) {event.preventDefault();event.returnValue='';}
  });
  window.addEventListener('popstate', async () => {
    const previous = workspaceOpen;
    if (working || (dirty && !(await saveForm(false)))) {
      history.pushState(null, '', previous ? '/studio?view=project' : '/studio');
      return;
    }
    workspaceOpen = new URLSearchParams(location.search).get('view') === 'project';
    showError('');await render();
  });
  root.addEventListener('change', async event => {
    if(!event.target.matches('[data-fire-station-import]')) return;
    try {await window.ZaryaFireStation.importFile(event.target);}
    catch(error) {failure(error);}
  });
  fileInput.addEventListener('change', () => { const files=Array.from(fileInput.files); fileInput.value=''; upload(files); });
  const drop=$('#drop-zone');
  drop.addEventListener('dragenter', event => {event.preventDefault();dragDepth++;drop.classList.add('drag');});
  drop.addEventListener('dragover', event => {event.preventDefault();event.dataTransfer.dropEffect='copy';});
  drop.addEventListener('dragleave', () => {dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)drop.classList.remove('drag');});
  drop.addEventListener('drop', event => {event.preventDefault();dragDepth=0;drop.classList.remove('drag');upload(Array.from(event.dataTransfer.files));});
  if (!workspaceOpen) root.classList.add('intro');
  setWorking(true);
  api('draft').then(value => {draft=value.draft===null ? null : value;return render(false);})
    .catch(async error => {await render(false);failure(error);}).finally(()=>setWorking(false));
})();
