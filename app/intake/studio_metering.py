"""Optional minimum-flow evidence; no invented minimum-demand formula."""
from dataclasses import asdict, replace

from app.calc.meter_verification import MeterMinimumEvidence
from app.data.metering_products import get_metering_catalogue


MINIMUM_NODES = {
    "total": "Общий ввод",
    "cold": "ХВС",
    "hot": "ГВС / перед водонагревателем",
}

VU_ORIENTATIONS = {
    "horizontal_dial_up": "Горизонтально →",
    "vertical_up": "Вертикально ↑ вверх",
    "vertical_down": "Вертикально ↓ вниз",
}


def minimum_checks(values):
    """Building minima are independent of DN. Current products supply passports.

    Keep incomplete evidence incomplete; zero is an explicit value, not missing.
    Each node has its own source: a total minimum must not be copied to branches.
    """
    result = {}
    for node in MINIMUM_NODES:
        prefix = f"meter_min_{node}_"
        flow = values.get(prefix + "m3h")
        reference = values.get(prefix + "source", "")
        if flow is not None or reference:
            result[node] = asdict(MeterMinimumEvidence(q_min_hourly_m3h=flow,
                                                       flow_reference=reference))
    return result


def catalogue_proposal(detail, *, orientation=None, dimensioned=False):
    """Explicit opt-in shared by Studio and its control case, before calculation.

    Does not accept a purchase, prescribe P/T or alter the hydraulic algorithm.
    Existing manual product assignments still take precedence in the resolver.
    """
    # A supplied Studio choice sets both axes. Other callers retain explicit
    # mixed-axis/manual settings; do not flatten an existing vertical project.
    if orientation is not None:
        if orientation not in VU_ORIENTATIONS:
            raise ValueError("Неизвестная компоновка ВУ")
        detail = replace(detail, assembly_orientation=orientation,
                         meter_mounting=orientation)
    elif detail.meter_mounting == "unknown" and detail.assembly_orientation == "horizontal_dial_up":
        detail = replace(detail, meter_mounting="horizontal_dial_up")
    if dimensioned:
        # Presentation only: match ordinary Studio's optional body-dimension
        # sheets. Never populate mounting lengths or change the chosen scale.
        detail = replace(detail, mounting=replace(detail.mounting, enabled=True))
    return replace(detail, meter_selection_mode="catalogue_proposal",
                   inline_joint_selection_mode="catalogue_proposal",
                   service_selection_mode="catalogue_proposal",
                   catalogue_revision=get_metering_catalogue().revision)


def studio_layout_choices(detail, values, *, common_topology="merge_before"):
    """Map visible choices to existing axes, never to hydraulic assumptions."""
    base = values.get('vu_orientation', 'horizontal_dial_up')
    detail = catalogue_proposal(detail, orientation=base)
    detail = replace(detail, maintenance_layout=values.get('vu_maintenance_layout', 'existing'))
    detail = replace(detail, inlet_metering_mode=(
        'per_inlet' if values.get('vu_per_inlet') == 'yes' else 'common'),
        common_topology=common_topology)
    overrides = {n: values[f'vu_{n}_orientation'] for n in ('cold', 'hot')
                 if f'vu_{n}_orientation' in values}
    if overrides:
        orientations = {n: base for n in MINIMUM_NODES} | overrides
        # Same topology condition as the current calculation. The entry is
        # total with local/in-scope heating; otherwise its meter is cold.
        primary = ('total' if values.get('hws_type') == 'local'
                   or values.get('hws_heater_in_scope') == 'yes' else 'cold')
        detail = replace(detail, meter_orientations=orientations,
                         assembly_orientation=orientations[primary],
                         meter_mounting=orientations[primary])
    if values.get('vu_filter_layout') == 'valtec_vt192_vtr090':
        detail = replace(detail, filter_offset_family='valtec_vt192_vtr090',
                         component_orientations={'filter': 'horizontal_dial_up'})
    elif values.get('vu_filter_layout') == 'valtec_vt386':
        detail = replace(detail, filter_inline_family='valtec_vt386')
    from app.pz.metering_supports import studio_supports
    detail = replace(detail, mounting=replace(detail.mounting, supports=studio_supports(values)))
    return detail


def layout_summary(project):
    """Current drawing/connection checks, not installation or purchase approval."""
    from app.pz.metering_detail import drawing_state
    from app.pz.metering_layout import build_metering_layout
    from app.pz.metering_product_selection import resolve_metering_products
    from app.pz.metering_chain import build_metering_chain
    from app.pz.metering_joint_audit import audit_direct_joints
    from app.pz.metering_orientation import meter_orientation
    from app.pz.meter_validation import meter_node_key

    detail = project.metering_detail
    state = drawing_state(project)
    selection = resolve_metering_products(project, state.meter, bypass=state.bypass,
                                          electric_bypass=state.electric_bypass)
    chain = build_metering_chain(detail, state, selection)
    joints = audit_direct_joints(chain, get_metering_catalogue(), inlet_dn=detail.inlet_dn)
    layout = build_metering_layout(project, state)
    counts = {key: sum(j.status == key for j in joints)
              for key in ("ports_match", "unresolved", "incompatible")}
    from app.pz.metering_hot_node import hot_meter_view
    from app.pz.metering_maintenance import audit_metering_maintenance
    hot_view = hot_meter_view(project)
    hot_layout = build_metering_layout(hot_view) if hot_view else None
    from app.pz.metering_supports import support_report
    supports = support_report(project, state, chain=chain)
    return {
        "orientation": detail.assembly_orientation,
        "inlet_metering_mode": state.inlet_metering_mode,
        "common_topology": state.common_topology,
        "inputs_count": state.inputs_count,
        "assemblies_count": state.assemblies_count,
        "label": VU_ORIENTATIONS.get(detail.assembly_orientation, "Компоновку уточнить"),
        "scale": detail.mounting.scale,
        "drawing_available": bool(layout.parts),
        "issues": list(dict.fromkeys((*layout.issues, *selection.errors, *supports['errors'],
                      *(f"{r['mark']}: {e}" for r in supports['rows'] for e in r['errors'])))),
        "connections": counts,
        "unselected_connectors": sum(c.part is None for c in selection.inline_joints),
        "nodes": [dict(node=meter_node_key(r),
                       title=r.label, orientation=meter_orientation(detail, meter_node_key(r)),
                       label=VU_ORIENTATIONS.get(meter_orientation(detail, meter_node_key(r)), 'Уточнить'))
                  for r in project.meters.rows],
        "filter_layout": detail.filter_inline_family or detail.filter_offset_family,
        "supports": asdict_support_summary(supports),
        "maintenance": audit_metering_maintenance(project,state,selection=selection,chain=chain),
        "hot_drawing": (dict(available=bool(hot_layout.parts), title=hot_view.node_title,
                             orientation=hot_layout.orientation, issues=list(hot_layout.issues),
                             installation_ready=False,
                             maintenance=audit_metering_maintenance(hot_view)) if hot_layout else None),
        "installation_ready": False,
        "notice": "Совпадение присоединений не подтверждает монтаж: посадки, уплотнения, "
                  "раскрой труб и опоры проверяются отдельно. Неизвестные размеры не назначены.",
    }


def asdict_support_summary(report):
    return {**report, 'rows': [{**r, 'product': asdict(r['product']) if r['product'] else None}
                              for r in report['rows']]}
