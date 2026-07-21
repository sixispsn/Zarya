"""Укрупнённая проверка принятых сечений В1 для стадии П.

Без аксонометрии нельзя достоверно распределить расходы по стоякам и
поквартирным ветвям или получить потери диктующего направления. Поэтому здесь
проверяется только ввод, через который однозначно проходит полный расчётный
расход В1. Для остальных характерных участков фиксируется точная геометрия,
а гидравлическая проверка переносится на стадию Р.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.calc.v1_hydraulics import velocity_mps
from app.data.pipe_catalog import pipe_size


@dataclass(frozen=True)
class V1StagePRow:
    section: str
    material: str
    dn: int
    outer_mm: float
    wall_mm: float
    inner_mm: float
    flow_lps: Optional[float]
    velocity_mps: Optional[float]
    velocity_limit_mps: Optional[float]
    velocity_ok: Optional[bool]
    basis: str


@dataclass(frozen=True)
class V1StagePResult:
    rows: list[V1StagePRow]
    design_flow_lps: float
    inputs_count: int
    checked_scope: str


def calculate_v1_stage_p(
    design_flow_lps: float,
    inputs_count: int,
    *,
    velocity_limit_mps: float = 1.5,
) -> V1StagePResult:
    """Проверить ввод и зафиксировать характерный сортамент стадии П."""
    if design_flow_lps <= 0:
        raise ValueError("Расчётный расход В1 должен быть > 0")
    if inputs_count <= 0:
        raise ValueError("Количество вводов В1 должно быть > 0")
    if velocity_limit_mps <= 0:
        raise ValueError("Предел скорости должен быть > 0")

    inlet = pipe_size("сталь ВГП обыкновенная по ГОСТ 3262-75", 50)
    riser = pipe_size("PE-X", 32)
    branch = pipe_size("PE-X", 20)
    inlet_velocity = velocity_mps(design_flow_lps, inlet.inner_mm)

    return V1StagePResult(
        design_flow_lps=round(design_flow_lps, 3),
        inputs_count=inputs_count,
        checked_scope="ввод В1",
        rows=[
            V1StagePRow(
                section=f"Каждый ввод В1 ({inputs_count} шт.)",
                material=f"сталь ВГП обыкновенная, {inlet.standard}",
                dn=inlet.dn,
                outer_mm=inlet.outer_mm,
                wall_mm=inlet.wall_mm,
                inner_mm=inlet.inner_mm,
                flow_lps=round(design_flow_lps, 3),
                velocity_mps=round(inlet_velocity, 3),
                velocity_limit_mps=velocity_limit_mps,
                velocity_ok=inlet_velocity <= velocity_limit_mps,
                basis="100% максимального секундного расхода В1",
            ),
            V1StagePRow(
                section="Характерный стояк В1",
                material="сшитый полиэтилен PE-X",
                dn=riser.dn,
                outer_mm=riser.outer_mm,
                wall_mm=riser.wall_mm,
                inner_mm=riser.inner_mm,
                flow_lps=None,
                velocity_mps=None,
                velocity_limit_mps=None,
                velocity_ok=None,
                basis="расход участка — после разработки аксонометрии на стадии Р",
            ),
            V1StagePRow(
                section="Характерная поквартирная ветвь В1",
                material="сшитый полиэтилен PE-X",
                dn=branch.dn,
                outer_mm=branch.outer_mm,
                wall_mm=branch.wall_mm,
                inner_mm=branch.inner_mm,
                flow_lps=None,
                velocity_mps=None,
                velocity_limit_mps=None,
                velocity_ok=None,
                basis="расход участка — после разработки аксонометрии на стадии Р",
            ),
        ],
    )
