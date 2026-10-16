"""Paper-space level marks for the IOS3 representative section (millimetres).

ГОСТ Р 21.620-2023, 5.2.1.6: two decimals; ГОСТ Р 21.101-2020,
5.4.3: thin open arrow, vertical stem and horizontal shelf. No datum is inferred.
"""
from math import isfinite
from xml.sax.saxutils import escape

from app.pz.wastewater_basement_profile import _line, _text


def level_text(value: float, decimals: int = 2) -> str:
    if not isfinite(value):
        raise ValueError("a level mark requires a finite elevation")
    # Do not print a signed zero after display rounding. Keep source precision.
    rounded = round(value, decimals)
    return (f"{rounded:+.{decimals}f}" if rounded else f"{0:.{decimals}f}").replace(".", ",")


def level_mark(key: str, x: float, y: float, value: float, caption: str,
               *, side: int = -1, width: float = 25, reference_x: float | None = None,
               decimals: int = 2) -> str:
    """Arrow tip is exactly on the marked contour; shelf is 6 mm above it."""
    if side not in {-1, 1}:
        raise ValueError("shelf side must be -1 or 1")
    end, shelf_y = x + side * width, y - 6
    tx = min(x, end) + 1
    pieces = [f'<g data-level-mark="{escape(key)}" data-elevation-m="{value!r}" '
              f'data-tip-x="{x:g}" data-tip-y="{y:g}">',
              _line(x, shelf_y, end, shelf_y, width=.25, marker='data-level-shelf="true"'),
              _line(x, shelf_y, x, y, width=.25),
              f'<path data-level-arrow="true" d="M{x-2:g},{y-2:g} L{x:g},{y:g} L{x+2:g},{y-2:g}" '
              'fill="none" stroke="black" stroke-width=".25"/>',
              _text(tx, shelf_y-1.5, level_text(value, decimals), height=3.5),
              _text(tx, shelf_y+4, caption, height=2.5)]
    if reference_x is not None:
        pieces.append(_line(x-3, y, reference_x, y, width=.25))
    return ''.join((*pieces, '</g>'))
