"""Nine-file overlay over meter-products; never publish the whole dirty tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from scripts.stage_studio_ios2_release import replace_once, segment

FULL = [
    'app/intake/studio_readiness.py', 'app/pz/water_package.py',
    'app/pz/generator.py', 'app/pz/ios2_orchestrator.py',
    'app/web/wizard.py', 'app/web/studio.py', 'app/web/templates/studio.html',
]
PARTIAL = ['app/intake/studio_project.py', 'app/web/static/studio.js']


def scoped(name, old, new):
    if name.endswith('studio_project.py'):
        start, end = 'STUDIO_HANDOFF_VERSION =', '\n\n\n'
        old = replace_once(old, segment(old, start, end), segment(new, start, end))
        for anchor, addition in [
            ('    quality = build_release_quality_report(preflight, bundle.commission_report)\n',
             '    from app.intake.studio_readiness import section_readiness as review_sections\n'),
            ('        "quality": quality.to_dict(),\n',
             '        "review_sections": review_sections(quality.to_dict()),\n'),
        ]:
            old = replace_once(old, anchor, anchor + addition)
        return old
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
            data = scoped(name, base.read_text(), data.decode()).encode()
        assert not base.exists() or base.read_bytes() != data, name
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
            scope='partial' if name in PARTIAL else 'full')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(
        'FROM zarya-release:20261005-meter-products\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=section-documents-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.pz.water_package import PARTS; assert PARTS"\n')
    (deploy / 'release.override.yaml').write_text(
        'services:\n  app:\n    image: zarya-release:20261005-section-documents\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: section-documents-20261005\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-section-documents').replace(
        '20261005-samara-vk', '20261005-meter-products').replace('restored-pre-studio', 'restored-pre-sections')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_section_documents_release.py', 'release_tree_snapshot.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-section-documents/answers.json', args.output / 'qa-answers.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__':
    main()
