/* Addresses from the validator, never parsed from prose or inferred from IDs. */
(() => {
  'use strict';
  const specs=Object.freeze({
    duplicate_riser_id:{registry:'sewage_risers',field:'riser_id',label:'Обозначение стояка'},
    blocked_pipe_section:{registry:'sewer_pipes',field:'wall_thickness_mm',label:'Толщина стенки трубы'},
    unlinked_riser:{registry:'sewage_risers',field:'riser_id',label:'Обозначение расчётного стояка'},
    unknown_element_section:{registry:'sewer_elements',field:'section_id',label:'Участок элемента'},
    element_section_system:{registry:'sewer_elements',field:'section_id',label:'Участок элемента'},
    unknown_element_connection:{registry:'sewer_elements',field:'connects_to',label:'Связь элемента'},
    duplicate_element_id:{registry:'sewer_elements',field:'element_id',label:'Обозначение элемента'},
    element_quantity_positive:{registry:'sewer_elements',field:'quantity',label:'Общее количество'},
    element_typical_quantity_positive:{registry:'sewer_elements',field:'typical_quantity',label:'Количество на типовом этаже'},
    element_floor_order:{registry:'sewer_elements',field:'floor_to',label:'Конечный этаж'},
    element_dn_positive:{registry:'sewer_elements',field:'dn_mm',label:'DN, мм'},
    element_slope_nonnegative:{registry:'sewer_elements',field:'slope_per_mille',label:'Уклон, ‰'},
    element_layout_nonnegative:{registry:'sewer_elements',field:'layout_column',label:'Колонка условной раскладки'},
    element_chainage_nonnegative:{registry:'sewer_elements',field:'service_chainage_m',label:'Расстояние точки обслуживания'},
    element_system_choice:{registry:'sewer_elements',field:'system',label:'Система элемента'},
    element_kind_choice:{registry:'sewer_elements',field:'kind',label:'Вид элемента'},
    element_direction_choice:{registry:'sewer_elements',field:'service_direction',label:'Направление обслуживания'},
    element_fitting_choice:{registry:'sewer_elements',field:'service_fitting',label:'Исполнение доступа'},
    element_spec_unit_required:{registry:'sewer_elements',field:'unit',label:'Единица измерения'},
    fan_ids_list:{registry:'wastewater_fan_ventilation',field:'riser_ids',label:'ID стояков К1'},
    fan_unlinked_riser:{registry:'wastewater_fan_ventilation',field:'riser_ids',label:'ID стояков К1'},
    fan_repeated_riser:{registry:'wastewater_fan_ventilation',field:'riser_ids',label:'ID стояков К1'},
    fan_model_id:{registry:'wastewater_fan_ventilation',field:'terminal_id',label:'Обозначение окончания'},
    fan_model_duplicate_id:{registry:'wastewater_fan_ventilation',field:'terminal_id',label:'Обозначение окончания'},
    fan_model_riser_ids:{registry:'wastewater_fan_ventilation',field:'riser_ids',label:'ID стояков К1'},
    fan_model_kind:{registry:'wastewater_fan_ventilation',field:'kind',label:'Тип окончания'},
  });
  const globals=Object.freeze({
    fan_global_boolean:{field:'external_ventilation_verified',label:'Вентиляция наружной сети'},
    fan_global_text:{field:'external_ventilation_ref',label:'Основание вентиляции наружной сети'},
  });
  function resolve(issue,submitted,current,editable=true,editors={},context={}) {
    const global=issue && Object.hasOwn(globals,issue.code)?globals[issue.code]:null;
    if(global) {
      if(!editable || issue.registry!=='wastewater_fan_ventilation' || issue.scope!=='global'
        || Object.hasOwn(issue,'row_index') || issue.field!==global.field
        || !submitted || typeof submitted!=='object' || Array.isArray(submitted)
        || (submitted.terminals!==undefined && !Array.isArray(submitted.terminals))
        || JSON.stringify(submitted)!==JSON.stringify(current))return null;
      return {key:issue.registry,field:global.field,scope:'global',label:global.label};
    }
    if(issue?.scope!==undefined && issue.scope!=='terminal')return null;
    let spec=issue && Object.hasOwn(specs,issue.code)?specs[issue.code]:null;
    if(issue && (['required_value','invalid_number','nonfinite_number','integer_required','boolean_required'].includes(issue.code)
        || (['fan_text_value','fan_model_number','fan_model_boolean','fan_model_reference'].includes(issue.code) && issue.registry==='wastewater_fan_ventilation'))
      && ['sewage_risers','sewer_pipes','sewer_elements','wastewater_fan_ventilation'].includes(issue.registry)) {
      const columns=editors[issue.registry];
      const matches=Array.isArray(columns)?columns.filter(column=>column.key===issue.field):[];
      const column=matches.length===1?matches[0]:null;
      if(column && /^[a-z][a-z0-9_]*$/.test(column.key) && typeof column.label==='string'
        && (issue.code==='required_value'?column.required===true
          :['fan_text_value','fan_model_reference'].includes(issue.code)?column.kind==='text'
          :['boolean_required','fan_model_boolean'].includes(issue.code)?column.kind==='boolean'
          :issue.code==='integer_required'?column.kind==='integer'
            :['integer','number'].includes(column.kind))) {
        spec={registry:issue.registry,field:column.key,label:column.label};
      }
    }
    const fan=spec?.registry==='wastewater_fan_ventilation';
    const submittedRows=fan && submitted && !Array.isArray(submitted)?submitted.terminals:submitted;
    const currentRows=fan && current && !Array.isArray(current)?current.terminals:current;
    if(!editable || !spec || issue.registry!==spec.registry || issue.field!==spec.field
      || !Number.isSafeInteger(issue.row_index) || issue.row_index<0
      || (fan && (Array.isArray(submitted) || Array.isArray(current)))
      || !Array.isArray(submittedRows) || !submittedRows[issue.row_index]
      || !Array.isArray(currentRows) || JSON.stringify(submitted)!==JSON.stringify(current))return null;
    if(['unlinked_riser','unknown_element_section','element_section_system','unknown_element_connection','fan_unlinked_riser','fan_repeated_riser'].includes(issue.code)) {
      for(const key of [spec.registry,'sewer_pipes']) {
        const before=context.submitted?.[key],now=context.current?.[key];
        const valid=key==='wastewater_fan_ventilation'
          ? before && !Array.isArray(before) && Array.isArray(before.terminals)
          : Array.isArray(before) || before===null;
        if(!valid || JSON.stringify(before)!==JSON.stringify(now))return null;
      }
      if(JSON.stringify(context.submitted[spec.registry])!==JSON.stringify(submitted))return null;
    }
    return {key:spec.registry,field:spec.field,index:issue.row_index,
      label:`${spec.label} · строка ${issue.row_index+1}`};
  }
  const api=Object.freeze({resolve});
  if(typeof window!=='undefined')window.ZaryaInputIssues=api;
  if(typeof module!=='undefined')module.exports=api;
})();
