/* Explicit fan inputs. No engineering defaults and no automatic approval. */
(() => {
  const root = document.querySelector('[data-fan-editor]');
  if (!root) return;
  const hidden = root.querySelector('[name="fan_data"]'), dialog = root.querySelector('dialog');
  const body = root.querySelector('[data-fan-body]'), error = root.querySelector('[data-fan-error]'), status = root.querySelector('[data-fan-status]');
  let draft, groups, confirmed, busy = false;
  const report = root.querySelector('[data-fan-report]');
  const reviewButton = root.querySelector('[data-fan-review]'), downloadButton = root.querySelector('[data-fan-download]');
  let reviewedRevision = null, dialogDirty = false, appliedUnsaved = root.dataset.fanMatchesSaved !== 'true';
  function invalidateReview(message = 'Данные изменились. Сохраните узлы и повторите проверку.') {
    reviewedRevision = null;
    status.textContent = ''; error.textContent = '';
    report.replaceChildren(el('p', message));
    if(downloadButton) downloadButton.disabled = true;
  }
  function setBusy(value) {
    busy = value;
    dialog.querySelectorAll('button,input,select').forEach(n=>{n.disabled=value;});
    if(downloadButton) downloadButton.disabled=value || reviewedRevision !== root.dataset.revision || dialogDirty || appliedUnsaved;
  }
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
  const button = (text, action) => { const b = el('button', text, 'btn'); b.type = 'button'; b.addEventListener('click', action); return b; };
  const touch = () => {
    dialogDirty = true; invalidateReview();
    draft.fan_geometry.confirmed = false;
    if (confirmed) confirmed.checked = false;
    status.textContent = 'Изменения ещё не применены. Подтверждение геометрии снято.';
  };
  function field(parent, target, key, title, kind = 'text') {
    const label = el('label', title), input = el(kind === 'tri' ? 'select' : 'input');
    if (kind === 'tri') [['','Нет данных'],['yes','Да'],['no','Нет']].forEach(([value, caption]) => { const o=el('option',caption); o.value=value; input.append(o); });
    else { input.type='text'; if(kind==='number') input.inputMode='decimal'; }
    input.value = kind === 'tri' ? (target[key] === true ? 'yes' : target[key] === false ? 'no' : '') : (target[key] ?? '');
    input.dataset.fanField=key;
    input.addEventListener(kind === 'tri' ? 'change' : 'input', () => {
      const raw=input.value.trim();
      // Invalid numeric text remains visible; server rejects it, never substitutes zero.
      target[key] = kind === 'tri' ? (raw === '' ? null : raw === 'yes') : kind === 'number'
        ? (raw === '' ? null : Number.isFinite(Number(raw.replace(',','.'))) ? Number(raw.replace(',','.')) : raw) : raw;
      touch();
    });
    label.append(input); parent.append(label); return input;
  }
  function section(parent,title) { const d=el('details'); d.append(el('summary',title)); const g=el('div','','fan-grid'); d.append(g); parent.append(d); return g; }
  const fields = (parent,obj,rows,kind) => rows.forEach(([k,l]) => field(parent,obj,k,l,kind));
  function describe() {
    try {
      const v=JSON.parse(hidden.value), count=v.fan_ventilation?.terminals?.length || 0;
      root.dataset.state=v.fan_geometry?.confirmed ? 'confirmed' : count ? 'draft' : 'missing';
      root.querySelector('[data-fan-summary]').textContent = count
        ? `${count} узл. · ${v.fan_geometry?.confirmed ? 'геометрия подтверждена' : 'геометрия требует уточнения'} · допуск к выпуску проверяется отдельно`
        : 'Узлы не заданы · для схемы нужны группы и отметки';
    } catch (_) { root.dataset.state='missing'; root.querySelector('[data-fan-summary]').textContent='Ошибка исходных данных — откройте узлы для проверки'; }
  }
  function draw() {
    body.replaceChildren();
    const top=el('div','','fan-grid'); body.append(top);
    field(top,draft,'roof_level','Общая относительная отметка кровли, м','number');
    const external=section(body,'Вентиляция наружной сети — подтверждённые исходные данные');
    field(external,draft.fan_ventilation,'external_ventilation_verified','Достаточность вентиляции проверена','tri');
    field(external,draft.fan_ventilation,'external_ventilation_ref','Основание проверки / расчёт');
    if (!groups.length) body.append(el('p','Добавьте только реально принятые узлы. Данные об этажах и стояках не заменяются предположениями.','fan-empty'));
    groups.forEach((g,index) => {
      const t=g.terminal, card=el('details','','fan-group'); card.open=groups.length===1 || !t.terminal_id;
      card.append(el('summary',`${t.terminal_id || 'Новый узел'} · ${t.kind==='roof' ? 'выход на кровлю' : t.kind==='valve' ? 'воздушный клапан' : 'тип не уточнён'}`)); body.append(card);
      const grid=el('div','','fan-grid'); card.append(grid);
      field(grid,t,'terminal_id','Обозначение узла');
      const ids=field(grid,{ids:t.riser_ids.join(', ')},'ids','Стояки группы через запятую');
      ids.addEventListener('input',()=>{t.riser_ids=ids.value.split(',').map(s=>s.trim()).filter(Boolean);});
      field(grid,t,'source_ref','Источник принятого решения');
      const proof=section(card,'Нормативные исходные данные и подтверждения');
      if (t.kind==='roof') {
        fields(proof,t,[['height_m','Высота вывода над кровлей, м'],['diameter_mm','DN вытяжки, мм'],['collector_diameter_mm','DN коллектора, мм'],['opening_distance_m','До окон и балконов по горизонтали, м']],'number');
        fields(proof,t,[['no_openings_confirmed','Окон и балконов поблизости нет'],['open_end_confirmed','Открытый конец без колпака'],['separate_from_other_systems','Отдельно от дымоходов и вентиляции'],['condensate_drains_to_risers','Конденсат отводится в стояки'],['cold_attic','Есть холодный чердак'],['attic_insulated','Трубы в холодном чердаке утеплены'],['plastic_exposed','Пластик на солнце'],['uv_protected','Есть защита от УФ']],'tri');
      } else if(t.kind==='valve') {
        field(proof,t,'separate_from_other_systems','Отдельно от дымоходов и вентиляции','tri');
        fields(proof,t,[['valve_above_highest_fixture','Выше борта верхнего прибора'],['valve_on_top_floor','На верхнем этаже'],['valve_sizing_verified','Пропускная способность клапана проверена']],'tri');
        field(proof,t,'valve_sizing_ref','Источник подбора / расчёт клапана');
      }
      if(['roof','valve'].includes(t.kind)) card.append(button(g.detail ? 'Убрать геометрию этого узла' : 'Задать геометрию узла',()=>{
        g.detail=g.detail ? null : t.kind==='roof' ? {risers:[],scale:50} : {scale:20}; touch(); draw();
      }));
      if(g.detail) {
        const d=g.detail, geo=section(card,'Отметки и привязки — метры в системе проекта'); geo.parentElement.open=true;
        field(geo,d,'source_ref','Источник геометрии / лист АР'); field(geo,d,'scale','Масштаб деталировки 1 :','number');
        if(t.kind==='roof') {
          field(geo,d,'roof_level_m','Отметка кровли узла, м','number');
          field(geo,d,'vent_riser_id','Стояк под общей вытяжкой'); field(geo,d,'condensate_riser_id','Крайний стояк для стока конденсата');
          const rows=el('div','','fan-wide'); geo.append(rows);
          (d.risers || []).forEach((r,ri)=>{
            const pos=el('div','','fan-grid fan-position'); rows.append(pos);
            field(pos,r,'riser_id','Стояк');
            fields(pos,r,[['x_m','Координата X на деталировке, м'],['lower_port_m','Отметка стыка с этажной схемой, м'],['collector_m','Отметка коллектора, м']],'number');
            pos.append(button('Убрать привязку',()=>{d.risers.splice(ri,1);touch();draw();}));
          });
          rows.append(button('Добавить привязку стояка',()=>{d.risers.push({});touch();draw();}));
        } else {
          fields(geo,d,[['floor_level_m','Пол верхнего этажа, м'],['ceiling_level_m','Потолок верхнего этажа, м'],['highest_fixture_rim_m','Борт верхнего прибора, м'],['connection_level_m','Присоединение клапана, м'],['connection_outer_diameter_mm','Наружный диаметр присоединения, мм']],'number');
          field(geo,d,'outline_ref','Чертёж производителя для контура клапана');
          geo.append(el('p','Сейчас графический адаптер поддерживает только явно выбранный контур HL900N с присоединением 110 мм. Сохранение другого узла не разрешает его выпуск.','fan-wide'));
        }
      }
      card.append(button('Удалить узел',()=>{groups.splice(index,1);touch();draw();}));
    });
    const actions=el('div','','fan-grid'); body.append(actions);
    for(const [kind,title] of [['roof','Добавить выход на кровлю'],['valve','Добавить клапан']]) actions.append(button(title,()=>{
      groups.push({terminal:{terminal_id:'',riser_ids:[],kind,source_ref:''},detail:null});touch();draw();
    }));
    const confirmation=el('div','','fan-grid');body.append(confirmation);
    field(confirmation,draft.fan_geometry,'confirmation_ref','Основание подтверждения геометрии');
    const check=el('label','','fan-check');confirmed=el('input');confirmed.type='checkbox';confirmed.checked=draft.fan_geometry.confirmed;
    confirmed.addEventListener('change',()=>{draft.fan_geometry.confirmed=confirmed.checked;dialogDirty=true;invalidateReview();});
    check.append(confirmed,document.createTextNode('Подтверждаю привязки и отметки всех узлов. Это не подтверждение нормативного соответствия и подбора оборудования.'));body.append(check);
  }
  function payload() {
    const geometry={...draft.fan_geometry,roofs:[],valves:[]};
    groups.forEach(g=>{if(g.detail) geometry[g.terminal.kind==='roof'?'roofs':'valves'].push({...g.detail,terminal_id:g.terminal.terminal_id});});
    return {...draft,fan_ventilation:{...draft.fan_ventilation,terminals:groups.map(g=>g.terminal)},fan_geometry:geometry};
  }
  root.querySelector('[data-fan-open]').addEventListener('click',()=>{
    error.textContent='';status.textContent='';
    dialogDirty=false;invalidateReview('Проверьте сохранённую версию проекта перед скачиванием PDF.');
    try {
      draft=JSON.parse(hidden.value);draft.fan_ventilation ||= {terminals:[]};draft.fan_geometry ||= {roofs:[],valves:[],confirmed:false,confirmation_ref:''};
      const known=new Set(draft.fan_ventilation.terminals.map(t=>t.terminal_id));
      if([...draft.fan_geometry.roofs,...draft.fan_geometry.valves].some(d=>!known.has(d.terminal_id))) throw new Error('orphan geometry');
      groups=draft.fan_ventilation.terminals.map(t=>({terminal:t,detail:[...draft.fan_geometry.roofs,...draft.fan_geometry.valves].find(d=>d.terminal_id===t.terminal_id)||null}));draw();
    } catch(_){body.replaceChildren();error.textContent='Повреждены сохранённые данные. Они не удалены; перезагрузите проект из исходного YAML.';draft=null;}
    dialog.showModal();
  });
  root.querySelectorAll('[data-fan-cancel]').forEach(b=>b.addEventListener('click',()=>{if(!busy)dialog.close();}));
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  dialog.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.tagName==='INPUT')e.preventDefault();});
  async function apply(save) {
    if(busy||!draft)return;setBusy(true);error.textContent='';status.textContent='Проверяем введённые данные…';
    try {
      const url=save?`/wizard/projects/${encodeURIComponent(root.dataset.projectId)}/fan-inputs`:'/wizard/fan-inputs/validate';
      const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json',...(save?{'If-Match':root.dataset.revision}:{})},body:JSON.stringify(payload())});
      const result=await response.json();if(!response.ok)throw new Error(result.error||result.detail||'Не удалось сохранить данные');
      hidden.value=JSON.stringify(result.data);if(result.revision)root.dataset.revision=result.revision;
      hidden.dispatchEvent(new Event('change',{bubbles:true}));describe();
      dialogDirty=false;appliedUnsaved=!save;invalidateReview(save ? 'Узлы сохранены. Теперь можно проверить проект.' : 'Данные применены только к форме. Сохраните узлы перед проверкой.');
      if(save){root.querySelector('[data-fan-summary]').textContent+=' · сохранено в проект';status.textContent='Узлы сохранены. Остальные исходные данные проекта не изменены.';}else dialog.close();
    }catch(e){error.textContent=e.message;status.textContent='Ничего не применено. Исправьте данные или отмените изменения.';}
    finally{setBusy(false);}
  }
  root.querySelector('[data-fan-apply]').addEventListener('click',()=>apply(false));
  root.querySelector('[data-fan-save]')?.addEventListener('click',()=>apply(true));describe();
  function showReview(result) {
    report.replaceChildren();
    const checks=result.checks||[], issues=checks.filter(c=>c.status!=='verified'), passed=checks.filter(c=>c.status==='verified');
    report.append(el('p',result.preview_ready ? 'Можно сформировать контрольный PDF. Это не допуск к выпуску ПД.' : `Нужно уточнить: ${issues.length}. Контрольный PDF пока недоступен.`,'fan-report-heading'));
    report.append(el('p',`Сохранённая версия: ${result.revision.slice(0,12)} · пройдено проверок: ${passed.length}`,'fan-version'));
    function list(rows,parent) {
      const ul=el('ul');parent.append(ul);
      rows.forEach(c=>{
        const li=el('li');li.dataset.status=c.status;
        li.append(el('strong',`${c.target} · ${c.status==='verified' ? 'Проверено' : c.status==='pending' ? 'Нужны данные' : 'Несоответствие'}`));
        li.append(el('div',c.message));
        if(c.reference)li.append(el('small',c.reference));
        if(c.detail){const d=el('details');d.append(el('summary','Техническая причина'),el('pre',c.detail));li.append(d);}
        ul.append(li);
      });
    }
    list(issues,report);
    if(passed.length){const d=el('details');d.append(el('summary',`Пройденные проверки (${passed.length})`));list(passed,d);report.append(d);}
    reviewedRevision=result.preview_ready ? result.revision : null;
  }
  async function review(download) {
    if(busy)return;
    if(dialogDirty||appliedUnsaved){invalidateReview('Есть несохранённые изменения фановых узлов. Сначала нажмите «Сохранить только узлы».');return;}
    if(download && reviewedRevision!==root.dataset.revision)return;
    setBusy(true);error.textContent='';status.textContent=download?'Формируем контрольный PDF…':'Проверяем сохранённый проект и связность схемы…';
    const revision=root.dataset.revision;
    try {
      const url=`/wizard/projects/${encodeURIComponent(root.dataset.projectId)}/${download?'fan-preview.pdf':'fan-check'}`;
      const response=await fetch(url,{method:'POST',headers:{'If-Match':revision}});
      if(!response.ok){const problem=await response.json();if(problem.checks)showReview(problem);throw new Error(problem.error||problem.detail||'Не удалось выполнить проверку');}
      if(download){
        if(response.headers.get('X-Zarya-Project-Revision')!==revision||!response.headers.get('Content-Type')?.includes('application/pdf'))throw new Error('Ответ не соответствует проверенной версии PDF');
        const blob=await response.blob(), href=URL.createObjectURL(blob), link=el('a');link.href=href;link.download='К1_К2_контроль_фановых_узлов.pdf';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(href),60000);
        status.textContent='Контрольный PDF сформирован. Готовность комплекта ПД к выпуску не подтверждена.';
      } else {const result=await response.json();showReview(result);status.textContent='Проверка сохранённой версии завершена. Несохранённые поля основной формы не учитывались.';}
    }catch(e){reviewedRevision=null;error.textContent=e.message;status.textContent='PDF не выдан. Исправьте данные или переоткройте актуальную версию проекта.';}
    finally{setBusy(false);}
  }
  reviewButton?.addEventListener('click',()=>review(false));downloadButton?.addEventListener('click',()=>review(true));
  root.closest('form').addEventListener('change',e=>{
    const name=e.target.name||'';
    if(!root.contains(e.target))invalidateReview('Основная форма изменена. Проверка и PDF используют только сохранённую версию проекта, без этих изменений.');
    if(root.contains(e.target)||!(/^(sewage_riser|sewer_pipe)/.test(name)||['floors','wastewater_floor_height_m','wastewater_roof_kind'].includes(name)))return;
    try{const value=JSON.parse(hidden.value);if(value.fan_geometry?.confirmed){value.fan_geometry.confirmed=false;hidden.value=JSON.stringify(value);appliedUnsaved=true;describe();}}catch(_){}
  });
})();
