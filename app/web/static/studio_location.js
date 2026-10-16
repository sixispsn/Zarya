/* Optional reference map. No engineering values are inferred from geography. */
(() => {
  'use strict';
  const dialog = document.getElementById('site-location-dialog');
  const $ = s => dialog.querySelector(s);
  let api, onSaved, current, point, map, marker, enabled=false, busy=false, epoch=0;
  let library;
  const status = text => { $('.location-status').textContent=text; };
  const escape = text => String(text).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = input => input.value.trim() === '' ? NaN : Number(input.value.trim().replace(',','.'));
  const valid = p => p && Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude)<=90 && Math.abs(p.longitude)<=180;
  function lock(value) { busy=value; dialog.querySelectorAll('button,input').forEach(el=>{el.disabled=value;}); }
  function elevationText(value) {
    if(value?.status==='available') return `≈ ${Math.round(value.metres)} м над уровнем моря · SRTM, сетка около 30 м. Не проектная абсолютная отметка и не привязка ±0,000.`;
    if(value?.status==='no_coverage') return 'В этой точке нет данных SRTM. Высота не определена, а не равна нулю.';
    if(value?.status==='unavailable') return 'Место сохранено. Справочная высота сейчас недоступна.';
    return '';
  }
  function updatePoint(p, pan=false) {
    point=p;
    $('#location-lat').value=p.latitude.toFixed(6);
    $('#location-lon').value=p.longitude.toFixed(6);
    $('#location-label').value=p.label || '';
    $('.location-point').textContent=`${p.latitude.toFixed(6)}, ${p.longitude.toFixed(6)} · WGS 84`;
    $('.location-elevation').textContent=elevationText(p.elevation);
    if(map) {
      if(!marker) {
        marker=L.marker([p.latitude,p.longitude],{draggable:true,autoPan:true,title:'Место строительства',
          icon:L.divIcon({className:'location-pin',html:'<span></span>',iconSize:[24,32],iconAnchor:[12,32]})}).addTo(map);
        marker.on('dragend',()=>{const p=marker.getLatLng();updatePoint({latitude:p.lat,longitude:p.lng,label:'',source:'map'});});
      } else marker.setLatLng([p.latitude,p.longitude]);
      if(pan) map.setView([p.latitude,p.longitude],16);
    }
    status('Точка выбрана. Сохраните место, чтобы оставить его в проекте.');
  }
  function loadLibrary() {
    if(window.L) return Promise.resolve();
    if(library) return library;
    library=new Promise((resolve,reject)=>{
      const css=document.createElement('link');css.rel='stylesheet';css.href='/static/vendor/leaflet/leaflet.css';document.head.append(css);
      const script=document.createElement('script');script.src='/static/vendor/leaflet/leaflet.js';
      script.onload=resolve;script.onerror=()=>{library=null;script.remove();reject(new Error('Не удалось загрузить карту. Используйте ручные координаты.'));};document.head.append(script);
    });
    return library;
  }
  async function enable() {
    const token=epoch;lock(true);status('Открываем карту…');
    try {
      const [config]=await Promise.all([api('location/config'),loadLibrary()]);
      if(token!==epoch || !dialog.open) return;
      enabled=true;
      $('.location-consent').hidden=true;$('.location-online').hidden=false;$('.location-elevation-option').hidden=false;
      map=L.map($('#location-map'),{scrollWheelZoom:false,worldCopyJump:false,minZoom:2,maxZoom:19,maxBounds:[[-85,-180],[85,180]],maxBoundsViscosity:1});
      // Moscow is only the initial viewport, never a selected project location.
      map.setView(valid(point)?[point.latitude,point.longitude]:[55.75,37.62],valid(point)?16:10);
      const link=`<a href="${escape(config.attribution_url)}" target="_blank" rel="noopener noreferrer">${escape(config.attribution)}</a>`;
      L.tileLayer(config.tiles,{attribution:link,maxZoom:19,noWrap:true,keepBuffer:0,updateWhenIdle:true,
        referrerPolicy:'origin'}).on('tileerror',()=>status('Подложка недоступна. Поиск и ручные координаты можно использовать отдельно.')).addTo(map);
      map.on('click',e=>updatePoint({latitude:e.latlng.lat,longitude:e.latlng.lng,label:'',source:'map'}));
      if(valid(point)) updatePoint(point);
      else status('Найдите адрес или нажмите на карту. Начальный вид не задаёт место проекта.');
      map.invalidateSize();
    } catch(error) {status(error.message || 'Карта недоступна. Используйте ручной ввод.');}
    finally {if(token===epoch) lock(false);}
  }
  async function search() {
    const query=$('#location-query').value.trim();
    if(query.length<3) {status('Введите хотя бы три символа.');return;}
    const token=epoch;lock(true);status('Ищем место…');$('.location-results').replaceChildren();
    try {
      const result=await api('location/search',{method:'POST',body:JSON.stringify({query,external_consent:true})});
      if(token!==epoch || !dialog.open) return;
      for(const row of result.results) {
        const button=document.createElement('button');button.type='button';button.textContent=row.label;
        button.addEventListener('click',()=>{updatePoint(row,true);$('.location-results').replaceChildren();});
        $('.location-results').append(button);
      }
      status(result.results.length?'Выберите подходящий адрес.':'Ничего не найдено. Уточните адрес или выберите точку на карте.');
    } catch(error) {status(error.message || 'Поиск недоступен.');}
    finally {if(token===epoch) lock(false);}
  }
  async function save(clear=false) {
    const lat=number($('#location-lat')),lon=number($('#location-lon'));
    if(!clear && !valid({latitude:lat,longitude:lon})) {status('Выберите точку или введите корректные широту и долготу.');$('.location-manual').open=true;return;}
    const payload={revision:current.revision,location:clear?null:{latitude:lat,longitude:lon,label:$('#location-label').value.trim(),source:point?.source || 'manual'},
      lookup_elevation:!clear && enabled && $('#location-elevation').checked,external_consent:enabled};
    lock(true);status(payload.lookup_elevation?'Сохраняем точку и запрашиваем справочную высоту…':'Сохраняем место…');
    try {
      const result=await api('location',{method:'PATCH',body:JSON.stringify(payload)});
      onSaved(result);current={...current,...result};point=result.site_location;
      if(point) {updatePoint(point);$('.location-elevation').textContent=elevationText(point.elevation);}
      if(point?.elevation?.status==='unavailable') status('Место сохранено; сервис высот недоступен. Можно закрыть окно.');
      else {status('Место сохранено.');dialog.close();}
    } catch(error) {status(error.message || 'Не удалось сохранить место.');}
    finally {lock(false);}
  }
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  dialog.addEventListener('close',()=>{epoch++;map?.remove();map=null;marker=null;});
  $('[data-location-enable]').onclick=()=>{if(!busy)enable();};
  $('[data-location-search]').onclick=()=>{if(!busy)search();};
  $('[data-location-save]').onclick=()=>{if(!busy)save();};
  $('[data-location-clear]').onclick=()=>{if(!busy)save(true);};
  $('[data-location-close]').onclick=()=>{if(!busy)dialog.close();};
  $('#location-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();if(!busy && enabled)search();}};
  for(const id of ['#location-lat','#location-lon']) $(id).addEventListener('input',()=>{
    const latitude=number($('#location-lat')),longitude=number($('#location-lon'));
    point={latitude,longitude,source:'manual'};$('.location-elevation').textContent='';
    $('.location-point').textContent=valid(point)?`${latitude.toFixed(6)}, ${longitude.toFixed(6)} · WGS 84`:'Проверьте координаты';
    if(marker && valid(point)) marker.setLatLng([latitude,longitude]);
  });
  window.ZaryaLocation=Object.freeze({open(options) {
    ({api,onSaved}=options);current=options.draft;point=current.site_location;enabled=false;epoch++;
    map?.remove();map=null;marker=null;lock(false);
    $('.location-consent').hidden=false;$('.location-online').hidden=true;$('.location-elevation-option').hidden=true;
    $('.location-manual').open=false;$('.location-results').replaceChildren();
    $('#location-elevation').checked=false;$('#location-query').value='';
    $('#location-lat').value='';$('#location-lon').value='';$('#location-label').value='';
    $('.location-point').textContent='Место пока не выбрано';$('.location-elevation').textContent='';
    if(valid(point)) updatePoint(point);
    status('');dialog.showModal();
  }});
})();
