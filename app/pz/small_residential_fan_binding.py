"""Geometry-only study of fan roof details on a residential cutaway.

This connects an explicitly confirmed test/design alternative, not automatic
roof grouping. Off-plane apartments do not imply off-plane fan nodes disappear.
The shared group's architectural route was NOT established. Building PDF export
is withdrawn until the actual permitted routing space is modelled. Diagnostic
SVG tests are retained to preserve the graph work, not to approve this route.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from xml.etree import ElementTree as ET

from app.pz.small_residential_preview import ResidentialPreview
from app.pz.wastewater_fan_drafting import (
    FanDetailsInput, _roof_svg, audit_fan_detail_svg, build_roof_detail_graph,
)
from app.pz.wastewater_fan_geometry import FanGeometryInput
from app.pz.wastewater_ventilation import FanTerminal


@dataclass(frozen=True)
class SectionFanBinding:
    data: FanDetailsInput
    geometry: FanGeometryInput

    @property
    def sheet_total(self) -> int:
        return 1 + len(self.data.roofs)

    def terminal(self, riser_id: str) -> FanTerminal:
        return next(t for t in self.data.evidence.terminals if riser_id in t.riser_ids)

    def port_level(self, riser_id: str) -> float:
        return next(r.lower_port_m for d in self.data.roofs for r in d.risers if r.riser_id == riser_id)

    def target_sheet(self, riser_id: str) -> int:
        return next(i+2 for i, d in enumerate(self.data.roofs) if any(r.riser_id == riser_id for r in d.risers))

    def validate(self, model: ResidentialPreview) -> None:
        from app.pz.small_residential_section import build_section_projection

        model.validate()
        build_section_projection(model)
        if not self.geometry.confirmed or not self.geometry.confirmation_ref.strip():
            raise ValueError("Геометрия фановых узлов не подтверждена")
        if self.geometry.roofs != self.data.roofs or self.geometry.valves != self.data.valves:
            raise ValueError("Подтверждена другая версия геометрии")
        if not self.data.residential:
            raise ValueError("Для жилого разреза требуется проверка жилого здания")
        if len({r.riser_id for r in self.data.risers}) != len(self.data.risers):
            raise ValueError("Повторяющиеся идентификаторы фановых стояков")
        self.data.validate()
        if self.data.valves:
            raise ValueError("Компактный адаптер клапанов ещё не подключён; отдельный контрольный вид обязателен")
        if model.roof is None or model.roof.kind != self.data.roof_kind:
            raise ValueError("Тип кровли фановых узлов отличается от разреза")
        ids = {a.stack_id for a in model.apartments}
        if ids != {r.riser_id for r in self.data.risers}:
            raise ValueError("Состав стояков фановых узлов отличается от полной модели")
        # DN comes from the existing fitting graph, not an OD110 -> DN100 alias.
        dns = {
            a.stack_id: next(s.dn_mm for s in model.lower_nodes[a.lane].segments if s.role == "riser")
            for a in model.apartments
        }
        if any(r.diameter_mm != dns[r.riser_id] for r in self.data.risers):
            raise ValueError("DN фановых стояков отличается от модели; переход не задан")
        top_floor = max(a.assembly.floor_elevation_m for a in model.apartments)
        for detail in self.data.roofs:
            if not isclose(detail.roof_level_m, model.roof.elevation_m, abs_tol=1e-6):
                raise ValueError("Отметка кровли фановых узлов отличается от разреза")
            for row in detail.risers:
                # Presentation clearance above the existing +1 m revision.
                # This is not a new SP requirement or an inferred pipe level.
                if not top_floor + 1.1 <= row.lower_port_m < model.roof.elevation_m:
                    raise ValueError("Порт фанового узла не помещается выше ревизии верхнего этажа")


def build_section_fan_preview_svgs(model: ResidentialPreview, binding: SectionFanBinding) -> tuple[str, ...]:
    """Diagnostic geometry only; use the one-sheet independent-vent PDF for the house."""
    from app.pz.small_residential_section import build_section_projection, build_small_residential_section_svg

    binding.validate(model)
    projection = build_section_projection(model)
    visible = {a.stack_id for a in projection.visible_apartments}
    all_ids = {a.stack_id for a in model.apartments}
    pages = [build_small_residential_section_svg(model, fan_binding=binding)]
    for i, detail in enumerate(binding.data.roofs, 2):
        svg = _roof_svg(binding.data, detail, i, binding.sheet_total,
                        {rid: 1 for rid in all_ids}, off_plane_risers=frozenset(all_ids-visible))
        if audit_fan_detail_svg(svg):
            raise ValueError("Наложение подписей в деталировке фанового узла")
        pages.append(svg)
    errors = audit_section_fan_svgs(model, binding, tuple(pages))
    if errors:
        raise ValueError("; ".join(errors))
    return tuple(pages)


def audit_section_fan_svgs(model: ResidentialPreview, binding: SectionFanBinding,
                          pages: tuple[str, ...]) -> tuple[str, ...]:
    from app.pz.small_residential_section import build_section_projection

    roots = tuple(ET.fromstring(s) for s in pages)
    errors = []
    if len(roots) != binding.sheet_total:
        return ("Неверное число контрольных листов",)
    main = roots[0]
    projection = build_section_projection(model)
    visible = {a.stack_id for a in projection.visible_apartments}
    all_ids = {a.stack_id for a in model.apartments}
    ports = [r for r in main.iter() if r.get("data-section-fan-port")]
    omitted = [r for r in main.iter() if r.get("data-fan-off-plane-riser")]
    if len(ports) != len(visible) or {r.get("data-section-fan-port") for r in ports} != visible:
        errors.append("Потерян видимый фановый порт")
    if len(omitted) != len(all_ids-visible) or {r.get("data-fan-off-plane-riser") for r in omitted} != all_ids-visible:
        errors.append("Не раскрыты фановые стояки вне разреза")
    if any(r.get("data-fan-vent") for r in main.iter()):
        errors.append("Остались прежние независимые вытяжки")
    detail_ports = [r for root in roots[1:] for r in root.iter() if r.get("data-fan-detail-port")]
    if len(detail_ports) != len(all_ids) or {r.get("data-fan-detail-port") for r in detail_ports} != all_ids:
        errors.append("Деталировка не охватывает все стояки")
    for detail, root in zip(binding.data.roofs, roots[1:]):
        if root.get("data-fan-roof-terminal") != detail.terminal_id:
            errors.append("Неверная группа на листе деталировки")
        graph = build_roof_detail_graph(binding.data, detail)
        edges = [r for r in root.iter() if r.get("data-fan-edge")]
        expected_edges = {(e.edge_id, e.start, e.end, e.role, e.dn_mm) for e in graph.edges}
        actual = {(e.get("data-fan-edge"), e.get("data-start"), e.get("data-end"), e.get("data-role"),
                   float(e.get("data-dn", "nan"))) for e in edges}
        if len(edges) != len(expected_edges) or actual != expected_edges:
            errors.append("Нарисованные связи вытяжки отличаются от графа")
        nodes = {n.node_id: n for n in graph.nodes}
        minimum_x = min(n.x_m for n in graph.nodes)
        factor = 1000/detail.scale
        for edge in edges:
            for end, suffix in (("start", "1"), ("end", "2")):
                node = nodes.get(edge.get(f"data-{end}", ""))
                if node is None or not all(isclose(float(edge.get(k+suffix, "nan")), v, abs_tol=.01)
                                          for k, v in (("x", 65+(node.x_m-minimum_x)*factor),
                                                       ("y", 112+(detail.roof_level_m-node.level_m)*factor))):
                    errors.append("Линия фанового узла не соединена с заданной точкой")
    for port in (*ports, *omitted):
        rid = port.get("data-section-fan-port") or port.get("data-fan-off-plane-riser")
        if rid is None or rid not in all_ids:
            errors.append("Неизвестный фановый стояк на разрезе")
            continue
        target = binding.target_sheet(rid)
        graphic_port = next((r for r in roots[target-1].iter() if r.get("data-fan-detail-port") == rid), None)
        expected = binding.port_level(rid)
        if (port.get("data-target-sheet") != str(target) or graphic_port is None
                or graphic_port.get("data-source-sheet") != "1"
                or port.get("data-terminal") != binding.terminal(rid).terminal_id
                or graphic_port.get("data-terminal") != binding.terminal(rid).terminal_id
                or float(graphic_port.get("data-level-m", "nan")) != expected):
            errors.append(f"{rid}: ссылки/отметки порта не совпадают")
        if port.get("data-fan-off-plane-riser"):
            continue
        if float(port.get("data-level-m", "nan")) != expected:
            errors.append(f"{rid}: отметка видимого порта не совпадает")
        number = next(a.lane+1 for a in model.apartments if a.stack_id == rid)
        pipe = next((r for r in main.iter() if r.get("data-k1-stack") == str(number)), None)
        if pipe is None or any(not isclose(float(pipe.get(k, "nan")), float(port.get(v, "nan")), abs_tol=.001)
                               for k, v in (("x1", "data-x"), ("y1", "data-y"))):
            errors.append(f"{rid}: порт не соединён со стояком")
    return tuple(errors)


def generate_section_fan_preview_pdf(output_path: str, model: ResidentialPreview,
                                     binding: SectionFanBinding) -> str:
    # Geometry/edge tests do not establish a route through building spaces.
    # This two-storey cutaway has apartments directly beneath the roof and no
    # modelled technical attic/storey. Do not export its experimental group as
    # a building proposal, even with confirmed raw geometry.
    binding.validate(model)
    raise ValueError(
        "Общий фановый трубопровод не привязан к допустимому пространству АР. "
        "В жилом разрезе техническая зона не задана; используйте самостоятельные "
        "фановые выводы на одном листе. Подтверждение геометрии не заменяет проверку трассы."
    )
