"""Paper-sized construction hatching for schematic building sections.

The upper edge is the existing floor datum. Band depth is a graphic convention,
not an inferred slab thickness, foundation type or fire-resistance rating.
Explicit clipped strokes survive both browser SVG and the PDF backend.
"""
from html import escape
from math import isfinite


def section_slab_svg(key, left, right, top, *, units_per_mm=1.0,
                     depth_mm=3.0, role="floor"):
    values = (left, right, top, units_per_mm, depth_mm)
    if not all(isfinite(v) for v in values) or right <= left or min(units_per_mm, depth_mm) <= 0:
        raise ValueError("Некорректная геометрия полосы перекрытия")
    width, depth = right-left, depth_mm*units_per_mm
    thin, hatch = .25*units_per_mm, .18*units_per_mm
    pitch = 4*units_per_mm
    rows = [f'<g data-section-slab="{escape(key)}" data-slab-role="{escape(role)}" '
            'data-geometry="schematic-not-structural" '
            f'data-units-per-mm="{units_per_mm:g}">',
            f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="{depth:g}" '
            'fill="white" stroke="none"/>']
    # x+y=c in slab-local coordinates, clipped analytically to its rectangle.
    c = pitch
    while c < width+depth:
        x1, x2 = max(0, c-depth), min(width, c)
        rows.append(f'<line data-slab-hatch="true" x1="{left+x1:.3f}" y1="{top+c-x1:.3f}" '
                    f'x2="{left+x2:.3f}" y2="{top+c-x2:.3f}" '
                    f'stroke="black" stroke-width="{hatch:.3f}"/>')
        c += pitch
    rows.append(f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="{depth:g}" '
                f'fill="none" stroke="black" stroke-width="{thin:.3f}"/></g>')
    return ''.join(rows)
