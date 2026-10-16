"""Small release on the current live baseline; excludes the local K1 experiment."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
from scripts.stage_studio_ios2_release import replace_once, segment
from scripts.stage_section_inputs_release import scoped as previous_scope

FILES = ('app/intake/studio_design_basis.py', 'app/intake/studio_intake.py',
         'app/intake/studio_project.py', 'app/intake/project_builder.py',
         'app/pz/project.py', 'app/pz/templates/subitems_residential.html',
         'app/web/static/studio.js', 'app/web/static/studio_configurator.js',
         'app/web/templates/studio.html')


def scoped(name, new):
    if name.endswith('studio_intake.py'):
        new = replace_once(new, segment(new, 'FIELDS += tuple(Field("section_k1_"',
            'FIELDS += (\n    Field("project_assignment_ref"'), '')
        new = replace_once(new, segment(new, '    "section_k1_flow_basis":', '    "rainwater_design_winter":'), '')
        new = replace_once(new, segment(new, '    if key.startswith(("section_k1_", "section_k2_")):\n        # Validate dependent', '    if key in QUICK_START_PRESETS:'), '')
        return new
    return previous_scope(name, new) if name.endswith('studio_configurator.js') else new


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    assert not args.output.exists(); args.output.mkdir(parents=True)
    manifest = {}
    for name in FILES:
        prior = args.baseline / name
        base = prior.read_bytes() if prior.exists() else None
        data = scoped(name, (root / name).read_text()).encode()
        if name.endswith('.py'): ast.parse(data, filename=name)
        assert base != data, name
        target = args.output / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base).hexdigest() if base is not None else None,
            scope='Optional shared design references and separate TU in Studio/PZ')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(
        'FROM zarya-release:20261005-section-inputs\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=design-basis-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.studio_intake import FIELD_MAP; assert \'project_assignment_ref\' in FIELD_MAP; assert \'section_k1_flow_basis\' not in FIELD_MAP"\n')
    (deploy / 'release.override.yaml').write_text(
        'services:\n  app:\n    image: zarya-release:20261005-design-basis\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: design-basis-20261005\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-design-basis').replace(
        '20261005-samara-vk', '20261005-section-inputs').replace('restored-pre-studio', 'restored-pre-basis')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_section_documents_release.py',
                 'verify_design_basis_release.py', 'release_tree_snapshot.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-section-documents/answers.json', args.output / 'qa-answers.json')
    shutil.copyfile(root / 'output/pdf/live-section-inputs/calculation.json', args.output / 'baseline-calculation.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__': main()
