"""Контроль технического списка элементов внутренних систем К1/К2/К3.

Список не является нормативным источником и не принимает проектных решений.
Он только связывает подтверждённые проектировщиком элементы с топологическими
участками. Требования СП проверяются отдельным аудитом и не материализуются в
элементы автоматически.
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
    """Проверить связи списка без восстановления отсутствующих данных."""
    elements = list(project.sewage.elements or [])
    pipes = list(project.sewage.pipes or [])
    result = WastewaterRegistryAudit(
        element_count=len(elements),
        spec_position_count=sum(1 for row in elements if row.include_in_spec),
    )
    if not elements:
        result.warnings.append(
            "список элементов К1/К2/К3 не заполнен: схема может показать "
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
    # его наличие уже подтверждено списком труб и топологическим графом.
    from app.pz.wastewater_topology import build_wastewater_topology

    topology = build_wastewater_topology(project)
    result.errors.extend(
        problem for problem in topology.errors if problem not in result.errors
    )
    result.warnings.extend(
        problem for problem in topology.warnings if problem not in result.warnings
    )

    # В проходном узле DN относится к оси горизонтальной магистрали. Если DN
    # увеличивается после присоединения стояка, переход должен начинать больший
    # DN ещё ДО тройника, а тройник должен иметь этот DN по проходу. Когда
    # входящая магистраль уже имеет тот же большой DN, отдельный переход у
    # стояка является лишним: меньший DN задаётся ответвлением тройника.
    mains = list(topology.mains)
    for outgoing in mains:
        incoming = [
            item for item in mains
            if item.system == outgoing.system
            and item.to_node == outgoing.from_node
        ]
        if len(incoming) != 1:
            continue
        upstream = incoming[0]
        upstream_dn = upstream.nominal_diameter_mm
        downstream_dn = outgoing.nominal_diameter_mm
        if upstream_dn is None or downstream_dn is None:
            continue
        node = outgoing.from_node
        transitions = [
            row for row in elements
            if row.kind == "transition"
            and row.system == outgoing.system
            and row.section_id == outgoing.section_id
            and row.connects_to == node
        ]
        through_tees = [
            row for row in elements
            if row.kind in {"tee", "cross"}
            and row.system == outgoing.system
            and row.section_id == outgoing.section_id
            and row.connects_to == node
        ]
        if downstream_dn > upstream_dn:
            if not transitions:
                result.errors.append(
                    f"{node}: перед проходным узлом не задан переход "
                    f"DN{upstream_dn}×{downstream_dn}"
                )
            if not any(row.dn_mm == downstream_dn for row in through_tees):
                result.errors.append(
                    f"{node}: проходной тройник/крестовина должен иметь "
                    f"DN{downstream_dn} по магистрали и присоединение стояка "
                    "меньшего DN"
                )
        elif downstream_dn == upstream_dn and transitions:
            for transition in transitions:
                result.errors.append(
                    f"{transition.element_id}: отдельный переход в проходном "
                    f"узле {node} не нужен — входящая и выходящая магистрали "
                    f"уже DN{downstream_dn}; требуется редукционный косой "
                    "тройник/крестовина по диаметру стояка"
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
