"""VU symbols, with their actual axial span supplied by the drawing caller.

Reference: GOST R 21.619-2023, Appendix Г, with valve types from GOST
21.205-2016 table 6. An envelope around a bow-tie changes its meaning; a
manufacturer L must therefore never be rendered as an extra symbol rectangle.
On the dimensional view the UGO itself occupies L / scale, without pipe tails
padding a small icon to the dimension endpoints. No maximum icon size applies.
No catalogue, quantities, connection topology or hydraulic data are changed.
"""
from math import sqrt


def vertical_meter(x, y, *, length, width):
    """Paper-oriented meter symbol from the user's VALTEC sheet 3 reference.

    The upper-left half is black; the diagonal rises left-to-right. This is
    NOT a flow arrow: up/down flow is indicated separately. Axial span stays
    equal to the supplied catalogue L/scale (or a clearly symbolic extent).
    """
    left, right = x-width/2, x+width/2
    top, bottom = y-length/2, y+length/2
    return ('<g data-vu-ugo="vertical-meter" data-symbol-source="VALTEC-00.2010-sheet-3">'
            f'<rect x="{left:g}" y="{top:g}" width="{width:g}" height="{length:g}" '
            'fill="white" stroke="black" stroke-width=".35"/>'
            f'<path data-meter-filled-half="upper-left" '
            f'd="M{left:g} {top:g} L{right:g} {top:g} L{left:g} {bottom:g} Z" fill="black"/>'
            f'<path d="M{left:g} {bottom:g} L{right:g} {top:g}" '
            'fill="none" stroke="black" stroke-width=".35"/></g>')


def flexible_insert(x1, x2, y):
    """Shock-absorbing insert: GOST 21.205-2016 table 4, position 6a.

    Axial span is supplied from the selected product, never from the icon.
    The zigzag is the standard symbol, not a drawn hose/bellows geometry.
    """
    from app.pz.metering_detail import _path
    w = x2 - x1
    h = min(3., w * .24)
    xs = [x1 + w * f for f in (0, .22, .22, .5, .5, .78, .78, 1)]
    ys = [y, y, y+h, y-h, y+h, y-h, y, y]
    return ('<g data-vu-ugo="flexible-insert" data-symbol-source="GOST-21.205-2016-table-4-6a">'
            + _path('M' + ' L'.join(f'{x:g},{v:g}' for x,v in zip(xs,ys)), .6)
            + _path(f'M{xs[1]:g},{y-h:g} V{y+h:g} M{xs[-2]:g},{y-h:g} V{y+h:g}',.6) + '</g>')


def connector(x1, x2, y, *, catalogue_id, pipe_on_left=False):
    """Compose a fitting from its connection types, not an invented body icon.

    GOST 21.206-2012 table 1, 6в/6е shows threaded coupling / socket
    connections. GOST 2.784-96 table 1, 12 shows the open threaded end.
    Neither table assigns a separate product UGO to a brass nipple or a
    PP-R/metal combined coupling. The two end signs identify the connections,
    not male/female thread gender or the manufacturer's transverse envelope.
    The full line/end-sign composite occupies exactly the supplied L/scale.
    """
    from app.data.metering_products import get_metering_catalogue
    from app.pz.metering_detail import _line
    catalog = get_metering_catalogue()
    if catalogue_id in catalog.thread_connectors:
        kind, ends = 'threaded-fitting', ('coupling-thread', 'coupling-thread')
    elif (part := catalog.connectors.get(catalogue_id)) and part.joining == 'socket_fusion':
        kind, ends = 'thread-socket-fitting', ('coupling-thread', 'socket')
        if pipe_on_left:
            ends = ends[::-1]
    else:
        return None  # An unknown connection must not acquire a guessed UGO.
    span = x2-x1
    h, length = min(2., span*.22), min(3., span*.25)
    g = [f'<g data-vu-ugo="{kind}" data-symbol-composition="connection-ends">',
         _line(x1,y,x2,y,.6)]
    for x, inward, end in ((x1,1,ends[0]), (x2,-1,ends[1])):
        g.append(f'<g data-vu-port="{end}" data-port-side="{"left" if inward == 1 else "right"}">')
        if end == 'coupling-thread':
            g += [_line(x,y-h,x+inward*length,y-h,.35),
                  _line(x,y+h,x+inward*length,y+h,.35)]
        else:
            # Socket mouth faces the pipe; its semicircle lies inside body L.
            g.append(f'<path d="M{x:g} {y-h:g} A{h:g} {h:g} 0 0 '
                     f'{1 if inward == 1 else 0} {x:g} {y+h:g}" '
                     'fill="none" stroke="black" stroke-width=".35"/>')
        g.append('</g>')
    return ''.join(g) + '</g>'


def shutoff(x, y, *, size=2.8, ball=False, check=False, electric=False):
    """General shutoff / ball cock / check valve, in the left-to-right axis."""
    h = size * .6
    kind = 'check' if check else 'ball-cock' if ball else 'shutoff'
    g = [f'<g data-vu-ugo="{kind}">',
         f'<path d="M{x-size:g} {y-h:g} V{y+h:g} L{x:g} {y:g} Z" '
         'fill="white" stroke="black" stroke-width=".35"/>',
         f'<path d="M{x+size:g} {y-h:g} V{y+h:g} L{x:g} {y:g} Z" '
         f'fill="{"black" if check else "white"}" stroke="black" stroke-width=".35"/>']
    if ball and not check:
        g.append(f'<circle cx="{x:g}" cy="{y:g}" r="{size*.3:g}" '
                 'fill="white" stroke="black" stroke-width=".35"/>')
    if electric:
        # Existing actuator meaning is retained; this is not a new valve model.
        from app.pz.metering_detail import _line, _text
        g += [_line(x,y-h,x,y-h-3,.25),
              f'<rect x="{x-2:g}" y="{y-h-7:g}" width="4" height="4" '
              'fill="white" stroke="black" stroke-width=".25"/>',
              _text(x,y-h-3.9,"М",2.5,"middle")]
    return ''.join(g) + '</g>'


def gauge(x, y, *, radius=3.5):
    """Circle with a diagonal ARROW as in Appendix Г, not an unheaded slash."""
    end = (x+radius*.62, y-radius*.62)
    start = (x-radius*.62, y+radius*.62)
    length = min(radius*.42, 1.6)
    d, side = length / sqrt(2), length*.4 / sqrt(2)
    bx, by = end[0]-d, end[1]+d
    return (f'<g data-vu-ugo="pressure-gauge">'
            f'<circle cx="{x:g}" cy="{y:g}" r="{radius:g}" '
            'fill="white" stroke="black" stroke-width=".35"/>'
            f'<path d="M{start[0]:g} {start[1]:g} L{end[0]:g} {end[1]:g}" '
            'fill="none" stroke="black" stroke-width=".25"/>'
            f'<path data-gauge-arrowhead="true" d="M{end[0]:g} {end[1]:g} '
            f'L{bx-side:g} {by-side:g} L{bx+side:g} {by+side:g} Z" fill="black"/></g>')


def is_ball_cock(catalogue_id):
    """Use the selected product's declared type, not every shutoff as a gate."""
    if not catalogue_id:
        return False
    from app.data.metering_products import get_metering_catalogue
    catalog = get_metering_catalogue()
    part = catalog.products.get(catalogue_id)
    if part:
        if part.valve_type != 'unknown':
            return part.valve_type == 'ball'
        return part.kind == 'shutoff' and 'шаров' in ' '.join((part.name, *part.notes)).casefold()
    part = catalog.service_products.get(catalogue_id)
    # Current service catalogue has the documented ball instrument cock.
    return part is not None and part.kind == 'gauge_cock'
