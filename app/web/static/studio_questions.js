/* Presentation queue only: required inputs are defined by the existing API. */
(() => {
  'use strict';
  function steps(draft) {
    if(!draft || draft.study) return [];
    if(draft.calculation) return draft.next_steps || [];
    const review=draft.fields.filter(row=>['review','conflict'].includes(row.status));
    if(review.length) return [{id:'sources',title:'Проверим найденное',fields:review.slice(0,3).map(row=>row.key),
      description:'Подтвердите значения из документов. Источник можно раскрыть под каждым полем.'}];
    if(!draft.next_question) return [];
    return [{id:'demand',title:'Уточним для расчёта',fields:[draft.next_question],
      description:draft.documents.length?'Этого значения не хватает или его нужно подтвердить по документам.':'Укажите недостающее значение. Остальное можно уточнить позже.'}];
  }
  window.ZaryaQuestions=Object.freeze({steps});
})();
