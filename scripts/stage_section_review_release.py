"""Only the PDF review UI/API, over the published design-basis image."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

FILES = ('app/intake/studio_section_review.py', 'app/web/studio.py', 'app/web/pilot.py',
         'app/web/static/studio.js', 'app/web/templates/studio.html')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('baseline', type=Path); p.add_argument('output', type=Path)
    args = p.parse_args(); root = Path(__file__).resolve().parents[1]
    assert not args.output.exists(); args.output.mkdir(parents=True)
    manifest = {}
    for name in FILES:
        prior = args.baseline / name
        base = prior.read_bytes() if prior.exists() else None
        data = (root / name).read_bytes()
        # Keep the pre-existing duplicate import in the deployed baseline; its
        # unrelated local cleanup is not a reason to expand this release.
        if name == 'app/web/studio.py':
            line = b'from app.intake.pilot_objects import calculation_stamp\n'
            assert base.count(line) == 2 and data.count(line) == 1
            data = data.replace(line, line + line, 1)
        if name.endswith('.py'): ast.parse(data, filename=name)
        assert base != data
        target = args.output / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base).hexdigest() if base else None,
            scope='Input/PDF-bound layout review; no release or calculation change')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(
        'FROM zarya-release:20261005-design-basis\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=section-review-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.studio_section_review import REVIEW_VERSION; from app.intake.studio_intake import FIELD_MAP; assert \'section_k1_flow_basis\' not in FIELD_MAP"\n')
    (deploy / 'release.override.yaml').write_text(
        'services:\n  app:\n    image: zarya-release:20261005-section-review\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: section-review-20261005\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-section-review').replace(
        '20261005-samara-vk', '20261005-design-basis').replace('restored-pre-studio', 'restored-pre-review')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_section_documents_release.py',
                 'verify_section_review_release.py', 'verify_design_basis_release.py', 'release_tree_snapshot.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-section-documents/answers.json', args.output / 'qa-answers.json')
    shutil.copyfile(root / 'output/pdf/live-design-basis/calculation.json', args.output / 'baseline-calculation.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__': main()
