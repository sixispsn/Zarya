"""Source-backed PFFS evidence for the local L06 study, not a purchase catalog.

A dimensional row and a generic manual do not identify a complete order code.
Conflicting sources stay unresolved; no station loss curve is manufactured.
"""

PFFS_PAGE = 'https://www.cnprussia.ru/catalog/aikon/avtomaticheskie-ustanovki-pozharotusheniya/pffs/'
MANUAL_URL = ('https://www.cnprussia.ru/upload/iblock/d2d/cr15ihbsa2x6lcy33v4vookxnzv2q5j3/'
              '%D0%A0%D0%AD_PFFS_%D0%92%D0%B5%D1%80%D1%81%D0%B8%D1%8F%2027052025.pdf')
PASSPORT_URL = ('https://www.cnprussia.ru/upload/iblock/c7b/k4p2k4yi3nk76081kj9n3xpogsqb3bmy/'
                '9%20%D0%9A%D1%80%D0%B0%D1%82%D0%BA%D0%BE%D0%B5%20%D0%A0%D0%AD%20PBS_PFFS_JM%2030052025.pdf')

SOURCES = {
    'catalog': dict(file='Каталог PFFS.pdf',
        sha256='fab7ea4dc4c37bf0d7c865f8398165139e6d0a77cc0689b039cc7dafc683dc39',
        scope='user_supplied_catalog', pages=(5, 7, 8, 11, 38, 40)),
    'manual': dict(file='РЭ_PFFS_Версия 27052025.pdf', url=MANUAL_URL,
        sha256='590c6a2baa0b12a2b2b715dcbd58996756d156902c5ff494666ef4d84bb8fd6c',
        scope='generic_series_manual_not_order_confirmation', pages=(11, 12, 15, 27, 42)),
    'passport': dict(file='9 Краткое РЭ PBS_PFFS_JM 30052025.pdf', url=PASSPORT_URL,
        sha256='b080de82de955a55cab0fd114a2910aa3fafe43603756ab8b255825e1ead28ec',
        scope='blank_generic_passport_not_completed_unit_data', pages=(1, 8)),
    'sp10_amendment1': dict(file='sp-10.13130-izm.1.pdf',
        sha256='930d6d249938dba8a9175791ed0576648db367a461e89a246296d596725c2225',
        scope='user_supplied_normative_amendment', pages=(25, 27, 28, 29)),
}

PFFS32_ROW = dict(
    candidate_id='cnp-cdm32-3', dimensional_model='PFFS 2 CDM32-3 D',
    full_order_code=None, pumps=2, power_per_motor_kw=5.5, connection_dn=100,
    dimensions_mm=dict(H=1213, H1=205, H2=1465, L=968, L1=778,
                       B1=628, B2=428, B=1056, C=1623),
    dimension_source='catalog:40; letter definitions catalog:38',
    series_pressure_options_bar=(16, 25), selected_pressure_rating_bar=None,
    series_room_temperature_c=(5, 40),
    station_curve_includes_internal_losses=False,
    guaranteed_assembled_station_curve=None,
    header_material=None,
    material_conflict=dict(
        catalog='AISI 304; catalog:8', manual_11='stainless steel; manual:11',
        manual_12='coated carbon steel; manual:12'),
    factory_dry_run_stop=dict(pump1=True, pump2=True, source='manual:27,42'),
    # Only an inventory of the standard arrangement, not separate purchase rows.
    included_components=(
        dict(id='pumps', name='Насос CDM32-3', quantity=2, unit='шт.', source='catalog:40'),
        dict(id='headers', name='Коллекторы: всасывающий и напорный', quantity=2, unit='шт.', source='catalog:8'),
        dict(id='check_valves', name='Обратные клапаны после насосов', quantity=2, unit='шт.', source='catalog:8'),
        dict(id='isolators', name='Запорная арматура до и после насосов', quantity=4, unit='шт.', source='passport:8; two pumps'),
        dict(id='gauges', name='Манометры на коллекторах', quantity=2, unit='шт.', source='catalog:8'),
        dict(id='cabinet', name='Шкаф управления', quantity=1, unit='шт.', source='catalog:5,8'),
        dict(id='frame', name='Общая рама', quantity=1, unit='шт.', source='catalog:8'),
    ),
    optional_not_selected=('jockey_module',),
    selection_confirmed=False,
)

MISSING_CONFIRMATIONS = (
    ('order_code', 'Полный заказной код, допустимое входное и рабочее давление, материал коллекторов.'),
    ('assembled_curve', 'Гарантированная Q-H на границах станции при одном рабочем насосе, с обвязкой и допусками.'),
    ('static', 'Максимальный напор при нулевой подаче с допусками, условия переходных режимов.'),
    ('npsh', 'NPSHr, допустимый диапазон подач и минимальный расход; условия отвода тепла при малой подаче.'),
    ('automation', 'Согласованная автоматика резервного насоса по п.12.3 СП10 с изменением 1, схема и версия шкафа.'),
    ('scope', 'Границы поставки: испытание расхода, дренаж, датчики, внешние задвижки и сигналы в смежные разделы.'),
)
