"""Fan presentation only: paper coordinates never become engineering lengths."""
from html import escape

from app.pz.residential_case_section import _callout
from app.pz.section_level_mark import level_mark
from app.pz.small_residential_section import _main_crossings
from app.pz.wastewater_basement_profile import _line, _text


def fan_dimension(key, x, roof_y, tip_y, value, dx=-8):
    return ''.join((f'<g data-fan-dimension="{escape(key)}" data-value="{escape(value)}">',
        _line(x, tip_y, x+dx, tip_y), _line(x, roof_y, x+dx, roof_y),
        _line(x+dx, tip_y, x+dx, roof_y),
        _line(x+dx-1, tip_y+1, x+dx+1, tip_y-1),
        _line(x+dx-1, roof_y+1, x+dx+1, roof_y-1),
        _text(x+dx-2, (tip_y+roof_y)/2, value, height=3.5, anchor="middle",
              marker=f'transform="rotate(-90 {x+dx-2:g} {(tip_y+roof_y)/2:g})"'), '</g>'))


def member_axes(count):
    """A characteristic cutaway always shows two connected representatives.

    The declared group is retained as data/caption, not as dangling pipes.
    """
    return (146., 186.)


def common_fan_svg(plan, roof_y, technical_floor_y, *, internal_storm):
    d = plan.source
    axes = member_axes(len(d.member_ids))
    # These are intentionally conventional paper levels. Only the two supplied
    # engineering end elevations are annotated; no route gradient is invented.
    low_y, high_y = technical_floor_y-9, roof_y+14
    ordinate = lambda x: low_y+(high_y-low_y)*(x-axes[0])/(axes[-1]-axes[0])
    parts = [f'<g data-common-fan="true" data-fan-group-size="{len(d.member_ids)}">',
        '<desc>'+escape('Группа К1: '+', '.join(d.member_ids))+'</desc>',
        _text(61, roof_y+8, {"cold_attic":"Холодный чердак", "warm_attic":"Тёплый чердак",
                           "technical_storey":"Технический этаж"}[d.space], height=2.5),
        _text(218, roof_y+8, "Сборная вентиляция К1", height=2.5),
        _text(218, roof_y+14, f"Стояков в группе: {len(d.member_ids)} (условно)", height=2.5),
        _text(218, roof_y+20, f"Коллектор DN{plan.diameter_mm}" if plan.diameter_mm else "DN уточнить по группе", height=2.5,
              marker=f'data-fan-collector-dn="{plan.diameter_mm or 0}"'),
        _text(218, roof_y+24, "В теплоизоляции" if d.attic_insulated is True else "Изоляция требует решения"
              if d.space == "cold_attic" else "", height=2.5),
        (f'<circle data-fan-crossing-clearance="K1-K2" cx="166" cy="{ordinate(166)-1.5:g}" '
         'r="2" fill="white"/>' if internal_storm else ""),
        '<g data-fan-collector="true">'+
        _main_crossings(axes[0], axes[-1], low_y, (166.,) if internal_storm else (), high_y, bridge_up=True)+'</g>',
        level_mark("fan-roof", 50, roof_y, d.roof_level_m, "Кровля", reference_x=55),
        level_mark("fan-space", 50, technical_floor_y, d.space_floor_m, "Тех. уровень", reference_x=55),
        _line(55, technical_floor_y, 277, technical_floor_y, width=.35)]
    for i, (rid, x) in enumerate(zip(d.member_ids[:2], axes)):
        y = ordinate(x)
        parts.append(f'<g data-fan-member="{escape(rid)}" data-fan-member-x="{x:g}" data-fan-member-y="{y:g}">')
        parts.append(f'<title>{escape(rid)}</title>')
        parts.append(_text(x+2 if i < len(axes)-1 else x-2, y+6,
                           rid if len(rid) <= 8 else f"Ст.{i+1}*", height=2.5,
                           anchor="start" if i < len(axes)-1 else "end"))
        parts.append('</g>')
    tip_y = roof_y-16
    parts.extend((_line(axes[0], tip_y, axes[0], low_y, width=.6,
                        marker='data-fan-open-terminal="common"'),
        _callout("common-fan", (axes[0], tip_y), "Общая вытяжка К1",
                 f"Открытое устье · DN{plan.diameter_mm}" if plan.diameter_mm else "Открытое устье · DN уточнить",
                 (123, tip_y-5), 62),
        fan_dimension("common", axes[0], roof_y, tip_y, plan.dimension),
        level_mark("fan-collector-low", axes[0], low_y, d.collector_low_m, "К1 вент.", width=17),
        level_mark("fan-collector-high", axes[-1], high_y, d.collector_high_m, "К1 вент.", side=1, width=20),
        _text(192, roof_y-7, "Конденсат - к первому стояку", height=2.5), '</g>'))
    return ''.join(parts), {x: ordinate(x) for x in axes[:2]}
