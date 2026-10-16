"""Connected, dimension-aware VU composition in paper millimetres.

This is a continuous principle layout, NOT a fabrication drawing: only accepted
catalogue body lengths have a scale. Adjacent UGO share endpoints; branch routes
connect with solid lines. Graphical routing never becomes pipe takeoff, overall
length, thread engagement or a service gap. Unresolved installation data remain
explicit in the notes/audit, not as artificial breaks in the water path.
All branches and item positions come from the existing graph/SO, not a second
hand-maintained list. In particular, the bypass valve is never stretched.
"""
from dataclasses import dataclass, replace
from html import escape


@dataclass(frozen=True)
class PlacedPart:
    id: str
    title: str
    catalogue_id: str
    points: tuple[tuple[float, float], ...]
    length_mm: float | None
    dimension_basis: str
    kind: str
    mark: str
    electric: bool = False
    gauge_diameter_mm: float | None = None
    gauge_center_height_mm: float | None = None
    branch_length_mm: float | None = None
    center_to_face_mm: float | None = None

    @property
    def center(self):
        a, b = self.points[0], self.points[-1]
        return ((a[0]+b[0])/2, (a[1]+b[1])/2)


@dataclass(frozen=True)
class PlacedLink:
    before: str
    after: str
    points: tuple[tuple[float, float], ...]
    unresolved: bool = True


@dataclass(frozen=True)
class MeteringLayout:
    scale: int
    parts: tuple[PlacedPart, ...]
    links: tuple[PlacedLink, ...]
    issues: tuple[str, ...]
    special_layout_pending: bool = False
    orientation: str = 'horizontal_dial_up'

    def part(self, ident):
        return next(p for p in self.parts if p.id == ident)

    @property
    def overall_length_mm(self):
        # Schematic routing / touching UGO do not specify installation seats.
        return None


def build_metering_layout(project, state=None):
    from app.data.metering_products import get_metering_catalogue
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_spec import build_metering_spec_section
    from app.pz.metering_rules import special_layout_pending
    state = state or drawing_state(project)
    detail, catalog = project.metering_detail, get_metering_catalogue()
    special_pending = special_layout_pending(project)
    if errors := detail.validate():
        return MeteringLayout(detail.mounting.scale, (), (), tuple(errors), special_pending)
    if state.node_key == "hot" and state.meter is None:
        return MeteringLayout(detail.mounting.scale, (), (), state.missing, True,
                              detail.assembly_orientation)
    from app.pz.metering_orientation import meter_orientation
    from app.pz.meter_validation import meter_node_key
    if state.meter and meter_orientation(detail, meter_node_key(state.meter)) != detail.meter_mounting:
        return MeteringLayout(detail.mounting.scale, (), (),
            ("Ориентация основного водомера расходится с осью деталировки; исправьте исходные.",), True)
    from app.pz.metering_orientation import nonhorizontal_layout_pending, horizontal_filter_offset
    if nonhorizontal_layout_pending(detail):
        return MeteringLayout(detail.mounting.scale, (), (),
            ("Смешанная ориентация задана. Для смены оси нужны явно заданные повороты и их размеры; "
             "горизонтальный шаблон вместо неё не выдан.",), True)
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                          electric_bypass=state.electric_bypass)
    chain = build_metering_chain(detail, state, selection)
    rows = build_metering_spec_section(project).rows
    marks = {ident: r.diagram_pos for r in rows for ident in r.component_ids}
    products = {**catalog.products, **catalog.connectors, **catalog.thread_connectors, **catalog.reducers,
                **catalog.service_products, **catalog.fittings}
    scale, parts, links = detail.mounting.scale, {}, []
    vertical = detail.assembly_orientation.startswith('vertical')
    mixed_filter = horizontal_filter_offset(detail)
    if (vertical or detail.filter_offset_family or detail.filter_inline_family or state.node_key == "hot") and selection.errors:
        return MeteringLayout(scale, (), (), tuple(selection.errors), True, detail.assembly_orientation)
    flex = {c['role']:c for c in selection.flexible_connections}

    def dimension(ident):
        if ident.startswith('flex_'):
            c = flex[ident.removeprefix('flex_')]
            return None if c['errors'] else (c['installed_length_mm'] or c['dimension_length_mm'])
        p = products.get(chain.node(ident).catalogue_id)
        return p.body_length_mm if p else chain.node(ident).minimum_length_mm

    def width(ident):
        p = products.get(chain.node(ident).catalogue_id)
        if p and getattr(p, 'kind', '') == 'elbow90':
            return p.dimensions_mm['A'] / scale
        if p and getattr(p, "kind", "") == "gauge":
            return (p.dimensions_mm["h"] + p.dimensions_mm["D"] / 2) / scale
        length = dimension(ident)
        # Unknown dimensions consume PAPER space, never model millimetres.
        return length/scale if length is not None else 7.

    def put(ident, points):
        node = chain.node(ident)
        p = products.get(node.catalogue_id)
        from app.pz.metering_product_selection import CATALOGUE_ROLES
        kind = getattr(p, "kind", "fitting") if p else CATALOGUE_ROLES.get(node.role, (None,"unknown"))[1]
        if not p and ident.startswith(('maintenance_cock_', 'maintenance_cap_')):
            from app.pz.metering_service import SERVICE_ROLES
            kind = next((kind for _,kind,ids in SERVICE_ROLES.values() if ident in ids), kind)
        if node.role == "inline_nipple":
            kind = "nipple"
        if node.role == "meter_straight":
            kind = "straight"
        basis = getattr(p, 'dimension_basis', 'nominal') if p else (
            'minimum' if node.minimum_length_mm is not None else 'unknown')
        if node.role == 'flexible_connection':
            kind = 'flexible_connection'
            c = flex[ident.removeprefix('flex_')]
            basis = 'installed' if c['installed_length_mm'] is not None else 'free'
        kit = catalog.connection_kits.get(node.catalogue_id)
        if ident in ("kit_in", "kit_out") and kit and kit.meter_seal == "flat_gasket":
            kind = "meter_union"
        if ident in ("reducer_in", "reducer_out") and p is not None:
            expands = (ident == "reducer_out") == (detail.inlet_dn == p.large_dn)
            kind = "reducer_expand" if expands else "reducer_reduce"
        parts[ident] = PlacedPart(ident, node.title, node.catalogue_id or "", tuple(points),
            dimension(ident), basis,
            kind, marks.get(ident, "—"),
            (ident=="bypass_valve" and state.electric_bypass)
            or (ident=="fire_valve" and project.fire.branch_electric_valves),
            p.dimensions_mm.get("D") if kind == "gauge" else None,
            p.dimensions_mm.get("h") if kind == "gauge" else None,
            getattr(p, "branch_length_mm", None),
            p.dimensions_mm['A'] if kind == 'elbow90' else None)

    def connect(a, b, start=None, end=None):
        links.append(PlacedLink(a, b, (start or parts[a].points[-1], end or parts[b].points[0])))

    main_y = 131.
    main = chain.paths[0].nodes
    island = (set(main[main.index('filter_turn_in')+1:main.index('filter_turn_out')])
              if mixed_filter else set())
    needed = sum(width(n) for n in main if n not in island)
    lateral = (sum(width(n) for n in island) + width('filter_turn_in') + width('filter_turn_out')
               if mixed_filter else 0.)
    if lateral > 65:
        return MeteringLayout(scale, (), (),
            (f"Горизонтальный участок фильтра не помещается при 1:{scale}; выберите более мелкий масштаб.",), True)
    if needed > (174 if vertical else 360):
        return MeteringLayout(scale, (), (),
            (f"Компоновка не помещается при 1:{scale}. Выберите более мелкий масштаб; изделия не уменьшены автоматически.",), special_pending)
    x = 30+(376-needed)/2
    y = main_y
    # Before the final rigid rotation, the transverse island travels up/down
    # so the filter always has left-to-right flow in paper coordinates.
    turn_sign = -1 if detail.assembly_orientation == 'vertical_down' else 1
    for i, ident in enumerate(main):
        w = width(ident)
        if mixed_filter and ident == 'filter_turn_in':
            put(ident, ((x,y),(x+w,y),(x+w,y+turn_sign*w)))
            x, y = x+w, y+turn_sign*w
        elif mixed_filter and ident == 'filter_turn_out':
            put(ident, ((x,y),(x,y+turn_sign*w),(x+w,y+turn_sign*w)))
            x, y = x+w, y+turn_sign*w
        elif ident in island:
            put(ident, ((x,y),(x,y+turn_sign*w)))
            y += turn_sign*w
        else:
            put(ident, ((x,y),(x+w,y)))
            x += w
        if i:
            connect(main[i-1],ident)

    for path in chain.paths[1:]:
        anchor = parts[path.nodes[0]].center
        branch = parts[path.nodes[0]].branch_length_mm
        # Attach to the real branch face, not the centre of a scaled tee.
        direction = 1 if path.id.startswith(("control_", "maintenance_")) else -1
        if branch is not None:
            anchor = (anchor[0], anchor[1] + direction * branch / scale)
        if path.id == "bypass":
            last = parts[path.nodes[-1]].center
            if parts[path.nodes[-1]].branch_length_mm is not None:
                last = (last[0], last[1]-parts[path.nodes[-1]].branch_length_mm/scale)
            # Route nodes represent unresolved pipe/elbow assemblies; they
            # are not single fittings, measured stock or hidden purchased tees.
            inner = path.nodes[2:-2]
            needed = sum(width(n) for n in inner)
            if needed+12 > last[0]-anchor[0]:
                return MeteringLayout(scale, (), (),
                    ("Арматура обводной не помещается между присоединениями. Нужна отдельная компоновка; корпус не растянут.",), special_pending)
            x = (anchor[0]+last[0]-needed)/2
            y = min(p.center[1] for p in parts.values())-69 if mixed_filter else 62.
            put(path.nodes[1], (anchor,(anchor[0],y),(x,y)))
            for ident in inner:
                w = width(ident)
                put(ident, ((x,y),(x+w,y)))
                x += w
            put(path.nodes[-2], ((x,y),(last[0],y),last))
            for a,b in zip(path.nodes,path.nodes[1:]):
                connect(a,b,anchor if a==path.nodes[0] else None,
                        last if b==path.nodes[-1] else None)
        else:
            up = path.id in ("gauge", "fire")
            step = -1 if up else 1
            # Service controls sit below the horizontal body dimensions, not
            # across them. This is paper routing, not an installed pipe L.
            y = anchor[1]+step*(30 if path.id.startswith(('control_', 'maintenance_')) else 15)
            for index, ident in enumerate(path.nodes[1:]):
                # No guessed instrument body/pipe size: an unresolved symbol
                # has a fixed paper extent, just like any principle symbol.
                extent = width(ident)
                put(ident, ((anchor[0],y),(anchor[0],y+step*extent)))
                previous = path.nodes[index]
                connect(previous, ident, anchor if index == 0 else None)
                y += step*extent
    if set(parts) != {n.id for n in chain.nodes} or len(links) != len(chain.links):
        raise ValueError("Компоновка ВУ потеряла элементы/связи исходной цепочки")
    if vertical:
        # Rigid rotation of topology ONLY; text and dimensions are laid out
        # afresh in paper coordinates, never rotated along with the whole page.
        sign = 1 if detail.assembly_orientation == 'vertical_down' else -1
        center = (parts['inlet'].points[0][0] + parts['outlet'].points[-1][0]) / 2
        def rotate(p):
            return (140-lateral/2 - sign*(p[1]-main_y), 128 + sign*(p[0]-center))
        parts = {k:replace(p, points=tuple(rotate(v) for v in p.points)) for k,p in parts.items()}
        links = [replace(e, points=tuple(rotate(v) for v in e.points)) for e in links]
    return MeteringLayout(scale, tuple(parts.values()), tuple(links), (), special_pending, detail.assembly_orientation)


def _dimension(x1, x2, y, value, axis, *, half_height=3):
    from app.pz.metering_detail import _line, _text
    side = 1 if y >= axis else -1
    edge=axis+side*(half_height+1)
    return "".join((_line(x1,edge,x1,y+side*2,.25), _line(x2,edge,x2,y+side*2,.25),
        _line(x1,y,x2,y,.25), _line(x1-1,y+1,x1+1,y-1,.25),
        _line(x2-1,y+1,x2+1,y-1,.25), _text((x1+x2)/2,y-1.5,value,3.5,"middle")))


def _symbol_half_height(part, scale):
    """Transverse UGO proportions, NOT an invented manufacturer body height."""
    if part.kind == 'gauge' and part.gauge_diameter_mm is not None:
        return part.gauge_diameter_mm/(2*scale)
    if part.length_mm is None:
        return 1.5 if part.kind == 'meter' else 3.
    span=part.length_mm/scale
    if part.kind == 'meter':
        return span/4
    if part.kind == 'strainer':
        return span/2
    if part.kind in ('shutoff','check','gauge_cock'):
        return span*.3
    return 2.


def _dimension_offset(part, scale):
    lane=23 if part.kind == 'nipple' or part.id in ('reducer_in','reducer_out','outlet_connector') else 13
    return max(lane,_symbol_half_height(part,scale)+8)


def _part_svg(part, scale, *, mark_y=None, mark_position=None, symbols_only=False,
              include_dimension=True):
    from app.pz.metering_detail import _line, _path, _text, ugo
    from app.pz.metering_ugo import shutoff, gauge, is_ball_cock, connector, flexible_insert, vertical_meter
    x,y = part.center
    a,b = part.points[0],part.points[-1]
    horizontal = len(part.points)==2 and a[1]==b[1]
    control = part.id.startswith(('control_', 'maintenance_cock_', 'maintenance_cap_'))
    attrs = f'data-vu-component="{escape(part.id)}" data-catalogue-id="{escape(part.catalogue_id)}" '
    attrs += f'data-body-length-mm="{part.length_mm if part.length_mm is not None else ""}" '
    attrs += f'data-dimension-basis="{part.dimension_basis}"'
    g = [f'<g {attrs}>']
    if part.kind == 'elbow90' and part.center_to_face_mm is not None:
        # Two centre-to-face arms, no fictitious axial L. End ticks show the
        # fitting faces; a short rounded corner is only conventional UGO ink.
        a,c,b = part.points
        arm = part.center_to_face_mm / scale
        r = min(arm*.35, 2.)
        u = ((c[0]-a[0])/arm, (c[1]-a[1])/arm)
        v = ((b[0]-c[0])/arm, (b[1]-c[1])/arm)
        p1 = (c[0]-r*u[0], c[1]-r*u[1])
        p2 = (c[0]+r*v[0], c[1]+r*v[1])
        g.append(_path(f'M{a[0]:g},{a[1]:g} L{p1[0]:g},{p1[1]:g} '
                       f'Q{c[0]:g},{c[1]:g} {p2[0]:g},{p2[1]:g} L{b[0]:g},{b[1]:g}',.6,
                       f'data-center-to-face-mm="{part.center_to_face_mm:g}"'))
        for p,d in ((a,u),(b,v)):
            g.append(_line(p[0]-d[1],p[1]+d[0],p[0]+d[1],p[1]-d[0],.35))
    elif len(part.points)>2:
        g.append(_path("M"+" L".join(f"{x:g},{y:g}" for x,y in part.points),.6,
                       'data-unmeasured-route="true"'))
    elif part.kind == "gauge" and part.gauge_diameter_mm is not None:
        # Radial gauge: h is measured from the threaded end to the centre,
        # NOT half an invented through-flow body length.
        r = part.gauge_diameter_mm / (2 * scale)
        cy = a[1] - part.gauge_center_height_mm / scale
        g += [_line(a[0],a[1],a[0],cy+r,.6), gauge(x,cy,radius=r)]
        if not symbols_only:
            g.append(_text(x+r+3,cy+1,part.mark,3.5))
    elif part.length_mm is not None and not horizontal:
        top, bottom = sorted((a[1], b[1]))
        g.append(f'<g data-vu-scaled-symbol="{part.id}">')
        if part.kind == "meter":
            g.append(vertical_meter(x,y,length=bottom-top,width=2*_symbol_half_height(part,scale)))
        elif part.kind in ("shutoff", "gauge_cock"):
            g.append(f'<g transform="rotate(90,{x:g},{y:g})">'+
                     shutoff(x,y,size=(bottom-top)/2,ball=is_ball_cock(part.catalogue_id))+'</g>')
        elif part.kind == "plug":
            g += [_line(*a,*b,.6),_line(x-3,b[1],x+3,b[1],.6)]
        else:
            g.append(_line(*a,*b,.6))
        g.append('</g>')
        if symbols_only:
            return ''.join(g) + '</g>'
        half_height=_symbol_half_height(part,scale)
        mark_offset = max(18 if control else 6,half_height+3)
        mx, anchor = mark_position or (x+mark_offset, 'start')
        g.append(_text(mx,y+1 if mark_y is None else mark_y,part.mark,3.5,anchor))
        # A short plug is identified by its SO mark; avoid a fake extension of
        # its scale envelope merely to fit a number between dimension ticks.
        if include_dimension and part.kind in ("shutoff", "gauge_cock"):
            side = 1 if control else -1
            dx=x+side*max(8,half_height+5)
            tx=dx+(3.5 if control else -2)
            g += [_line(x+side*(half_height+1),top,dx+side*2,top,.25),
                  _line(x+side*(half_height+1),bottom,dx+side*2,bottom,.25),
                  _line(dx,top,dx,bottom,.25),
                  _line(dx-1,top+1,dx+1,top-1,.25),
                  _line(dx-1,bottom+1,dx+1,bottom-1,.25),
                  f'<g transform="rotate(-90,{tx:g},{y:g})">'+
                  _text(tx,y,f"{part.length_mm:g}".replace('.',','),3.5,'middle')+'</g>']
    elif part.length_mm is not None and horizontal:
        w = b[0]-a[0]
        half_height=_symbol_half_height(part,scale)
        # The actual UGO, not UGO + two pipe tails, must occupy the entire L.
        # Draw closed symbols without a pipe through their white interior.
        g.append(f'<g data-vu-scaled-symbol="{part.id}">')
        if part.kind == "meter":
            g.append(ugo.meter(x,y,rw=w,rh=half_height*2,ext=0,w=.35))
        elif part.kind == 'flexible_connection':
            g.append(flexible_insert(a[0], b[0], y))
        elif part.kind in ("shutoff", "gauge_cock"):
            g.append(shutoff(x,y,electric=part.electric,size=w/2,
                             ball=is_ball_cock(part.catalogue_id)))
        elif part.kind == "strainer":
            g.append(ugo.filt(x,y,hd=w/2,vd=half_height,ext=0,w=.35))
        elif part.kind == "check":
            g.append(shutoff(x,y,size=w/2,check=True))
        elif part.kind in ("tee", "cross"):
            branch = part.branch_length_mm / scale
            g.append(_line(*a,*b,.6))
            signs = (-1,1) if part.kind == "cross" else ((1,) if part.id in ("service_after", "maintenance_in", "maintenance_out") else (-1,))
            for sign in signs:
                by = y + sign * branch
                g += [_line(x,y,x,by,.6), _line(x-1,by,x+1,by,.35)]
            g += [_line(a[0],y-1,a[0],y+1,.35),_line(b[0],y-1,b[0],y+1,.35)]
        elif part.kind in ("nipple", "fitting"):
            symbol = connector(a[0],b[0],y,catalogue_id=part.catalogue_id,
                               pipe_on_left=part.id in ('connection_inlet_valve_in_connector',
                                                        'connection_filter_in_connector',
                                                        'connection_bypass_valve_in_connector'))
            g.append(symbol if symbol is not None else _line(a[0],y,b[0],y,.6))
        elif part.id.startswith("reducer_"):
            # Unlike K1, VU can reduce at entry and expand at exit.
            d = (f"M{a[0]} {y-2} V{y+2} L{b[0]} {y} Z" if part.kind=="reducer_reduce"
                 else f"M{a[0]} {y} L{b[0]} {y-2} V{y+2} Z")
            g.append(f'<path d="{d}" fill="white" stroke="black" stroke-width=".35"/>')
        else:
            g.append(_line(a[0],y,b[0],y,.6))
        g.append('</g>')
        if symbols_only:
            return ''.join(g) + '</g>'
        prefix = {"maximum": "≤", "minimum": "≥", "free": "L0=", "installed": "Lм="}.get(part.dimension_basis, "")
        # Dimensions and labels clear the actual, now fully scaled UGO.
        level = _dimension_offset(part,scale)
        g.append(_dimension(a[0],b[0],y+level,prefix+f"{part.length_mm:g}".replace(".",","),y,
                            half_height=half_height))
        if part.mark and part.mark!="—":
            # A tee's vertical branch owns its centreline: place the position
            # beside it, never print the mark across the pipe.
            tx = x+3 if part.kind in ("tee", "cross") else x
            g.append(_text(tx,y-max(7,half_height+3.5),part.mark,3.5,
                           "start" if part.kind in ("tee", "cross") else "middle"))
    elif part.kind == "meter" and not horizontal:
        # No invented catalogue L for an unselected meter; only a paper icon.
        sign = 1 if b[1] > a[1] else -1
        g += [_line(*a,x,y-sign*1.5,.6), vertical_meter(x,y,length=3,width=3),
              _line(x,y+sign*1.5,*b,.6)]
    else:
        g.append(_line(*a,*b,.6))
        if part.kind == "meter":
            g.append(ugo.meter(x,y,rw=3,rh=3,ext=0,w=.35))
        elif part.kind == "shutoff":
            symbol=shutoff(x,y,electric=part.electric,size=2.1,
                           ball=is_ball_cock(part.catalogue_id))
            g.append(symbol if horizontal else f'<g transform="rotate(90,{x:g},{y:g})">{symbol}</g>')
        elif part.kind == "strainer":
            g.append(ugo.filt(x,y,hd=2.5,vd=3,ext=0,w=.35))
        elif part.kind == 'flexible_connection':
            g.append(flexible_insert(a[0], b[0], y))
        elif part.kind == "check":
            g.append(shutoff(x,y,size=2.5,check=True))
        elif part.kind == "nipple":
            g += [_line(x-2,y-2,x-2,y+2,.35),_line(x+2,y-2,x+2,y+2,.35)]
        elif part.kind == "meter_union":
            # Symbolic detail, not an inferred tail length or nut envelope.
            # The nut and gasket belong to ONE kit, not extra SO nodes.
            toward = 1 if part.id == "kit_in" else -1
            nx = x + toward
            gx = x + toward * 3
            g += [f'<rect data-kit-union-nut="{part.id}" x="{nx-1.1:g}" y="{y-3:g}" width="2.2" height="6" '
                  'fill="white" stroke="black" stroke-width=".35"/>',
                  _line(nx-1.1,y-1.8,nx+1.1,y-1.8,.25), _line(nx-1.1,y+1.8,nx+1.1,y+1.8,.25),
                  _line(gx,y-2.5,gx,y+2.5,.65,f'data-kit-gasket="{part.id}"')]
        elif part.id == "gauge":
            g.append(gauge(x,y))
        elif "cock" in part.id or part.id=="fire_valve":
            symbol = shutoff(x,y,electric=part.electric,size=2.1,
                             ball=is_ball_cock(part.catalogue_id))
            g.append(symbol if horizontal else f'<g transform="rotate(90,{x:g},{y:g})">{symbol}</g>')
        elif "cap" in part.id:
            g.append(_line(b[0],b[1]-2,b[0],b[1]+2,.6) if horizontal
                     else _line(b[0]-2,b[1],b[0]+2,b[1],.6))
        elif part.id in ("kit_in","kit_out"):
            g += [_line(x-1,y-2.5,x-1,y+2.5,.35),_line(x+1,y-2.5,x+1,y+2.5,.35)]
        if not symbols_only and part.mark and part.mark!="—":
            mx, anchor = mark_position or (x+(3 if control else 6), 'start')
            g.append(_text(x,y-7,part.mark,3.5,"middle") if horizontal
                     else _text(mx,y+1 if mark_y is None else mark_y,part.mark,3.5,anchor))
    g.append('</g>')
    return ''.join(g)


def _connection_svg(link):
    """Docked UGO touch; a branch route visibly joins its declared endpoints.

    A solid schematic connection is not an approved fitting or pipe length.
    Render only real graph edges, never a background axis through every UGO.
    """
    from app.pz.metering_detail import _line
    a,b = link.points
    touching = a == b
    return (f'<g data-vu-link="{escape(link.before+">"+link.after)}" '
            'data-mounting-unresolved="true" '
            f'data-link-ink="{"docked" if touching else "solid"}">'
            + ('' if touching else _line(*a,*b,.6,'data-schematic-connection="true"')) + '</g>')


def _vertical_mark_positions(layout):
    """Short catalogue caps must not merge their position with the cock's.

    Space text only; never extend a physical UGO to accommodate the font.
    """
    columns = {}
    for part in layout.parts:
        if (len(part.points) == 2 and part.points[0][0] == part.points[1][0]
                and part.kind != 'gauge' and part.mark and part.mark != '—'):
            columns.setdefault(part.center[0],[]).append(part)
    positions = {}
    for parts in columns.values():
        previous = float('-inf')
        for part in sorted(parts,key=lambda p:p.center[1]):
            positions[part.id] = max(part.center[1]+1,previous+5.5)
            previous = positions[part.id]
    return positions


def _control_mark_positions(layout, mark_y):
    """Put paired drain marks outside the pair, clear of body dimensions.

    A catalogue cock and an unresolved cap share a label column; their
    different dimension status must not move the cap number onto the UGO.
    Only annotations move, never service-branch geometry or product lengths.
    """
    positions = {}
    from app.pz.metering_detail import _label_width
    if any(p.id == 'maintenance_cock_in' for p in layout.parts):
        # Four neighbouring service branches, not the old two-control layout.
        # Repeated dimensions are shown once on the first (left) takeoff.
        # Keep each pair's marks next to its own branch, never over the next.
        groups = [('maintenance_cock_in','maintenance_cap_in'),
                  ('control_cock_1','control_cap_1'), ('control_cock_2','control_cap_2'),
                  ('maintenance_cock_out','maintenance_cap_out')]
        for index, names in enumerate(groups):
            parts = [p for p in layout.parts if p.id in names]
            half = max(_symbol_half_height(p,layout.scale) for p in parts)
            x = parts[0].center[0]
            offset = half+3
            position = (x-offset,'end') if index==0 else (x+offset,'start')
            positions.update((p.id,position) for p in parts)
        return positions
    for number in (1, 2):
        parts = [p for p in layout.parts
                 if p.id in (f'control_cock_{number}', f'control_cap_{number}')]
        if not parts:
            continue
        half_height = max(_symbol_half_height(p, layout.scale) for p in parts)
        x = parts[0].center[0]
        has_dimension = any(p.length_mm is not None and p.kind == 'shutoff' for p in parts)
        # Control dimensions are on the right. The second column clears
        # their number lane; the first column sits to the left of its UGO.
        offset = max(18 if has_dimension else 3, half_height+3)
        position = ((x-half_height-3, 'end') if number == 1
                    else (x+offset, 'start'))
        positions.update((p.id, position) for p in parts)
        if number == 1 and all(layout.part(n).kind == 'meter_union' for n in ('kit_in', 'kit_out')):
            meter = layout.part('meter')
            bracket_y = max(155, meter.center[1]+_dimension_offset(meter, layout.scale)+6)
            captions = [(bracket_y+6, 'Штатный комплект'), (bracket_y+12, 'Без врезок')]
            cx = (layout.part('kit_in').points[0][0]+layout.part('kit_out').points[-1][0])/2
            overlaps = any(
                position[0]-_label_width(p.mark, 3.5) < cx+_label_width(text, 3.5)/2+2
                and position[0] > cx-_label_width(text, 3.5)/2-2
                and abs(mark_y[p.id]-cy) < 5.5
                for p in parts for cy, text in captions
            )
            if overlaps:
                shift = max(0, bracket_y+17.5-min(mark_y[p.id] for p in parts))
                for p in parts:
                    mark_y[p.id] += shift
    return positions


def layout_contents(project, state=None):
    from app.pz.metering_detail import _text, _lines, _line, drawing_state, _leader
    from app.pz.metering_mounting import resolve_mounting
    from app.pz.metering_spec import build_metering_spec_section
    state = state or drawing_state(project)
    from app.pz.metering_support_drawing import support_contents
    layout = build_metering_layout(project,state)
    title = getattr(project, "node_title", "Водомерный узел. Связная размерная компоновка")
    system = getattr(project, "node_system", "В1")
    g = [_text(28,17,title,5),
         _text(28,25,f"УГО изделий с известной длиной L: М 1:{layout.scale}. Соединения требуют привязки.",3.5)]
    if layout.special_layout_pending:
        title = (f"Сейсмичность {project.building.seismicity} баллов" if project.building.seismic
                 else "Особые условия установки")
        g += ['<g data-special-layout="unresolved">',
              _text(28,34,title + ": проходка, компенсация перемещений и опоры требуют привязки.",3.5), '</g>']
    if layout.issues:
        y=42
        for issue in layout.issues:
            for line in _lines(issue,372,3.5):
                g.append(_text(28,y,line,3.5)); y+=5.5
        return [''.join(g)]
    if layout.orientation.startswith('vertical'):
        from app.pz.metering_vertical_drawing import vertical_contents
        continuation = []
        drawing = vertical_contents(project, state, layout, continuation_pages=continuation)
        return [drawing, *continuation] + support_contents(project, state, layout) + _composition_pages(project, state, layout)
    g.append('<g data-vu-layout="connected" data-installation-ready="false">')
    g.extend(_connection_svg(link) for link in layout.links)
    mark_y = _vertical_mark_positions(layout)
    mark_positions = _control_mark_positions(layout, mark_y)
    g.extend(_part_svg(part,layout.scale,mark_y=mark_y.get(part.id),
                       mark_position=mark_positions.get(part.id),
                       include_dimension=not (project.metering_detail.maintenance_layout=='serviceable'
                           and part.id in ('control_cock_1','control_cock_2','maintenance_cock_out')))
             for part in layout.parts)
    for part in layout.parts:
        if part.id in mark_positions and mark_y[part.id] > part.center[1]+1.1:
            mx, anchor = mark_positions[part.id]
            side = -1 if anchor == 'end' else 1
            edge = part.center[0]+side*(_symbol_half_height(part,layout.scale)+.5)
            g.append(_line(edge,part.center[1],mx-side*.5,mark_y[part.id]-1,.25))
    g.append('</g>')
    meter=layout.part('meter')
    meter_half_height=_symbol_half_height(meter,layout.scale)
    g += [_leader('layout-meter',(meter.center[0],meter.center[1]-meter_half_height), (meter.center[0]-15,100),
                  meter.center[0]-50,"Счётчик","Поз. " + meter.mark),
          _text(layout.part('inlet').center[0],118,system,3.5,'middle'),
          _text(layout.part('outlet').center[0],118,system,3.5,'middle')]
    if all(layout.part(n).kind == "meter_union" for n in ("kit_in", "kit_out")):
        a,b=layout.part('kit_in').points[0][0],layout.part('kit_out').points[-1][0]
        bracket_y=max(155,meter.center[1]+_dimension_offset(meter,layout.scale)+6)
        g += ['<g data-protected-meter-kit="true">',
              _path_bracket(a,b,bracket_y),
              _text((a+b)/2,bracket_y+6,"Штатный комплект",3.5,'middle'),
              _text((a+b)/2,bracket_y+12,"Без врезок",3.5,'middle'),'</g>']
    if state.core_bypass:
        v=layout.part('bypass_valve')
        g.append(_text(v.center[0],44,"Обводная линия",3.5,'middle'))
    if state.fire_branch and not state.common_inlets:
        v=layout.part('fire_outlet')
        g.append(_text(v.center[0]-5,v.points[-1][1]-3,"В2 до учёта",3.5))
    audit=resolve_mounting(project,state)
    bad=[c for c in audit.joint_checks if c.status=='incompatible']
    if bad:
        c=bad[0]; a,b=layout.part(c.before),layout.part(c.after)
        mid=((a.points[-1][0]+b.points[0][0])/2, a.points[-1][1])
        g.append(_leader('joint-problem',mid,(mid[0]-10,172),max(32,mid[0]-71),
                         'Стык требует детали',f'{c.left.label} / {c.right.label}'))
    elif nipples := [p for p in layout.parts if p.kind=="nipple"]:
        n=nipples[0]; mid=n.center
        # Keep text below the bypass; the nipple dimension uses the lower
        # staggered lane so its number stays clear of this oblique segment.
        g.append(_leader('joint-nipple',(n.points[0][0],mid[1]+min(2.,n.length_mm/layout.scale*.22)
                                       if n.length_mm is not None else mid[1]+2),
                         (mid[0]-10,172),max(32,mid[0]-71),
                         'Ниппель '+n.mark,
                         (f'L корпуса {n.length_mm:g} мм; посадки уточнить'
                          if n.length_mm is not None else 'Модель и длину уточнить')))
    notes = [
        "Изделия соединены условно. Размеры L относятся к корпусам; посадки соединений в них не вычтены.",
        "УГО: ГОСТ Р 21.619-2023, приложение Г; ГОСТ 21.205. Детали С - композиция знаков соединений:",
        "резьбовые / раструбные по ГОСТ 21.206-2012, табл. 1; резьбовые концы по ГОСТ 2.784-96, табл. 1.",
        "Посадки резьбы, толщина сжатых прокладок, отборы, опоры и пространство обслуживания требуют привязки.",
        "По этой компоновке нельзя определять раскрой и общий монтажный размер. Количества - из той же модели, что и СО.",
    ]
    if any(p.dimension_basis == "minimum" for p in layout.parts):
        notes[1] = "УГО оборудования: ГОСТ Р 21.619-2023, приложение Г; ГОСТ 21.205. Размеры из каталогов изготовителей."
        notes[2] = "Прямые участки с ≥: паспортный минимум выбранного водомера, не раскрой трубы. Фланцы требуют проверки стыков."
    if any(p.kind == 'flexible_connection' for p in layout.parts):
        notes.append('Вставка: ГОСТ 21.205-2016, табл. 4, 6а. L0 — свободная длина; Lм — после заданного сжатия. Не общий размер узла.')
    y=200
    if project.metering_detail.service_selection_mode == 'catalogue_proposal' or project.metering_detail.service_items:
        g += [_text(28,184,"Сервисные изделия: подбор по текущему P/T; состав отборов к магистрали требует привязки.",3.5),
              _text(28,190,"Источники: VALTEC ПС 47639-4, ПС 47605, VT.214; РОСМА ТМ серии 10. Проверено 12.10.2026.",2.5)]
    notes.extend(_gauge_cock_dimension_notes(layout))
    for note in notes:
        for line in _lines(note,372,3.5):
            g.append(_text(28,y,line,3.5)); y+=5.5
    from app.data.metering_products import get_metering_catalogue
    catalog=get_metering_catalogue()
    kit=catalog.connection_kits.get(layout.part('kit_in').catalogue_id)
    if kit and kit.contents:
        ref='; '.join(catalog.sources[s]['title'] for s in kit.source_ids)
        for line in _lines('Комплект: '+ref+'. Раздел 5, рисунок 1. Поставка уточняется при заказе.',372,2.5):
            g.append(_text(28,y+1,line,2.5)); y+=4
    return [''.join(g)] + support_contents(project, state, layout) + _composition_pages(project, state, layout)


def _composition_pages(project, state, layout):
    from app.data.metering_products import get_metering_catalogue
    from app.pz.metering_detail import _text, _lines, _line
    from app.pz.metering_spec import build_metering_spec_section
    catalog = get_metering_catalogue()
    pages = []
    def start():
        return [_text(28,17,(project.node_title + ". Состав" if getattr(project,"metering_node","") else
                             "ВУ. Состав компоновки и незавершённые соединения"),5),
                _text(28,25,f"Один изображённый узел; количество одинаковых узлов в проекте: {state.assemblies_count}.",3.5),
                _text(30,35,"Поз.",3.5),_text(51,35,"Наименование и исполнение",3.5),
                _text(339,35,"Всего в проекте",3.5)]
    def close_page(g, y):
        # Close every sheet, including continuations. Empty rows are drawing
        # grid only: never additional equipment or a repeated quantity.
        g.append('<g data-vu-composition-grid="true">')
        for x in (28, 48, 335, 405):
            g.append(_line(x,29,x,224,.25))
        g.append(_line(28,29,405,29,.25))
        while y < 224:
            g.append(_line(28,y,405,y,.25))
            y += 8
        g.extend((_line(28,224,405,224,.25), '</g>'))
        return ''.join(g)
    g=start(); y=39
    rows=[r for r in build_metering_spec_section(project).rows if r.component_ids
          or r.quantity_basis in ("metering_mounting_reference", "explicit_vu_supports", "metering_special_requirement", "metering_flange_requirement", "explicit_vu_accessory")]
    for row in rows:
        # Display the SAME specification quantities, including the one kit
        # owning both meter ends. Never count drawn symbols as purchase items.
        caption=row.name+(' | '+row.type_mark if row.type_mark else '')
        if row.quantity_basis == "explicit_vu_accessory" and row.manufacturer:
            caption += ' | ' + row.manufacturer
        if row.quantity_basis == "metering_special_requirement":
            caption = row.name + " " + row.quantity_source
        local_pos = row.diagram_pos.removeprefix('Г.')
        if row.catalogue_id and local_pos in ('3.1','3.2','4.1','4.2','4.3','4.4'):
            if 'Предварительное каталожное предложение' in row.note:
                caption += '. Предварительно'
            if local_pos == '3.2':
                product = catalog.service_products.get(row.catalogue_id)
                if product:
                    caption += '. ' + product.notes[0]
        if row.catalogue_id and any(i.startswith('joint_') for i in row.component_ids):
            caption += '. ' + row.note
        if any(i.startswith('flex_') for i in row.component_ids):
            caption += '. ' + row.note
        if row.quantity_basis == "metering_mounting_reference":
            caption += '. ' + row.note
        if row.quantity_basis == 'explicit_vu_support_points':
            caption += '. Предварительный состав; крепление и нагрузка требуют проверки'
        if row.quantity_basis == "metering_flange_requirement":
            caption += '. Исполнение и количество по стыкам уточнить'
        for ident in row.component_ids:
            if ident in ('kit_in', 'kit_out') and layout.part(ident).dimension_basis == 'minimum':
                caption += f'. Не менее {layout.part(ident).length_mm:g} мм; не раскрой трубы'
        if 'kit_in' in row.component_ids and row.catalogue_id:
            kit=catalog.connection_kits.get(row.catalogue_id)
            if kit and kit.contents:
                caption += '. В комплекте: ' + '; '.join(f'{title} - {qty} шт.' for title,qty in kit.contents)
        body=_lines(caption,260,3.5)
        height=max(8,len(body)*5+3)
        if height > 224-39:
            raise ValueError('Строка состава ВУ выше поля листа: '+row.name)
        if y+height>224:
            pages.append(close_page(g,y)); g=start(); y=39
        g.append(_line(28,y,405,y,.25))
        g.append(_text(30,y+6,row.diagram_pos or '—',3.5))
        for i,line in enumerate(body):
            g.append(_text(51,y+6+i*5,line,3.5))
        quantity=('требование' if row.quantity_basis in ("metering_special_requirement", "metering_flange_requirement")
                  else 'в общем метраже' if row.quantity_basis == "metering_mounting_reference"
                  else 'уточнить' if row.qty is None else f'{row.qty:g} {row.unit}')
        g.append(_text(339,y+6,quantity,3.5))
        y+=height
    pages.append(close_page(g,y))
    return pages


def _path_bracket(a,b,y):
    from app.pz.metering_detail import _path
    return _path(f'M{a:g} {y-2:g} V{y:g} H{b:g} V{y-2:g}',.25)


def _gauge_cock_dimension_notes(layout):
    """Never let an unresolved instrument cock silently masquerade as scaled."""
    notes = []
    for part in layout.parts:
        if part.id != 'gauge_cock':
            continue
        if part.length_mm is None:
            notes.append(f'Поз. {part.mark}: УГО крана манометра вне масштаба; паспортная длина не задана.')
        elif part.dimension_basis == 'passport_nominal':
            notes.append(f'Поз. {part.mark}: L={part.length_mm:g} мм по паспорту; расхождение с отдельным чертежом см. на листе состава.')
    return notes
