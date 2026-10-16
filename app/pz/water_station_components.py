"""Ownership of the fittings already shown on the station principle sheet.

Not a product catalogue or a sizing algorithm. Factory parts stay in the PBS
assembly; a repeated view of the heater meter stays in its existing VU-Г.
Only the explicitly drawn station points get a count of one. General building
service points, paper-space pipes and annotation-only Т1/Т2 are not counted.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StationExternalItem:
    id: str
    name: str
    note: str


def external_items(project):
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_hot_node import hot_meter_view

    state = drawing_state(project)
    result = []
    if not state.switching_bridge:
        result.append(StationExternalItem('station_feed_isolation',
            'Запорная арматура подводки к насосной / распределительному узлу',
            'На границе листа насосной, не повторная арматура ВУ'))
    if project.pumps.required:
        result += [
            StationExternalItem('station_air', 'Устройство удаления воздуха напорного коллектора НУ',
                'Внешняя обвязка; не воздушные пробки насосов и не верхние узлы стояков'),
            StationExternalItem('station_drain', 'Кран общего спуска напорного коллектора НУ',
                'Внешняя обвязка; приёмник и безопасный отвод воды уточнить. '
                'Не заменяет слив отсечённых насосов и полостей за обратными клапанами'),
        ]
    if max(int(project.building.zones or 1), 1) == 1:
        result.append(StationExternalItem('station_cold_isolation',
            'Запорная арматура ответвления В1 к сети здания',
            'Одна показанная отсечка ответвления; не полный состав узла счётчика ХВС'))
        if (getattr(project.building.hws_type, 'value', project.building.hws_type) == 'central'
                and project.source.hws_heater_in_scope and hot_meter_view(project) is None):
            result.append(StationExternalItem('station_heater_isolation',
                'Запорная арматура ответвления к водонагревателю',
                'Узел учёта этой ветви не задан; не назначает состав ВУ-Г'))
    return tuple(result)


def branch_spec_ids(project, node):
    """Existing meter identity and its shown upstream isolation, not new parts."""
    from app.pz.metering_hot_node import hot_meter_view
    if node == 'cold':
        return 'meter_cold', 'station_cold_isolation'
    if node == 'hot':
        return (('hot:meter', 'hot:valve_before') if hot_meter_view(project) else
                ('meter_hot', 'station_heater_isolation'))
    raise ValueError('Неизвестная ветвь учёта насосной')


def external_spec_rows(project, next_pos):
    from app.pz.spec import SpecRow
    return [SpecRow(next_pos(), item.name, type_mark='DN, PN, исполнение и модель по подбору',
        unit='шт.', qty=1, component_ids=(item.id,),
        quantity_basis='principle_requirement',
        quantity_source='Одна точка в принятой схеме насосной; не по числу квартир/стояков',
        note=item.note + '; в подтверждённый комплект PBS не включено')
        for item in external_items(project)]
