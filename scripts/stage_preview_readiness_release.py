"""Four-file scoped overlay; leave unpublished Studio inputs out of this release."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

from scripts.stage_studio_ios2_release import replace_once, segment

FILES = ('app/intake/studio_project.py', 'app/web/studio.py',
         'app/pz/ios2_orchestrator.py', 'app/pz/commission.py')


def scoped(name, old, new):
    if name.endswith('studio_project.py'):
        start, end = 'STUDIO_HANDOFF_VERSION =', 'def calculate_project('
        old = replace_once(old, segment(old, start, end), segment(new, start, end))
        old = replace_once(old, 'def calculate_project(draft: dict) -> dict:',
                          'def calculate_project(draft: dict, *, artifacts: dict[str, bool] | None = None) -> dict:')
        return replace_once(old, '    project = bundle.project\n',
            '    project = bundle.project\n' + segment(new, '    if artifacts is not None:', '    from app.intake.studio_fire_station'))
    if name.endswith('web/studio.py'):
        old = replace_once(old,
            'from app.intake.studio_project import STUDIO_HANDOFF_VERSION, calculate_project\n',
            segment(new, 'from app.intake.studio_project import', '\nCOOKIE'))
        old = replace_once(old, 'def capture_pilot(',
                          segment(new, 'def current_preview_artifacts(', 'def capture_pilot(') + 'def capture_pilot(')
        for start, end in (
            ('@router.post("/api/calculate"', '@router.patch("/api/answers"'),
            ('@router.post("/api/package"', '@router.get("/api/package/'),
            ('@router.post("/api/preview"', '@router.get("/api/preview/'),
        ):
            old = replace_once(old, segment(old, start, end), segment(new, start, end))
        anchor = '        saved.get("id") != preview_id\n'
        return replace_once(old, anchor, anchor +
                           '        or (not draft.get("study") and saved.get("stamp") != calculation_stamp(draft))\n')
    if name.endswith('ios2_orchestrator.py'):
        old = replace_once(old, 'from dataclasses import dataclass, field, replace\n',
                          'from dataclasses import dataclass, field, replace\nfrom pathlib import Path\n')
        old = replace_once(old, 'def design_ios2(', segment(new, 'def bundle_artifact_files(', 'def design_ios2(') + 'def design_ios2(')
        start, end = '    bundle.commission_report = build_commission_report(project, artifacts=', '    bundle.commission_control_pdf ='
        return replace_once(old, segment(old, start, end), segment(new, start, end))
    if name.endswith('commission.py'):
        start, end = '        assessment = project.storm.network_assessment', '    if project.grease_trap.required:'
        return replace_once(old, segment(old, start, end), segment(new, start, end))
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
    for name in FILES:
        base = (args.baseline / name).read_bytes()
        data = scoped(name, base.decode(), (root / name).read_text()).encode()
        ast.parse(data, filename=name)
        assert data != base, name
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = dict(sha256=hashlib.sha256(data).hexdigest(),
                              baseline_sha256=hashlib.sha256(base).hexdigest(), scope='partial')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    deploy = args.output / 'deploy'; deploy.mkdir()
    (deploy / 'Dockerfile').write_text(
        'FROM zarya-release:20261005-section-documents\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=preview-readiness-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.studio_project import refresh_document_readiness"\n')
    (deploy / 'release.override.yaml').write_text(
        'services:\n  app:\n    image: zarya-release:20261005-preview-readiness\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: preview-readiness-20261005\n')
    activation = (root / 'deploy/activate-studio-ios2.sh').read_text().replace(
        '20261005-studio-ios2', '20261005-preview-readiness').replace(
        '20261005-samara-vk', '20261005-section-documents').replace('restored-pre-studio', 'restored-pre-preview')
    (deploy / 'activate.sh').write_text(activation)
    scripts = args.output / 'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py', 'verify_section_documents_release.py', 'release_tree_snapshot.py'):
        shutil.copyfile(root / 'scripts' / name, scripts / name)
    shutil.copyfile(root / 'output/pdf/studio-section-documents/answers.json', args.output / 'qa-answers.json')
    print(json.dumps(dict(files=len(manifest), output=str(args.output))))


if __name__ == '__main__':
    main()
