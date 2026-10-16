"""Optional VU wishes and explicit accessory choices, not hydraulic methods.

One vocabulary for Studio, saved requests, PZ, drawing conditions and SO.
No option disables mandatory remote readout, changes fire controls or replaces
a physical component. Fulfilment needs a separate, verified product selection.

Manufacturer scope checks, 2026-09-30:
https://www.saures.ru/kb/article-3721/ (coverage, antennas, battery)
https://www.caleffi.com/en-int/products/dirt-separators-wall-hanging-boiler-systems
(heating dirt separators are not automatically potable-water VU products).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class MeteringOption:
    title: str
    choices: dict[str, str]
    help: str
    requirement: str


METERING_OPTIONS = {
    "technology": MeteringOption("Тип счётчика", {
        "mechanical": "Механический", "ultrasonic": "Ультразвуковой",
        "electromagnetic": "Электромагнитный",
    }, "Пожелание к подбору, не замена рассчитанного счётчика.",
        "Подтвердить конкретную модель, диапазон расходов, потери, прямые участки и условия применения. "
        "Для электромагнитного прибора проверить электропроводность воды и заполнение сечения. "
        "Текущий расчёт базового счётчика не подтверждает другое исполнение; нулевые потери не принимаются."),
    "telemetry": MeteringOption("Передача показаний", {
        "pulse": "Импульсный выход", "mbus": "M-Bus", "rs485": "RS-485",
        "nb_iot": "NB-IoT", "lorawan": "LoRaWAN",
    }, "Интерфейс счётчика, регистратор и принимающую систему согласуем при подборе.",
        "Проверить совместимость интерфейсов и протоколов, регистратор и принимающую систему. "
        "Для NB-IoT нужны покрытие и оператор; для LoRaWAN — сеть/шлюз. Связь из подвала и срок батареи не гарантированы."),
    "leak_monitoring": MeteringOption("Контроль протечки", {
        "requested": "Да — подобрать оборудование",
    }, "Комплекты на одну точку воды на полу. Только уведомление, без перекрытия воды.",
        "Определить источник данных, пороги, расписание и задержку передачи; непрерывный расход сам по себе "
        "не доказывает утечку. Автоматическое закрытие В1/В2 не задано; пожарное водоснабжение не отключается."),
    "tamper_monitoring": MeteringOption("Контроль вмешательства", {
        "requested": "Да — подобрать оборудование",
    }, "Вскрытие, магнитное воздействие — только если поддерживает прибор.",
        "Уточнить паспортные события вмешательства, датчик вскрытия/магнитного воздействия и передачу сигналов. "
        "Не считать эти функции встроенными в любой электронный счётчик."),
    "valve_feedback": MeteringOption("Обратная связь задвижек", {
        "requested": "Да — подобрать оборудование",
    }, "Открыто / закрыто / авария. Только для предусмотренной электроприводной арматуры.",
        "Проверить наличие электроприводной арматуры и сигналы «открыто», «закрыто», «авария». "
        "Процент открытия — только по паспорту привода. Опция не создаёт обводную или новую задвижку "
        "и не заменяет обязательную пожарную автоматику."),
    "assembly": MeteringOption("Исполнение узла", {
        "factory_module": "Заводской блочный модуль",
    }, "Материал труб остаётся по проекту; рама не означает автоматически нержавеющую сталь.",
        "Получить состав поставки, габариты, материалы, опоры и данные испытаний. "
        "Не суммировать модуль и входящие в него счётчик, арматуру и раму как отдельные поставки."),
    "magnetic_filter": MeteringOption("Магнитная очистка", {
        "requested": "Да — подобрать оборудование",
    }, "Только изделие для питьевой воды. Штатный фильтр не заменяется автоматически.",
        "Подтвердить пригодность для питьевой воды, давление, температуру, потери и обслуживание. "
        "Шламоотделитель/деаэратор отопления не переносится в ВУ; замену или дополнительную ступень определить отдельно."),
    "power": MeteringOption("Питание электроники", {
        "battery": "Автономное", "mains": "От сети", "backed_up": "С резервированием",
    }, "Для счётчика и передачи данных; не задаёт питание пожарного электропривода.",
        "Согласовать питание счётчика, модема/шлюза и резервирование. Автономность определяется паспортом, "
        "режимом опроса и условиями связи; питание пожарной автоматики рассматривается отдельно."),
}

from app.data.metering_extras import extra_choices

for _key, _choices in extra_choices().items():
    METERING_OPTIONS[_key].choices.update(_choices)

OPTIONS_NOTICE = (
    "Дополнительное оборудование ВУ: выбранные контроллеры и комплекты контроля протечки "
    "учтены отдельно для одной водомерной. Кандидаты и общие пожелания не включены в количество. "
    "Базовая схема и гидравлический расчёт сохранены; замена счётчика или фильтра требует "
    "паспортной проверки и пересчёта зависимых потерь/напора. Монтаж и подключение уточняются."
)


def validate_options(values) -> list[str]:
    if not isinstance(values, dict):
        return ["metering_detail.enhancements: требуется словарь опций"]
    return [f"metering_detail.enhancements.{key}: неизвестная опция или значение"
            for key, value in values.items()
            if key not in METERING_OPTIONS or not isinstance(value, str)
            or value not in METERING_OPTIONS[key].choices]


def option_requests(detail) -> list[dict]:
    values = detail.enhancements
    if errors := validate_options(values):
        raise ValueError("; ".join(errors))
    return [dict(key=key, title=option.title, value=values[key],
                 label=option.choices[values[key]], requirement=option.requirement)
            for key, option in METERING_OPTIONS.items() if key in values]
