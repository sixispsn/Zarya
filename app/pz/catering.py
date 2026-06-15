"""
Препроцессор предприятий общественного питания.

Норма cafe_* в таблице А.2 СП 30 задана на одно условное блюдо, а не на
посадочное место. Число блюд считается по примечанию 5 к таблице А.2 (Изм.3):

    Uч  = 2,2 · n · m              — условных блюд в час (для часового максимума)
    Uсут = Uч · T · y             — условных блюд в сутки

где n — число посадочных мест;
    m — число посадок: кафе/столовая открытого типа = 2, при предприятии = 3,
        ресторан = 1,5;
    T — время работы предприятия, ч;
    y — коэффициент неравномерности посадок: кафе/столовая = 0,45,
        ресторан = 0,55.

Для расчёта водопотребления в ConsumerGroup подаётся Uч (часовой максимум),
поскольку ядро рассчитывает пик по часовой норме, а суточный добивает через qu_tot.

Если данных по посадкам нет — функция выбрасывает CateringDataNeeded,
чтобы запросить их, а не подставлять выдуманное число.
"""
from dataclasses import dataclass

# Параметры по типу предприятия: (m — посадок, y — неравномерность)
CATERING_TYPES = {
    "cafe":        {"m": 2.0, "y": 0.45, "label": "кафе/столовая открытого типа"},
    "canteen_ent": {"m": 3.0, "y": 0.45, "label": "столовая при предприятии"},
    "restaurant":  {"m": 1.5, "y": 0.55, "label": "ресторан"},
}


class CateringDataNeeded(Exception):
    """Недостаточно данных для расчёта числа блюд — нужно запросить у пользователя."""


@dataclass
class CateringResult:
    seats: int
    dishes_per_hour: int     # Uч — подаётся в расчёт
    dishes_per_day: int      # Uсут — справочно
    catering_type: str
    work_hours: float


def dishes_from_seats(
    seats: int,
    catering_type: str = "cafe",
    work_hours: float | None = None,
) -> CateringResult:
    """
    Число условных блюд из посадочных мест (прим.5 табл. А.2).

    Raises:
        CateringDataNeeded: если не заданы посадочные места или время работы.
        ValueError: неизвестный тип предприятия.
    """
    if not seats or seats <= 0:
        raise CateringDataNeeded(
            "Не заданы посадочные места предприятия общепита — "
            "запросите число мест и режим работы."
        )
    if catering_type not in CATERING_TYPES:
        raise ValueError(
            f"Неизвестный тип предприятия: {catering_type}. "
            f"Доступно: {', '.join(CATERING_TYPES)}"
        )
    if work_hours is None or work_hours <= 0:
        raise CateringDataNeeded(
            "Не задано время работы предприятия (T, ч) — "
            "запросите режим работы для расчёта суточного числа блюд."
        )

    params = CATERING_TYPES[catering_type]
    u_hr = 2.2 * seats * params["m"]
    u_day = u_hr * work_hours * params["y"]
    return CateringResult(
        seats=seats,
        dishes_per_hour=round(u_hr),
        dishes_per_day=round(u_day),
        catering_type=catering_type,
        work_hours=work_hours,
    )
