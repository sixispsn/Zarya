"""Publish the existing K2/fan intake only, not the unrelated K1 experiment."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

from scripts.stage_studio_ios2_release import replace_once, segment

FILES = ('app/intake/studio_intake.py', 'app/intake/studio_section.py',
         'app/intake/studio_project.py', 'app/web/static/studio.js',
         'app/web/static/studio_configurator.js', 'app/web/templates/studio.html')


def scoped(name, new):
    if name.endswith('studio_intake.py'):
        new = replace_once(new, segment(new, 'FIELDS += tuple(Field("section_k1_"', 'FIELD_MAP ='), '')
        new = replace_once(new, segment(new, '    "section_k1_flow_basis":', '    "rainwater_design_winter":'), '')
        new = replace_once(new, segment(new, '    if key.startswith(("section_k1_", "section_k2_")):\n        # Validate dependent', '    if key in QUICK_START_PRESETS:'), '')
    if name.endswith('studio_section.py'):
        new = replace_once(new, 'from app.pz.section_main_hydraulics import current_k1_total\n', '')
        new = replace_once(new, segment(new, '        k1_total_flow_lps=current_k1_total(', '    )\n'), '')
    if name.endswith('studio_configurator.js'):
        new = replace_once(new, segment(new, "        ['К1 · проверка конечного участка'", "        ['Схема К2"), '')
    return new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    assert not args.output.exists()
    args.output.mkdir(parents=True)
    manifest = {}
    for name in FILES:
        base = (args.baseline / name).read_bytes()
        data = scoped(name, (root / name).read_text()).encode()
        if name.endswith('.py'):
            ast.parse(data, filename=name)
        assert base != data, name
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
                              baseline_sha256=hashlib.sha256(base).hexdigest(), scope='K2/fan intake')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(
        'FROM zarya-release:20261005-preview-readiness\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=section-inputs-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.studio_intake import FIELD_MAP; assert \'section_fan_mode\' in FIELD_MAP"\n')
    (deploy / 'release.override.yaml').write_text(
        'services:\n  app:\n    image: zarya-release:20261005-section-inputs\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: section-inputs-20261005\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-section-inputs').replace(
        '20261005-samara-vk', '20261005-preview-readiness').replace('restored-pre-studio', 'restored-pre-inputs')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_section_documents_release.py', 'release_tree_snapshot.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-section-documents/answers.json', args.output / 'qa-answers.json')
    shutil.copyfile(root / 'output/pdf/live-preview-readiness/calculation.json', args.output / 'baseline-calculation.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__':
    main()
