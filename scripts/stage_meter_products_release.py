"""Scoped meter overlay over the inspected live IOS2 image; no sewer/auth edits."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from scripts.stage_studio_ios2_release import replace_once, segment

FULL = [
    'app/data/metering_products.json', 'app/data/metering_products.py',
    'app/pz/meter_products.py', 'app/pz/meter_product_sheet.py',
    'app/pz/metering_detail_data.py', 'app/pz/project.py',
    'app/pz/meter_validation.py', 'app/intake/project_builder.py',
    'app/pz/ios2_orchestrator.py', 'app/pz/metering_product_selection.py',
    'app/pz/metering_detail.py', 'app/pz/metering_rules.py', 'app/pz/spec.py',
    'app/pz/generator.py', 'app/pz/templates/meter_table.html',
    'app/pz/templates/frame.css', 'app/pz/commission.py',
    'app/web/static/studio.css', 'app/web/templates/studio.html',
]
PARTIAL = ['app/intake/studio_intake.py', 'app/intake/studio_project.py',
           'app/web/static/studio.js']


def partial(name, old, new):
    if name.endswith('studio_intake.py'):
        anchor = 'from app.pz.metering_detail_data import MeteringDetailData\n'
        old = replace_once(old, anchor, anchor + 'from app.data.metering_products import get_metering_catalogue\n')
        start, end = '        metering_detail=MeteringDetailData(', '        document=DocumentRequest('
        return replace_once(old, segment(old, start, end), segment(new, start, end))
    if name.endswith('studio_project.py'):
        start, end = 'STUDIO_HANDOFF_VERSION =', '\n\n\n'
        return replace_once(old, segment(old, start, end), segment(new, start, end))
    if name.endswith('studio.js'):
        return replace_once(new, segment(new, '    const fanMode=', '    const technology='), '')
    raise AssertionError(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    manifest = {}
    for name in FULL + PARTIAL:
        base = args.baseline / name
        data = (root / name).read_bytes()
        if name in PARTIAL:
            data = partial(name, base.read_text(), data.decode()).encode()
        assert not base.exists() or base.read_bytes() != data, name
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
            scope='partial' if name in PARTIAL else 'full')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    dockerfile = (root / 'deploy/studio-ios2.Dockerfile').read_text()
    dockerfile = dockerfile.replace('20261005-samara-vk', '20261005-studio-ios2').replace(
        'studio-ios2-20261005', 'meter-products-20261005').replace('COPY demo/ /app/demo/\n', '')
    (deploy / 'Dockerfile').write_text(dockerfile)
    override = (root / 'deploy/studio-ios2.override.yaml').read_text().replace(
        '20261005-studio-ios2', '20261005-meter-products').replace('studio-ios2-20261005', 'meter-products-20261005')
    (deploy / 'release.override.yaml').write_text(override)
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-meter-products').replace(
        '20261005-samara-vk', '20261005-studio-ios2').replace('restored-pre-studio', 'restored-pre-meters')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_meter_products_release.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-meter-products/answers.json', args.output / 'qa-answers.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__':
    main()
