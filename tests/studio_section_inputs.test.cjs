const {test}=require('node:test');
const assert=require('node:assert/strict');
global.window={};
require('../app/web/static/studio_configurator.js');
const visible=window.ZaryaConfigurator.fanFieldVisible;

test('horizontal flow only asks inputs for the selected method; conflicts stay visible',()=>{
  assert(!visible('section_k1_receiving_length_m',{}));
  assert(visible('section_k1_flow_source',{}));
  const values={section_k1_flow_basis:'whole_building'};
  assert(visible('section_k1_fixtures_count',values));
  assert(visible('section_k1_receiving_length_m',values));
  assert(!visible('section_k1_q_hour_max_m3h',values));
  assert(!visible('section_k1_design_flow_lps',values));
  assert(visible('section_k1_design_flow_lps',{...values,section_k1_design_flow_lps:5}));
  assert(visible('section_k1_q_hour_max_m3h',{section_k1_flow_basis:'section_hourly'}));
});

test('individual and automatic outlets keep diameter and safety inputs editable',()=>{
  for (const mode of ['', 'auto', 'individual']) {
    const values={section_fan_mode:mode};
    for (const key of ['mode','height_m','working_diameter_mm','opening_distance_m',
        'no_openings_confirmed','plastic_exposed','source_ref']) {
      assert(visible('section_fan_'+key,values),`${mode}: ${key}`);
    }
    assert(visible('section_fan_roof_level_m',values)); // shared water/sewer building datum
    for (const key of ['member_ids','space','space_floor_m',
        'collector_low_m','collector_high_m','attic_insulated']) {
      assert(!visible('section_fan_'+key,values),`${mode}: ${key}`);
      assert(visible('section_fan_'+key,{section_fan_mode:'common'}));
    }
  }
});

test('UV question follows exposed plastic without inventing a yes/no answer',()=>{
  for (const value of ['', 'unknown', 'no']) {
    assert(!visible('section_fan_uv_protected',{section_fan_plastic_exposed:value}));
  }
  assert(visible('section_fan_uv_protected',{section_fan_plastic_exposed:'yes'}));
});
