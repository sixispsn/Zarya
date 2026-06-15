"""
Нормативные решения для пояснительной записки (ВК).

Чистые функции: на вход — части модели Project, на выходе — структурированное
решение с текстом обоснования и ссылкой на пункт норматива. Логика держится
здесь (не в шаблоне и не в сборщике PDF), чтобы её можно было покрыть тестами
и переиспользовать в API.

Источники:
  СП 30.13330.2020 (ред. Изм. №3 от 18.12.2023)
  СП 10.13130.2020
  ГОСТ Р 21.619-2023 (оформление)
"""
from dataclasses import dataclass
from typing import List, Optional

from app.pz.project import FireSystem, FlowsData, PipeMaterials, WaterSource

# Порог рабочего давления, выше которого хоз-питьевую и пожарную сети разделяют
# (СП 10.13130.2020, пп. 6.1.1–6.1.2; СП 30.13330.2020, 5.4.1)
PRESSURE_LIMIT_MPA = 0.45


@dataclass
class FireNetworkDecision:
    """Решение по схеме внутреннего противопожарного водопровода (В2)."""
    combined: bool                 # True — объединён с В1, False — раздельная сеть
    reasons: List[str]             # основания для раздельной схемы (пустой при combined)

    @property
    def summary(self) -> str:
        """Готовая фраза для подпункта в)."""
        if self.combined:
            return (
                "Система внутреннего противопожарного водопровода (В2) принята "
                "объединённой с хозяйственно-питьевым водопроводом (В1) — допускается "
                "при совпадении требований к качеству воды и рабочему давлению "
                "(СП 30.13330.2020, 6.1.2; СП 10.13130.2020, 4.2). Застойные "
                "(без циркуляции) участки в системе отсутствуют."
            )
        reasons_txt = "; ".join(self.reasons)
        return (
            "Система внутреннего противопожарного водопровода (В2) принята "
            f"самостоятельной (раздельной) из стальных труб. Основание: {reasons_txt}."
        )


def decide_fire_network(
    fire: FireSystem,
    materials: PipeMaterials,
) -> Optional[FireNetworkDecision]:
    """
    Объединённая или раздельная сеть В2.

    Возвращает None, если ВПВ не требуется.
    """
    if not fire.required:
        return None

    reasons: List[str] = []

    if (
        fire.pressure_at_lowest_pk_mpa is not None
        and fire.pressure_at_lowest_pk_mpa > PRESSURE_LIMIT_MPA
    ):
        reasons.append(
            f"гидростатическое давление у наиболее низко расположенного "
            f"пожарного крана ({fire.pressure_at_lowest_pk_mpa:.2f} МПа) превышает "
            f"{PRESSURE_LIMIT_MPA} МПа (СП 10.13130.2020, 6.1.1–6.1.2)"
        )

    if materials.cold_is_plastic_uncertified:
        reasons.append(
            "хозяйственно-питьевая сеть выполнена из пластиковых труб без "
            "пожарного сертификата (СП 30.13330.2020, 7.1.3)"
        )

    if fire.has_aupt:
        reasons.append(
            "пожарные краны запитываются от трубопроводов установки "
            "автоматического пожаротушения (СП 10.13130.2020, 12.1)"
        )

    return FireNetworkDecision(combined=not reasons, reasons=reasons)


@dataclass
class HeadCalc:
    """Расчёт требуемого напора и решение по необходимости насосов."""
    h_required_m: Optional[float]   # требуемый напор Hтр, м (None — нет данных)
    h_guaranteed_m: Optional[float] # гарантированный напор, м
    components: List[tuple]         # [(название, значение_м), ...] для таблицы
    pump_needed: Optional[bool]     # True/False/None (None — недостаточно данных)

    @property
    def deficit_m(self) -> Optional[float]:
        if self.h_required_m is None or self.h_guaranteed_m is None:
            return None
        return round(self.h_required_m - self.h_guaranteed_m, 2)


def calc_required_head(source: WaterSource) -> HeadCalc:
    """
    Hтр = Hgeom + ∑Hil + Hпр + ∑Hвод + Hтепл + Hlввод
    — формула (14) п.8.27 СП 30.13330.2020.

    Hпр (напор перед прибором, п.8.21) по умолчанию 20 м — минимум по СП.
    Hтепл (теплообменник) ≈ 3 м задаётся для централизованного ГВС.
    Складывает заданные составляющие; обязательные Hпр и Hтепл всегда учитываются,
    даже если остальные не заданы (тогда расчёт неполный — отметить в ПЗ).
    Решение о насосах — при известных Hтр и гарантированном напоре.
    """
    parts = [
        ("Hgeom — геометрическая высота диктующего прибора", source.h_geom_m),
        ("∑Hil — потери напора по диктующему направлению", source.h_il_m),
        ("Hпр — напор перед диктующим прибором (п.8.21)", source.h_pr_m),
        ("∑Hвод — потери в узлах учёта (п.12.15)", source.h_vod_m),
        ("Hтепл — потери в теплообменнике/ИТП", source.h_tepl_m or None),
        ("Hlввод — потери на вводе(ах)", source.h_vvod_m),
    ]
    components = [(name, val) for name, val in parts if val is not None]
    # Hтр считаем, только если заданы основные геометрия и потери
    has_core = source.h_geom_m is not None and source.h_il_m is not None
    h_req = round(sum(val for _, val in components), 2) if has_core else None

    pump_needed: Optional[bool] = None
    if h_req is not None and source.guaranteed_head_m is not None:
        pump_needed = h_req > source.guaranteed_head_m

    return HeadCalc(
        h_required_m=h_req,
        h_guaranteed_m=source.guaranteed_head_m,
        components=components,
        pump_needed=pump_needed,
    )


@dataclass
class TuCheck:
    """Результат одной проверки соответствия расчёта лимиту ТУ."""
    label: str           # что проверяем
    calc: float          # расчётное значение
    limit: float         # лимит ТУ
    unit: str
    ok: bool             # проходит ли (calc <= limit)

    @property
    def margin(self) -> float:
        """Запас (если ok) или превышение (если не ok), той же размерности."""
        return round(self.limit - self.calc, 3)


@dataclass
class TuComplianceResult:
    """Сводка проверки соответствия расчётных расходов лимитам ТУ."""
    checks: list          # list[TuCheck]
    all_ok: bool

    @property
    def summary(self) -> str:
        if not self.checks:
            return ("Лимиты присоединения в техн. условиях не заданы — "
                    "проверку соответствия выполнить после получения ТУ.")
        lines = []
        for c in self.checks:
            verb = "не превышает" if c.ok else "ПРЕВЫШАЕТ"
            lines.append(
                f"{c.label}: расчётное {c.calc:.2f} {c.unit} {verb} "
                f"лимит присоединения по ТУ {c.limit:.2f} {c.unit}"
                + (f" (запас {c.margin:.2f} {c.unit})" if c.ok
                   else f" (превышение {-c.margin:.2f} {c.unit} — требуется корректировка)")
            )
        return ". ".join(lines) + "."


def check_tu_limits(flows: FlowsData, source: WaterSource) -> TuComplianceResult:
    """
    Проверка: расчётные расходы (наш расчёт по СП 30) не превышают лимиты
    присоединения (дебит), выданные ресурсоснабжающей организацией в ТУ.

    Наш расчёт — главный; ТУ задаёт потолок. Превышение означает, что
    решение не проходит и требует пересмотра либо других ТУ.
    """
    checks: list = []

    if source.tu_limit_q_day is not None:
        ok = flows.q_day_tot <= source.tu_limit_q_day
        checks.append(TuCheck(
            "Суточный расход ХВС", flows.q_day_tot, source.tu_limit_q_day, "м³/сут", ok))

    if source.tu_limit_q_sec is not None:
        ok = flows.q_sec_tot <= source.tu_limit_q_sec
        checks.append(TuCheck(
            "Секундный расход ХВС", flows.q_sec_tot, source.tu_limit_q_sec, "л/с", ok))

    all_ok = all(c.ok for c in checks) if checks else True
    return TuComplianceResult(checks=checks, all_ok=all_ok)
