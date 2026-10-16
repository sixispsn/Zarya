(() => {
  const root=document.querySelector('[data-route-workspace]');
  if(!root) return;
  const svg=root.querySelector('[data-plan-preview]'), form=root.querySelector('[data-route-form]');
  const field=name=>form.elements.namedItem(name), status=root.querySelector('[data-route-status]');
  const height=Number(svg.dataset.pdfHeight), scale=Number(root.dataset.scale);
  const ns='http://www.w3.org/2000/svg', overlay=document.createElementNS(ns,'g');
  overlay.dataset.routeOverlay='true'; svg.append(overlay);
  let vertices=[];
  const number=value=>String(value).trim()===''?null:Number(String(value).replace(',','.'));
  const changed=()=>{field('reviewed').checked=false;};
  for(const event of ['input','change']) form.addEventListener(event,e=>{
    if(e.target!==field('reviewed')) changed();
  });
  function draw() {
    overlay.replaceChildren();
    const valid=p=>Number.isFinite(p.x_pt) && Number.isFinite(p.y_pt);
    const line=document.createElementNS(ns,'polyline');
    if(vertices.every(valid)) line.setAttribute('points',vertices.map(p=>`${p.x_pt},${height-p.y_pt}`).join(' '));
    overlay.append(line);
    for(const p of vertices.filter(valid)) {
      const dot=document.createElementNS(ns,'circle'); dot.setAttribute('cx',p.x_pt);
      dot.setAttribute('cy',height-p.y_pt); dot.setAttribute('r',2.5); overlay.append(dot);
    }
    const planar=vertices.slice(1).reduce((s,p,i)=>s+Math.hypot(p.x_pt-vertices[i].x_pt,p.y_pt-vertices[i].y_pt)*scale,0);
    root.querySelector('[data-route-length]').textContent=vertices.every(valid)
      ? `${vertices.length} точек · по плану ${planar.toFixed(3).replace('.',',')} м`
      : 'Заполните числовые координаты всех точек.';
  }
  function refresh() {
    draw();
    const mode=field('vertical_mode').value;
    root.querySelector('[data-height-fields]').hidden=!['level','slope'].includes(mode);
    root.querySelector('[data-slope-field]').hidden=mode!=='slope';
    root.querySelector('[data-route-duplicate]').disabled=mode!=='vertices' || vertices.length===0;
    const tbody=root.querySelector('[data-route-points]'); tbody.replaceChildren();
    vertices.forEach((point,i)=>{
      const row=document.createElement('tr'), index=document.createElement('td'); index.textContent=String(i+1); row.append(index);
      for(const key of ['x_pt','y_pt','elevation_m']) {
        const cell=document.createElement('td'), input=document.createElement('input'); input.inputMode='decimal';
        input.setAttribute('aria-label',`${key} точки ${i+1}`); input.value=point[key]??'';
        input.disabled=key==='elevation_m' && mode!=='vertices';
        // Do not rebuild inputs on edit: retain focus/caret and keep the model
        // current before Save or a mode change, including pasted values.
        input.addEventListener('input',()=>{vertices[i][key]=number(input.value); draw();});
        cell.append(input); row.append(cell);
      } tbody.append(row);
    });
  }
  svg.addEventListener('click',e=>{
    if(vertices.length>=500) return;
    const matrix=svg.getScreenCTM(); if(!matrix) return;
    const p=svg.createSVGPoint(); p.x=e.clientX; p.y=e.clientY;
    const local=p.matrixTransform(matrix.inverse());
    vertices.push({x_pt:Number(local.x.toFixed(4)),y_pt:Number((height-local.y).toFixed(4)),elevation_m:null}); changed(); refresh();
  });
  root.querySelector('[data-route-undo]').addEventListener('click',()=>{vertices.pop();changed();refresh();});
  root.querySelector('[data-route-clear]').addEventListener('click',()=>{vertices=[];changed();refresh();});
  root.querySelector('[data-route-duplicate]').addEventListener('click',()=>{
    if(vertices.length && vertices.length<500) {vertices.push({...vertices.at(-1),elevation_m:null});changed();refresh();}
  });
  field('vertical_mode').addEventListener('change',refresh);
  const saved=JSON.parse(root.querySelector('[data-saved-route-traces]').textContent);
  root.querySelectorAll('[data-route-edit]').forEach(button=>button.addEventListener('click',()=>{
    const trace=saved.find(t=>t.route_id===button.dataset.routeEdit);
    if(!trace || trace.floor!==Number(root.dataset.floor)) return;
    for(const name of ['route_id','system','start_node','end_node','vertical_mode','start_elevation_m','slope'])
      field(name).value=trace[name]??'';
    vertices=trace.vertices.map(p=>({...p}));
    const current=trace.context_hash===root.dataset.contextHash;
    field('reviewed').checked=current && trace.reviewed;
    status.className=current?'':'route-error';
    status.textContent=current?'Измерение открыто. После правки сохраните его повторно.':
      'Привязка плана изменилась. Проверьте все точки и отметки заново перед сохранением.';
    refresh(); form.scrollIntoView({block:'start'});
  }));
  form.addEventListener('submit',async e=>{
    e.preventDefault(); status.className=''; status.textContent='Проверяю точки и привязку…';
    const mode=field('vertical_mode').value;
    const trace={route_id:field('route_id').value.trim(),system:field('system').value,
      floor:Number(root.dataset.floor),context_hash:root.dataset.contextHash,
      start_node:field('start_node').value.trim(),end_node:field('end_node').value.trim(),
      vertices:vertices.map(p=>({...p,elevation_m:mode==='vertices'?p.elevation_m:null})),
      vertical_mode:mode,start_elevation_m:['level','slope'].includes(mode)?number(field('start_elevation_m').value):null,
      slope:mode==='slope'?number(field('slope').value):null,reviewed:field('reviewed').checked};
    const submit=form.querySelector('[type=submit]'); submit.disabled=true;
    try {
      const response=await fetch(root.dataset.saveUrl,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({revision:Number(root.dataset.revision),trace})});
      const result=await response.json(); if(!response.ok) throw new Error(result.error||'Не удалось сохранить');
      location.reload();
    } catch(error) {status.className='route-error';status.textContent=error.message;submit.disabled=false;}
  });
  refresh();
})();
