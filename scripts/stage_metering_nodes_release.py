"""Publish the reviewed VU and dependent water specification, not the worktree.

The baseline must be an export of the live 20261007-vk-delivery image.
Sewer calculations, Samara hydraulic inputs, authentication and legacy stay intact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

RELEASE = '20261014-metering-nodes'
BASE = '20261007-vk-delivery'
FILES = '''
app/api/water_meters.py
app/calc/apartment_meters.py
app/data/apartment_pipe_connections.py
app/data/apartment_regulators.py
app/data/engineering_catalogue.json
app/data/engineering_catalogue.py
app/data/engineering_catalogue_adapters.py
app/data/engineering_catalogue_store.py
app/data/flexible_connections.json
app/data/flexible_connections.py
app/data/metering_coverage.py
app/data/metering_extras.py
app/data/metering_fittings.json
app/data/metering_fittings.py
app/data/metering_installation.json
app/data/metering_installation.py
app/data/metering_products.json
app/data/metering_products.py
app/data/metering_products_20261012.json
app/data/metering_products_flanged.json
app/data/metering_review_20261012.json
app/data/metering_service_products.json
app/data/metering_service_products.py
app/data/pipe_catalog.py
app/intake/project_builder.py
app/intake/request_dto.py
app/intake/studio_apartment_meters.py
app/intake/studio_intake.py
app/intake/studio_metering.py
app/intake/studio_project.py
app/intake/yaml_io.py
app/pz/apartment_connections.py
app/pz/apartment_products.py
app/pz/apartment_water_units.py
app/pz/commission.py
app/pz/drawing_numbers.py
app/pz/equipment_origin.py
app/pz/generator.py
app/pz/hws_building_drafting.py
app/pz/hws_presentation.py
app/pz/meter_product_sheet.py
app/pz/meter_products.py
app/pz/metering_accessories.py
app/pz/metering_catalogue_sheet.py
app/pz/metering_chain.py
app/pz/metering_connections.py
app/pz/metering_detail.py
app/pz/metering_detail_data.py
app/pz/metering_extras.py
app/pz/metering_fitting_selection.py
app/pz/metering_flexible.py
app/pz/metering_joint_audit.py
app/pz/metering_layout.py
app/pz/metering_mounting.py
app/pz/metering_orientation.py
app/pz/metering_pipes.py
app/pz/metering_product_selection.py
app/pz/metering_reducers.py
app/pz/metering_rules.py
app/pz/metering_service.py
app/pz/metering_spec.py
app/pz/metering_ugo.py
app/pz/metering_vertical_drawing.py
app/pz/project.py
app/pz/scheme.py
app/pz/spec.py
app/pz/spec_quantity_review.py
app/pz/templates/spec_table.html
app/pz/templates/spec.css
app/pz/templates/v1_calculation_body.html
app/pz/water_apartment_assembly.py
app/pz/water_building_section.py
app/pz/water_residential_section.py
app/pz/water_scheme_delivery.py
app/pz/water_service_assemblies.py
app/pz/water_station_drafting.py
app/web/static/studio.css
app/web/static/studio.js
app/web/static/studio_configurator.js
app/web/static/studio_spec_review.js
app/web/templates/studio.html
app/web/wizard.py
'''.split()


def water_only_samara(old):
    """Bind previously reviewed water quantities/catalogue without the K1 overlay."""
    def once(text, before, after):
        assert text.count(before) == 1, before
        return text.replace(before, after, 1)
    old = once(old, 'ENGINE_FILES = (',
               "QUANTITY_REVIEW = ROOT/'demo/samara_quantity_review_assumptions.json'\nENGINE_FILES = (")
    helper = '''def reviewed_water_inputs(data):
    from app.intake.studio_intake import validate_value
    from app.intake.studio_metering import catalogue_proposal
    from app.pz.apartment_water_units import apartment_units_from_values
    from app.pz.metering_detail_data import MeteringDetailData
    quantity = json.loads(QUANTITY_REVIEW.read_text())
    if (quantity['scope'] != 'samara_section_3_2_only'
            or quantity['base_payload_sha256'] != data['payload_sha256']
            or set(quantity['values']) != {'apartment_units_mode'}):
        raise IntakeError('Решение по количествам не принадлежит текущему примеру Самары.')
    answers = deepcopy(data['payload']['answers'])
    values = deepcopy(data['payload']['accepted_values'])
    for key, value in quantity['values'].items():
        value = validate_value(key, value)
        answers[key] = dict(value=value, candidates_hash=digest([]),
            source=dict(kind='study_assumption', evidence=[], note=quantity['basis']))
        values[key] = value
    snapshot = digest(dict(base=data['payload_sha256'], quantities=quantity,
        apartment_units=asdict(apartment_units_from_values(values)),
        metering=asdict(catalogue_proposal(MeteringDetailData())),
        scope='20261014-water-only'))
    return answers, values, snapshot


'''
    old = once(old, 'def initialize(draft, return_id):', helper + 'def initialize(draft, return_id):')
    old = once(old, "draft['answers'] = deepcopy(data['payload']['answers'])",
               "draft['answers'], _, snapshot = reviewed_water_inputs(data)")
    old = once(old, "version=1, snapshot=data['payload_sha256'], return_id=return_id)",
               "version=2, snapshot=snapshot, return_id=return_id)")
    old = once(old, "payload = data['payload']\n", "payload = data['payload']\n    answers, values, snapshot = reviewed_water_inputs(data)\n")
    old = once(old, "exposed = {k:v for k,v in payload['accepted_values'].items() if k in FIELD_MAP}",
               "exposed = {k:v for k,v in values.items() if k in FIELD_MAP}")
    old = once(old, "draft['study']['snapshot'] != data['payload_sha256']", "draft['study']['snapshot'] != snapshot")
    old = once(old, "draft.get('answers') != payload['answers']", "draft.get('answers') != answers")
    old = once(old, "req = load_request(payload['request_yaml'])", """req = load_request(payload['request_yaml'])
    from app.intake.studio_metering import catalogue_proposal
    from app.pz.apartment_water_units import apartment_units_from_values
    req.metering_detail = catalogue_proposal(req.metering_detail)
    req.apartment_water_units = apartment_units_from_values(values)""")
    old = once(old, "return req, station, payload['result'], data['payload_sha256']",
               "return req, station, payload['result'], snapshot")
    old = once(old, "r = p.fire_pumps.station_design\n", "r = p.fire_pumps.station_design\n        from app.pz.spec_quantity_review import water_spec_quantity_review\n")
    old = once(old, "model_hash=fingerprint, storm=asdict(p.storm.result),",
               "model_hash=fingerprint, storm=asdict(p.storm.result),\n            spec_quantity_review=water_spec_quantity_review(p),")
    return old


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert not args.output.exists() and not args.candidate.exists()
    shutil.copytree(args.baseline, args.candidate)
    args.output.mkdir(parents=True)
    manifest = {}
    for name in FILES + ['app/intake/samara_study.py', 'demo/samara_quantity_review_assumptions.json']:
        data = (root / name).read_bytes()
        base = args.baseline / name
        if name == 'app/intake/samara_study.py':
            data = water_only_samara(base.read_text()).encode()
        assert not base.exists() or base.read_bytes() != data, name
        dest = args.output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        target = args.candidate / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # QA is outside the production overlay/image; source tree above is exact.
    for folder in ('tests', 'scripts', 'docs'):
        shutil.copytree(root / folder, args.candidate / folder,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('pyproject.toml', 'pytest.ini'):
        if (root / name).exists(): shutil.copyfile(root / name, args.candidate / name)
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(f'FROM zarya-release:{BASE}\nUSER root\n'
        f'ENV ZARYA_BUILD_COMMIT={RELEASE}\nCOPY app/ /app/app/\nCOPY demo/ /app/demo/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.data.engineering_catalogue import get_engineering_catalogue; assert get_engineering_catalogue().items"\n')
    (deploy / 'release.override.yaml').write_text(f'services:\n  app:\n    image: zarya-release:{RELEASE}\n'
        f'    environment:\n      ZARYA_BUILD_COMMIT: {RELEASE}\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', RELEASE).replace('20261005-samara-vk', BASE).replace(
        'restored-pre-studio', 'restored-pre-metering-nodes')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_pilot_container.py',
                 'verify_metering_nodes_release.py', 'release_tree_snapshot.py'):
        source = root / 'scripts' / name
        if source.exists(): shutil.copyfile(source, scripts / name)
    print(json.dumps(dict(release=RELEASE, files=len(manifest), candidate=str(args.candidate))))


if __name__ == '__main__':
    main()
