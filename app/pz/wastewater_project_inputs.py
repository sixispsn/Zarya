"""Resolve confirmed project inputs for the K1 basement schematic.

The resolver deliberately refuses to choose between several plausible
outlets.  A missing or ambiguous registry remains a visible incompleteness;
it is never replaced with a generated elevation, slope or outlet mark.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.pz.project import Project, SewerPipeSpec


@dataclass(frozen=True)
class WastewaterBasementProjectInputs:
    """Confirmed values and selection diagnostics for one K1 outlet."""

    basement_floor_elevation_m: float | None
    outlet_invert_elevation_m: float | None
    collector_slope_per_mille: float | None
    outlet_dn_mm: int | None
    outlet_id: str
    selected_section_id: str
    selection_status: str
    diagnostics: tuple[str, ...]

    @property
    def missing_project_inputs(self) -> tuple[str, ...]:
        missing: list[str] = []
        if self.basement_floor_elevation_m is None:
            missing.append("basement_floor_elevation_m")
        if not self.outlet_id:
            missing.append("outlet_id")
        if self.outlet_dn_mm is None:
            missing.append("outlet_dn_mm")
        if self.outlet_invert_elevation_m is None:
            missing.append("outlet_invert_elevation_m")
        if self.collector_slope_per_mille is None:
            missing.append("collector_slope_per_mille")
        return tuple(missing)

    @property
    def complete(self) -> bool:
        return not self.missing_project_inputs


def _system(value: str) -> str:
    return value.strip().upper()


def _section(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _select_outlet_pipe(project: Project) -> tuple[SewerPipeSpec | None, str, list[str]]:
    diagnostics: list[str] = []
    k1_pipes = [row for row in project.sewage.pipes if _system(row.system) == "K1"]
    linked_section_ids = {
        _section(row.section_id): row.section_id.strip()
        for row in project.sewage.elements
        if _system(row.system) == "K1"
        and row.kind == "outlet"
        and row.section_id.strip()
    }

    if len(linked_section_ids) > 1:
        diagnostics.append(
            "В реестре элементов К1 несколько выпусков; для листа стояка "
            "нужен однозначный участок выпуска."
        )
        return None, "ambiguous", diagnostics

    if len(linked_section_ids) == 1:
        section_key, display_id = next(iter(linked_section_ids.items()))
        matches = [row for row in k1_pipes if _section(row.section_id) == section_key]
        if len(matches) == 1:
            return matches[0], "linked", diagnostics
        if len(matches) > 1:
            diagnostics.append(
                f"Участок выпуска {display_id} повторяется в реестре труб К1."
            )
            return None, "ambiguous", diagnostics
        diagnostics.append(
            f"Элемент выпуска ссылается на участок {display_id}, которого нет "
            "в реестре труб К1."
        )
        return None, "missing", diagnostics

    purpose_matches = [
        row for row in k1_pipes if "выпуск" in row.purpose.strip().casefold()
    ]
    if len(purpose_matches) == 1:
        diagnostics.append(
            "Выпуск выбран по единственной трубе К1 с назначением «выпуск»; "
            "рекомендуется связать её с элементом типа «выпуск»."
        )
        return purpose_matches[0], "purpose", diagnostics
    if len(purpose_matches) > 1:
        diagnostics.append(
            "Найдено несколько труб К1 с назначением «выпуск»; выбор не выполнен."
        )
        return None, "ambiguous", diagnostics

    diagnostics.append(
        "Выпуск К1 не найден: добавьте элемент типа «выпуск» и свяжите его "
        "с участком трубы."
    )
    return None, "missing", diagnostics


def resolve_wastewater_basement_project_inputs(
    project: Project,
) -> WastewaterBasementProjectInputs:
    """Resolve only project-confirmed basement values from the K1 registry."""
    pipe, selection_status, diagnostics = _select_outlet_pipe(project)
    basement_floor = project.sewage.basement_floor_elevation_m

    if basement_floor is None:
        diagnostics.append("Не задана относительная отметка чистого пола подвала.")

    if pipe is None:
        return WastewaterBasementProjectInputs(
            basement_floor_elevation_m=basement_floor,
            outlet_invert_elevation_m=None,
            collector_slope_per_mille=None,
            outlet_dn_mm=None,
            outlet_id="",
            selected_section_id="",
            selection_status=selection_status,
            diagnostics=tuple(diagnostics),
        )

    if pipe.elevation_end_m is None:
        diagnostics.append(
            f"Для выпуска {pipe.section_id} не задана относительная отметка конца."
        )
    if pipe.slope_per_mille is None:
        diagnostics.append(f"Для выпуска {pipe.section_id} не задан уклон.")
    if pipe.nominal_diameter_mm is None:
        diagnostics.append(
            f"Для выпуска {pipe.section_id} не задан номинальный диаметр."
        )

    missing_value = (
        basement_floor is None
        or pipe.elevation_end_m is None
        or pipe.slope_per_mille is None
        or pipe.nominal_diameter_mm is None
        or not pipe.section_id.strip()
    )
    status = "partial" if missing_value else "resolved"
    return WastewaterBasementProjectInputs(
        basement_floor_elevation_m=basement_floor,
        outlet_invert_elevation_m=pipe.elevation_end_m,
        collector_slope_per_mille=pipe.slope_per_mille,
        outlet_dn_mm=pipe.nominal_diameter_mm,
        outlet_id=pipe.section_id.strip(),
        selected_section_id=pipe.section_id.strip(),
        selection_status=status,
        diagnostics=tuple(diagnostics),
    )
