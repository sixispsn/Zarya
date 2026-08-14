"""Контроль реестра элементов внутренних систем К1/К2/К3.

Реестр не выполняет расчётов и не выводит количества из протяжённости труб.
Он связывает подтверждённые проектировщиком элементы с топологическими
участками, чтобы схема и спецификация собирались из одного источника.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.pz.project import Project, SewerElementSpec
from app.pz.wastewater_ugo import KIND_LABELS


@dataclass
class WastewaterRegistryAudit:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    element_count: int = 0
    spec_position_count: int = 0
    covered_sections: List[str] = field(default_factory=list)
    uncovered_sections: List[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors and self.element_count > 0


def audit_wastewater_registry(project: Project) -> WastewaterRegistryAudit:
    """Проверить связи реестра без попытки восстановить отсутствующие данные."""
    elements = list(project.sewage.elements or [])
    pipes = list(project.sewage.pipes or [])
    result = WastewaterRegistryAudit(
        element_count=len(elements),
        spec_position_count=sum(1 for row in elements if row.include_in_spec),
    )
    if not elements:
        result.warnings.append(
            "реестр элементов К1/К2/К3 не заполнен: схема может показать "
            "только подтверждённые трубопроводные участки"
        )
        return result

    pipe_ids = {row.section_id for row in pipes if row.section_id}
    pipe_systems = {row.section_id: row.system for row in pipes if row.section_id}
    node_ids = {
        node
        for row in pipes
        for node in (row.from_node, row.to_node)
        if node
    }
    element_ids = set()
    covered = set()
    for row in elements:
        if row.kind not in KIND_LABELS:
            result.warnings.append(
                f"{row.element_id}: вид элемента {row.kind!r} отсутствует "
                "в каталоге УГО и будет показан знаком «иной элемент»"
            )
        if not row.element_id:
            result.errors.append("обнаружен элемент без обозначения")
        elif row.element_id in element_ids:
            result.errors.append(f"повтор обозначения элемента: {row.element_id}")
        element_ids.add(row.element_id)
        if row.section_id:
            if row.section_id not in pipe_ids:
                result.errors.append(
                    f"{row.element_id}: неизвестный участок {row.section_id}"
                )
            else:
                covered.add(row.section_id)
                if pipe_systems[row.section_id] != row.system:
                    result.errors.append(
                        f"{row.element_id}: система {row.system} не совпадает "
                        f"с участком {row.section_id} ({pipe_systems[row.section_id]})"
                    )
        if row.quantity <= 0:
            result.errors.append(f"{row.element_id}: количество должно быть > 0")
        if row.include_in_spec and (not row.name.strip() or not row.unit.strip()):
            result.errors.append(
                f"{row.element_id}: для спецификации нужны наименование и единица"
            )
        if row.include_in_spec and not (row.type_mark.strip() or row.dn_mm):
            result.warnings.append(
                f"{row.element_id}: для спецификации не задана марка/тип или DN"
            )
        if row.include_in_spec and not row.standard.strip():
            result.warnings.append(
                f"{row.element_id}: для спецификации не задан стандарт/ТУ"
            )
    valid_targets = pipe_ids | node_ids | element_ids
    for row in elements:
        if row.connects_to and row.connects_to not in valid_targets:
            result.errors.append(
                f"{row.element_id}: неизвестная связь {row.connects_to}"
            )

    result.covered_sections = sorted(covered)
    result.uncovered_sections = sorted(pipe_ids - covered)
    # Магистральный участок может не нести самостоятельного штучного элемента;
    # его наличие уже подтверждено реестром труб и топологическим графом.
    from app.pz.wastewater_topology import build_wastewater_topology

    topology = build_wastewater_topology(project)
    result.errors.extend(
        problem for problem in topology.errors if problem not in result.errors
    )
    result.warnings.extend(
        problem for problem in topology.warnings if problem not in result.warnings
    )
    from app.pz.wastewater_sp30 import audit_wastewater_sp30

    sp30 = audit_wastewater_sp30(project)
    result.errors.extend(
        problem for problem in sp30.errors if problem not in result.errors
    )
    result.warnings.extend(
        problem for problem in sp30.warnings if problem not in result.warnings
    )
    return result


def elements_by_system(project: Project, system: str) -> List[SewerElementSpec]:
    """Стабильная выборка элементов системы для схемы и ведомостей."""
    return sorted(
        (row for row in project.sewage.elements if row.system == system),
        key=lambda row: (
            row.layout_column,
            row.floor_from,
            row.floor_to if row.floor_to is not None else row.floor_from,
            row.element_id,
        ),
    )
