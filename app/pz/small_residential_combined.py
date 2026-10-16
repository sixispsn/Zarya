"""One-sheet presentation of the existing K1/K2 preview, not a new design model.

Identical apartment internals are referenced to one detailed fragment. Every
apartment, riser and lower junction remains individually traceable. Presentation
may mirror a network on paper, but may not change its flow graph or plan outlet
side. Unlike collapsing several risers into one, this does not aggregate flows.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from xml.etree import ElementTree as ET

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest
from app.pz.small_residential_preview import (
    ApartmentPreview, ResidentialPreview, _arrow, _floor_geometry, _level_mark, _revision,
)
from app.pz.small_residential_rainwater import FUNNEL_OUTLET_ANCHOR
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame, validate_study_section_frame
from app.pz.wastewater_basement_profile import STYLE, _elev, _line, _text
from app.pz.wastewater_drafting import render_inline_pipe_label, render_lower_turn_assembly_svg
from app.pz.wastewater_floor_drafting import WastewaterFloorAssembly
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo


@dataclass(frozen=True)
class ApartmentReference:
    apartment_id: str
    floor_number: int
    stack_id: str
    fixture_ids: tuple[str, ...]
    detail_id: str = "A"


def _installation_signature(floor: WastewaterFloorAssembly) -> tuple:
    """Compare topology, fittings and geometry, ignoring instance IDs/elevation."""
    names = {f.fixture_id: f"fixture-{i}" for i, f in enumerate(floor.fixtures)}

    def normalize(value: str) -> str:
        for original in sorted(names, key=len, reverse=True):
            value = value.replace(original, names[original])
        return value

    return (
        floor.system,
        tuple((f.kind, f.room_label, f.quantity, f.dn_mm, f.trap_mode) for f in floor.fixtures),
        tuple((normalize(p.port_id), p.point, p.role) for p in floor.ports),
        tuple((normalize(s.start_port_id), normalize(s.end_port_id), s.dn_mm, s.role, s.carries_flow)
              for s in floor.segments),
        tuple((normalize(j.start_port_id), normalize(j.end_port_id), j.dn_mm) for j in floor.direct_fitting_joints),
        tuple((f.kind, f.point, f.dn_mm, f.replaces_kind) for f in floor.fittings),
    )


def apartment_references(model: ResidentialPreview) -> tuple[ApartmentReference, ...]:
    model.validate()
    if model.roof is None or len(model.lower_nodes) != 4:
        raise ValueError("combined small-house preview requires four K1 risers and the confirmed roof")
    signature = _installation_signature(model.apartments[0].assembly)
    refs = []
    for apt in model.apartments:
        if _installation_signature(apt.assembly) != signature:
            raise ValueError(f"{apt.apartment_id}: non-identical branch needs its own detail; cannot hide differences")
        refs.append(ApartmentReference(apt.apartment_id, apt.floor_number, apt.stack_id,
                                       tuple(f.fixture_id for f in apt.assembly.fixtures)))
    return tuple(refs)


def _connection_tail(floor: WastewaterFloorAssembly, *, scale: float) -> str:
    root = ET.fromstring(_floor_geometry(floor, scale=scale))
    # Include the root itself: the paper-style helper may return the assembly
    # directly, not a wrapper. Otherwise the complete fixture set leaks out.
    assemblies = [r for r in root.iter() if r.get("data-floor-assembly")]
    if len(assemblies) != 1:
        raise ValueError("expected exactly one canonical apartment fragment")
    for row in tuple(assemblies[0]):
        keep = (row.get("data-floor-segment") == "collector_to_riser"
                or row.get("data-direct-fitting-joint") == "riser_elbow_to_wye"
                or row.get("data-floor-fitting") in {"riser_branch_elbow_45", "riser_branch_wye_45"})
        if not keep:
            assemblies[0].remove(row)
    return ET.tostring(root, encoding="unicode")


def _fan_vent(x: float, roof_y: float, tip_y: float, number: int) -> str:
    polka = roof_y-20
    return "".join((
        f'<g data-fan-vent="К1-{number}" data-height-mm="200" data-roof-y="{roof_y:g}" data-tip-y="{tip_y:g}">',
        f'<path d="M{x:g},{tip_y+1:g} L{x-5:g},{polka:g} H{x-44:g}" fill="none" stroke="black" stroke-width=".25"/>',
        _text(x-43, polka-2, "Фановый стояк", height=3.5),
        render_inline_pipe_label(line_id=f"fan-{number}", label=f"К1-{number} ⌀110", start=(x-43, polka+5),
                                 end=(x-6, polka+5), font_size=STYLE.font_size(2.5, 1), padding=.5),
        _arrow((x, tip_y+1), (5, tip_y+1-polka), marker=f"fan-{number}", length=1.3),
        _line(x-10, tip_y-4, x-10, roof_y+4, marker='data-vent-dimension-line="true"'),
        _line(x-12, tip_y, x-1, tip_y), _line(x-12, roof_y, x-1, roof_y),
        _arrow((x-10, tip_y), (0, 1), marker=f"fan-{number}-dim-top", length=1.2),
        _arrow((x-10, roof_y), (0, -1), marker=f"fan-{number}-dim-bottom", length=1.2),
        _text(x-14, (tip_y+roof_y)/2+1, "200", height=3.5, anchor="end"), '</g>',
    ))


def _detail(apt: ApartmentPreview) -> str:
    floor, s, axis, baseline = apt.assembly, .28, 575., 204.
    tx, ty = axis-floor.port("riser_join").point.x_mm*s, baseline-212*s
    parts = [
        '<g data-typical-apartment-detail="A">',
        '<rect x="463" y="110" width="121" height="114" fill="none" stroke="black" stroke-width=".25"/>',
        _text(469, 119, "Фрагмент А", height=3.5),
        _text(469, 127, "Разводка одной квартиры; 8 повторений", height=2.5),
        _text(469, 135, "По 1 мойке, ванне, умывальнику и унитазу", height=2.5),
        '<rect x="490" y="144" width="22" height="60" fill="none" stroke="black" stroke-width=".25"/>',
        '<rect x="512" y="144" width="69" height="60" fill="none" stroke="black" stroke-width=".25"/>',
        _text(501, 151, "Кухня", height=2.5, anchor="middle"),
        _text(546, 151, "Санузел", height=2.5, anchor="middle"),
        _line(axis, 157, axis, 211, width=.6),
        f'<g transform="translate({tx:.4f} {ty:.4f}) scale({s})">{_floor_geometry(floor, scale=s)}</g>',
    ]
    a, c = floor.port("junction_2").point, floor.port("junction_3").point
    parts.append(render_inline_pipe_label(line_id="detail-50", label="К1 ⌀50",
                                         start=(tx+a.x_mm*s, ty+a.y_mm*s), end=(tx+c.x_mm*s, ty+c.y_mm*s),
                                         font_size=STYLE.font_size(2.5, 1), padding=.5))
    cap = floor.port("cleanout_cap").point
    cx, cy = tx+cap.x_mm*s, ty+cap.y_mm*s
    parts.extend((
        f'<path d="M{cx:g},{cy:g} l-5,-9 h-13" fill="none" stroke="black" stroke-width=".25"/>',
        _arrow((cx, cy), (5, 9), marker="detail-cleanout", length=1.2),
        _text(cx-18, cy-10, "Пр.", height=2.5), _text(cx-18, cy-5, "DN50", height=2.5),
        render_inline_pipe_label(line_id="detail-110", label="⌀110", start=(553, 183), end=(572, 183),
                                 font_size=STYLE.font_size(2.5, 1), padding=.5),
        _line(553, 186, 570, 186), _line(570, 186, 567, baseline-6),
        _arrow((567, baseline-6), (-3, baseline-6-186), marker="detail-WC", length=1.2),
        _text(469, 218, "Ревизия стояка показана на общем разрезе.", height=2.5), '</g>',
    ))
    return "".join(parts)


def build_small_residential_combined_svg(model: ResidentialPreview) -> str:
    refs = apartment_references(model)
    roof, b = model.roof, model.basement
    assert roof is not None
    levels = {a.floor_number: a.assembly.floor_elevation_m for a in model.apartments}
    # Preserve actual vertical distances of the accepted 1:50 exercise.
    if max(levels.values())-b.basement_floor_m > 9.5:
        raise ValueError("combined preview needs a different sheet for these levels")
    sy = 20.
    def y(z: float) -> float:
        return 290+(b.basement_floor_m-z)*sy
    roof_y, base_y, ceiling_y = y(roof.elevation_m), 290., y(b.ceiling_m)
    if roof_y < 92 or any((levels[n+1]-levels[n])*sy < 50 for n in (1,)):
        raise ValueError("insufficient space for combined annotations at confirmed levels")
    # K1 is unfolded toward the left outlet; K2 toward the right. No crossing
    # or white mask can accidentally imply a cross-system hydraulic junction.
    k1_axes, k2_axes = (270., 215., 160., 105.), (309., 344., 379., 414.)
    left, right, main1, main2, lower_s = 65., 445., y(b.proposed_invert_m), 280., .22
    turn1, turn2 = main1-76*lower_s, main2-76*lower_s
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
        'data-combined-residential-preview="true" data-release-ready="false" data-floor-scale-denominator="50">',
        '<defs><pattern id="combined-hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="3" stroke="#777" stroke-width=".25"/></pattern></defs>',
        '<rect width="594" height="420" fill="white"/>',
        _text(25, 17, "К1, К2. Принципиальная схема двухэтажного жилого дома", height=5),
        _text(25, 27, "8 квартир | 4 стояка К1 | 4 воронки и 4 стояка К2 | самостоятельный выпуск каждой системы", height=3.5),
        _text(25, 36, "Компоновочный вариант. Отметки М 1:50; развёртка по ширине условная. Типовая квартирная разводка - фрагмент А.", height=2.5),
        _text(25, 44, "Кровля +6,60: плоская неэксплуатируемая. Фановые выводы - 200 мм над кровлей. Воронки - над общедомовым холлом.", height=2.5),
    ]
    # Eight numbered references, not one apartment multiplied into an aggregate pipe.
    for apt, ref in zip(model.apartments, refs):
        axis, fy = k1_axes[apt.lane], y(levels[apt.floor_number])
        top = roof_y if apt.floor_number == 2 else y(levels[2])+2
        x = axis-40
        parts.append(f'<g data-apartment-reference="{ref.apartment_id}" data-detail-id="A" '
                     f'data-stack-id="{ref.stack_id}" data-floor="{ref.floor_number}" '
                     f'data-fixture-ids="{escape("|".join(ref.fixture_ids))}">')
        for name, rx, width in (("Кухня", x, 13.), ("Санузел", x+13, 37.)):
            parts.append(f'<rect data-preview-room="{name}" x="{rx:g}" y="{top:g}" width="{width:g}" '
                         f'height="{fy-top:g}" fill="none" stroke="black" stroke-width=".25"/>')
            parts.append(_text(rx+width/2, top+13, name, height=2.5, anchor="middle"))
        parts.append(_text(x+25, top+5, f"Квартира {int(apt.apartment_id[1:])}*", height=3.5, anchor="middle"))
        f, s = apt.assembly, .28
        tx, ty = axis-f.port("riser_join").point.x_mm*s, fy-212*s
        p = f.port("junction_4").point
        start_x, start_y = tx+p.x_mm*s, ty+p.y_mm*s
        parts.append(f'<g data-apartment-connection="{apt.apartment_id}" data-stack-x="{axis:g}" '
                     f'transform="translate({tx:.4f} {ty:.4f}) scale({s})">{_connection_tail(f, scale=s)}</g>')
        parts.extend((
            f'<circle data-detail-reference="A" cx="{start_x-4:g}" cy="{start_y:g}" r="4" '
            'fill="white" stroke="black" stroke-width=".25"/>',
            _text(start_x-4, start_y+1.2, "А", height=3.5, anchor="middle"),
            _arrow((axis-7, start_y+.2), (1, 0), marker=f"{apt.apartment_id}-flow", length=1.5),
            _text(start_x-4, start_y-7, "см. А", height=2.5, anchor="middle"), '</g>',
        ))
    # Four distinct K2 shafts shown outside apartment boundaries.
    for i, axis in enumerate(k2_axes, 1):
        parts.append(f'<rect data-k2-common-shaft="{i}" x="{axis-3:g}" y="{roof_y:g}" width="6" '
                     f'height="{ceiling_y-roof_y:g}" fill="none" stroke="black" stroke-width=".25"/>')
        for top in (roof_y, y(levels[2])+2):
            parts.append(_text(axis+5, top+12, f"Шахта {i}", height=2.5))
            parts.append(_text(axis+5, top+18, "Общая зона*", height=2.5))
    for floor, z in sorted(levels.items()):
        parts.append(_line(left, y(z), right, y(z), marker=f'data-floor-boundary="{floor}"'))
        parts.extend(_level_mark(y(z), z, f"{floor} этаж"))
    parts.extend((_line(left, roof_y, right, roof_y, width=.6), *_level_mark(roof_y, roof.elevation_m, "Кровля")))
    for xx in (left, right-4):
        parts.append(f'<rect data-building-wall="true" x="{xx:g}" y="{roof_y:g}" width="4" '
                     f'height="{base_y+4-roof_y:g}" fill="url(#combined-hatch)" stroke="black" stroke-width=".25"/>')
    for top, h in ((y(b.first_floor_m), ceiling_y-y(b.first_floor_m)), (base_y, 4)):
        parts.append(f'<rect x="{left:g}" y="{top:g}" width="{right-left:g}" height="{h:g}" '
                     'fill="url(#combined-hatch)" stroke="black" stroke-width=".25"/>')
    parts.extend((*_level_mark(base_y, b.basement_floor_m, "Пол подвала"), _text(74, ceiling_y+8, "Подвал", height=3.5)))
    # K1: identical axes upstairs and downstairs; only the paper direction flips.
    previous = None
    for lane, (axis, node) in enumerate(zip(k1_axes, model.lower_nodes)):
        tip_y = roof_y-roof.vent_height_m*sy
        parts.append(_line(axis, tip_y, axis, turn1, width=.6, marker=f'data-k1-stack="{lane+1}"'))
        parts.append(_fan_vent(axis, roof_y, tip_y, lane+1))
        for z in levels.values():
            parts.extend(_revision(axis, y(z), sy))
            parts.append(render_inline_pipe_label(line_id=f"K1-{lane}-{z}", label=f"К1-{lane+1} ⌀110",
                         start=(axis, y(z)-45), end=(axis, y(z)-28), font_size=STYLE.font_size(2.5, 1), padding=.5))
        parts.append(_arrow((axis, ceiling_y+7), (0, 1), marker=f"K1-stack-{lane}"))
        raw = render_lower_turn_assembly_svg(node, x=axis, y=turn1, scale=lower_s, pipe_width=.6,
                                             graphic_size=FittingGraphicSize(100, 100, 1), annotations=False,
                                             pipe_labels=False, flow_direction=False)
        parts.append(f'<g data-lower-system="K1" data-lane="{lane}" data-axis-x="{axis:g}" '
                     f'transform="translate({2*axis:g} 0) scale(-1 1)">{raw}</g>')
        if previous is not None:
            incoming = axis-node.port("main_in").point.x_mm*lower_s
            parts.append(_line(previous, main1, incoming, main1, width=.6, marker=f'data-k1-main-link="{lane}"'))
            parts.append(render_inline_pipe_label(line_id=f"K1-main-{lane}", label="К1 ⌀110", start=(incoming, main1),
                         end=(previous, main1), font_size=STYLE.font_size(2.5, 1), padding=.5))
        previous = axis-node.port("main_out").point.x_mm*lower_s
    assert previous is not None
    parts.append(_line(previous, main1, 41, main1, width=.6, marker='data-k1-outlet="true"'))
    parts.append(_arrow((47, main1), (-1, 0), marker="K1-outlet"))
    # K2 retains every lower through-node and the actual free initial cleanout.
    previous = None
    for lane, (axis, node) in enumerate(zip(k2_axes, roof.lower_nodes)):
        number = lane+1
        parts.extend((
            f'<rect x="{axis-6.5:g}" y="{roof_y-4:g}" width="13" height="9.9" fill="white"/>',
            render_ugo("roof_funnel", axis-FUNNEL_OUTLET_ANCHOR[0]*.25, roof_y, scale=.25),
            _line(axis, roof_y+FUNNEL_OUTLET_ANCHOR[1]*.25, axis, turn2, width=.6,
                  marker=f'data-k2-stack="{number}" data-funnel-id="К2-Вр{number}"'),
            f'<path d="M{axis-2:g},{roof_y-2:g} L{axis-4:g},{roof_y-29:g} H{axis-30:g}" '
            'fill="none" stroke="black" stroke-width=".25"/>',
            _text(axis-29, roof_y-31, f"К2-Вр{number}", height=3.5),
            _text(axis-29, roof_y-24, "DN уточнить", height=2.5),
            _arrow((axis-2, roof_y-2), (2, 27), marker=f"funnel-{number}", length=1.3),
            _arrow((axis, ceiling_y+8), (0, 1), marker=f"K2-stack-{number}"),
        ))
        for z in levels.values():
            parts.append(render_inline_pipe_label(line_id=f"K2-{lane}-{z}", label=f"К2-{number}", start=(axis, y(z)-43),
                         end=(axis, y(z)-27), font_size=STYLE.font_size(2.5, 1), padding=.5))
        parts.append(f'<g data-lower-system="K2" data-lane="{lane}" data-axis-x="{axis:g}">')
        parts.append(render_lower_turn_assembly_svg(node, x=axis, y=turn2, scale=lower_s, pipe_width=.6,
                                                   graphic_size=FittingGraphicSize(100, 100, 1), annotations=False,
                                                   pipe_labels=False, flow_direction=False))
        parts.append('</g>')
        centre = base_y-sy
        if centre >= turn2+node.port("elbow_45").point.y_mm*lower_s:
            raise ValueError("revision must remain on the vertical K2 pipe")
        parts.append(f'<g data-k2-revision="{number}" data-centre-y="{centre:g}">')
        parts.append(render_ugo("revision", axis, centre-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90))
        parts.extend((_text(axis+4, centre-1, "R", height=3.5), '</g>'))
        if previous is not None:
            incoming = axis+node.port("main_in").point.x_mm*lower_s
            if incoming <= previous:
                raise ValueError("K2 lower nodes overlap")
            parts.append(_line(previous, main2, incoming, main2, width=.6, marker=f'data-k2-main-link="{lane}"'))
            parts.append(render_inline_pipe_label(line_id=f"K2-main-{lane}", label="К2", start=(previous, main2),
                         end=(incoming, main2), font_size=STYLE.font_size(2.5, 1), padding=.5))
        previous = axis+node.port("main_out").point.x_mm*lower_s
    assert previous is not None
    parts.append(_line(previous, main2, 480, main2, width=.6, marker='data-k2-outlet="true"'))
    parts.append(_arrow((470, main2), (1, 0), marker="K2-outlet"))
    parts.extend((_line(right, y(b.ground_m), 588, y(b.ground_m), color="#555"),
                  _text(right+3, y(b.ground_m)-3, f"Земля {_elev(b.ground_m)}", height=2.5)))
    # One dimension serves the repeated K2 revision placement, with explicit note.
    dx, centre = k2_axes[0]-12, base_y-sy
    parts.extend((_line(dx, centre, dx, base_y), _line(dx-2, centre, k2_axes[0]-1, centre),
                  _line(dx-2, base_y, k2_axes[0]-1, base_y),
                  _line(dx-1, centre+1, dx+1, centre-1), _line(dx-1, base_y+1, dx+1, base_y-1),
                  _text(dx-2, (base_y+centre)/2, "1000", height=3.5, anchor="middle",
                        marker=f'transform="rotate(-90 {dx-2:g} {(base_y+centre)/2:g})"')))
    # Sleeve at each separate wall opening. Restore pipe through the thin sleeve.
    for system, xx, yy in (("K1", left, main1), ("K2", right-4, main2)):
        parts.extend((f'<rect data-outlet-sleeve="{system}" x="{xx-1:g}" y="{yy-2:g}" width="6" height="4" '
                      'fill="white" stroke="black" stroke-width=".25"/>', _line(xx-1, yy, xx+5, yy, width=.6)))
    # Explicit targets survive mirroring; no leader points to the former coordinate.
    for system, target, bounds, title, detail, side in (
        ("K1-outlet", (41., main1), LeaderBounds(22, ceiling_y+7, 115, main1-6), "Выпуск К1", f"Лоток {_elev(b.proposed_invert_m)}*", 1),
        ("K2-outlet", (480., main2), LeaderBounds(467, ceiling_y+7, 588, main2-6), "Выпуск К2", "Лоток уточнить", 1),
        ("K1-cleanout", (k1_axes[0]-model.lower_nodes[0].port("cleanout_cap").point.x_mm*lower_s, main1),
         LeaderBounds(220, ceiling_y+9, 287, main1-3), "Прочистка К1", "DN100", -1),
        ("K2-cleanout", (k2_axes[0]+roof.lower_nodes[0].port("cleanout_cap").point.x_mm*lower_s, main2),
         LeaderBounds(273, ceiling_y+8, 304, main2-13), "Пр. К2", "DN *", -1),
    ):
        engine = LeaderLayoutEngine(bounds=bounds, units_per_mm=1)
        parts.append(engine.place_and_render(LeaderRequest(system, system, target, title, detail, preferred_side=side)))
    parts.append(_detail(model.apartments[0]))
    parts.extend(_schedule(model, refs))
    notes = (
        "1. А - развёрнутый фрагмент одной квартиры, не сборный коллектор восьми квартир. Каждая ссылка относится только к своей квартире.",
        "2. Все 32 прибора, четыре стояка К1 и четыре стояка К2 сохранены в модели. Упрощено только повторение квартирной графики.",
        "3. К1 и К2 не соединяются. Разворот выпусков на листе условный; заданная сторона выпуска на плане не изменена.",
        "4. * Номера квартир условные; трассы и шахты предложены. К2 - вне квартир. Отметки пола, кровли и фановых выводов заданы.",
        "5. К1: PP HT 50x1,8 / 110x2,7; цифры со знаком диаметра - наружный размер. Лоток -2,20 - предварительная граница по морозу.",
        "6. DN* для К2 требует расчёта; материал, расход, уклон и лоток не назначены. Подвальная трасса условная. Ревизии К2 - 1000 мм от пола.",
        "7. Прочистки на свободных началах, остальные нижние тройники проходные. Доступность и интервалы обслуживания проверить по длинам.",
        "8. СП 30: 18.18-18.21, 21.2, 21.5, 21.8-21.15. Проверить УФ-защиту К1, расстояния до окон, разуклонку кровли и гидростатику К2.",
        "9. Требуют дополнения: расчётные параметры, привязки АР, проходки/изоляция/огнезащита и план сетей. Это не готовый комплект ИОС3.",
    )
    parts.extend((
        _text(25, 309, "Указания к принципиальной схеме", height=3.5),
        study_notes_svg(notes, x=25, y=318, width=370, bottom=397, pitch=8),
        _text(25, 404, "ЗАРЯ | Общая компоновка К1 и К2", height=3.5),
        _text(25, 411, "Представление по ГОСТ Р 21.620-2023, пп. 5.2.2.2-5.2.2.4. Требует расчёта и согласования.", height=2.5),
        study_section_frame(), '</svg>',
    ))
    return "".join(parts)


def _schedule(model: ResidentialPreview, refs: tuple[ApartmentReference, ...]) -> tuple[str, ...]:
    parts = ['<g data-study-schedule="true">',
             _text(467, 59, "Привязка фрагмента А", height=3.5),
             '<rect x="465" y="61" width="117" height="41" fill="none" stroke="black" stroke-width=".25"/>',
             _text(467, 67, "Квартиры*", height=2.5), _text(503, 67, "Стояк", height=2.5),
             _text(535, 67, "Подключения", height=2.5)]
    parts.extend(_line(x, 61, x, 102) for x in (501, 533))
    parts.extend(_line(465, y, 582, y) for y in (70, 78, 86, 94))
    for lane in range(len(model.lower_nodes)):
        rows = sorted((r for r in refs if r.stack_id == f"К1-{lane+1}"), key=lambda r: r.floor_number)
        numbers = ", ".join(str(int(r.apartment_id[1:])) for r in rows)
        yy = 76+lane*8
        parts.extend((_text(467, yy, numbers, height=2.5), _text(503, yy, f"К1-{lane+1}", height=2.5),
                      _text(535, yy, "1 и 2 этажи", height=2.5)))
    parts.extend((_text(467, 233, "К2-Вр1...Вр4: по одной воронке на стояк.", height=2.5), '</g>'))
    return tuple(parts)


def generate_small_residential_combined_pdf(output_path: str, model: ResidentialPreview) -> str:
    import cairosvg  # type: ignore[import-untyped]

    ensure_drafting_font_registered()
    svg = build_small_residential_combined_svg(model)
    validate_study_section_frame(svg)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(path))
    return str(path)
