/* A collapsed, read-only quantity review. No green procurement/release badge. */
(() => {
  'use strict';
  const escape = value => String(value ?? '').replace(/[&<>"']/g,
    char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const allowedActions = new Set(['risers', 'apartments', 'area', 'sectional_valves', 'service_nodes', 'balancing']);
  function render(review, {editable=true}={}) {
    if (!review || review.scope !== 'ios2') return '';
    if(review.state==='unavailable') return `<details class="section-details spec-quantity-review"><summary>Спецификация ИОС2 · проверка не выполнена</summary><p class="field-help">${escape(review.notice)}</p></details>`;
    const c=review.counts;
    const title=c.missing || c.invalid
      ? `без количества: ${c.missing}${c.invalid ? ` · ошибки: ${c.invalid}` : ''}`
      : 'количества заполнены';
    const actions=editable ? review.actions.filter(a=>allowedActions.has(a.id)).map(a=>
      `<div class="spec-review-action"><button type="button" class="text-button" data-action="spec-quantity-inputs" data-spec-input="${a.id}">${escape(a.title)} →</button><p class="field-help">${escape(a.note)}</p></div>`).join('') : '';
    const groups=review.groups.map(group=>`<details class="spec-review-group"><summary>${escape(group.title)} · ${group.count}</summary><ul>${group.items.map(item=>`<li><strong>${item.position ? `Поз. ${escape(item.position)} · ` : ''}${escape(item.name)}</strong><p>${escape(item.detail)}</p></li>`).join('')}</ul></details>`).join('');
    return `<details class="section-details spec-quantity-review"><summary>Спецификация ИОС2 · ${title}</summary><div class="spec-review-counts"><span>Позиций: <b>${c.positions}</b></span><span>Количество указано: <b>${c.assigned}</b></span><span>Из них оценочных: <b>${c.estimated}</b></span></div><p class="field-help">${escape(review.notice)}</p>${actions}${groups}${c.requirements ? `<p class="field-help">Отдельные текстовые требования: ${c.requirements}. В число материальных позиций не включены.</p>` : ''}</details>`;
  }
  const api=Object.freeze({render});
  if (typeof window !== 'undefined') window.ZaryaSpecReview=api;
  if (typeof module !== 'undefined') module.exports=api;
})();
