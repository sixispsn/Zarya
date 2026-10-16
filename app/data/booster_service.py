"""Documented CDM15 service provisions, not a permission to dismantle a PBS.

Only exact catalogue selections are matched. A factory plug is not an added
automatic air vent or a drain valve, and does not drain adjacent pipe pockets.
"""
from app.data.booster_controls import booster_control

CDM_MANUAL_URL = 'https://www.cnprussia.ru/upload/iblock/c4e/23rryzb27z1zrncaeu89dh99h5idhq25/%D0%A0%D0%AD_CDM06102026.pdf'
PBS_MANUAL_URL = 'https://www.cnprussia.ru/upload/iblock/f10/nxsr5i5a6nf3tmr2cumqikhlgn1q3o41/%D0%A0%D0%AD_PBS_30.03.2026.pdf'
CDM_MANUAL_SHA256 = 'e2d979db89d914d1134264c4912e79f0d305c12f29b8c783776299e9338932ca'
PBS_MANUAL_SHA256 = 'e8722c18521bf8d98c2b0bf2447c32173ca3fe53e6edd09548ea1d03e01cd9ed'
_MODELS = frozenset(f'CNP / Aikon PBS CDM15-{stage}' for stage in (2,3,5,7,9,11))


def booster_service(pump):
    if not booster_control(pump) or pump.model not in _MODELS:
        return None
    return dict(
        source='РЭ CNP CDM, 06.10.2026: с. 23, 29, 34; приложение А, рис. 7-Н, с. 51',
        source_url=CDM_MANUAL_URL, source_sha256=CDM_MANUAL_SHA256,
        station_source='РЭ Aikon PBS, 30.03.2026, с. 44',
        station_source_url=PBS_MANUAL_URL, station_source_sha256=PBS_MANUAL_SHA256,
        drain='Узел сливной пробки, поз. 28; дренажный винт, поз. 28b',
        vent='Узел пробки воздушного клапана, поз. 36',
        summary='СВ1/2 - штатные воздушные пробки; СС1/2 - штатные сливные пробки насосов. '
                'Входят в насос, отдельной закупки нет. Не заменять автоматическим воздухоотводчиком.',
        limitation='Подтверждено наличие точек у серии CDM15 по РЭ, не опорожнение всей ветви. '
                   'Сверить исполнение поставки; приём воды и полость за НОК требуют отдельного решения.',
        maintenance='РЭ PBS описывает обслуживание с отключением установки и блокировкой питания. '
                    'Путь через второй насос не разрешает ремонт при работающей станции.',
        live_maintenance_approved=False,
    )
