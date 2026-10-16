/* Optional explicit check. All hydraulic arithmetic and graph validation are server-side. */
(() => {
  'use strict';
  const dialog = document.getElementById('suction-dialog');
  const $ = s => dialog.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = value => value == null ? 'не определено' : value.toLocaleString('ru-RU', {maximumFractionDigits: 4});
  const labels = {
    max_flow_m3h:'Максимальная подача одного насоса, м³/ч', temperature_c:'Температура воды, °C',
    pressure_kind:'Вид давления', pressure_bar:'Давление в исходном сечении, бар',
    atmospheric_pressure_bar:'Атмосферное давление, бар (для избыточного)',
    source_elevation_m:'Отметка исходного сечения, м', pump_elevation_m:'Ось всасывания, м',
    vapor_head_m:'Hv при заданной температуре, м', basis:'Источники давления, отметок, режима и Hv',
    npshr_m:'NPSHr при той же максимальной подаче, м', npshr_basis:'Модель, кривая, расход и источник NPSHr',
    safety_margin_m:'Запас Hs, м · минимум CNP 0,5 м', suction_losses_m:'Полные потери пути',
    loss_m:'Потери, м', flow_m3h:'Расход результата, м³/ч', path_basis:'Границы и режим пути'
  };
  let api, onSaved, state, busy = false, nextRow = 0;
  function field(key, value, text = false) {
    return `<label>${esc(labels[key])}${text ? `<textarea data-balance="${key}" rows="2">${esc(value)}</textarea>` : `<input class="field-control" data-balance="${key}" inputmode="decimal" value="${esc(value)}" placeholder="Не задано">`}</label>`;
  }
  function number(input) {
    const raw = input.value.trim().replace(',', '.');
    if (!raw) return null;
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error('Введите конечное число: ' + (labels[input.dataset.balance || input.dataset.lossField] || 'значение'));
    return value;
  }
  const route = () => state.context.routes.find(r => r.id === $('[data-route]').value);
  function row(loss = {}) {
    const id = loss.id || `loss-${++nextRow}`;
    const components = route()?.components || {};
    const all = {...Object.fromEntries((loss.covers || []).map(id => [id, 'Отсутствует в текущем пути: ' + id])), ...components};
    return `<fieldset data-loss-id="${esc(id)}"><legend>Готовый результат потерь</legend>
      <details><summary>Состав результата · отметить учтённые элементы и соединения</summary><div class="suction-components">${Object.entries(all).map(([key, label]) => `<label><input type="checkbox" data-cover="${esc(key)}"${loss.covers?.includes(key) ? ' checked' : ''}> ${esc(label)}</label>`).join('')}</div></details>
      <div class="suction-grid">${['loss_m','flow_m3h','temperature_c'].map(key => `<label>${esc(labels[key])}<input class="field-control" data-loss-field="${key}" inputmode="decimal" value="${esc(loss[key])}" placeholder="Не задано"></label>`).join('')}</div>
      <label>Источник расчёта, размеры, состояние фильтра и границы учёта<textarea data-loss-field="basis" rows="2">${esc(loss.basis)}</textarea></label>
      <button type="button" class="text-button" data-remove-loss>Удалить строку</button></fieldset>`;
  }
  function displayResult(saved) {
    const target = $('[data-suction-result]');
    if (!saved.result) {
      target.textContent = saved.status === 'stale' ? 'Сохранённая проверка устарела. Перепроверьте значения, режим и основания по текущему проекту.' : 'Проверка ещё не сохранена.';
      return;
    }
    const {balance, losses} = saved.result;
    const status = {needs_data:'Нужны данные', available_only:'NPSHa рассчитан; паспортное сравнение не завершено', margin_satisfied:'Запас выполнен в заданном режиме', insufficient_margin:'Запаса недостаточно'};
    const components = route()?.components || {};
    target.innerHTML = `<p><b>${esc(status[balance.status])}</b></p><p>NPSHa: ${fmt(balance.available_m)} м. Требуется NPSHr + Hs: ${fmt(balance.required_m)} м.</p>
      <p>Полные потери пути: ${fmt(losses.total_loss_m)} м; известная часть: ${fmt(losses.known_loss_m)} м.</p>
      ${balance.missing.length ? `<p>Дополнить: ${balance.missing.map(k => esc(labels[k] || k)).join('; ')}.</p>` : ''}
      ${losses.missing_components.length ? `<details><summary>Не подтверждено элементов/соединений: ${losses.missing_components.length}</summary><ul>${losses.missing_components.map(k => `<li>${esc(components[k] || k)}</li>`).join('')}</ul></details>` : ''}
      ${losses.rows.filter(r => r.status !== 'bound').map(r => `<p>Строка ${esc(r.id)}: проверьте наличие потерь, основания и соответствие расхода/температуры выбранному режиму.</p>`).join('')}
      ${losses.issues.map(i => `<p>${esc(i)}</p>`).join('')}<p>${esc(balance.source)}. Проверка одного режима не разрешает пуск.</p>`;
  }
  function render() {
    const input = state.saved.inputs || {};
    const balance = input.balance || {safety_margin_m: 0.5};
    nextRow = 0;
    dialog.innerHTML = `<div class="suction-heading"><h2 id="suction-title">Проверка всасывания</h2><button type="button" class="text-button" data-suction-close aria-label="Закрыть проверку">×</button></div>
      <p>Отдельный баланс CNP. Исходные сохраняются в проекте и YAML; в ПЗ и расчёте насосов проверка пересчитывается заново. Подбор насоса и разрешение на пуск автоматически не меняются.</p>
      <p>Выберите один путь и обоснуйте режим, в котором применима последовательная сумма. Распределение по открытым параллельным ветвям здесь не рассчитывается.</p>
      <form data-suction-form><label>Путь от границы ввода до насоса<select class="field-control" data-route required><option value="">Выберите путь</option>${state.context.routes.map((r, i) => `<option value="${r.id}"${r.id === input.route_id ? ' selected' : ''}>Путь ${i + 1} · ${esc(r.source === 'inlet' ? 'Ввод' : 'Ввод ' + r.source.split('_').pop())} → Н${esc(r.pump.split('_').pop())}</option>`).join('')}</select></label>
      <details><summary>Состав выбранного пути</summary><p data-route-description></p></details>
      <label>Режим арматуры, граница давления и основание последовательной суммы<textarea data-path-basis rows="2">${esc(input.path_basis)}</textarea></label>
      <div class="suction-grid">${field('max_flow_m3h', balance.max_flow_m3h)}${field('temperature_c', balance.temperature_c)}</div>
      <details><summary>Давление, отметки и паспортные данные</summary><label>Вид давления<select class="field-control" data-balance="pressure_kind"><option value="">Не задан</option><option value="absolute"${balance.pressure_kind === 'absolute' ? ' selected' : ''}>Абсолютное</option><option value="gauge"${balance.pressure_kind === 'gauge' ? ' selected' : ''}>Избыточное</option></select></label>
      ${state.context.pump_elevation_m == null ? '' : `<p>Заданная в проекте ось всасывания: ${fmt(state.context.pump_elevation_m)} м.</p>`}
      <div class="suction-grid">${['pressure_bar','atmospheric_pressure_bar','source_elevation_m','pump_elevation_m','vapor_head_m','npshr_m','safety_margin_m'].map(k => field(k, balance[k])).join('')}</div>${field('basis', balance.basis, true)}${field('npshr_basis', balance.npshr_basis, true)}</details>
      <details><summary>Доступные данные и ограничения каталога</summary>${state.context.catalogue_notes.map(n => `<p>${esc(n)}</p>`).join('')}</details>
      <div data-loss-rows></div><button type="button" class="text-button" data-add-loss>+ Добавить готовые потери</button>
      <p>Один результат может покрывать несколько элементов. Общие участки и местные потери учитывайте один раз. Пустое значение означает отсутствие данных; ноль требует основания.</p>
      ${state.saved.status === 'stale' ? '<label><input type="checkbox" data-reviewed> Перепроверил значения и основания по текущим размерам, изделиям и режиму</label>' : ''}
      <p data-suction-error role="alert"></p><div data-suction-result aria-live="polite"></div>
      <button type="submit" class="soft-button">Сохранить и проверить</button> <button type="button" class="text-button" data-suction-close>Закрыть</button></form>`;
    updateRouteDescription();
    $('[data-loss-rows]').innerHTML = (input.losses || []).map(row).join('');
    displayResult(state.saved);
  }
  function updateRouteDescription() { $('[data-route-description]').textContent = route()?.label || 'Путь ещё не выбран.'; }
  function changed() { $('[data-suction-result]').textContent = 'Изменения ещё не проверены и не сохранены.'; $('[data-suction-error]').textContent = ''; }
  function lock(value) { busy = value; dialog.querySelectorAll('button,input,select,textarea').forEach(el => { el.disabled = value; }); }
  dialog.addEventListener('input', changed);
  dialog.addEventListener('change', event => {
    if (event.target.matches('[data-route]')) {
      $('[data-loss-rows]').replaceChildren();
      updateRouteDescription();
      changed();
    }
  });
  dialog.addEventListener('click', event => {
    if (busy) return;
    if (event.target.closest('[data-suction-close]')) dialog.close();
    if (event.target.closest('[data-remove-loss]')) { event.target.closest('fieldset').remove(); changed(); }
    if (event.target.closest('[data-add-loss]')) {
      if (!route()) { $('[data-suction-error]').textContent = 'Сначала выберите путь.'; return; }
      // IDs must stay unique after reload, removal and insertion.
      const ids = new Set([...dialog.querySelectorAll('[data-loss-id]')].map(el => el.dataset.lossId));
      while (ids.has(`loss-${nextRow + 1}`)) nextRow++;
      $('[data-loss-rows]').insertAdjacentHTML('beforeend', row()); changed();
    }
  });
  dialog.addEventListener('submit', async event => {
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    changed();
    try {
      const balance = Object.fromEntries([...dialog.querySelectorAll('[data-balance]')].map(el => [el.dataset.balance,
        ['basis','npshr_basis'].includes(el.dataset.balance) ? el.value.trim() : el.dataset.balance === 'pressure_kind' ? el.value || null : number(el)]));
      const losses = [...dialog.querySelectorAll('[data-loss-id]')].map(el => ({id:el.dataset.lossId,
        covers:[...el.querySelectorAll('[data-cover]:checked')].map(c => c.dataset.cover),
        ...Object.fromEntries([...el.querySelectorAll('[data-loss-field]')].map(c => [c.dataset.lossField, c.dataset.lossField === 'basis' ? c.value.trim() : number(c)]))}));
      const payload = {revision:state.revision, fingerprint:state.context.fingerprint, route_id:$('[data-route]').value,
        balance, losses, path_basis:$('[data-path-basis]').value.trim(), reviewed:$('[data-reviewed]')?.checked || false};
      lock(true);
      state = await api('suction', {method:'POST', body:JSON.stringify(payload)});
      await onSaved(state); render(); $('[data-suction-result]').scrollIntoView({block:'center'});
    } catch (error) { $('[data-suction-error]').textContent = error.message || 'Не удалось сохранить проверку.'; }
    finally { lock(false); }
  });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  window.ZaryaSuction = {async open(options) {
    if (dialog.open) return;
    api = options.api; onSaved = options.onSaved;
    dialog.innerHTML = '<h2 id="suction-title">Проверка всасывания</h2><p>Проверяем текущую компоновку…</p>';
    dialog.showModal(); busy = true;
    try { state = await api('suction', {headers:{'X-Zarya-Draft':options.projectId}}); render(); dialog.scrollTop = 0; }
    catch (error) { dialog.innerHTML = `<h2 id="suction-title">Проверка всасывания</h2><p role="alert">${esc(error.message)}</p><button type="button" class="text-button" data-suction-close>Закрыть</button>`; }
    finally { busy = false; }
  }};
})();
