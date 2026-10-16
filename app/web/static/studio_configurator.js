/* Three presentation groups. No engineering formulas or hidden input defaults. */
(() => {
  'use strict';
  const groups = [
    {id:'building', title:'Здание', caption:'Этажи, кровля и условия', description:'Начнём с архитектуры. Пол первого этажа принимаем за 0,000.',
      primary:['building_purpose','floors','floor_height_m','basement_kind','basement_floor_m','roof_type'],
      sections:[
        ['Геометрия и водосток',['building_height_m','fire_height_m','fire_corridor_length_m','attic_kind','building_area_m2','building_volume_m3','section_drainage','section_funnel_heated','storm_city','storm_roof_area_m2','storm_walls_area_m2']],
        ['Фановая вентиляция · уточнение схемы',['section_fan_mode','section_fan_height_m','section_fan_member_ids','section_fan_working_diameter_mm','section_fan_space','section_fan_space_floor_m','section_fan_collector_low_m','section_fan_collector_high_m','section_fan_source_ref',
          ...['opening_distance_m','no_openings_confirmed','attic_insulated','plastic_exposed','uv_protected'].map(k=>'section_fan_'+k)]],
        ['К2 · данные планов, необязательно',['storm_funnels_count','storm_risers_count']],
        ['Стояк К2 · проверка выбранного DN',['storm_selected_riser_dn_mm','storm_max_riser_flow_lps','storm_funnels_on_different_levels']],
        ['Конструкции и особые условия',['foundation_kind','geology_status','geology_note','permafrost','seismic_zone']],
        ['Название объекта',['object_name']],
        ['Привязка отметок · для схемы',['section_fan_roof_level_m','section_zero_absolute_m','section_zero_source_ref']],
        ['Основания проекта · для ПЗ',['project_assignment_ref','project_survey_ref','project_service_life_years','project_overhaul_period_years']],
      ]},
    {id:'connection',title:'Подключение и ТУ',caption:'Ввод, напор и ограничения',description:'Возьмём известные условия подключения. Чего нет в ТУ — можно оставить на потом.',
      primary:['guaranteed_head_m','inputs_count','h_geom_m','hws_heater_in_scope'],
      sections:[
        ['Другие условия ТУ',['connection_note','fire_topology']],
        ['Привязка ввода · для схемы',['water_inlet_elevation_m']],
        ['Насосная · привязки для схемы',['station_room_number','station_floor_elevation_m','station_suction_elevation_m']],
        ['ТУ · водоснабжение',['water_source_description','water_connection_point','water_tu_org','water_tu_number','water_tu_date']],
        ['ТУ · водоотведение',['wastewater_disposal_mode','wastewater_tu_org','wastewater_tu_number','wastewater_tu_date']],
        ['Реальные участки К1/К2 · отдельный реестр',['sewer_pipes']],
        ['Элементы К1/К2 · отдельный реестр',['sewer_elements']],
        ['Расчётные стояки К1 · отдельный реестр',['sewage_risers']],
        ['Фановые окончания · реальная сеть К1',['wastewater_fan_ventilation']],
        ['Узел учёта К1 · необязательно',['enabled','location','regime','basis'].map(k=>'sewer_service_k1_metering_'+k)],
        ['Приямок · утечки и обслуживание',['enabled','room','location','reserve_location','discharge_note','basis'].map(k=>'sewer_service_sump_'+k)],
        ['Пожарная насосная · необязательно',['fire_station_model']],
        ['Схема К1 · магистраль и выпуск',['section_k1_dn_mm','section_k1_slope','section_k1_start_invert_m','section_k1_outlet_invert_m','section_k1_discharge_point','section_k1_source_ref']],
        ['К1 · проверка конечного участка',['flow_basis','design_flow_lps','flow_source','q_hour_max_m3h','fixtures_count','receiving_length_m','fixture_max_lps','outer_diameter_mm','wall_thickness_mm','material','manning_n','roughness_source'].map(k=>'section_k1_'+k)],
        ['Схема К2 · магистраль и выпуск',['section_k2_dn_mm','section_k2_slope','section_k2_start_invert_m','section_k2_outlet_invert_m','section_k2_discharge_point','section_k2_source_ref']],
        ['Водомерный узел',['vu_per_inlet','russian_equipment_only','vu_orientation','vu_drawing_scale','vu_cold_orientation','vu_hot_orientation','vu_filter_layout','vu_maintenance_layout','vu_technology','vu_telemetry','vu_leak_monitoring','vu_tamper_monitoring','vu_valve_feedback','vu_assembly','vu_magnetic_filter','vu_power']],
        ['Водомеры · проверка минимального расхода',['total','cold','hot'].flatMap(n=>['m3h','source'].map(k=>`meter_min_${n}_${k}`))],
        ['Опоры основного ВУ · необязательно',['inlet','outlet','bypass','bypass_after','height_mm'].map(k=>'vu_support_'+k)],
        ['Ручной ввод · расчётные пути и оборудование',['pressure_loss_mode','v1_sections','h_il_m','h_vvod_m','t3_loss_mode','t3_sections','h_il_hot_m','h_pr_m','h_tepl_m','h_apartment_c_meter_m','h_apartment_h_meter_m']],
      ]},
    {id:'consumers',title:'Потребители',caption:'Жители, квартиры и приборы',description:'Расходы определим существующим расчётным ядром. Жителей не выводим из количества квартир.',
      primary:['residents','apartments','consumer_code','hws_type'],
      sections:[
        ['Квартирные узлы · для спецификации',['apartment_units_mode','apartment_units_cold_count','apartment_units_hot_count']],
        ['Стояки · известные количества',['risers_v1','risers_t3','risers_t4']],
        ['Магистрали В1 · арматура по компоновке',['v1_sectional_valves_count','v1_sectional_valves_basis']],
        ['Обслуживание стояков · для спецификации',['water_service_mode', ...['v1','t3','t4'].flatMap(s=>['upper','lower'].map(p=>`water_service_${s}_${p}`))]],
        ['Балансировка ГВС · по компоновке',['hws_balance_mode','hws_balance_count','hws_balance_collector_count']],
        ['Циркуляция ГВС · оценка стадии П',['hws_stage_p_enabled','hws_water_towel_rails','hws_circulation_zones','hws_delta_t_c','hws_loss_percent','hws_hot_temp_c','hws_cold_temp_c']],
        ['Встроенные помещения и режим работы',['technology_presence','technology_note','building_operation']],
        ['Ручные поправки',['apartment_design_residents','sewage_max_fixture_lps']],
        ['Дождевая вода · необязательно',['rainwater_enabled','rainwater_purpose','rainwater_location','rainwater_demand_m3_day','rainwater_useful_volume_m3','rainwater_collection_area_m2','rainwater_collection_factor','rainwater_profile','rainwater_source','rainwater_technical_use',
          ...['setup','surface','selection_flow_lps','filter_loss_m','uv_loss_m','selection_source','quality_basis'].map(k=>'rainwater_treatment_'+k),
          ...['basis','storage','diversion','quality','network','annual','storage_days','annual_saving_m3','winter','discharge'].map(k=>'rainwater_design_'+k),
          ...['pump_setup','pump_flow_lps','outlets_count','hose_choice','pump_geometric_head_m','pump_terminal_head_m','pump_network_loss_m','pump_treatment_loss_m','pump_loss_source','pump_pipe_inner_mm','pump_pipe_length_m','pump_min_submergence_m','pump_max_submergence_m','pump_temperature_c','pump_clean_water','hose_model','hose_length_m','hose_inner_mm','hose_pn_bar','hose_loss_m','hose_sets'].map(k=>'rainwater_'+k)]],
      ]},
  ];
  const allKeys = group => [...group.primary, ...group.sections.flatMap(row=>row[1])];
  const commonFanKeys = new Set(['member_ids','space','space_floor_m',
    'collector_low_m','collector_high_m','attic_insulated'].map(key=>'section_fan_'+key));
  const fanFieldVisible = (key, values) => {
    if (key === 'vu_per_inlet') return Number(values.inputs_count) > 1;
    if (key === 'vu_support_height_mm') return ['inlet','outlet','bypass','bypass_after'].some(k=>values['vu_support_'+k]==='kromber-osvu1');
    if (key.startsWith('sewer_service_')) {
      const prefix=key.startsWith('sewer_service_k1_')?'sewer_service_k1_metering_':'sewer_service_sump_';
      if (key === prefix+'enabled') return true;
      if (values[prefix+'enabled'] !== 'yes') return false;
      // Preserve an incompatible saved reserve choice so it can be corrected.
      if (key === 'sewer_service_sump_reserve_location') return Boolean(values[key]) || !['',undefined,'supply_ventilation','other'].includes(values.sewer_service_sump_room);
      return true;
    }
    if (key.startsWith('water_service_') && key !== 'water_service_mode') return values.water_service_mode === 'explicit' && (key.startsWith('water_service_v1_') || values.hws_type === 'central');
    if (key.startsWith('hws_balance_')) {
      if (values.hws_type !== 'central') return false;
      if (key === 'hws_balance_count') return ['collection_branches','floor_loops','towel_rail_returns'].includes(values.hws_balance_mode);
      if (key === 'hws_balance_collector_count') return values.hws_balance_mode === 'towel_rail_returns';
    }
    if (['risers_t3','risers_t4'].includes(key)) return values.hws_type === 'central';
    if (['apartment_units_cold_count','apartment_units_hot_count'].includes(key)) return values.apartment_units_mode === 'explicit_counts';
    // Keep conflicting saved values visible so they can be cleared, not hidden.
    if (key.startsWith('section_k1_') && !values[key]) {
      const mode = values.section_k1_flow_basis || 'manual';
      if (['section_k1_design_flow_lps','section_k1_flow_source'].includes(key)) return mode === 'manual';
      if (['section_k1_q_hour_max_m3h','section_k1_fixture_max_lps'].includes(key)) return mode === 'section_hourly';
      if (['section_k1_fixtures_count','section_k1_receiving_length_m'].includes(key)) return mode !== 'manual';
    }
    if (commonFanKeys.has(key)) return values.section_fan_mode === 'common';
    if (key === 'section_fan_uv_protected') return values.section_fan_plastic_exposed === 'yes';
    return true;
  };
  const groupFor = key => groups.find(group=>allKeys(group).includes(key)) || groups[0];
  const state = (group,draft) => {
    const rows=group.primary.filter(key=>(key!=='basement_floor_m' || ['basement','subfloor'].includes(draft.fields.find(row=>row.key==='basement_kind')?.value)) && (key!=='hws_heater_in_scope' || draft.fields.find(row=>row.key==='hws_type')?.value!=='none'))
      .map(key=>draft.fields.find(row=>row.key===key)).filter(Boolean);
    const filled=rows.filter(row=>['confirmed','default'].includes(row.status)).length;
    const unresolved=draft.fields.filter(row=>allKeys(group).includes(row.key) && ['review','conflict'].includes(row.status));
    return {filled,total:rows.length,review:unresolved.length,kind:unresolved.length?'review':filled===rows.length?'filled':filled?'partial':'empty'};
  };
  window.ZaryaConfigurator=Object.freeze({groups,allKeys,groupFor,state,fanFieldVisible});
})();
