"""Explicit extension: T3 draw-off path, SP 30 10.9/10.11 (not legacy).

Formula (15) is shared with the existing hydraulic kernel by the explicit
cross-reference in 10.9, including its 10 C reference conditions. This is not
a circulation-ring calculation and does not size a T4 pump or balancing valve.
No extrapolation/interpolation of appendix G is silently introduced.
"""

from dataclasses import asdict, dataclass, field
import math

from app.calc.v1_hydraulics import V1SectionInput, calculate_v1_hydraulics


KCIR_TABLE = ((1.2, .57), (1.3, .48), (1.4, .43), (1.5, .40), (1.6, .38),
              (1.7, .36), (1.8, .33), (1.9, .25), (2.0, .12), (2.1, 0.0))
FLOW_MODES = {
    "unknown": "Учёт циркуляции не задан",
    "none": "Система без циркуляции",
    "terminal": "Участок вне поправки по п. 10.11",
    "main": "Начальный участок — учесть циркуляцию",
    "corrected": "Расход уже скорректирован отдельным расчётом",
}


@dataclass(frozen=True)
class T3SectionInput:
    section_id: str
    length_m: float
    inner_diameter_mm: float
    roughness_mm: float
    flow_lps: float
    flow_mode: str = "unknown"
    circulation_flow_lps: float | None = None
    basis: str = ""
    velocity_limit_mps: float | None = None
    material: str = ""


def validate_t3_section(s: T3SectionInput) -> None:
    for name in ("section_id", "basis", "material"):
        value = getattr(s, name)
        if not isinstance(value, str) or len(value) > 240:
            raise ValueError(f"Т3: неверное поле {name}")
    if not s.section_id.strip():
        raise ValueError("Т3: нужно обозначение участка")
    if not isinstance(s.flow_mode, str) or s.flow_mode not in FLOW_MODES:
        raise ValueError(f"{s.section_id}: неизвестный режим учёта циркуляции")
    for name in ("length_m", "inner_diameter_mm", "roughness_mm", "flow_lps",
                 "circulation_flow_lps", "velocity_limit_mps"):
        value = getattr(s, name)
        if value is None and name in {"circulation_flow_lps", "velocity_limit_mps"}:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0
                or (value == 0 and name != "roughness_mm")):
            raise ValueError(f"{s.section_id}: недопустимое значение {name}")
    if s.circulation_flow_lps is not None and s.flow_mode != "main":
        raise ValueError(f"{s.section_id}: qcir задают только для начального участка")


def circulation_factor(ratio: float) -> float:
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("Недопустимое отношение qh/qcir")
    if ratio >= 2.1:
        return 0.0
    for point, factor in KCIR_TABLE[:-1]:
        if math.isclose(ratio, point, rel_tol=0, abs_tol=1e-10):
            return factor
    raise ValueError(
        "Для этого qh/qcir нет прямого значения приложения Г. "
        "Нужен отдельно обоснованный скорректированный расход; "
        "интерполяция и экстраполяция автоматически не выполняются."
    )


@dataclass(frozen=True)
class T3HydraulicResult:
    sections: list[dict] = field(default_factory=list)
    total_loss_m: float | None = None
    missing: list[str] = field(default_factory=list)
    all_velocities_ok: bool = False
    method: str = "СП 30.13330.2020, пп. 10.9, 10.11; формулы (14), (15), (17)"
    reference_temperature_c: float = 10.0
    scope: str = "Заданный путь к горячему прибору в режиме водоразбора; не расчёт колец Т4"


def calculate_t3_hydraulics(sections: list[T3SectionInput]) -> T3HydraulicResult:
    if not sections:
        raise ValueError("Путь Т3 не содержит участков")
    ids = set()
    rows, missing = [], []
    for s in sections:
        validate_t3_section(s)
        if s.section_id.strip() in ids:
            raise ValueError("Обозначения участков Т3 повторяются")
        ids.add(s.section_id.strip())
        reason = None
        factor = 0.0
        if s.flow_mode == "unknown":
            reason = "укажите применимость поправки на циркуляцию по п. 10.11"
        elif s.flow_mode == "main":
            if s.circulation_flow_lps is None:
                reason = "нужен qcir участка из расчёта по п. 10.10, без условного распределения"
            else:
                try:
                    factor = circulation_factor(s.flow_lps / s.circulation_flow_lps)
                except ValueError as exc:
                    reason = str(exc)
        elif s.flow_mode == "corrected" and not s.basis.strip():
            reason = "укажите источник скорректированного расхода"
        if s.velocity_limit_mps is None:
            reason = (reason + "; " if reason else "") + "нужен предел скорости по п. 8.26/приложению И"
        if reason:
            missing.append(f"{s.section_id}: {reason}")
            rows.append(dict(section_id=s.section_id, missing=reason))
            continue
        corrected = s.flow_lps * (1.0 + factor)
        # T3 domestic service is not made a fire network by a combined V1 inlet.
        result = calculate_v1_hydraulics([V1SectionInput(
            section_id=s.section_id, length_m=s.length_m,
            inner_diameter_mm=s.inner_diameter_mm, roughness_mm=s.roughness_mm,
            flow_lps=corrected, material=s.material,
            velocity_limit_mps=s.velocity_limit_mps,
        )], network_kind="domestic", water_temperature_c=10.0).sections[0]
        rows.append(dict(asdict(result), original_flow_lps=s.flow_lps,
                         roughness_mm=s.roughness_mm,
                         circulation_flow_lps=s.circulation_flow_lps,
                         circulation_factor=factor, flow_mode=s.flow_mode,
                         basis=s.basis, missing=None))
    return T3HydraulicResult(
        sections=rows, missing=missing,
        total_loss_m=None if missing else round(sum(row["total_loss_m"] for row in rows), 3),
        all_velocities_ok=not missing and all(row["velocity_ok"] for row in rows),
    )
