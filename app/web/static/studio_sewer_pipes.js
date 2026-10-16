/* Explicit registry input. Schema/labels come from the server, no geometry defaults. */
(() => {
  function rows(items, columns, escape, elements=false) {
    function control(column, item) {
      const value=item[column.key] ?? '';
      const options=column.key==='system' ? [['K1','К1'],['K2','К2']]
        : column.options || (column.kind==='boolean' ? [['true','Да'],['false',column.key==='accessible'?'Нет / не подтверждена':'Нет']] : null);
      const attrs=`data-column="${escape(column.key)}" class="field-control"`;
      // Preserve an existing unsupported element enum until an explicit choice.
      // It remains invalid server-side; this option is not a new accepted value.
      const unsupported=((elements===true && ['system','kind','service_direction','service_fitting'].includes(column.key))
        || (elements==='fans' && column.key==='kind'))
        && options && value!=='' && !options.some(([v])=>String(value)===v);
      const retained=unsupported?`<option value="${escape(value)}" selected data-unsupported>Не поддерживается: ${escape(value)} — выберите явно</option>`:'';
      const input=column.kind==='ids' ? `<textarea ${attrs} data-id-list rows="3" placeholder="Каждый ID с новой строки">${escape(Array.isArray(value)?value.join('\n'):value)}</textarea>` : options ? `<select ${attrs}${column.kind==='boolean'?' data-pipe-boolean':''}><option value="">Не задано</option>${retained}${options.map(([v,label])=>`<option value="${escape(v)}"${String(value)===v?' selected':''}>${escape(label)}</option>`).join('')}</select>`
        : `<input ${attrs} value="${escape(value)}" ${column.kind==='text'?'maxlength="200"':'inputmode="decimal"'} placeholder="Не задано">`;
      return `<label>${escape(column.label)}${column.required?' *':''}${input}</label>`;
    }
    const noun=elements==='risers'?'расчётный стояк':elements==='fans'?'фановое окончание':elements?'элемент':'участок';
    const system=['fans','risers'].includes(elements)?'К1':'К1/К2';
    const details=elements==='risers'?'Рабочая высота, внутренние диаметры и клапан':elements==='fans'?'Размеры и подтверждения окончания':elements?'Этажи, отметки, изделие и обслуживание':'Расход, DN, уклон, отметки и дополнительные исходные';
    const help=elements==='risers'?'Неизвестное оставьте пустым. Площадь клапана требует паспортного источника и режима с клапаном. Не переносите размеры и расходы из условного разреза.':elements==='fans'?'Пусто — неизвестно. Да и нет — явные исходные. Наличие источника и заполненные поля не означают успешной проверки. Для коллектора и клапана есть отдельные ограничения графики.':elements?'Неизвестное оставьте пустым. Общее и типовое количество сохраняются раздельно. Ссылка — точный ID из реестра, не подпись рисунка. Доступность не заменяет проверку обслуживания.':'Неизвестное оставьте пустым. Отметки начала и конца задаются парой; расчётные исходные относятся только к этому участку. Трубы и связи не определяются по изображению.';
    return items.map((item,index)=>`<fieldset class="route-row"><legend data-registry-row-label="${system} · ${noun}">${system} · ${noun} ${index+1}</legend>${columns.filter(c=>c.primary).map(c=>control(c,item)).join('')}<details class="sewer-pipe-options"><summary>${details}</summary><p class="field-help">${help}</p><div class="pipe-option-fields">${columns.filter(c=>!c.primary).map(c=>control(c,item)).join('')}</div></details><button type="button" class="text-button" data-action="remove-section" data-registry-remove-label="Удалить ${noun} ${system}" aria-label="Удалить ${noun} ${system} ${index+1}">Удалить строку</button></fieldset>`).join('');
  }
  function renumber(editor) {
    editor.querySelectorAll('.route-row').forEach((row,index)=>{
      const legend=row.querySelector('[data-registry-row-label]');
      const remove=row.querySelector('[data-registry-remove-label]');
      if(legend)legend.textContent=legend.dataset.registryRowLabel+' '+(index+1);
      if(remove)remove.setAttribute('aria-label',remove.dataset.registryRemoveLabel+' '+(index+1));
    });
  }
  window.ZaryaSewerPipes={rows,renumber};
})();
