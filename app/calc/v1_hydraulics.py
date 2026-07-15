"""Гидравлический расчёт диктующего направления В1.

СП 30.13330.2020:
- п. 8.23: расчёт по максимальному секундному расходу;
- п. 8.26: ограничение скорости;
- п. 8.28, формула (15): H_il = i*l*(1+k_l).

Удельные потери i определяются по Darcy-Weisbach с учётом абсолютной
шероховатости трубы. Для турбулентного режима применяется явная формула
Swamee-Jain; для ламинарного - 64/Re.
"""
from dataclasses import dataclass, field
import math
from typing import Literal, Optional


SectionRole = Literal["internal", "input"]


@dataclass(frozen=True)
class V1SectionInput:
    section_id: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    roughness_mm: float
    role: SectionRole = "internal"
    local_loss_factor: Optional[float] = None
    velocity_limit_mps: float = 1.5
    material: str = ""


@dataclass(frozen=True)
class V1SectionResult:
    section_id: str
    role: SectionRole
    material: str
    length_m: float
    inner_diameter_mm: float
    flow_lps: float
    velocity_mps: float
    velocity_limit_mps: float
    velocity_ok: bool
    reynolds: float
    friction_factor: float
    specific_loss_m_per_m: float
    linear_loss_m: float
    local_loss_factor: float
    total_loss_m: float


@dataclass(frozen=True)
class V1HydraulicResult:
    sections: list[V1SectionResult] = field(default_factory=list)
    internal_loss_m: float = 0.0
    input_loss_m: float = 0.0
    total_loss_m: float = 0.0
    max_velocity_mps: float = 0.0
    all_velocities_ok: bool = True


def _friction_factor(reynolds: float, roughness_m: float, diameter_m: float) -> float:
    if reynolds <= 0:
        return 0.0
    if reynolds < 2300:
        return 64.0 / reynolds
    # Swamee-Jain, инженерная явная аппроксимация Colebrook-White.
    term = roughness_m / (3.7 * diameter_m) + 5.74 / (reynolds ** 0.9)
    return 0.25 / (math.log10(term) ** 2)


def calculate_v1_hydraulics(
    sections: list[V1SectionInput],
    *,
    water_temperature_c: float = 10.0,
) -> V1HydraulicResult:
    """Рассчитать потери по последовательным участкам диктующего направления."""
    if not sections:
        raise ValueError("Диктующее направление В1 не содержит участков")
    if not (0.0 < water_temperature_c <= 40.0):
        raise ValueError("Температура воды для расчёта В1 должна быть в диапазоне 0-40 °C")

    # Кинематическая вязкость при 10 °C согласно расчётной постановке СП 30.
    # Для других температур - инженерная аппроксимация в рабочем диапазоне.
    nu = 1.307e-6 * math.exp(-0.0337 * (water_temperature_c - 10.0))
    out: list[V1SectionResult] = []

    for s in sections:
        if not s.section_id.strip():
            raise ValueError("У участка В1 отсутствует обозначение")
        if s.length_m <= 0 or s.inner_diameter_mm <= 0 or s.flow_lps <= 0:
            raise ValueError(f"Участок {s.section_id}: L, dвн и q должны быть > 0")
        if s.roughness_mm < 0:
            raise ValueError(f"Участок {s.section_id}: шероховатость не может быть отрицательной")
        if s.velocity_limit_mps <= 0:
            raise ValueError(f"Участок {s.section_id}: предел скорости должен быть > 0")
        if s.role not in ("internal", "input"):
            raise ValueError(f"Участок {s.section_id}: неизвестная роль {s.role}")

        d = s.inner_diameter_mm / 1000.0
        q = s.flow_lps / 1000.0
        area = math.pi * d * d / 4.0
        velocity = q / area
        reynolds = velocity * d / nu
        friction = _friction_factor(reynolds, s.roughness_mm / 1000.0, d)
        specific = friction * velocity * velocity / (2.0 * 9.80665 * d)
        linear = specific * s.length_m
        # Для хозяйственно-питьевой сети жилых и общественных зданий
        # k_l=0,3 по п. 8.28. Иное значение задаётся участку явно.
        local_factor = 0.3 if s.local_loss_factor is None else s.local_loss_factor
        if local_factor < 0:
            raise ValueError(f"Участок {s.section_id}: k_l не может быть отрицательным")
        total = linear * (1.0 + local_factor)
        out.append(V1SectionResult(
            section_id=s.section_id,
            role=s.role,
            material=s.material,
            length_m=round(s.length_m, 2),
            inner_diameter_mm=round(s.inner_diameter_mm, 2),
            flow_lps=round(s.flow_lps, 3),
            velocity_mps=round(velocity, 3),
            velocity_limit_mps=round(s.velocity_limit_mps, 2),
            velocity_ok=velocity <= s.velocity_limit_mps,
            reynolds=round(reynolds),
            friction_factor=round(friction, 5),
            specific_loss_m_per_m=round(specific, 5),
            linear_loss_m=round(linear, 3),
            local_loss_factor=round(local_factor, 2),
            total_loss_m=round(total, 3),
        ))

    internal = sum(x.total_loss_m for x in out if x.role == "internal")
    input_loss = sum(x.total_loss_m for x in out if x.role == "input")
    return V1HydraulicResult(
        sections=out,
        internal_loss_m=round(internal, 3),
        input_loss_m=round(input_loss, 3),
        total_loss_m=round(internal + input_loss, 3),
        max_velocity_mps=max(x.velocity_mps for x in out),
        all_velocities_ok=all(x.velocity_ok for x in out),
    )
