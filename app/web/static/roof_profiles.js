/* UI silhouettes only. These paths never become engineering/model geometry. */
(() => {
  'use strict';
  const profiles = {
    single_slope: {label:'Односкатная', path:'M8 28L104 8 M18 26V52H94V12'},
    gable: {label:'Двускатная', path:'M8 30L56 7L104 30 M18 26V52H94V26'},
    complex: {label:'Сложная / составная', path:'M6 28L32 9L60 28L80 15L106 30 M16 22V52H96V25 M60 28V45', note:'Профиль и участки — по АР'},
    flat_accessible: {label:'Плоская эксплуатируемая', path:'M14 15V25H98V15 M18 25V52H94V25 M14 25H98'},
    flat_non_accessible: {label:'Плоская неэксплуатируемая', path:'M12 22H100 M18 22V52H94V22'},
  };
  function render(value) {
    const p = profiles[value];
    if(!p) return '';
    return `<div class="roof-profile" data-roof-profile="${value}"><svg viewBox="0 0 112 60" aria-hidden="true" focusable="false"><path d="${p.path}"/></svg><span>${p.label}<small>${p.note || 'Условный профиль · не разрез АР'}</small></span></div>`;
  }
  window.ZaryaRoofProfiles = Object.freeze({render});
  document.querySelectorAll('[data-roof-profile-control]').forEach(preview=>{
    const select=document.querySelector(`[name="${preview.dataset.roofProfileControl}"]`);
    if(!select) return;
    const refresh=()=>{
      preview.innerHTML=render(select.value);
      const note=document.getElementById(preview.dataset.roofNote);
      if(note) {
        note.textContent = select.value==='complex'
          ? 'Нужны участки кровли, их отметки, доступность и места фановых выходов. Единый профиль и общую высоту пока не назначаем.'
          : select.value==='pitched' ? 'Ранее указана скатная кровля без формы. Прежнее значение сохранено; уточните форму.' : '';
        note.hidden=!note.textContent;
      }
    };
    select.addEventListener('input',refresh);
    refresh();
  });
})();
