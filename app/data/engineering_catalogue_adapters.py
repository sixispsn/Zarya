"""Read-only adapters: existing IDs/algorithms remain canonical and unchanged."""
from app.data.engineering_catalogue import CatalogueItem, CataloguePort, freeze, plain


def existing_items():
    from app.data.metering_products import get_metering_catalogue
    from app.data.pipe_catalog import STEEL_VGP_ORDINARY
    from app.data.metering_extras import get_metering_extras_catalogue
    c = get_metering_catalogue()
    sources = {k:plain(v) for k,v in c.sources.items()}
    sources['zarya-vgp-3262'] = {
        'title':'ГОСТ 3262-75, таблица 1 — ранее принятый сортамент ЗАРИ',
        'kind':'retained_catalogue', 'locator':'app/data/pipe_catalog.py: STEEL_VGP_ORDINARY',
        'note':'Значения перенесены через адаптер без изменения канонической таблицы; покрытие не входит в толщину металла.'}
    result = []

    def add(part, family, kind, ports, **kwargs):
        data = plain(part)
        status = getattr(part,'dimension_status','reference_only')
        # A passport value accepted for the schematic does not resolve the
        # manufacturer-document discrepancy for assembly/automatic selection.
        if status == 'passport_nominal':
            status = 'conflict'
        result.append(CatalogueItem(part.id, family, kind,
            getattr(part,'name', getattr(part,'article',part.id)), tuple(part.source_ids),
            '; '.join(str(sources[s].get('pages', sources[s].get('title',s))) for s in part.source_ids),
            status, freeze(getattr(part,'dimensions_mm',{})),
            tuple(ports), manufacturer=getattr(part,'manufacturer',''), article=getattr(part,'article',''),
            pn_bar=getattr(part,'pn_bar',None), temperature_c=getattr(part,'temperature_c',None),
            pressure_temperature=getattr(part,'pressure_temperature',()),
            country_of_manufacture=getattr(part,'country_of_manufacture','unknown'),
            origin_source_ids=getattr(part,'origin_source_ids',()), notes=getattr(part,'notes',()),
            native=freeze(data), **kwargs))

    for p in c.products.values():
        flange = p.flange
        port = dict(connection='flanged' if flange else 'threaded', dn=p.dn,
            sex=p.connection_sex, thread=p.thread,
            standard=flange.standard if flange else p.connection_standard)
        if flange:
            port.update(flange_face=flange.face, bolt_circle_mm=flange.bolt_circle_mm,
                        bolt_count=flange.bolt_count, bolt_hole_mm=flange.bolt_hole_mm)
        add(p, 'metering.products', p.kind, [CataloguePort(n,**port) for n in ('in','out')])
    for p in c.fittings.values():
        ports = []
        for n,q in zip(('in','out','branch','branch2'),p.ports):
            drill = q.drilling or (None,None,None)
            # Thread standard is not supplied by FittingPort. Preserve it as
            # unknown here; the existing fitting checker remains authoritative.
            ports.append(CataloguePort(n, q.connection, dn=q.dn, sex=q.sex, thread=q.thread,
                                       bolt_circle_mm=drill[0],bolt_count=drill[1],bolt_hole_mm=drill[2]))
        add(p,'metering.fittings',p.kind,ports,material=p.material)
    for p in c.connectors.values():
        add(p,'metering.connectors','pipe_connector',[
            CataloguePort('pipe',p.joining,outer_diameter_mm=p.pipe_outer_diameter_mm,
                          system_id=p.pipe_system,sex='socket'),
            CataloguePort('equipment','threaded',sex=p.connection_sex,thread=p.thread,standard=p.connection_standard)
        ],material=p.pipe_material,system_id=p.pipe_system)
    for p in c.thread_connectors.values():
        add(p,'metering.thread_connectors','thread_connector',[
            CataloguePort('equipment','threaded',sex=p.equipment_sex,thread=p.equipment_thread,standard=p.connection_standard),
            CataloguePort('pipe','threaded',sex=p.pipe_connector_sex,thread=p.pipe_connector_thread,standard=p.connection_standard)])
    for p in c.reducers.values():
        add(p,'metering.reducers','reducer',[
            CataloguePort('large','threaded',dn=p.large_dn,sex=p.large_sex,thread=p.large_thread,standard=p.connection_standard),
            CataloguePort('small','threaded',dn=p.small_dn,sex=p.small_sex,thread=p.small_thread,standard=p.connection_standard)])
    for p in c.service_products.values():
        add(p,'metering.service',p.kind,[CataloguePort(f'port{i+1}','threaded',dn=p.dn,
             standard=q[0],thread=q[1],sex=q[2]) for i,q in enumerate(p.ports)])
    for p in c.pipe_clamps.values():
        add(p,'metering.clamps','pipe_clamp',[],material=p.pipe_material)
    for p in c.connection_kits.values():
        add(p,'metering.kits','meter_connection_kit',[])
    # Keep all modern electronics, leak detection and factory modules in the
    # same index, without inventing dimensions or duplicate SKU identities.
    extras = get_metering_extras_catalogue()
    for ident, source in extras['sources'].items():
        if ident in sources and sources[ident] != source:
            raise ValueError('Противоречие источников адаптеров: ' + ident)
        sources[ident] = source
    known = {p.id for p in result}
    for ident, p in extras['products'].items():
        if ident in known:
            continue
        result.append(CatalogueItem(ident,'metering.extras',p['kind'],p['model'],tuple(p['source_ids']),
            'Карточка дополнительного оборудования; габариты не импортированы',
            'reference_only',freeze({}),(),manufacturer=p['manufacturer'],
            notes=tuple(p['requirements']),native=freeze(p)))
    for material, coat in (('steel','none'),('galvanized_steel','galvanized')):
        for p in STEEL_VGP_ORDINARY.values():
            ident = f'gost3262-ordinary-{material}-dn{p.dn}'
            dims = freeze({'outer_diameter_mm':p.outer_mm,'wall_thickness_mm':p.wall_mm})
            ports = tuple(CataloguePort(n,'plain_pipe',p.dn,p.outer_mm,p.wall_mm,sex='plain') for n in ('in','out'))
            result.append(CatalogueItem(ident,'gost3262-ordinary-'+material,'pipe',
                f'ВГП обыкновенная DN{p.dn}, {p.size_label}',('zarya-vgp-3262',),'ГОСТ 3262-75, таблица 1',
                'verified',dims,ports,material=material,manufacturing='welded',coating=coat,
                standard=p.standard,series=p.series,joinings=('threaded','welded'),
                notes=('Сварка и восстановление покрытия, рабочие P/T и марка стали проверяются отдельно.',),
                native=freeze({'canonical_size':plain(p)})))
    return sources, tuple(result)
