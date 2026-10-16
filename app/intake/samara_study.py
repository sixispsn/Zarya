"""Fixed, reviewed Studio control case; never a fallback for user buildings.

The slow L06 matrix is prepared by a reproducible script. Studio validates the
frozen inputs, engine fingerprint, report checksum and current project binding.
No source PDF, absolute Mac path or external request is needed at runtime.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import json

from app.intake.studio_intake import IntakeError, FIELD_MAP, accepted_values, calculate_draft
from app.pz.fire_station_binding import digest

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT/'demo/samara_station_review.json'
K1_REVIEW = ROOT/'demo/samara_k1_review_assumptions.json'
QUANTITY_REVIEW = ROOT/'demo/samara_quantity_review_assumptions.json'
ENGINE_FILES = (
    'app/calc/fire_station_pipework.py', 'app/data/fire_station_design.py',
    'app/calc/fire_nomogram_flow.py', 'app/calc/fire_pressure_flow.py',
    'app/calc/fire_diaphragm_graph.py', 'app/data/fire_diaphragm_nomogram.py',
    'app/calc/fire_hydraulics.py', 'app/calc/fire_pump_station.py',
    'app/calc/pump_curve.py', 'app/data/fire_pump_study.py',
    'legacy/sp30_calculator.html',
    'app/calc/fire_repair_flow.py', 'app/data/fire_diaphragm_layout.py',
)


def engine_fingerprint():
    from hashlib import sha256
    return digest({name:sha256((ROOT/name).read_bytes()).hexdigest() for name in ENGINE_FILES})


def load_case():
    data = json.loads(CASE.read_text())
    if digest(data['payload']) != data['payload_sha256'] or data['engine_sha256'] != engine_fingerprint():
        raise IntakeError('Контрольный пример устарел после изменения расчётного ядра. Пересоберите проверенный пример.')
    return data


def reviewed_inputs(data):
    """Visible study inputs through the ordinary DTO, not edits of a built Project.

    Keep the expensive signed fire result unchanged. Bind the additional K1
    assumptions into a separate document snapshot; old study drafts fail closed.
    """
    from app.data.sewer_pipe_catalog import sewer_pipe_geometry
    from app.intake.studio_intake import validate_value
    from app.pz.wastewater_presentation import SectionMainInput
    review = json.loads(K1_REVIEW.read_text())
    if (review['scope'] != 'samara_section_3_2_only'
            or review['base_payload_sha256'] != data['payload_sha256']):
        raise IntakeError('Допущения К1 не принадлежат текущему контрольному примеру Самары.')
    main = SectionMainInput.from_mapping(review['main'])
    counts = [row['count'] for row in review['fixture_inventory']]
    if any(type(n) is not int or n <= 0 for n in counts) or sum(counts) != main.fixtures_count:
        raise IntakeError('N К1 расходится с учебным составом приборов.')
    geometry = sewer_pipe_geometry(review['catalog_series_id'], main.outer_diameter_mm)
    if (geometry.wall_thickness_mm != main.wall_thickness_mm
            or geometry.series.material != main.material):
        raise IntakeError('Размеры трубы К1 расходятся с выбранным сортаментом.')
    answers = deepcopy(data['payload']['answers'])
    values = deepcopy(data['payload']['accepted_values'])
    quantity = json.loads(QUANTITY_REVIEW.read_text())
    if (quantity['scope'] != 'samara_section_3_2_only'
            or quantity['base_payload_sha256'] != data['payload_sha256']
            or set(quantity['values']) != {'apartment_units_mode'}):
        raise IntakeError('Решение по количествам не принадлежит текущему примеру Самары.')
    for key, value in quantity['values'].items():
        value = validate_value(key, value)
        answers[key] = dict(value=value, candidates_hash=digest([]),
                            source=dict(kind='study_assumption', evidence=[], note=quantity['basis']))
        values[key] = value
    for name, value in review['main'].items():
        key = 'section_k1_' + name
        value = validate_value(key, value)
        answers[key] = dict(value=value, candidates_hash=digest([]),
                            source=dict(kind='study_assumption', evidence=[], note=review['basis']))
        values[key] = value
    from app.intake.studio_metering import catalogue_proposal
    from app.pz.apartment_water_units import apartment_units_from_values
    from app.pz.metering_detail_data import MeteringDetailData
    # The model proposal is the same as ordinary Studio, not a new hydraulic
    # input. Bind its policy/catalogue revision so old preview files are revoked.
    snapshot = digest(dict(base=data['payload_sha256'], k1=review, quantities=quantity,
                           apartment_units=asdict(apartment_units_from_values(values)),
                           metering=asdict(catalogue_proposal(MeteringDetailData(), dimensioned=True))))
    return review, answers, values, snapshot


def initialize(draft, return_id):
    data = load_case()
    review, draft['answers'], _, snapshot = reviewed_inputs(data)
    draft['documents'] = []
    draft['study'] = dict(kind='samara', title='Самара · секция 3.2 · 16 этажей',
        description='Фиксированный контрольный пример ИОС2 + ИОС3: В1/Т3, В2, К1 и К2. Исходные и ограничения приложены.',
        version=4, snapshot=snapshot, return_id=return_id,
        k1_assumptions=deepcopy(review))
    draft['calculation'] = calculate_draft(draft)
    draft['project_calculation'] = calculate(draft)


def inputs(draft):
    from app.intake.yaml_io import load_request
    from app.calc.fire_pump_station import CommonFireStation, StationSupply
    from app.calc.fire_hydraulics import PipeSegment
    data = load_case()
    payload = data['payload']
    review, answers, values, snapshot = reviewed_inputs(data)
    # Preserve the entire signed snapshot, including fields that this deployed
    # ordinary configurator does not expose (e.g. pending IOS3 extensions).
    exposed = {k:v for k,v in values.items() if k in FIELD_MAP}
    if (draft['study']['snapshot'] != snapshot or
            draft['study'].get('k1_assumptions') != review or
            draft.get('answers') != answers or
            accepted_values(draft) != exposed):
        raise IntakeError('Исходные изменились: прежний контрольный расчёт В2 больше не применим. Откройте пример заново.')
    req = load_request(payload['request_yaml'])
    from app.intake.studio_section import section_main
    req.wastewater_presentation = replace(req.wastewater_presentation, k1=section_main(values, 'k1'))
    from app.intake.studio_metering import catalogue_proposal
    req.metering_detail = catalogue_proposal(req.metering_detail, dimensioned=True)
    from app.pz.apartment_water_units import apartment_units_from_values
    req.apartment_water_units = apartment_units_from_values(values)
    s = payload['station']
    station = CommonFireStation(s['pump_axis_m'], tuple(StationSupply(
        **{k:v for k,v in row.items() if k!='segments'},
        segments=tuple(PipeSegment(**p) for p in row['segments'])) for row in s['supplies']),
        s['basis'], tuple(s['review_notes']))
    return req, station, payload['result'], snapshot


def build(draft, folder, render=False):
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    req, station, result, fingerprint = inputs(draft)
    project = build_project(req)
    # A separately documented presentation/pressure-review assumption. It does
    # not replace the frozen hydraulic inputs or the reviewed L06 matrix.
    water_review = json.loads((ROOT/'demo/samara_water_review_assumptions.json').read_text())
    if water_review['scope'] != 'samara_section_3_2_only':
        raise IntakeError('Допущения проверки В1 не принадлежат примеру Самары.')
    project.source.lowest_fixture_elevation_m = water_review['lowest_fixture_elevation_m']
    project.source.lowest_fixture_basis = water_review['basis']
    project.water_regulation_design = deepcopy(water_review.get('regulation_design'))
    project.document.review_notes = (
        'Контрольный пример по согласованным исходным. Не для реального выпуска без замены допущений данными АР/ТУ.',
    )
    bundle = design_ios2(project, output_dir=str(folder), fire_station=station,
                        fire_station_design=result, render_documents=render)
    wastewater_summary(bundle.project)
    return bundle, fingerprint


def wastewater_summary(project):
    """Cross-check the shared model, without certifying the assumed network."""
    from math import isclose
    from app.pz.wastewater_graphic_exports import representative_document_model
    from app.pz.wastewater_gost import audit_wastewater_gost
    section = representative_document_model(project)
    if section is None or project.sewage.result is None or project.storm.result is None:
        raise IntakeError('Контрольный ИОС3 неполон: нет разреза либо текущих расходов К1/К2.')
    k1 = project.sewage.result.total.q_sewage_lps
    if not (isclose(k1, project.flows.sewage_l_per_s, abs_tol=1e-9)
            and isclose(k1, section.k1_total_flow_lps, abs_tol=1e-9)
            and isclose(project.sewage.result.total.q_water_total_lps,
                        project.flows.q_sec_tot, abs_tol=1e-9)):
        raise IntakeError('Расходы ИОС2, расчёта К1 и принципиального разреза расходятся.')
    return dict(q_k1_lps=k1, q_k2_lps=project.storm.result.q_total_l_per_s,
        horizontal_k1=asdict(section.main_checks[0]),
        q_day_m3=project.flows.q_day_tot, preliminary=True,
        missing=[dict(code=c.code, requirement=c.requirement, reference=c.reference)
                 for c in audit_wastewater_gost(project).missing])


def calculate(draft):
    from tempfile import TemporaryDirectory
    try:
        with TemporaryDirectory(prefix='zarya-samara-') as folder:
            bundle, fingerprint = build(draft, folder)
        p = bundle.project
        r = p.fire_pumps.station_design
        from app.pz.spec_quantity_review import water_spec_quantity_review
        return dict(state='study', ios2=True, ios3=True, can_preview=True, can_release=False,
            model_hash=fingerprint, storm=asdict(p.storm.result),
            spec_quantity_review=water_spec_quantity_review(p),
            wastewater=wastewater_summary(p),
            fire_station=dict(model=p.fire_pumps.model, q_min_m3h=r['required_q_m3h'],
                head_m=r['required_bare_pump_head_m'], pipework_loss_m=r['pipework']['total_loss_m'],
                duty_units=1,reserve_units=1,preliminary=True),
            preview_notes=list(p.document.review_notes))
    except (ValueError, IntakeError) as exc:
        return dict(state='blocked',can_preview=False,can_release=False,issues=[dict(message=str(exc))])


def render(draft, folder):
    from pypdf import PdfReader, PdfWriter
    folder.mkdir(parents=True,exist_ok=True)
    bundle, fingerprint = build(draft, folder, render=True)
    documents = [
        (bundle.pz_pdf,'pz_pdf','ПЗ ИОС2 с расчётами и автоматикой'),
        (bundle.scheme_pdf,'scheme_pdf',bundle.water_scheme_delivery['label']),
        (bundle.fire_station_scheme_pdf,'fire_station_scheme_pdf','Схемы насосной и стояков В2'),
        (bundle.metering_scheme_pdf,'metering_scheme_pdf','Вводы и водомерный узел'),
        (bundle.pump_zone_scheme_pdf,'pump_zone_scheme_pdf','Насосы В1, зоны и ГВС'),
        (bundle.spec_pdf,'spec_pdf','Спецификация ИОС2'),
    ]
    if any(not path or not Path(path).is_file() for path,_,_ in documents):
        raise IntakeError('Неполный контрольный комплект: один из генераторов не выдал PDF.')
    combined = folder/'ИОС2_Самара_согласованный.pdf'
    # Same IOS2 package as ordinary Studio, not a parallel hand-picked composition.
    from shutil import copyfile
    if not bundle.water_package_pdf or not Path(bundle.water_package_pdf).is_file():
        raise IntakeError('Объединённый ИОС2 не сформирован.')
    copyfile(bundle.water_package_pdf, combined)
    documents.insert(0,(str(combined),'ios2_package_pdf','Комплект ИОС2 · одним PDF'))
    documents.append((bundle.fire_station_design_pdf,'fire_station_design_pdf','В2 · расчёт, график и автоматика'))
    sewer_documents = [
        (bundle.wastewater_pz_pdf,'wastewater_pz_pdf','ПЗ ИОС3 с расчётами и балансом'),
        (bundle.wastewater_scheme_pdf,'wastewater_scheme_pdf','Принципиальная схема К1 + К2'),
        (bundle.wastewater_ugo_pdf,'wastewater_ugo_pdf','Условные обозначения К1 + К2'),
        (bundle.wastewater_spec_pdf,'wastewater_spec_pdf','Предварительная спецификация ИОС3'),
    ]
    if any(not path or not Path(path).is_file() for path,_,_ in sewer_documents):
        raise IntakeError('Неполный контрольный ИОС3: один из генераторов не выдал PDF.')
    sewer = folder/'ИОС3_Самара_согласованный.pdf'
    writer = PdfWriter()
    for path,kind,label in sewer_documents:
        writer.append(PdfReader(path),outline_item=label,import_outline=True)
    writer.add_metadata({'/Title':'Самара, секция 3.2. Контрольный комплект ИОС3',
                         '/Subject':'Предварительные проектные решения; не для выпуска'})
    with sewer.open('wb') as f: writer.write(f)
    documents.extend([(str(sewer),'ios3_package_pdf','Комплект ИОС3 · одним PDF'), *sewer_documents,
        (bundle.wastewater_calculation_pdf,'wastewater_calculation_pdf','Расчёты К1 и К2 · отдельные листы'),
        (bundle.wastewater_balance_pdf,'wastewater_balance_pdf','Баланс ИОС3 · отдельный лист')])
    total = folder/'ВК_Самара_ИОС2_ИОС3.pdf'
    writer = PdfWriter()
    for path,label in ((combined,'ИОС2 · водоснабжение'),(sewer,'ИОС3 · водоотведение')):
        writer.append(PdfReader(path),outline_item=label,import_outline=True)
    writer.add_metadata({'/Title':'Самара, секция 3.2. ИОС2 + ИОС3',
                         '/Subject':'Контрольный пример; не для выпуска'})
    with total.open('wb') as f: writer.write(f)
    documents.insert(0,(str(total),'vk_package_pdf','ИОС2 + ИОС3 · общий PDF'))
    return [dict(name=Path(path).name,kind=kind,label=label,state='incomplete',
        state_note='Контрольный пример. Допущения и неполнота указаны в документах; не для выпуска.',
        model_hash=fingerprint,
        **({'water_scheme': bundle.water_scheme_delivery}
           if kind in {'scheme_pdf', 'ios2_package_pdf', 'vk_package_pdf'} else {}))
        for path,kind,label in documents], fingerprint
