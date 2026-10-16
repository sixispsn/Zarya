"""Studio input adapter only: no duplicated thermal calculation."""
from app.calc.hws_stage_p import HwsStagePInput


def from_values(values):
    return HwsStagePInput(
        enabled=values.get('hws_stage_p_enabled') == 'yes',
        apartment_building=(values['building_purpose'] == 'residential'
                            if 'building_purpose' in values else None),
        water_towel_rails=({'yes': True, 'no': False}.get(values.get('hws_water_towel_rails'))),
        zones=int(values['hws_circulation_zones']) if 'hws_circulation_zones' in values else None,
        hot_temp_c=values.get('hws_hot_temp_c', 65),
        cold_temp_c=values.get('hws_cold_temp_c', 5),
        delta_t_c=values.get('hws_delta_t_c'),
        loss_percent=values.get('hws_loss_percent'),
    )
