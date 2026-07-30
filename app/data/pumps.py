"""
База насосов с кривыми Q-H.

Архивная база Grundfos из legacy хранится отдельно от актуального расширения
каталога. Это позволяет запускать неизменные golden/parity-тесты legacy и
одновременно выполнять проектный подбор по проверенным кривым изготовителей.

Перенесено из legacy/sp30_calculator.html (массив PUMP_CURVES).
"""
from dataclasses import dataclass, field
from typing import Literal


PumpType = Literal["boost", "circ", "fire"]


@dataclass(frozen=True)
class PumpCurvePoint:
    """Точка кривой Q-H."""
    q: float   # расход, м³/ч
    h: float   # напор, м


@dataclass(frozen=True)
class Pump:
    """Насос с характеристиками и кривой Q-H."""
    model: str
    brand: str
    type: PumpType
    p_kw: float              # мощность, кВт
    p_max_bar: float         # макс. давление, бар
    t_max: float             # макс. температура, °С
    npshr: float | None      # требуемый кавитационный запас, м; None — нет в источнике
    q_opt: float             # оптимальный расход (BEP), м³/ч
    note: str
    curve: tuple[PumpCurvePoint, ...]
    npsh_curve: tuple[PumpCurvePoint, ...] = ()  # Q-NPSHr; h = NPSHr, м
    archived: bool = False   # архивная база (Grundfos)
    source_url: str = ""     # официальная карточка/кривая изготовителя
    source_note: str = ""    # идентификатор изделия и дата проверки


# Архивная база Grundfos (реальные кривые из каталога)
PUMPS: list[Pump] = [
    Pump(
        model="MAGNA3 32-80", brand="Grundfos", type="circ",
        p_kw=0.130, p_max_bar=10, t_max=110, npshr=2.0, q_opt=3.5,
        note="Резьбовое DN32, 1×230В, ЧРП встроен", archived=True,
        curve=(
            PumpCurvePoint(0, 8.5), PumpCurvePoint(1, 8.3), PumpCurvePoint(2, 8.0),
            PumpCurvePoint(3, 7.5), PumpCurvePoint(4, 6.5), PumpCurvePoint(5, 5.0),
            PumpCurvePoint(6, 3.0),
        ),
    ),
    Pump(
        model="CR 10-4", brand="Grundfos", type="boost",
        p_kw=2.2, p_max_bar=10, t_max=120, npshr=3.5, q_opt=6.0,
        note="Вертикальный многоступенчатый, DN50", archived=True,
        curve=(
            PumpCurvePoint(0, 40), PumpCurvePoint(2, 39), PumpCurvePoint(4, 37),
            PumpCurvePoint(6, 34), PumpCurvePoint(8, 29), PumpCurvePoint(10, 22),
            PumpCurvePoint(11, 16),
        ),
    ),
    Pump(
        model="CR 5-8", brand="Grundfos", type="boost",
        p_kw=1.1, p_max_bar=10, t_max=120, npshr=3.0, q_opt=3.5,
        note="Вертикальный многоступенчатый, DN32", archived=True,
        curve=(
            PumpCurvePoint(0, 66), PumpCurvePoint(1, 64), PumpCurvePoint(2, 62),
            PumpCurvePoint(3, 58), PumpCurvePoint(4, 52), PumpCurvePoint(5, 44),
            PumpCurvePoint(6, 34), PumpCurvePoint(7, 20),
        ),
    ),
    Pump(
        model="Hydro MX-A CR15-9", brand="Grundfos", type="fire",
        p_kw=11.0, p_max_bar=16, t_max=40, npshr=4.0, q_opt=12.0,
        note="1 осн.+1 рез., шкаф автоматики, DN65, СП 10", archived=True,
        curve=(
            PumpCurvePoint(0, 97), PumpCurvePoint(3, 95), PumpCurvePoint(6, 92),
            PumpCurvePoint(9, 87), PumpCurvePoint(12, 80), PumpCurvePoint(15, 70),
            PumpCurvePoint(18, 57), PumpCurvePoint(20, 45), PumpCurvePoint(22, 28),
        ),
    ),
]

# Актуальное расширение каталога. Эти позиции не входят в PUMPS намеренно:
# PUMPS остаётся дословным зеркалом legacy для source-parity теста.
#
# Wilo Helix FIRST V 1606:
# - артикул 4200993, P2=4 кВт, PN16, Tmax=120 °C — карточка Wilo;
# - точки Q-H перенесены из официального SVG интерактивной характеристики;
# - NPSHr=1,8 м принят по официальной NPSH-кривой в зоне BEP Q≈17,5 м³/ч.
#
# CNP / Aikon:
# - PFFS — пожарные установки, кривая «1» одного рабочего насоса; резервный
#   агрегат не суммируется с рабочим;
# - PBS — повысительные установки, кривая «1» одного рабочего насоса;
# - TD — циркуляционный in-line насос с табличной характеристикой;
# - Q-H CDM10/CDM15 перенесены из таблиц официального каталога CDM/CDMF
#   версии 24.11.2025, без оцифровки графика;
# - Q-NPSHr перенесены из векторных кривых того же каталога и округлены до
#   0,1 м. В расчёте NPSHr интерполируется при расходе рабочей точки;
# - трассировка, страницы и SHA-256 приведены в docs/catalogs/cnp_2025.md.


def _curve_from_table(
    q_values: tuple[float, ...],
    h_values: tuple[float, ...],
) -> tuple[PumpCurvePoint, ...]:
    """Собрать дословную табличную характеристику изготовителя."""
    if len(q_values) != len(h_values):
        raise ValueError("Число расходов и напоров каталожной кривой не совпадает")
    return tuple(PumpCurvePoint(q, h) for q, h in zip(q_values, h_values))


_CNP_CDM10_Q = (0, 5, 6, 8, 10, 12, 14)
_CNP_CDM10_HEADS = {
    2: (22.2, 21, 20.5, 19, 16.5, 13.5, 9.5),
    3: (33.3, 31.5, 31, 28.5, 25.5, 22, 16.5),
    4: (44.5, 42, 41, 38, 34, 29, 22),
    5: (56, 52.5, 51, 48, 43, 37, 28),
    6: (67, 63, 62, 58, 52, 44, 34),
    7: (78.5, 74, 73, 69, 62, 52, 40),
    8: (90, 85, 84, 79, 71, 60, 46),
    9: (101.5, 96, 94, 89, 80, 67, 52),
    10: (113, 107, 105, 98, 89, 76, 58),
    11: (124, 118, 115, 108, 98, 84, 64),
    13: (147, 140, 138, 130, 116, 99, 76),
    15: (171, 162, 159, 149, 134, 114, 88),
}
_CNP_CDM10_CURVES = {
    stage: _curve_from_table(_CNP_CDM10_Q, heads)
    for stage, heads in _CNP_CDM10_HEADS.items()
}
_CNP_CDM10_NPSH = _curve_from_table(
    _CNP_CDM10_Q,
    (1.0, 1.3, 1.4, 1.7, 2.0, 2.3, 2.8),
)

_CNP_CDM15_Q = (0, 8, 10, 12, 14, 15, 16, 18, 20, 22, 24)
_CNP_CDM15_HEADS = {
    1: (12.6, 12.2, 12, 11.8, 11.5, 11, 10.5, 10, 9, 8, 6.5),
    2: (26, 24.5, 24, 23.5, 23, 22.5, 21.5, 20, 18, 16, 13.5),
    3: (40, 37.5, 37, 36.5, 35.5, 34.5, 34, 32, 29, 25, 21),
    4: (54, 50.5, 50, 49, 47.5, 47, 46, 43, 39, 34, 28.5),
    5: (68, 63, 62, 61, 59, 58, 57, 53, 48, 42.5, 36),
    7: (96, 89, 88, 86, 83, 81, 79, 74, 68, 61, 51),
    9: (124, 115, 113, 111, 108, 106, 103, 96, 88, 78, 67),
    11: (151, 142, 140, 137, 133, 130, 126, 117, 107, 95, 83),
}
_CNP_CDM15_CURVES = {
    stage: _curve_from_table(_CNP_CDM15_Q, heads)
    for stage, heads in _CNP_CDM15_HEADS.items()
}
_CNP_CDM15_NPSH = _curve_from_table(
    _CNP_CDM15_Q,
    (1.3, 1.5, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.3, 2.7, 3.4),
)

_CNP_CDM10_POWER = {
    2: 0.75, 3: 1.1, 4: 1.5, 5: 2.2, 6: 2.2, 7: 3.0,
    8: 3.0, 9: 4.0, 10: 4.0, 11: 4.0, 13: 5.5, 15: 5.5,
}
_CNP_CDM15_POWER = {
    1: 1.1, 2: 2.2, 3: 3.0, 4: 4.0, 5: 4.0,
    7: 5.5, 9: 7.5, 11: 11.0,
}

_CNP_PBS_MODELS = {
    10: (3, 4, 6, 8, 10, 13, 15),
    15: (2, 3, 5, 7, 9, 11),
}
_CNP_PFFS_MODELS = {
    10: (2, 3, 4, 5, 6, 7, 8, 9, 11, 15),
    15: (1, 2, 3, 4, 5, 7, 9, 11),
}


def _cnp_series_data(series: int):
    if series == 10:
        return (
            _CNP_CDM10_CURVES,
            _CNP_CDM10_NPSH,
            _CNP_CDM10_POWER,
            10.0,
            "стр. 26-27",
        )
    return (
        _CNP_CDM15_CURVES,
        _CNP_CDM15_NPSH,
        _CNP_CDM15_POWER,
        15.0,
        "стр. 28-29",
    )


def _cnp_boost_pumps() -> list[Pump]:
    pumps: list[Pump] = []
    for series, stages in _CNP_PBS_MODELS.items():
        curves, npsh_curve, powers, q_opt, cdm_pages = _cnp_series_data(series)
        for stage in stages:
            pumps.append(Pump(
                model=f"PBS CDM{series}-{stage}",
                brand="CNP / Aikon",
                type="boost",
                p_kw=powers[stage],
                p_max_bar=16.0,
                t_max=70.0,
                npshr=None,
                q_opt=q_opt,
                note="Повысительная установка с ПЧ; кривая одного рабочего насоса",
                curve=curves[stage],
                npsh_curve=npsh_curve,
                source_note=(
                    "CNP/Aikon «Каталог PBS», 12.05.2025, стр. 46-47; "
                    f"«Каталог CDM/CDMF», 24.11.2025, {cdm_pages}: "
                    "табличная Q-H и векторная NPSH"
                ),
            ))
    return pumps


def _cnp_fire_pumps() -> list[Pump]:
    pumps: list[Pump] = []
    for series, stages in _CNP_PFFS_MODELS.items():
        curves, npsh_curve, powers, q_opt, cdm_pages = _cnp_series_data(series)
        for stage in stages:
            pumps.append(Pump(
                model=f"PFFS 2 CDM{series}-{stage} DS 16 S",
                brand="CNP / Aikon",
                type="fire",
                p_kw=powers[stage],
                p_max_bar=16.0,
                t_max=70.0,
                npshr=None,
                q_opt=q_opt,
                note="1 рабочий + 1 резервный; кривая одного рабочего насоса",
                curve=curves[stage],
                npsh_curve=npsh_curve,
                source_note=(
                    "CNP/Aikon «Каталог PFFS», 27.06.2025, стр. 38-39; "
                    f"«Каталог CDM/CDMF», 24.11.2025, {cdm_pages}: "
                    "табличная Q-H и векторная NPSH"
                ),
            ))
    return pumps

CURRENT_PUMPS: list[Pump] = [
    Pump(
        model="Helix FIRST V 1606-5/16/E/S/400-50",
        brand="Wilo",
        type="boost",
        p_kw=4.0,
        p_max_bar=16.0,
        t_max=120.0,
        npshr=1.8,
        q_opt=17.5,
        note="Вертикальный многоступенчатый, G 2, 3~400 В; артикул 4200993",
        curve=(
            PumpCurvePoint(0, 75.9),
            PumpCurvePoint(2, 75.2),
            PumpCurvePoint(4, 74.6),
            PumpCurvePoint(6, 73.7),
            PumpCurvePoint(8, 72.0),
            PumpCurvePoint(10, 70.1),
            PumpCurvePoint(12, 67.0),
            PumpCurvePoint(14, 63.7),
            PumpCurvePoint(16, 59.7),
            PumpCurvePoint(18, 54.7),
            PumpCurvePoint(20, 48.6),
            PumpCurvePoint(22, 41.0),
            PumpCurvePoint(24, 32.8),
            PumpCurvePoint(26, 24.6),
            PumpCurvePoint(28, 15.0),
            PumpCurvePoint(30, 6.6),
        ),
        source_url=(
            "https://wilo.com/oem/en/Products/en/application/heating/heating/"
            "renewables-heating/wilo-helix-first-v/"
            "helix-first-v-1606-5-16-e-s-400-50?t=1"
        ),
        source_note="Wilo, артикул 4200993; Q-H/NPSH проверены 23.07.2026",
    ),
    *_cnp_boost_pumps(),
    *_cnp_fire_pumps(),
    Pump(
        model="TD32-10(I)/2",
        brand="CNP",
        type="circ",
        p_kw=0.37,
        p_max_bar=16.0,
        t_max=120.0,
        npshr=1.1,
        q_opt=6.5,
        note="Циркуляционный in-line DN32; табличная Q-H характеристика",
        curve=(
            PumpCurvePoint(2, 11.0), PumpCurvePoint(3, 10.8),
            PumpCurvePoint(4, 10.6), PumpCurvePoint(5, 10.3),
            PumpCurvePoint(6, 10.0), PumpCurvePoint(7, 9.2),
            PumpCurvePoint(8, 7.8), PumpCurvePoint(9, 6.0),
        ),
        source_note=(
            "CNP «Каталог TD, LLT», версия 15.08.2025, стр. 74-75: "
            "таблица Q-H и график NPSH"
        ),
    ),
]


def list_pumps(
    pump_type: str | None = None,
    *,
    include_current: bool = False,
) -> list[Pump]:
    """Список насосов, опционально отфильтрованный по типу.

    ``include_current=False`` сохраняет дословный legacy-каталог и его golden
    результаты. Проектные мосты явно включают актуальное расширение.
    """
    catalog = PUMPS + (CURRENT_PUMPS if include_current else [])
    if pump_type is None:
        return list(catalog)
    return [p for p in catalog if p.type == pump_type]
