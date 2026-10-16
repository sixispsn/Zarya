"""Source-backed bare-pump reference; never dimensions of a complete station.

Source: user-supplied «Каталог CDM, CDMF.pdf», printed/PDF page 62,
SHA-256 abc39dac7beba67fe392c27a427f3f52c629474244901d8cc20deb7b6fccfac0.
Standard motor only. No assumed PN variant, foundation or service clearances.
"""
from copy import deepcopy

CDM32_3 = dict(
    model='CNP CDM32-3', source='Каталог CDM, CDMF.pdf, с. 62',
    source_sha256='abc39dac7beba67fe392c27a427f3f52c629474244901d8cc20deb7b6fccfac0',
    scope='Отдельный насос со стандартным двигателем; не блок PFFS',
    nozzle_dn=65, flange_pn_options=[25, 40], selected_pn=None,
    height_mm=1055, nozzle_axis_from_base_mm=105,
    dimensions_mm={'H1':560, 'H2':390, 'H':1055, 'D1':260, 'D2':168},
    mass_kg=102, product_verified=False,
)


def reference(pump_model):
    # Exact model only: CDMF, 32-3-2, Ex and other motors are not synonyms.
    return deepcopy(CDM32_3) if pump_model == CDM32_3['model'] else None


def connection_review(model, pump_model):
    ref = reference(pump_model)
    if ref is None:
        return None
    from app.intake.studio_fire_pipework import from_model
    pipework = from_model(model)
    branches = ({e.id:e.dn for e in pipework.elements if e.id.endswith('_branch')}
                if pipework else {})
    ref['branch_dn'] = branches
    ref['mismatched_sides'] = [side for side in ('suction', 'discharge')
                             if branches.get(side+'_branch', ref['nozzle_dn']) != ref['nozzle_dn']]
    # Principle-level DN connections only. No chosen concentric/eccentric
    # product, mounting length or extra resistance follows from this list.
    ref['transitions'] = [dict(side=side, prefix='ПВ' if side=='suction' else 'ПД',
        branch_dn=branches[side+'_branch'], nozzle_dn=ref['nozzle_dn'],
        left_dn=branches[side+'_branch'] if side=='suction' else ref['nozzle_dn'],
        right_dn=ref['nozzle_dn'] if side=='suction' else branches[side+'_branch'])
        for side in ref['mismatched_sides']]
    from app.intake.studio_fire_fittings import coverage
    ref['fittings_coverage'] = coverage(model, pump_model)
    ref['note'] = (f"{ref['model']}: патрубки DN65, H=1055 мм ({ref['source']}). "
        'Размеры относятся к отдельному насосу со стандартным двигателем, не к станции PFFS. ')
    if ref['mismatched_sides']:
        ref['note'] += 'DN насосных ветвей отличается от DN65: требуются переходы к патрубкам. '
        ref['note'] += ref['fittings_coverage']['note'] + ' '
    elif not pipework:
        ref['note'] += 'DN насосных ветвей не задан; присоединения не проверены. '
    else:
        ref['note'] += 'DN ветвей совпадает с патрубками; это не проверка фланцев и монтажных размеров. '
    ref['note'] += 'Исполнение, PN, опоры и проходы требуют выбора/увязки.'
    return ref
