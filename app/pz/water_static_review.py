"""Read-only pressure screen when only a characteristic V1 path is available.

Uses the existing hydrostatic balance, not a reconstructed building network.
Floor planes are NOT fixtures. Q=0 on a published pump curve is an unregulated
scenario, never a claimed controller setpoint or a completed pressure audit.
"""
from dataclasses import dataclass
import math

from app.calc.pump_curve import interpolate_head
from app.calc.v1_hydraulics import static_head_at_elevation
from app.pz.pump_validation import check_project_booster
from app.pz.rules import calc_head_paths, project_governing_head


@dataclass(frozen=True)
class StaticReference:
    label: str
    kind: str
    elevation_m: float
    head_m: float
    limit_m: float | None = None

    @property
    def exceeds(self):
        return None if self.limit_m is None else self.head_m > self.limit_m


@dataclass(frozen=True)
class WaterStaticReview:
    source_head_m: float | None = None
    source_elevation_m: float | None = None
    external_max_m: float | None = None
    pump_zero_head_m: float | None = None
    pump_model: str = ""
    rows: tuple[StaticReference, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def has_exceedance(self):
        return any(row.exceeds is True for row in self.rows)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def review_water_static_pressure(project):
    """Screen the explicitly unregulated, single-zone characteristic path.

    Do not assign this pressure to a multi-zone or unbound network. Do not
    extrapolate a pump curve to Q=0, borrow Hgar as Hmax, or invent floor levels.
    No regulation is selected and no project/calculation state is modified.
    """
    source = project.source
    issues = []
    if source.network_kind != "domestic":
        return WaterStaticReview(issues=(
            "Этот предварительный просмотр предназначен только для хозяйственно-питьевой сети В1.",))
    if project.v1_network is not None or project.building.zones != 1:
        return WaterStaticReview(issues=(
            "Для зонной/узловой сети нужен её поузловой расчёт: общий напор не распространяется на все этажи.",))
    if not _finite(source.maximum_head_m) or source.maximum_head_m < 0:
        issues.append("Не задан корректный максимальный напор наружной сети; Hгар его не заменяет.")
    elif (_finite(source.guaranteed_head_m)
          and source.maximum_head_m < source.guaranteed_head_m):
        issues.append("Максимальный напор наружной сети меньше гарантированного; уточнить исходные.")
    if not _finite(source.elev_header_m):
        issues.append("Не задана отметка, к которой отнесён напор источника.")
    if issues:
        return WaterStaticReview(issues=tuple(issues))
    pump_zero = None
    if project.head_paths is not None:
        current_paths = calc_head_paths(source, project.meters,
            hws_type=project.building.hws_type.value,
            apartment_meter_required=project.meters.has_apartment_meters)
        if current_paths != project.head_paths:
            return WaterStaticReview(issues=(
                "Составляющие напора изменились после расчёта; сначала пересчитать пути и насос.",))
    head = project_governing_head(project)
    if head.pump_needed is None:
        issues.append("Необходимость повысительной установки ещё не определена.")
    elif head.pump_needed:
        status, reason = check_project_booster(project, head)
        if status != "verified":
            issues.append("Насос не привязан к текущим Q/H: " + reason)
        else:
            pump_zero = interpolate_head(project.pumps.curve, 0)
            if pump_zero is None:
                issues.append("В опубликованной кривой нет точки Q=0; экстраполяция не выполняется.")
    elif project.pumps.required:
        issues.append("Сохранён насос, хотя текущему расчёту он не требуется; нужен пересчёт подбора.")
    if issues:
        return WaterStaticReview(issues=tuple(issues))

    total = source.maximum_head_m + (pump_zero if pump_zero is not None else 0)
    rows = []
    # Only the real selected datum of each supplied above-ground floor.
    # No +1 m fixture assumption, inferred floor height, or basement appliance.
    for floor, elevation in sorted(project.building.floor_elevations_m.items()):
        if not isinstance(floor, int) or not 1 <= floor <= project.building.floors_above:
            continue
        if not _finite(elevation):
            issues.append(f"Этаж {floor}: некорректная отметка; точка не проверена.")
            continue
        rows.append(StaticReference(f"Уровень пола {floor}-го этажа", "floor", elevation,
            static_head_at_elevation(total, source.elev_header_m, elevation)))
    if _finite(source.elev_fixture_m):
        rows.append(StaticReference("Заданный диктующий прибор В1", "fixture", source.elev_fixture_m,
            static_head_at_elevation(total, source.elev_header_m, source.elev_fixture_m),
            # SP30 8.22 explicitly gives 45 m water column; no MPa conversion.
            45.0))
    else:
        issues.append("Отметка диктующего прибора не задана.")
    lowest = source.lowest_fixture_elevation_m
    if lowest is not None:
        if not _finite(lowest):
            issues.append("Некорректная отметка нижнего прибора; точка не проверена.")
        elif _finite(source.elev_fixture_m) and lowest > source.elev_fixture_m:
            issues.append("Нижний прибор выше диктующего; уточнить отметки и расчётную схему.")
        elif not source.lowest_fixture_basis.strip():
            issues.append("Для отметки нижнего прибора не указан источник или допущение.")
        else:
            rows.append(StaticReference("Заданный нижний прибор В1", "lowest_fixture", lowest,
                static_head_at_elevation(total, source.elev_header_m, lowest), 45.0))
    if not rows:
        issues.append("Нет заданных отметок для предварительной проверки.")
    return WaterStaticReview(total, source.elev_header_m, source.maximum_head_m,
        pump_zero, project.pumps.model if pump_zero is not None else "", tuple(rows), tuple(issues))
