"""Dimension chain in real mm, never measured from SVG or inferred from DN.

The logical VU remains the source of composition. Every physical span/joint
must have an explicit size and evidence. Partial data produces partial chains,
NOT a plausible-looking complete installation. Hydraulics are not changed.
"""
from dataclasses import dataclass, field
from math import isfinite


@dataclass
class MeteringMounting:
    enabled: bool = False
    scale: int = 5
    # Axial installed extents of non-catalogue nodes, or meter kit halves.
    # Each entry: length_mm, source, [above_axis_mm, below_axis_mm].
    spans: dict = field(default_factory=dict)
    # Consecutive IDs separated by '>'. One dimension only: overlap_mm is
    # subtracted (thread engagement), face_gap_mm added (compressed gasket).
    # No default zero for either kind. Sources refer to installed dimensions.
    joints: dict = field(default_factory=dict)
    # Total lengths of pipe stock, NOT sum of drawing gaps. No auto cutting.
    pipe_cuts: dict = field(default_factory=dict)
    support_count: int | None = None
    support_basis: str = ""
    # Individual permanent points; old aggregate quantities remain separate.
    supports: dict = field(default_factory=dict)
    # Declared available/required service clearances, not body dimensions.
    service_spaces: dict = field(default_factory=dict)

    def validate(self):
        errors = []
        from app.pz.metering_supports import validate_supports
        errors.extend(validate_supports(self.supports))
        if self.supports and self.support_count is not None:
            errors.append('supports: нельзя одновременно задавать точки и общее количество опор')
        if type(self.enabled) is not bool:
            errors.append("enabled: требуется да/нет")
        if type(self.scale) is not int or self.scale not in (1, 2, 5, 10, 20, 25, 50):
            errors.append("scale: допустимы 1:1, 1:2, 1:5, 1:10, 1:20, 1:25, 1:50")
        fields = {"spans": ("length_mm",), "joints": (),
                  "pipe_cuts": ("length_mm",), "service_spaces": ("required_mm", "available_mm")}
        for name, numbers in fields.items():
            mapping = getattr(self, name)
            if not isinstance(mapping, dict) or len(mapping) > 300:
                errors.append(f"{name}: требуется словарь (до 300 записей)")
                continue
            for ident, row in mapping.items():
                if not isinstance(ident, str) or not isinstance(row, dict):
                    errors.append(f"{name}: неверная запись")
                    continue
                if not isinstance(row.get("source"), str) or not row["source"].strip():
                    errors.append(f"{name}.{ident}: нужно основание размера")
                keys = numbers
                if name == "joints":
                    keys = tuple(k for k in ("overlap_mm", "face_gap_mm") if k in row)
                    if len(keys) != 1:
                        errors.append(f"joints.{ident}: задайте только посадку overlap_mm либо сжатую прокладку face_gap_mm")
                for key in keys:
                    n = row.get(key)
                    if type(n) not in (int, float) or not isfinite(n) or n < 0 or n > 100000:
                        errors.append(f"{name}.{ident}.{key}: нужен размер 0-100000 мм")
                    elif key in ("length_mm", "face_gap_mm") and n == 0:
                        errors.append(f"{name}.{ident}.{key}: размер должен быть положительным")
        if self.support_count is not None and (type(self.support_count) is not int or not 0 <= self.support_count <= 100):
            errors.append("support_count: целое число 0-100")
        if not isinstance(self.support_basis, str) or (self.support_count is not None and not self.support_basis.strip()):
            errors.append("support_basis: нужно основание схемы опор")
        return errors


@dataclass(frozen=True)
class MountingSpan:
    id: str
    title: str
    length_mm: float | None
    source: str
    catalogue_id: str = ""


@dataclass(frozen=True)
class MountingChain:
    id: str
    title: str
    spans: tuple[MountingSpan, ...]
    # None prevents displaying a made-up overall dimension.
    length_mm: float | None
    offsets_mm: tuple[float, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True)
class MountingResult:
    chains: tuple[MountingChain, ...]
    issues: tuple[str, ...]
    pipe_lengths_m: dict
    support_count: int | None
    joint_checks: tuple = ()

    @property
    def dimensions_complete(self):
        return bool(self.chains) and not self.issues and all(c.length_mm is not None for c in self.chains)


def joint_axial_delta(row, check):
    """Signed, sourced distance between adjacent body end faces.

    A gasket separates two faces. Subtracting its thickness as thread overlap
    is a real length-chain error, even when every product L is correct.
    Caller validates numerical inputs through MeteringMounting first.
    """
    if check is None or check.status != "ports_match":
        return None, "Сопряжение деталей не подтверждено; размер стыка не разрешает несовместимое соединение"
    if check.left.seal == "flat_gasket":
        if "face_gap_mm" not in row:
            return None, "Для торцевого стыка нужна толщина сжатой прокладки face_gap_mm, не глубина свинчивания"
        return row["face_gap_mm"], ""
    if "overlap_mm" not in row:
        return None, "Для резьбового стыка нужна посадка overlap_mm, не толщина прокладки"
    return -row["overlap_mm"], ""


def resolve_mounting(project, state=None, selection=None):
    from app.data.metering_products import get_metering_catalogue
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_pipes import PIPE_ROLES
    d = project.metering_detail
    m = d.mounting
    if errors := m.validate():
        return MountingResult((), tuple(errors), {}, None)
    state = state or drawing_state(project)
    selection = selection or resolve_metering_products(project, state.meter,
        bypass=state.bypass, electric_bypass=state.electric_bypass)
    chain = build_metering_chain(d, state, selection)
    catalog = get_metering_catalogue()
    from app.pz.metering_joint_audit import audit_direct_joints, meter_kit_topology_issues
    joint_checks = audit_direct_joints(chain, catalog, inlet_dn=d.inlet_dn)
    checks_by_id = {c.id: c for c in joint_checks}
    kit_issues = meter_kit_topology_issues(chain, catalog)
    products = {**catalog.products, **catalog.connectors, **catalog.thread_connectors, **catalog.reducers,
                **catalog.service_products, **catalog.fittings}
    active = {n.id for n in chain.nodes}
    edges = {f"{a}>{b}" for a, b in chain.links}
    issues = list(selection.errors)
    from app.pz.metering_rules import seismic_metering_rules, special_layout_pending
    if special_layout_pending(project):
        issues.append("Специальная компоновка ВУ не сформирована; размеры обычной обвязки "
                      "не подтверждают проходку, компенсацию перемещений и опоры")
        issues.extend(f"{rule.code}: {rule.message}" for rule in seismic_metering_rules(project))
    issues.extend(kit_issues)
    issues.extend(f"Стык {c.id}: {c.reason} ({c.left.label} / {c.right.label})"
                  for c in joint_checks if c.status == "incompatible")
    for key in m.spans.keys() - active:
        issues.append(f"Размер {key}: элемент отсутствует в текущем ВУ")
    for key in m.joints.keys() - edges:
        issues.append(f"Стык {key}: связь отсутствует в текущем ВУ")
    # Branch anchor nodes belong to the main chain and are not purchased twice.
    results = []
    for path in chain.paths:
        spans, local = [], list(kit_issues) if path.id == "main" else []
        ids = path.nodes if path.id == "main" else tuple(n for n in path.nodes if n not in chain.paths[0].nodes)
        for ident in ids:
            node = chain.node(ident)
            product = products.get(node.catalogue_id)
            length = product.body_length_mm if product else None
            source = "; ".join(product.source_ids) if length is not None else ""
            if product and getattr(product, "dimension_basis", "") == "passport_nominal":
                local.append(f'{node.title}: паспортный размер принят только для компоновки; расхождение источников и монтажную длину уточнить')
            if node.role == 'flexible_connection':
                check = next(c for c in selection.flexible_connections if 'flex_'+c['role']==ident)
                length = check['installed_length_mm'] if not check['errors'] else None
                source = 'Паспорт выбранной вставки; L0 минус явно заданное предварительное сжатие' if length is not None else ''
            if product and getattr(product, "dimension_basis", "nominal") == "maximum":
                # Upper envelope is not a guaranteed mating-face distance.
                length, source = None, ""
            entered = m.spans.get(ident)
            if entered:
                if product and getattr(product, 'kind', '') == 'elbow90':
                    local.append(f'{node.title}: поворот имеет два размера A; один ручной L не задаёт его геометрию')
                elif node.role == 'flexible_connection' and length is None:
                    local.append(f'{node.title}: ручной размер не заменяет выбор изделия и предварительного сжатия')
                elif node.minimum_length_mm is not None and entered["length_mm"] < node.minimum_length_mm:
                    local.append(f"{node.title}: меньше паспортного минимума {node.minimum_length_mm:g} мм")
                elif product and getattr(product, "dimension_basis", "nominal") == "maximum" and entered["length_mm"] > product.body_length_mm:
                    local.append(f"{node.title}: размер больше паспортного предельного габарита")
                elif length is not None and abs(entered["length_mm"] - length) > 1e-6:
                    local.append(f"{node.title}: ручной размер расходится с паспортным L={length:g} мм")
                elif length is None:
                    length, source = entered["length_mm"], entered["source"]
            if length is None:
                local.append(f"{node.title}: нет подтверждённого осевого размера")
            spans.append(MountingSpan(ident, node.title, length, source, node.catalogue_id or ""))
        offsets, x = [], 0.
        for i, span in enumerate(spans):
            if i:
                key = f"{spans[i-1].id}>{span.id}"
                joint = m.joints.get(key)
                if joint is None:
                    local.append(f"Стык {key}: не заданы посадка/прокладка")
                else:
                    delta, error = joint_axial_delta(joint, checks_by_id.get(key))
                    if error:
                        local.append(f"Стык {key}: {error}")
                    overlap = max(0., -(delta or 0.))
                    lengths = (spans[i-1].length_mm, span.length_mm)
                    if any(n is not None and overlap >= n and overlap > 0 for n in lengths):
                        local.append(f"Стык {key}: посадка поглощает соседний элемент")
                    if delta is not None:
                        x += delta
            offsets.append(x)
            x += span.length_mm or 0
        if path.id != "main":
            # Developed branch lengths are not the end-to-end dimensions of a
            # bent bypass. Never stretch a bypass to fit the main pipe spacing.
            local.append(f"{path.title}: нужна пространственная привязка ответвления; показана развёртка деталей")
        elif any(n in ids for n in ('filter_turn_in', 'filter_turn_out')):
            local.append('Основная линия содержит повороты: сумма длин не является габаритом узла или раскроем трубы')
        for i, span in enumerate(spans):
            overlap_sum = sum(m.joints.get(f"{spans[j].id}>{spans[j+1].id}", {}).get("overlap_mm", 0)
                              for j in (i-1, i) if 0 <= j < len(spans)-1)
            if span.length_mm is not None and overlap_sum >= span.length_mm:
                local.append(f"{span.title}: суммарные посадки не оставляют длины корпуса")
        results.append(MountingChain(path.id, path.title, tuple(spans),
                                     x if not local else None, tuple(offsets), tuple(local)))
        issues.extend(local)
    lengths = {}
    active_roles = {r for r in PIPE_ROLES if r not in ("bypass", "fire_branch")
                    or (r == "bypass" and state.core_bypass)
                    or (r == "fire_branch" and state.fire_branch and not state.common_inlets)}
    expected_dns = {"inlet": d.inlet_dn,
                    "before_meter": state.meter.dn if state.meter else None,
                    "after_meter": state.meter.dn if state.meter else None,
                    "bypass": d.bypass_dn, "fire_branch": d.fire_branch_dn}
    for role, row in m.pipe_cuts.items():
        pipe = d.pipe_sections.get(role)
        if role not in active_roles or not pipe or pipe.inner_diameter_mm is None:
            issues.append(f"{role}: раскрой не привязан к активной трубе с заданными размерами")
        elif pipe.material == "unknown" or not pipe.geometry_source.strip():
            issues.append(f"{role}: для метража нужны материал и источник размеров трубы")
        elif role in expected_dns and (expected_dns[role] is None or pipe.nominal_dn != expected_dns[role]):
            issues.append(f"{role}: метраж не принят; DN трубы расходится с текущей схемой")
        else:
            lengths[role] = row["length_mm"] / 1000 * chain.instances
    for ident, space in m.service_spaces.items():
        if ident not in active:
            issues.append(f"{ident}: зона обслуживания относится к отсутствующему элементу")
        elif space["available_mm"] < space["required_mm"]:
            issues.append(f"{ident}: недостаточно места обслуживания ({space['available_mm']:g} < {space['required_mm']:g} мм)")
    return MountingResult(tuple(results), tuple(dict.fromkeys(issues)), lengths,
                          m.support_count * chain.instances if m.support_count is not None else None,
                          joint_checks)


def product_dimension_contents(project, state):
    """Dimensioned product fragments; never scale an unverified assembly.

Only known axial dimensions are drawn; the actual assembled chain is a
separate output and is omitted when even one joint is unknown.
"""
    from app.pz.metering_detail import _text, _line, _lines, _gate, ugo
    from app.data.metering_products import get_metering_catalogue
    result = resolve_mounting(project, state)
    scale = project.metering_detail.mounting.scale
    catalog = get_metering_catalogue()
    products = {**catalog.products, **catalog.connectors, **catalog.thread_connectors, **catalog.reducers,
                **catalog.service_products, **catalog.fittings}
    unique = {}
    for chain in result.chains:
        for span in chain.spans:
            if span.catalogue_id in products:
                unique.setdefault(span.catalogue_id, []).append(span.title)
    pages, g = [], []
    def start():
        return [_text(28,17, f"Водомерный узел. Габаритные фрагменты М 1:{scale}", 5),
                _text(28,25,"Размеры в мм. Осевые длины в масштабе; изображения корпусов условные.",3.5)]
    g = start()
    for i, (ident, roles) in enumerate(unique.items()):
        if i and i % 8 == 0:
            pages.append("".join(g)); g = start()
        col, row = (i % 8) % 2, (i % 8) // 2
        x, y = 28 + col * 192, 32 + row * 48
        p = products[ident]
        title = getattr(p, "name", "") or f"{p.manufacturer} {p.article}"
        for j, line in enumerate(_lines(f"{i+1}. {title}",181,3.5)[:2]):
            g.append(_text(x,y+j*5,line,3.5))
        role = "; ".join(dict.fromkeys(roles))
        g.append(_text(x,y+12,_lines(role,180,2.5)[0],2.5))
        length = p.body_length_mm
        if length is None:
            if getattr(p, 'kind', '') == 'elbow90':
                g.append(_text(x,y+24,f"Поворот 90°; A={p.dimensions_mm['A']:g} мм от оси до торца по обеим ветвям",3.5))
                g.append(_text(x,y+31,"A не является длиной прямого корпуса; размеры показаны на компоновке",2.5))
            elif getattr(p, "kind", "") == "gauge":
                g.append(_text(x,y+24,f"Корпус Ø{p.dimensions_mm['D']:g}; h={p.dimensions_mm['h']:g} до центра от торца штуцера",3.5))
                g.append(_text(x,y+31,"Терминальный прибор: проходная монтажная длина не применяется",2.5))
            else:
                g.append(_text(x,y+30,"Габариты противоречат источникам; отрисовка исключена",2.5))
            continue
        width = length / scale
        if width > 172:
            raise ValueError("Деталь ВУ не помещается: выберите меньший масштаб")
        left, axis = x+6, y+23
        g += [_line(left,axis,left+width,axis,.6),
              _line(left,axis-4,left,axis+13,.25), _line(left+width,axis-4,left+width,axis+13,.25),
              _line(left,axis+10,left+width,axis+10,.25),
              _line(left-1,axis+11,left+1,axis+9,.25),
              _line(left+width-1,axis+11,left+width+1,axis+9,.25)]
        center=left+width/2
        kind=getattr(p,"kind", "fitting")
        # Reuse the established UGO. Symbol height is intentionally schematic;
        # the separate dimension line, not the pictogram, defines the envelope.
        if kind == "meter":
            g.append(ugo.meter(center,axis,rw=min(7,width/2),rh=4,ext=0,w=.35))
        elif kind == "shutoff":
            g.append(_gate(center,axis,size=min(2.8,width/3)))
        elif kind == "gauge_cock":
            from app.pz.metering_ugo import shutoff
            g.append(shutoff(center,axis,size=width/2,ball=True))
        elif kind == "strainer":
            g.append(ugo.filt(center,axis,hd=min(3,width/3),vd=3,ext=0,w=.35))
        bound = "≤ " if getattr(p,"dimension_basis","nominal") == "maximum" else ""
        g.append(_text(left+width/2,axis+8,bound+f"{length:g}",3.5,"middle"))
        # Manufacturer height reference is retained as text; an unknown axis
        # offset may NOT be guessed to create a convincing body envelope.
        heights = [(k,v) for k,v in p.dimensions_mm.items() if k in ("H", "H_total", "B_above_axis", "A_handle", "SW")]
        terms={"H":"H", "H_total":"H общ.", "B_above_axis":"над осью", "A_handle":"рукоять", "SW":"под ключ"}
        dims="; ".join(f"{terms[k]}={v:g}" for k,v in heights)
        g.append(_text(x,y+39,dims or "Поперечный габарит по отдельному чертежу изготовителя",2.5))
        g.append(_text(x,y+44,f"Источник {i+1}; присоединение: " + getattr(p,"thread",getattr(p,"equipment_thread","по паспорту")),2.5))
    if not unique:
        g.append(_text(28,43,"Модели изделий не назначены. Размерная отрисовка пока недоступна.",3.5))
    pages.append("".join(g))
    g = start()
    y=38
    notice="Полный монтажный габарит не подтверждён. Ни DN, ни сумма длин корпусов не заменяют монтажную цепочку. "
    notice+="Паспортные габариты проверены 12.10.2026. Присоединительные комплекты, посадки, ответвления и обслуживание проверяются отдельно."
    for line in _lines(notice,375,3.5):
        g.append(_text(28,y,line,3.5)); y+=5.5
    y+=7
    for i, ident in enumerate(unique):
        p=products[ident]
        refs="; ".join(catalog.sources[s]["title"] for s in p.source_ids)
        for line in _lines(f"{i+1}. {refs}",375,2.5):
            if y>220:
                pages.append("".join(g)); g=start(); y=38
            g.append(_text(28,y,line,2.5)); y+=4.5
    y+=7
    for line in _lines(f"Незакрытых размерных проверок: {len(result.issues)}. "
        "Изготовление и заказ монтажной сборки по этому листу не допускаются. Принципиальная схема и количества изделий сохранены.",375,3.5):
        if y>220:
            pages.append("".join(g)); g=start(); y=38
        g.append(_text(28,y,line,3.5)); y+=5.5
    pages.append("".join(g))
    return pages


def mounting_contents(project, state):
    """One connected composition first, with the detailed catalogue appendix.

    Unknown joins remain marked breaks, not invented pipe pieces. The layout
    consumes the same graph and specification as the existing principle sheet.
    """
    from app.pz.metering_layout import layout_contents
    return layout_contents(project, state) + product_dimension_contents(project, state)
