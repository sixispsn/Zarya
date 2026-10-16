"""K2 companion sheet for the opt-in small residential composition preview.

This is a schematic gravity routing proposal, not a sizing calculation. It
deliberately cannot borrow K1's PP HT series, invert or outlet/mains. Four
proposed roof positions are linked one-to-one to separate K2 risers; widths of
the unfolded common service zones are graphical, not architectural distances.
"""
from __future__ import annotations

from app.pz.drawing_sheet_style import FittingGraphicSize
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest
from app.pz.small_residential_preview import ResidentialPreview, _arrow, _level_mark
from app.pz.study_graphic_frame import study_notes_svg, study_section_frame
from app.pz.wastewater_basement_profile import STYLE, _elev, _line, _text
from app.pz.wastewater_drafting import render_inline_pipe_label, render_lower_turn_assembly_svg
from app.pz.wastewater_ugo import REVISION_CENTRE_ANCHOR, render_ugo


# Exact transformed last endpoint of the canonical CAD-vector funnel symbol.
# x = 4662*0.008192524322 - 38.197644649258
# y = -3045*0.008192524322 + 47.725550435228
FUNNEL_OUTLET_ANCHOR = (-.004096260094, 22.779313874738)
HEATED_FUNNEL_OUTLET_ANCHOR = (
    5106*.015187470337-77.547223540579,
    -4605*.015187470337+87.593735168486,
)


def build_small_residential_k2_svg(model: ResidentialPreview) -> str:
    model.validate()
    roof, b = model.roof, model.basement
    if roof is None:
        raise ValueError("confirmed roof inputs are required for the K2 sheet")
    # Same architectural elevation transform as the companion K1 sheet.
    highest = max(a.assembly.floor_elevation_m for a in model.apartments)
    denominator = 50 if (highest-b.basement_floor_m)*20 <= 190 else 100
    scale_y = 1000/denominator
    y0 = 290+b.basement_floor_m*scale_y

    def y(z: float) -> float:
        return y0-z*scale_y

    levels = {a.floor_number: a.assembly.floor_elevation_m for a in model.apartments}
    roof_y, floor_y, base_y, ceiling_y = y(roof.elevation_m), y(b.first_floor_m), 290., y(b.ceiling_m)
    axes, left, wall = (130., 235., 340., 445.), 60., 496.
    # No surveyed/selected K2 invert exists: this is paper-space arrangement.
    main_y, turn_scale = base_y-10, .22
    turn_y = main_y-76*turn_scale
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" '
        'data-small-residential-k2="true" data-release-ready="false" data-route-elevations="unknown">',
        '<defs><pattern id="k2-hatch" width="3" height="3" patternUnits="userSpaceOnUse" '
        'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="3" stroke="#777" stroke-width=".25"/></pattern></defs>',
        '<rect width="594" height="420" fill="white"/>',
        _text(25, 17, "К2. Четыре воронки - общедомовые шахты - отдельный выпуск", height=5),
        _text(25, 26, "Компоновочный вариант. К2 не подключается к К1. Трассы в пределах жилых квартир не предусматриваются.", height=2.5),
        _text(25, 34, f"Отметки этажей М 1:{denominator}. Развёртка шахт условная; высота магистрали в подвале пока не назначена.", height=2.5),
        _text(25, 44, "4 воронки | 4 предлагаемых стояка | 1 самостоятельный выпуск К2 | диаметры и расходы - по расчёту", height=3.5),
        _text(25, 56, "Воронки над общедомовым холлом. Рельеф и водосборные участки кровли требуется согласовать с АР.", height=2.5),
    ]
    # Common service zones, not a duplication of apartment room boxes.
    for number, axis in enumerate(axes, 1):
        parts.append(f'<rect data-k2-common-shaft="{number}" x="{axis-8:g}" y="{roof_y:.3f}" '
                     f'width="16" height="{ceiling_y-roof_y:.3f}" fill="none" stroke="black" stroke-width=".25"/>')
        for n, z in levels.items():
            top = roof_y if n == max(levels) else y(levels[n+1])
            parts.append(_text(axis+14, top+14, f"Шахта К2-{number}", height=3.5))
            parts.append(_text(axis+14, top+21, "Общая зона*", height=2.5))
    parts.extend((
        _line(left, roof_y, wall, roof_y, width=.6, marker='data-confirmed-roof="true"'),
        f'<rect x="{left:g}" y="{floor_y:.3f}" width="{wall-left:g}" height="{ceiling_y-floor_y:.3f}" '
        'fill="url(#k2-hatch)" stroke="black" stroke-width=".25"/>',
        f'<rect x="{left:g}" y="{base_y:g}" width="{wall-left:g}" height="4" '
        'fill="url(#k2-hatch)" stroke="black" stroke-width=".25"/>',
        f'<rect data-k2-wall="true" x="492" y="{roof_y:.3f}" width="4" height="{base_y+4-roof_y:.3f}" '
        'fill="url(#k2-hatch)" stroke="black" stroke-width=".25"/>',
        _text(65, ceiling_y+8, "Подвал", height=3.5),
    ))
    for label, level in (("Кровля", roof.elevation_m), *((f"{n} этаж", z) for n, z in sorted(levels.items())),
                         ("Пол подвала", b.basement_floor_m)):
        parts.extend(_level_mark(y(level), level, label))
    for n, z in levels.items():
        parts.append(_line(left, y(z), wall, y(z), marker=f'data-floor-boundary="{n}"'))
    roof_leaders = LeaderLayoutEngine(bounds=LeaderBounds(62, 61, 490, roof_y-8), units_per_mm=1)
    previous_out = None
    for i, (axis, node) in enumerate(zip(axes, roof.lower_nodes)):
        number = i+1
        sx = axis-FUNNEL_OUTLET_ANCHOR[0]*.25
        sy = roof_y+FUNNEL_OUTLET_ANCHOR[1]*.25
        parts.extend((
            f'<rect x="{axis-6.5:.3f}" y="{roof_y-4:.3f}" width="13" height="9.9" fill="white"/>',
            render_ugo("roof_funnel", sx, roof_y, scale=.25),
            _line(axis, sy, axis, turn_y, width=.6,
                  marker=f'data-k2-riser="{number}" data-funnel-id="К2-Вр{number}"'),
            roof_leaders.place_and_render(LeaderRequest(
                f"funnel-{number}", f"К2-Вр{number}", (axis, roof_y-1), f"Воронка К2-Вр{number}",
                "DN по расчёту", preferred_side=-1, preferred_vertical=-1,
            )),
            _arrow((axis, y(levels[2])+10), (0, 1), marker=f"K2-{number}-flow"),
            render_inline_pipe_label(line_id=f"K2-riser-{number}", label=f"К2-{number}",
                                     start=(axis, floor_y-45), end=(axis, floor_y-23),
                                     font_size=STYLE.font_size(3.5, 1), padding=1),
            render_lower_turn_assembly_svg(node, x=axis, y=turn_y, scale=turn_scale,
                                          pipe_width=.6, graphic_size=FittingGraphicSize(100, 100, 1),
                                          annotations=False, pipe_labels=False, flow_direction=False),
        ))
        # Lowest-storey revision, centre 1 m above basement floor; connected to
        # the vertical portion of the proposed lower fitting node, never floating.
        revision_y = base_y-scale_y
        vertical_end = turn_y+node.port("elbow_45").point.y_mm*turn_scale
        if not revision_y < vertical_end:
            raise ValueError("K2 revision cannot fit on the vertical riser; revise layout")
        parts.extend((
            f'<g data-k2-revision="{number}" data-centre-y="{revision_y:.3f}" data-floor-y="{base_y:g}">',
            render_ugo("revision", axis, revision_y-REVISION_CENTRE_ANCHOR[0]*.2, scale=.2, rotation=90),
            _text(axis+4, revision_y-1, "R", height=3.5),
            _line(axis-10, revision_y, axis-10, base_y),
            _line(axis-12, revision_y, axis-1, revision_y), _line(axis-12, base_y, axis-1, base_y),
            _line(axis-11, revision_y+1, axis-9, revision_y-1), _line(axis-11, base_y+1, axis-9, base_y-1),
            _text(axis-12, (revision_y+base_y)/2, "1000", height=3.5, anchor="middle",
                  marker=f'transform="rotate(-90 {axis-12:g} {(revision_y+base_y)/2:g})"'), '</g>',
        ))
        if previous_out is not None:
            incoming = axis+node.port("main_in").point.x_mm*turn_scale
            parts.append(_line(previous_out, main_y, incoming, main_y, width=.6,
                               marker=f'data-k2-main-link="{number}"'))
            parts.append(render_inline_pipe_label(line_id=f"K2-main-{number}", label="К2",
                                                 start=(previous_out, main_y), end=(incoming, main_y),
                                                 font_size=STYLE.font_size(3.5, 1), padding=1))
        previous_out = axis+node.port("main_out").point.x_mm*turn_scale
    # One accessible capped free end, three open through-junctions. No reducer
    # or arbitrary numeric DN is drawn before the still-missing K2 sizing.
    leaders = LeaderLayoutEngine(bounds=LeaderBounds(80, ceiling_y+8, 588, base_y-1), units_per_mm=1)
    cap = roof.lower_nodes[0].port("cleanout_cap").point
    assert previous_out is not None
    parts.extend((
        leaders.place_and_render(LeaderRequest("K2-cleanout", "K2:cleanout", (axes[0]+cap.x_mm*turn_scale, main_y),
                                              "Прочистка К2", "DN по расчёту", preferred_side=-1)),
        f'<rect x="491" y="{main_y-2:g}" width="6" height="4" fill="white" stroke="black" stroke-width=".25"/>',
        _line(float(previous_out), main_y, 536, main_y, width=.6, marker='data-k2-building-outlet="true"'),
        _arrow((515, main_y), (1, 0), marker="K2-outlet"),
        leaders.place_and_render(LeaderRequest("K2-outlet", "K2:outlet", (536, main_y), "Выпуск К2",
                                              "Лоток уточнить", preferred_side=1)),
        _line(wall, y(b.ground_m), 588, y(b.ground_m), color="#555"),
        _text(500, y(b.ground_m)-3, f"Земля {_elev(b.ground_m)}", height=2.5),
    ))
    parts.extend(_roof_plan(model))
    notes = (
        "1. * Шахты предложены в нежилой общедомовой зоне. Проверить места и доступ по АР; внутри квартир К2 не прокладывать (СП 30, 21.15).",
        "2. Вр1-Вр4 поставлены над общим холлом, не над квартирами. Координаты на эскизе - предложение, не утверждённый план кровли.",
        "3. Уточнить разуклонку, водосборные площади и расчётный дождь; затем подобрать воронки, диаметры и пропускную способность (21.5, 21.10-21.12).",
        "4. Соединение воронок - с компенсационным раструбом и эластичной заделкой (21.9). Тип воронки, обогрев и узел кровли уточнить.",
        "5. Материал и прочность К2 - отдельный подбор с проверкой гидростатики при засоре (21.13, 21.14). Серия PP HT из К1 не перенесена в К2.",
        "6. Ревизии показаны в нижнем этаже (21.15, изм. 3); 1000 мм - принятое правило доступности. Прочистка только на свободном начале магистрали.",
        "7. Уклон, отметка и длина магистрали К2 не заданы. Высота её прокладки здесь условная; проверить обслуживание по 21.8 и разделу 18.",
        "8. Выпуск К2 самостоятельный, без перепуска в К1 (21.2). Наружная ливневая сеть и отметка присоединения не заданы и не показаны.",
    )
    parts.append(_text(25, 309, "Условия и следующие проверки", height=3.5))
    parts.append(study_notes_svg(notes, x=25, y=318, width=370, bottom=397))
    parts.extend((
        _text(25, 404, "ЗАРЯ | Согласование компоновки К2", height=3.5),
        _text(25, 411, "Компоновка по ГОСТ Р 21.620-2023, прил. В. Не заменяет расчёт, план кровли и готовый комплект ИОС3.", height=2.5),
        study_section_frame(system_label="К2", sheet_no=2, sheet_total=2), '</svg>',
    ))
    return "".join(parts)


def _roof_plan(model: ResidentialPreview) -> tuple[str, ...]:
    """Small locator sketch tied to the supplied 21 x 12 m floor-plan base."""
    assert model.roof
    x, y, scale = 503., 119., 3.8
    parts = [
        '<g data-roof-locator="proposed">',
        _text(503, 105, "Воронки на плане*", height=2.5),
        _text(503, 112, "Габарит основы 21 x 12 м", height=2.5),
        f'<rect x="{x:g}" y="{y:g}" width="{21*scale:g}" height="{12*scale:g}" fill="none" stroke="black" stroke-width=".25"/>',
        f'<rect x="{x+9*scale:g}" y="{y+3*scale:g}" width="{3*scale:g}" height="{3*scale:g}" fill="#eee" stroke="black" stroke-width=".25"/>',
    ]
    for i, (xx, yy) in enumerate(model.roof.funnel_positions_m, 1):
        px, py = x+xx*scale, y+yy*scale
        parts.append(f'<circle data-funnel-plan-position="{i}" data-x-m="{xx:g}" data-y-m="{yy:g}" '
                     f'cx="{px:g}" cy="{py:g}" r=".65" fill="black"/>')
        dx = -3.7 if i in (1, 3) else 3.7
        dy = -3 if i <= 2 else 6
        parts.append(_text(px+dx, py+dy, str(i), height=2.5, anchor="middle"))
    for j, text in enumerate(("1-4: Вр1-Вр4", "Серое поле - общий холл.", "Координаты от левого верха, мм:",
                              "Вр1 (9900; 3600), Вр2 (11100; 3600)",
                              "Вр3 (9900; 5200), Вр4 (11100; 5200)", "Разуклонку согласовать с АР.")):
        parts.append(_text(503, 175+j*7, text, height=2.5))
    return tuple(parts + ['</g>'])
