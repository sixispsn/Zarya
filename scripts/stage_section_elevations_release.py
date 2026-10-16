"""Apply only this turn's annotation diff to the exact running image sources."""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

FILES = ('app/pz/wastewater_presentation.py', 'app/pz/residential_concept_section.py',
    'app/intake/studio_section.py', 'app/intake/studio_intake.py',
    'app/pz/wastewater_graphic_exports.py', 'app/intake/studio_section_review.py',
    'app/intake/studio_project.py', 'app/web/static/studio_configurator.js', 'app/web/static/studio.css',
    'app/web/templates/studio.html')


def without_unpublished_experiment(name, text):
    from scripts.stage_studio_ios2_release import segment
    from scripts.stage_section_inputs_release import scoped
    if name.endswith(('studio_section.py','studio_configurator.js')):
        return scoped(name,text)
    if name.endswith('studio_intake.py'):
        text = text.replace(segment(text,'FIELDS += tuple(Field("section_k1_"','FIELDS += (\n'),'',1)
        text = text.replace(segment(text,'    "section_k1_flow_basis":','    "rainwater_design_winter":'),'',1)
        text = text.replace(segment(text,'    if key.startswith(("section_k1_", "section_k2_")):\n        # Validate dependent',
                                    '    if key in QUICK_START_PRESETS:'),'',1)
    return text


def main():
    p = argparse.ArgumentParser()
    p.add_argument('baseline', type=Path); p.add_argument('before', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args(); root = Path(__file__).resolve().parents[1]
    assert not a.output.exists(); a.output.mkdir(parents=True)
    manifest = {}
    for name in FILES:
        base = (a.baseline/name).read_bytes()
        before = without_unpublished_experiment(name,(a.before/name).read_text())
        after = without_unpublished_experiment(name,(root/name).read_text())
        patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                            fromfile='a/'+name, tofile='b/'+name, n=1))
        assert patch, name
        dest = a.output/name; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(base)
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1'], input=patch, text=True, cwd=a.output, check=True)
        data = dest.read_bytes()
        if name.endswith('.py'): ast.parse(data, filename=name)
        manifest[name] = dict(baseline_sha256=hashlib.sha256(base).hexdigest(),
            sha256=hashlib.sha256(data).hexdigest(), scope='Explicit section datum/main elevations only')
    intake = (a.output/'app/intake/studio_intake.py').read_text()
    assert 'Field("section_k1_"+key' not in intake and 'section_k1_flow_basis' not in intake
    assert 'k1_total_flow_lps=current_k1_total' not in (a.output/'app/intake/studio_section.py').read_text()
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    deploy = a.output/'deploy'; deploy.mkdir()
    (deploy/'Dockerfile').write_text(
        'FROM zarya-release:20261005-section-review\nUSER root\n'
        'ENV ZARYA_BUILD_COMMIT=section-elevations-20261005\nCOPY app/ /app/app/\n'
        'RUN chmod -R a+rX /app/app\nUSER zarya\n'
        'RUN python -c "from app.main import app; from app.intake.studio_intake import FIELD_MAP; assert \'section_zero_absolute_m\' in FIELD_MAP; assert \'section_k1_flow_basis\' not in FIELD_MAP"\n')
    (deploy/'release.override.yaml').write_text('services:\n  app:\n    image: zarya-release:20261005-section-elevations\n'
        '    environment:\n      ZARYA_BUILD_COMMIT: section-elevations-20261005\n')
    activation = (root/'deploy/activate-studio-ios2.sh').read_text().replace('20261005-studio-ios2',
        '20261005-section-elevations').replace('20261005-samara-vk','20261005-section-review').replace(
        'restored-pre-studio','restored-pre-elevations')
    (deploy/'activate.sh').write_text(activation)
    scripts = a.output/'scripts'; scripts.mkdir()
    for name in ('verify_backup_restore.py','verify_section_documents_release.py',
        'verify_section_review_release.py','verify_design_basis_release.py','release_tree_snapshot.py'):
        shutil.copyfile(root/'scripts'/name,scripts/name)
    shutil.copyfile(root/'output/pdf/section-elevations/answers.json',a.output/'qa-answers.json')
    shutil.copyfile(root/'output/pdf/live-section-review/calculation.json',a.output/'baseline-calculation.json')
    print(json.dumps(dict(files=len(FILES),output=str(a.output))))


if __name__ == '__main__': main()
