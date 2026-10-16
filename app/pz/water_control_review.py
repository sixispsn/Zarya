"""Explain the current design-head balance; do not simulate a VFD controller.

All numbers come from the existing cold/hot head paths. Their common source
reference is not the physical pressure-transmitter location. No setpoint,
valve size, pressure zone or equipment quantity is inferred here.
"""
from dataclasses import dataclass
from math import isfinite

from app.pz.pump_validation import check_project_booster
from app.pz.rules import calc_head_paths, project_governing_head


@dataclass(frozen=True)
class DutyPathBalance:
    code: str
    label: str
    required_head_m: float
    residual_head_m: float
    excess_head_m: float


@dataclass(frozen=True)
class WaterControlReview:
    rows: tuple[DutyPathBalance, ...] = ()
    reference_head_m: float | None = None
    governing_code: str = ""
    issues: tuple[str, ...] = ()


def review_water_control(project):
    """Invert the accepted head balance at its design flow, read-only.

This is a target condition (Hsource=Hrequired), not the actual pump operating
point. It neither treats the name of a station as a control scheme nor uses
the full-speed Q=0 curve to certify normal variable-speed operation.
    """
    if project.source.network_kind != "domestic" or project.v1_network is not None or project.building.zones != 1:
        return WaterControlReview(issues=("Общий баланс не заменяет расчёт регулируемой узловой/зонной сети.",))
    paths = project.head_paths
    if paths is None or not paths.complete:
        return WaterControlReview(issues=("Для баланса регулирования нужны полные текущие пути В1/Т3.",))
    current = calc_head_paths(project.source, project.meters,
        hws_type=project.building.hws_type.value,
        apartment_meter_required=project.meters.has_apartment_meters)
    if current != paths:
        return WaterControlReview(issues=("Пути изменились; сначала пересчитать напор и подбор насоса.",))
    head = project_governing_head(project)
    if head.pump_needed is not True:
        return WaterControlReview(issues=("Режим повысительной установки этим балансом не определяется.",))
    if check_project_booster(project, head)[0] != "verified":
        return WaterControlReview(issues=("Насос не подтверждён по текущей расчётной паре Q/H.",))
    if not all(isfinite(x) for path in paths.paths for x in
               (path.head.h_required_m, path.head.h_pr_m)):
        return WaterControlReview(issues=("В балансе напора есть некорректные значения.",))
    reference = head.h_required_m
    rows = tuple(DutyPathBalance(path.code, path.label, path.head.h_required_m,
        path.head.h_pr_m + reference-path.head.h_required_m,
        reference-path.head.h_required_m) for path in paths.paths)
    return WaterControlReview(rows, reference, paths.governing.code)
