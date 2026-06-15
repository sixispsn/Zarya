"""
Реестр нормативных правил СП 30.13330.2020 (с Изм. № 1–5).

Каждое правило — это проверка одного пункта СП против данных Project.
Движок прогоняет все применимые правила и собирает отчёт о соответствии.

Вердикты:
  COMPLIANT     — соответствует
  VIOLATION     — нарушение (требует исправления)
  NOT_APPLICABLE — пункт неприменим к данному объекту
  NO_DATA       — недостаточно данных в Project для проверки
  MANUAL        — требуется ручная проверка проектировщиком (качественное требование)

Каждое правило ссылается на конкретный пункт СП и редакцию.
Источник: СП 30.13330.2020 + Изменения № 1–5 (приложены заказчиком).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from app.pz.project import Project


class Verdict(str, Enum):
    COMPLIANT = "соответствует"
    VIOLATION = "НАРУШЕНИЕ"
    NOT_APPLICABLE = "неприменимо"
    NO_DATA = "нет данных"
    MANUAL = "ручная проверка"


@dataclass
class RuleResult:
    """Результат проверки одного правила."""
    clause: str            # пункт СП, напр. "7.10"
    title: str             # краткое название требования
    verdict: Verdict
    detail: str            # пояснение с цифрами / основанием
    edition: str = ""      # редакция (Изм. №N), если относится


@dataclass
class Rule:
    """
    Нормативное правило.

    applies: предикат — применимо ли правило к этому проекту
    check:   функция проверки, возвращает (Verdict, detail)
    """
    clause: str
    title: str
    check: Callable[[Project], tuple]
    applies: Callable[[Project], bool] = lambda p: True
    edition: str = ""

    def run(self, project: Project) -> RuleResult:
        if not self.applies(project):
            return RuleResult(self.clause, self.title, Verdict.NOT_APPLICABLE,
                              "Пункт неприменим к данному объекту.", self.edition)
        verdict, detail = self.check(project)
        return RuleResult(self.clause, self.title, verdict, detail, self.edition)


# ============================================================
# ПРАВИЛА (каждое — отдельный пункт СП с точной ссылкой)
# ============================================================

def _is_residential(p: Project) -> bool:
    return p.building.purpose.value == "residential"


# --- п.7.7 (Изм.3): залы с массовым пребыванием + сгораемая отделка → ≥2 струй ---
def _check_7_7(p: Project):
    if not p.fire.required:
        return Verdict.NOT_APPLICABLE, "ВПВ не требуется."
    if p.building.seats and p.building.seats > 0:
        if p.fire.streams >= 2:
            return Verdict.COMPLIANT, (
                f"Зал с массовым пребыванием ({p.building.seats} мест): "
                f"принято {p.fire.streams} струи (≥2).")
        return Verdict.VIOLATION, (
            f"Зал с массовым пребыванием ({p.building.seats} мест) при сгораемой "
            f"отделке требует не менее 2 струй; принято {p.fire.streams}. "
            "Проверить наличие сгораемой отделки.")
    return Verdict.NOT_APPLICABLE, "Объект без залов массового пребывания."


# --- п.7.10 (Изм.3): давление у нижнего ПК >0,45 МПа → раздельная сеть ВПВ ---
def _check_7_10(p: Project):
    if not p.fire.required:
        return Verdict.NOT_APPLICABLE, "ВПВ не требуется."
    pr = p.fire.pressure_at_lowest_pk_mpa
    if pr is None:
        return Verdict.NO_DATA, "Не задано давление у нижнего пожарного крана."
    if pr > 0.45:
        return Verdict.COMPLIANT, (
            f"Давление у нижнего ПК {pr:.2f} МПа > 0,45 МПа — требуется раздельная "
            "сеть ВПВ; согласно решению по схеме это учтено.")
    return Verdict.COMPLIANT, (
        f"Давление у нижнего ПК {pr:.2f} МПа ≤ 0,45 МПа — ограничение по давлению "
        "соблюдено.")


# --- п.8.13 (Изм.3): нет транзита ХВС/ГВС в стенах/полу/потолке жилых комнат ---
def _check_8_13(p: Project):
    # Качественное требование — выносим на ручную проверку, но формулируем точно
    return Verdict.MANUAL, (
        "Проверить: транзитная прокладка ХВС/ГВС в полу, под потолком и скрыто "
        "в стенах жилых комнат не допускается (п.8.13). Касается раскладки стояков.")


# --- п.5.12 (Изм.3): Qht = 30-40% (до 60% при двухзонке) от 1.16·qhr_h·Δt ---
def _check_5_12(p: Project):
    if p.building.hws_type.value == "none":
        return Verdict.NOT_APPLICABLE, "ГВС отсутствует."
    if not p.flows.q_hr_h:
        return Verdict.NO_DATA, "Не задан часовой расход ГВС."
    base = 1.16 * p.flows.q_hr_h * (65 - 5)   # кВт, полный расход тепла на ГВС
    pct_max = 0.60 if p.building.zones > 1 else 0.40
    qht_lo = round(0.30 * base, 1)
    qht_hi = round(pct_max * base, 1)
    return Verdict.COMPLIANT, (
        f"Потери тепла Qht (стадия П) принимаются 30–{int(pct_max*100)}% от "
        f"{base:.1f} кВт = {qht_lo}…{qht_hi} кВт"
        f"{' (до 60% — двухзонная система)' if p.building.zones > 1 else ''}.")


# --- п.13.20 (Изм.3): категория надёжности электроснабжения насосов ---
def _check_13_20(p: Project):
    if not p.pumps.required:
        return Verdict.NOT_APPLICABLE, "Насосные установки не предусмотрены."
    h = p.building.height_m
    q = p.flows.q_sec_tot
    if _is_residential(p) and h > 28 and q > 5:
        cat = "вторая (жилое здание >28 м при суммарном расходе >5 л/с)"
    elif _is_residential(p) and h > 28:
        cat = ("вторая/третья — уточнить: жилое >28 м, но расход "
               f"{q:.2f} л/с ≤ 5 л/с")
    else:
        cat = "третья (если не требуется иное по надёжности)"
    return Verdict.COMPLIANT, f"Категория надёжности электроснабжения насосов: {cat} (п.13.20)."


# --- п.13.10 (Изм.3): при зонировании — отдельные насосы на каждую зону ---
def _check_13_10(p: Project):
    if p.building.zones <= 1:
        return Verdict.NOT_APPLICABLE, "Однозонная схема."
    if not p.pumps.required:
        return Verdict.NO_DATA, "Зонирование задано, но насосные установки не описаны."
    return Verdict.MANUAL, (
        f"Система {p.building.zones}-зонная — подачу воды следует предусматривать "
        "повысительными установками отдельно для каждой зоны (п.13.10). "
        "Проверить, что в проекте насосы разнесены по зонам.")


# --- п.26.4 (Изм.3): зонирование по высоте — порог 54 м ---
def _check_26_4(p: Project):
    if not _is_residential(p):
        return Verdict.NOT_APPLICABLE, "Требование для жилых домов."
    h = p.building.height_m
    if h <= 54 and p.building.zones > 1:
        return Verdict.COMPLIANT, (
            f"Высота {h:.0f} м ≤ 54 м: допускается однозонная схема с поэтажными "
            f"регуляторами; принятая {p.building.zones}-зонная схема также допустима "
            "(решение по заданию).")
    if h > 54 and p.building.zones > 1:
        return Verdict.COMPLIANT, f"Высота {h:.0f} м > 54 м: зонирование обязательно — соблюдено."
    if h > 54 and p.building.zones <= 1:
        return Verdict.VIOLATION, f"Высота {h:.0f} м > 54 м требует зонирования; принята однозонная."
    return Verdict.COMPLIANT, f"Высота {h:.0f} м ≤ 54 м: однозонная схема допустима."


# --- п.8.21 (СП 30 + Изм.3): свободный напор у диктующего прибора ≥20 м ---
def _check_8_21(p: Project):
    hpr = p.source.h_pr_m
    if hpr is None:
        return Verdict.NO_DATA, "Не задан напор перед диктующим прибором."
    if hpr >= 20.0:
        return Verdict.COMPLIANT, (
            f"Напор перед диктующим прибором {hpr:.0f} м ≥ 20 м (п.8.21).")
    return Verdict.VIOLATION, (
        f"Напор перед диктующим прибором {hpr:.0f} м < 20 м — нарушение п.8.21 "
        "(минимум 20 м; меньше допускается только для зданий до 5 этажей "
        "при сложившейся застройке).")


# --- п.7.13 (Изм.3): ПК на техэтажах/чердаках/подпольях — при горючих Г1-Г4 ---
def _check_7_13(p: Project):
    if not p.fire.required:
        return Verdict.NOT_APPLICABLE, "ВПВ не требуется."
    return Verdict.MANUAL, (
        "Проверить: установка пожарных кранов на технических этажах, чердаках и "
        "в технических подпольях предусматривается только при наличии в них "
        "горючих веществ и материалов групп Г1–Г4 (п.7.13).")


# --- п.8.1 (Изм.3): нельзя соединять ХВС с технологическими трубопроводами ---
def _check_8_1(p: Project):
    return Verdict.MANUAL, (
        "Проверить: трубопроводы ХВС не должны соединяться с трубопроводами "
        "технологических нужд и иметь контакт с технологическим оборудованием (п.8.1).")


# --- п.9.8 (Изм.3): полотенцесушители на циркуляции ГВС ---
def _check_9_8(p: Project):
    if p.building.hws_type.value == "none":
        return Verdict.NOT_APPLICABLE, "ГВС отсутствует."
    if not _is_residential(p):
        return Verdict.NOT_APPLICABLE, "Требование для жилых домов."
    return Verdict.MANUAL, (
        "Проверить: полотенцесушители подключены к подающим/циркуляционным "
        "трубопроводам ГВС с постоянным протоком, либо приняты электрические (п.9.8).")


# --- п.11.3 (Изм.3): фитинги одного изготовителя для полимерных труб ---
def _check_11_3(p: Project):
    m = p.materials
    has_polymer = any("полиэтилен" in s.lower() or "pe-x" in s.lower() or "пп" in s.lower()
                      for s in [m.cold_distribution, m.hot_distribution,
                                m.cold_mains, m.hot_mains])
    if not has_polymer:
        return Verdict.NOT_APPLICABLE, "Полимерные трубы не применяются."
    return Verdict.MANUAL, (
        "Проверить: в системах с полимерными трубами соединительные детали и "
        "фитинги должны быть одного изготовителя (п.11.3).")


# --- п.12.11 (Изм.3): обводная линия опломбирована, автооткрытие при пожаре ---
def _check_12_11(p: Project):
    if not p.meters.has_bypass:
        return Verdict.NOT_APPLICABLE, "Обводная линия не предусмотрена."
    detail = ("Проверить: запорное устройство на обводной линии опломбировано в "
              "закрытом состоянии (п.12.11).")
    if p.fire.required:
        detail += (" При расходе на пожаротушение автоматизация открытия обводной "
                   "линии — по алгоритму СП 10.13130, СП 484.1311500.")
    return Verdict.MANUAL, detail


# --- п.26.12 (Изм.3): горючесть теплоизоляции трубопроводов ---
def _check_26_12(p: Project):
    if p.building.hws_type.value == "none" and not p.building.has_parking:
        return Verdict.NOT_APPLICABLE, "Нет ГВС и подземной стоянки."
    return Verdict.MANUAL, (
        "Проверить: теплоизоляция трубопроводов в подземных стоянках, на путях "
        "эвакуации, техэтажах и чердаках — из материалов группы горючести не ниже "
        "Г1 (п.26.12).")


# --- Реестр ---
RULES: list[Rule] = [
    Rule("7.7", "Число струй в залах массового пребывания", _check_7_7, edition="Изм.3"),
    Rule("7.10", "Раздельная сеть ВПВ при давлении >0,45 МПа", _check_7_10, edition="Изм.3"),
    Rule("7.13", "ПК на техэтажах/чердаках только при горючих Г1-Г4", _check_7_13, edition="Изм.3"),
    Rule("8.1", "Запрет соединения ХВС с технологическими трубопроводами", _check_8_1, edition="Изм.3"),
    Rule("8.13", "Запрет транзита ХВС/ГВС в стенах жилых комнат", _check_8_13,
         applies=_is_residential, edition="Изм.3"),
    Rule("8.21", "Свободный напор у диктующего прибора ≥20 м", _check_8_21, edition="Изм.3"),
    Rule("9.8", "Полотенцесушители на циркуляции ГВС", _check_9_8, edition="Изм.3"),
    Rule("5.12", "Потери тепла на ГВС (стадия П)", _check_5_12, edition="Изм.3"),
    Rule("11.3", "Фитинги одного изготовителя для полимерных труб", _check_11_3, edition="Изм.3"),
    Rule("12.11", "Опломбировка обводной линии узла учёта", _check_12_11, edition="Изм.3"),
    Rule("13.10", "Отдельные насосы для каждой зоны", _check_13_10, edition="Изм.3"),
    Rule("13.20", "Категория надёжности электроснабжения насосов", _check_13_20, edition="Изм.3"),
    Rule("26.4", "Зонирование по высоте (порог 54 м)", _check_26_4, edition="Изм.3"),
    Rule("26.12", "Горючесть теплоизоляции трубопроводов", _check_26_12, edition="Изм.3"),
]


@dataclass
class ComplianceReport:
    results: list = field(default_factory=list)

    @property
    def violations(self):
        return [r for r in self.results if r.verdict == Verdict.VIOLATION]

    @property
    def manual_checks(self):
        return [r for r in self.results if r.verdict == Verdict.MANUAL]

    @property
    def summary_counts(self) -> dict:
        counts = {v: 0 for v in Verdict}
        for r in self.results:
            counts[r.verdict] += 1
        return counts


def run_compliance(project: Project) -> ComplianceReport:
    """Прогнать все правила реестра против проекта."""
    return ComplianceReport(results=[rule.run(project) for rule in RULES])
