"""Regression of the accepted compact composition extended to В1/Т3/Т4."""
from copy import deepcopy
from dataclasses import asdict,replace
from xml.etree import ElementTree as ET

import cairosvg
import pymupdf
import pytest

from app.pz.generator import generate_scheme_result
from app.pz.project import HwsType,Stage
from app.pz.water_residential_section import (
    AXES,LEFT,RIGHT,ROOF,ROOM_EDGES,build_residential_water_section,
    can_draw_residential_water_section,residential_water_layout,
)
from tests.test_water_unified_section import project as source_project


def project(floors=16):
    p=source_project(floors)
    p.building.hws_type=HwsType.CENTRAL
    p.consumer_groups=[('residential_full_bath',350)]
    return p


def render(p):
    return build_residential_water_section(p,profile='residential_full_bath')


def tagged(root,name):
    return [e for e in root.iter() if e.get(name) is not None]


@pytest.mark.parametrize('floors',[1,2,3,4,9,16,25,200])
def test_autonomous_profile_floors_and_immutable_source(floors):
    p=project(floors)
    original=deepcopy(asdict(p))
    assert can_draw_residential_water_section(p)
    result=generate_scheme_result(p)
    root=ET.fromstring(result.svg)
    m=residential_water_layout(p)
    assert m.floors == (tuple(range(1,floors+1)) if floors<=3 else (1,2,floors))
    assert root.get('data-takeoff-eligible') == root.get('data-release-ready') == 'false'
    assert root.get('data-residential-water-section') == 'approval'
    assert asdict(p)==original
    assert len(tagged(root,'data-floor-break')) == (2 if floors>3 else 0)
    assert len(tagged(root,'data-section-slab')) == len(m.floors)+1
    fixtures=[e for e in tagged(root,'data-fragment-component') if e.get('data-fragment-component')=='fixture']
    assert len(fixtures)==8*len(m.floors)
    assert {e.get('data-system') for e in tagged(root,'data-pipe')}=={'В1','Т3','Т4'}


def test_two_mixer_ports_no_hot_water_at_wc_and_no_draw_off_on_t4():
    root=ET.fromstring(render(project()).svg)
    pipes=tagged(root,'data-pipe')
    for fixture in tagged(root,'data-fragment-component'):
        if fixture.get('data-fragment-component')!='fixture': continue
        kind,side,floor=(fixture.get(k) for k in ('data-kind','data-side','data-floor'))
        if kind=='wc':
            assert fixture.get('data-systems')=='В1'
            assert not fixture.get('data-hot-port')
            assert not any(p.get('data-to')==f'{side}-{floor}-wc-hot-port' for p in pipes)
        else:
            c,h=fixture.get('data-cold-port'),fixture.get('data-hot-port')
            assert c!=h
            for system,port,ending in [('В1',c,'cold'),('Т3',h,'hot')]:
                feed=next(p for p in pipes if p.get('data-to')==f'{side}-{floor}-{kind}-{ending}-port')
                assert feed.get('data-system')==system
                assert feed.get('d').startswith('M'+port)
    assert not any('port' in p.get('data-to','') or 'apartment' in p.get('data-to','')
                   for p in pipes if p.get('data-system')=='Т4')


def test_mixer_symbols_are_visible_closed_ugo_not_bare_pipe_terminals():
    root=ET.fromstring(render(project()).svg)
    symbols=tagged(root,'data-water-ugo')
    assert len(symbols)==6*3  # Three mixers in each of two representative groups.
    assert {s.get('data-water-ugo') for s in symbols}=={'mixer-shower','mixer-swivel-spout'}
    for symbol in symbols:
        assert symbol.get('data-ugo-reference')=='GOST-21.205-2016-table-6-25'
        paths=[e for e in symbol if e.tag.endswith('path')]
        assert paths[0].get('d').endswith('Z')
        assert float(paths[0].get('stroke-width'))==.35
        assert any(e.tag.endswith('circle') and e.get('fill')=='black' for e in symbol)
    for fixture in tagged(root,'data-fragment-component'):
        if fixture.get('data-fragment-component')!='fixture' or fixture.get('data-kind')=='wc':
            continue
        cold,hot=([float(v) for v in fixture.get(k).split(',')]
                  for k in ('data-cold-port','data-hot-port'))
        assert abs(cold[0]-hot[0])==pytest.approx(8.4)
        assert cold[1]==hot[1]


def test_fixture_feed_geometry_reaches_each_branch_and_does_not_leave_a_tail():
    # Semantic graph reachability alone cannot detect a graphical gap after
    # resizing a UGO. Check the physical endpoints on both mirrored groups.
    import re
    root=ET.fromstring(render(project()).svg)
    pipes={e.get('data-pipe'):e for e in tagged(root,'data-pipe')}
    for side in AXES:
        for floor in (1,2,16):
            for system,suffix in (('В1','cold'),('Т3','hot')):
                branch=pipes[f'{side}-{floor}-{system}-branch'].get('d')
                lo,y=map(float,re.match(r'M([^,]+),([^ H]+)',branch).groups())
                hi=float(branch.rsplit(' H',1)[1])
                for kind in ('sink','bath','basin',*(['wc'] if system=='В1' else [])):
                    feed=pipes[f'{side}-{floor}-{kind}-{suffix}'].get('d')
                    x=float(re.match(r'M([^,]+),',feed).group(1))
                    assert lo<=x<=hi
                    assert float(feed.rsplit(' V',1)[1])==y
                    if kind=='sink':
                        assert x==(lo if side=='left' else hi)
                        assert ' A' not in feed


def test_every_draw_off_has_a_path_and_hot_circulation_returns_to_its_own_source():
    root=ET.fromstring(render(project()).svg)
    edges={}
    for p in tagged(root,'data-pipe'):
        a,b,key=p.get('data-from'),p.get('data-to'),p.get('data-pipe')
        edges.setdefault(a,set()).add(key)
        edges.setdefault(key,set()).add(b)
    def reached(start):
        done,todo=set(),[start]
        while todo:
            n=todo.pop()
            if n in done: continue
            done.add(n);todo.extend(edges.get(n,()))
        return done
    cold,hot=reached('outside'),reached('hws-source')
    assert 'hws-return' in hot
    assert 'hws-return' not in cold
    for side in AXES:
        for floor in (1,2,16):
            for kind in ('sink','bath','basin','wc'):
                assert f'{side}-{floor}-{kind}-cold-port' in cold
                if kind!='wc': assert f'{side}-{floor}-{kind}-hot-port' in hot
    for side,axes in AXES.items():
        closure=next(p for p in tagged(root,'data-pipe') if p.get('data-pipe')==side+'-hws-closure')
        assert closure.get('d')==f'M{axes["Т3"]:g},{ROOF+9:g} L{axes["Т4"]:g},{ROOF+9:g}'


def test_current_pipe_sizes_and_unknown_t4_are_never_substituted():
    p=project()
    result=render(p)
    assert 'Размер не задан' in result.svg and 'Т4 DN не задан' in result.svg
    assert any('размер Т4' in w for w in result.warnings)
    assert 'Ø76×3,5' in result.svg  # В1 only; T3 has no path in this fixture.
    assert 'Т3 Ø по расчёту' in result.svg
    assert not any('Ø' in (e.text or '') for e in ET.fromstring(result.svg).iter('{http://www.w3.org/2000/svg}text'))
    for e in tagged(ET.fromstring(result.svg),'data-fragment-component'):
        if e.get('data-fragment-component')=='circulation-balance':
            assert e.get('data-dn')==e.get('data-kv')=='unknown'


def test_external_source_has_no_cold_makeup_into_local_heater():
    p=project();p.source.hws_heater_in_scope=False
    svg=render(p).svg
    assert 'data-pipe="cold-to-hws"' not in svg
    assert 'Источник ГВС' in svg
    assert 'Узел нагрева ГВС' not in svg


@pytest.mark.parametrize('change',['profile','mixed','schedule','local','zones','stage','basement','elevation','roof','inlet','fire'])
def test_new_composition_does_not_replace_unsupported_inputs(change):
    p=project()
    if change=='profile': p.consumer_groups=[('residential_no_bath',20)]
    elif change=='mixed': p.consumer_groups.append(('hospital',20))
    elif change=='schedule': p.fixtures=[object()]
    elif change=='local': p.building.hws_type=HwsType.LOCAL
    elif change=='zones': p.building.zones=2
    elif change=='stage': p.document.stage=Stage.R
    elif change=='basement': p.building.floors_below=0
    elif change=='elevation': p.building.floor_elevations_m.pop(2)
    elif change=='roof': p.sewage.roof_relative_elevation_m=None
    elif change=='inlet': p.metering_detail.inlet_elevation_m=float('nan')
    elif change=='fire': p.fire.required=True
    assert not can_draw_residential_water_section(p)


def test_bridge_halos_painted_last_and_all_break_lines_meet_the_knife():
    p=project();svg=render(p).svg;root=ET.fromstring(svg);m=residential_water_layout(p)
    geometry=next(e for e in root if e.get('clip-path'))
    # Final white/black bridge pairs survive later risers and symbols.
    overlays=tagged(geometry,'data-bridge-overlay')
    assert len(overlays)>25
    assert list(geometry)[-1].get('data-bridge-overlay')=='true'
    breaks=tagged(root,'data-floor-break')
    assert all(e.get('data-tail-mm')=='10' and f'M{LEFT-10:g},' in e.get('d') and f'H{RIGHT+10:g}' in e.get('d') for e in breaks)
    mm=72/25.4
    pdf=pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()),filetype='pdf')
    mid=sum(m.break_edges)/2
    for x in (*ROOM_EDGES,*(x for axes in AXES.values() for x in axes.values())):
        box=pymupdf.Rect((x-.3)*mm,(mid-.7)*mm,(x+.3)*mm,(mid+.7)*mm)
        assert min(pdf[0].get_pixmap(matrix=pymupdf.Matrix(3,3),clip=box,colorspace=pymupdf.csGRAY).samples)>245
        for y in (m.break_edges[0]-.8,m.break_edges[1]+.8):
            box=pymupdf.Rect((x-.3)*mm,(y-.2)*mm,(x+.3)*mm,(y+.2)*mm)
            assert min(pdf[0].get_pixmap(matrix=pymupdf.Matrix(3,3),clip=box,colorspace=pymupdf.csGRAY).samples)<180


def test_printable_a2_text_frame_and_fully_vector_drawing():
    p=project();svg=render(p).svg
    pdf=pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()),filetype='pdf')
    page=pdf[0];mm=72/25.4
    assert len(pdf)==1 and not page.get_images()
    assert page.rect.width/mm==pytest.approx(594,abs=.01)
    assert page.rect.height/mm==pytest.approx(420,abs=.01)
    assert any('OpenGOST' in f[3] for f in page.get_fonts())
    safe=pymupdf.Rect(20*mm,5*mm,589*mm,415*mm)
    inventory=pymupdf.Rect(8*mm,330*mm,13*mm,415*mm)
    paper_format=pymupdf.Rect(564*mm,415*mm,589*mm,420*mm)
    for word in page.get_text('words'):
        rect=pymupdf.Rect(word[:4])
        assert (safe.contains(rect) or
                (word[4] in {'Взам.', 'инв.', '№', 'Подп.', 'и', 'дата', 'Инв.', 'подл.', '№подл.'}
                 and inventory.contains(rect)) or
                (word[4] in {'Формат', 'А2'} and paper_format.contains(rect))),word
    assert '\ufffd' not in page.get_text()


def test_real_samara_regulators_only_on_accepted_lower_floors(tmp_path):
    from app.intake import samara_study
    draft=dict(revision=0,answers={},documents=[])
    samara_study.initialize(draft,None)
    p=samara_study.build(draft,tmp_path,render=False)[0].project
    # Normal orchestration retains the separate V2 sheet.
    p.fire.required=False;p.fire_pumps.required=False
    before=deepcopy(asdict(p))
    root=ET.fromstring(generate_scheme_result(p).svg)
    assert root.get('data-residential-water-section')=='approval'
    regs=[e for e in tagged(root,'data-fragment-component') if e.get('data-fragment-component')=='apartment-regulator']
    assert len(regs)==8
    assert {e.get('data-floor') for e in regs}=={'1','2'}
    assert {e.get('data-system') for e in regs}=={'В1','Т3'}
    assert asdict(p)==before
