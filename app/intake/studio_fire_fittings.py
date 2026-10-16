"""Explicit coverage of reducers by a designer's existing equivalent zeta.

This is input provenance, not a new resistance formula or a product approval.
No coefficients, flow paths or losses are added here.
"""


def validate_scope(scope, rows):
    from app.intake.studio_fire_station import _object
    from app.data.fire_pump_geometry import reference
    keys = ('pump_model nozzle_dn suction_header_dn suction_branch_dn '
            'discharge_header_dn discharge_branch_dn basis')
    _object(scope, keys, 'Состав суммарных местных сопротивлений')
    ref = reference(scope['pump_model'])
    if ref is None or type(scope['nozzle_dn']) is not int or scope['nozzle_dn'] != ref['nozzle_dn']:
        raise ValueError('Состав фасонины: нужны известная модель и подтверждённый DN патрубка')
    for role in ('suction_header', 'suction_branch', 'discharge_header', 'discharge_branch'):
        dn = scope[role+'_dn']
        if type(dn) is not int or dn != rows[role]['dn']:
            raise ValueError('Состав фасонины устарел: диаметры обвязки изменены')
    if not isinstance(scope['basis'], str) or not 1 <= len(scope['basis'].strip()) <= 600:
        raise ValueError('Состав фасонины: нужно основание включения переходов в суммарный коэффициент')


def coverage(model, pump_model=None):
    """Never infer a confirmed loss boundary from a drawn wedge or an old input."""
    p = (model or {}).get('pipework') or {}
    scope = p.get('fittings_scope')
    if scope is None:
        return dict(included=False, note='Учёт переходов в суммарных местных сопротивлениях не задан.')
    rows = {r['role']:r for r in p['elements']}
    validate_scope(scope, rows)
    if pump_model is not None and scope['pump_model'] != pump_model:
        raise ValueError('Состав фасонины устарел: изменена модель насоса')
    from app.data.pipe_catalog import steel_vgp_ordinary
    sides = {}
    for side in ('suction', 'discharge'):
        row = rows[side+'_fittings']
        sides[side] = dict(zeta=row['value'], reference_dn=row['dn'],
            reference_inner_mm=steel_vgp_ordinary(row['dn']).inner_mm)
    return dict(included=True, sides=sides, basis=scope['basis'],
        note='Переходы коллектора и патрубков входят в суммарные местные сопротивления каждой ветви. '
             'Отдельная надбавка не применяется; это допущение стадии П, не паспорт изделия.')
