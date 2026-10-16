"""Independent hot/heater meter view of the EXISTING calculation.

This is a drawing/specification context, not a second hydraulic project.
The common inlet's lengths, products, room, bypass and fire takeoff never
become branch inputs. Unknown branch geometry remains explicitly unknown.
"""
from dataclasses import dataclass, replace

from app.pz.metering_detail_data import MeteringDetailData
from app.pz.metering_mounting import MeteringMounting
from app.pz.meter_validation import meter_node_key


@dataclass(frozen=True)
class HotMeterView:
    original: object
    metering_detail: MeteringDetailData
    node_meter: object | None
    node_title: str
    node_system: str
    metering_node: str = "hot"

    def __getattr__(self, name):
        return getattr(self.original, name)

    @property
    def fire(self):
        # The building's fire decision stays untouched. It is not a branch
        # of this meter, even when the common inlet has a pre-meter В2 takeoff.
        return replace(self.original.fire, required=False)


def hot_meter_view(project):
    if getattr(project, "metering_node", ""):
        return None
    rows = [r for r in project.meters.rows if meter_node_key(r) == "hot"
            and "кварт" not in r.label.casefold()]
    if not rows:
        return None
    row = rows[0] if len(rows) == 1 else None
    before_heater = bool(row and "нагревател" in row.label.casefold())
    d = project.metering_detail
    from app.pz.metering_orientation import meter_orientation
    axis = meter_orientation(d, "hot")
    # Retain global procurement/meter selection and the paper scale only.
    # No cold temperature, DN inlet, kit, support count or room is inherited.
    detail = MeteringDetailData(
        catalogue_revision=d.catalogue_revision,
        meter_selection_mode=d.meter_selection_mode,
        meter_products={"hot": d.meter_products["hot"]} if "hot" in d.meter_products else {},
        meter_mounting=axis, assembly_orientation=(axis if axis != "unknown" else "horizontal_dial_up"),
        # Copy only an authored override. With none, meter_mounting retains
        # the scalar fallback (including valid "unknown"); promoting that
        # fallback to a per-node override would make valid old data invalid.
        # Explicit malformed overrides must still reach validate().
        meter_orientations={"hot": d.meter_orientations["hot"]}
        if "hot" in d.meter_orientations else {},
        inline_joint_selection_mode=d.inline_joint_selection_mode,
        service_selection_mode=d.service_selection_mode,
        russian_equipment_only=d.russian_equipment_only,
        enhancements={"technology": d.enhancements["technology"]} if "technology" in d.enhancements else {},
        mounting=MeteringMounting(enabled=True, scale=d.mounting.scale),
    )
    return HotMeterView(project, detail, row,
        "ВУ-Г. Учёт перед водонагревателем" if before_heater else "ВУ-Г. Узел учёта ГВС",
        "В1" if before_heater else "Т3")


def hot_drawing_state(view):
    from app.pz.metering_detail import MeteringDrawingState
    from app.pz.meter_validation import check_meter_average
    row = view.node_meter
    missing = ["DN подводящей трубы и номер помещения узла ГВС уточнить"]
    if view.meters.selection_error:
        row = None
        missing.append("Подбор водомера не подтверждён")
    if row:
        ok, note = check_meter_average(row, view.flows, view.source)
        if ok is False:
            row = None
            missing.append(note)
        elif ok is None:
            missing.append(note)
    if row is None or row.dn <= 0:
        row = None
        missing.append("Нет однозначного расчётного водомера ГВС")
    elif not row.ok_a:
        missing.append("Потери на водомере превышают допустимые")
    return MeteringDrawingState(1, row, False, False, False, False, tuple(missing), "hot")


def hot_spec_section(project):
    """Namespaced ownership: one hot assembly, not one per cold inlet."""
    view = hot_meter_view(project)
    if view is None:
        return None
    from app.pz.metering_spec import build_metering_spec_section
    section = build_metering_spec_section(view)
    for row in section.rows:
        row.component_ids = tuple("hot:" + ident for ident in row.component_ids)
    return section


def hot_detail_contents(project):
    view = hot_meter_view(project)
    if view is None:
        return []
    from app.pz.metering_layout import layout_contents
    from app.pz.metering_detail import _text, _lines, _panel_rows
    state = hot_drawing_state(view)
    pages = layout_contents(view, state)
    # Full-size evidence on a separate sheet, never squeezed over the scheme.
    g = [_text(28, 17, view.node_title + ". Данные и условия", 5)]
    y = 31
    for title, value in _panel_rows(view, state):
        for line in _lines(title + ": " + value, 372, 3.5):
            g.append(_text(28, y, line, 3.5)); y += 5.5
        y += 2
    notes = [
        "Помещение № и DN подводящей трубы не заданы. DN счётчика не подменяет DN трубопровода.",
        "Запорная арматура с двух сторон, два контрольных крана с заглушками: СП 30, п. 12.9.",
        "Второй контрольный кран — не далее 0,5 м после запорного; прямые участки — по паспорту.",
        "Фильтр и обратный клапан: п. 12.13; применимость фильтра уточнить по материалу труб и паспорту.",
        ("ГВС: обводная не требуется по п. 12.12; пожарная ветвь к узлу не относится."
         if view.node_system == "Т3" else
         "Показан учёт холодной воды перед нагревателем, не ввод здания и не циркуляция Т4."),
        "Показан один расчётный узел ветви. Количество не умножено на вводы ХВС.",
        "Рабочие P/T, помещение, материалы, соединения и монтажная привязка этого узла уточняются отдельно.",
        "Сигнал дистанционного считывания — по паспорту и заданию автоматизации, не подтверждение готовой АСКУЭ.",
    ]
    from app.pz.metering_product_selection import resolve_metering_products
    selection = resolve_metering_products(view, state.meter, bypass=False, electric_bypass=False)
    notes += list(dict.fromkeys([*state.missing, *selection.errors]))
    for note in notes:
        lines = _lines(note, 372, 3.5)
        if y + len(lines)*5.5 > 225:
            pages.append("".join(g)); g = [_text(28,17,view.node_title + ". Условия (продолжение)",5)]; y = 31
        for line in lines:
            g.append(_text(28, y, line, 3.5)); y += 5.5
    pages.append("".join(g))
    from app.pz.metering_maintenance import maintenance_contents
    pages.extend(maintenance_contents(view,state))
    return pages
