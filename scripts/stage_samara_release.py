"""Build a narrow overlay on the inspected production code, not the dirty tree.

Only the approved V2 prerequisites and fixed Samara example are published.
Unrelated, unpublished IOS3/intake edits deliberately stay local. The four
partial files are patched from the production snapshot with exact anchors.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


FULL = '''
app/calc/fire_diaphragm.py
app/calc/fire_diaphragm_graph.py
app/calc/fire_hydraulics.py
app/calc/fire_nomogram_flow.py
app/calc/fire_pressure_flow.py
app/calc/fire_pump_envelope.py
app/calc/fire_pump_station.py
app/calc/fire_regulator_review.py
app/calc/fire_station_documents.py
app/calc/fire_station_pipework.py
app/calc/ring_hydraulics.py
app/data/fire_diaphragm_nomogram.py
app/data/fire_pump_study.py
app/data/fire_regulators.py
app/data/fire_station_design.py
app/data/fire_station_documents.py
app/intake/project_builder.py
app/intake/samara_study.py
app/intake/studio_study.py
app/pz/fire_station_binding.py
app/pz/fire_station_design_report.py
app/pz/fire_station_design_scheme.py
app/pz/geometry_builder.py
app/pz/ios2_orchestrator.py
app/pz/project.py
app/pz/section_level_mark.py
app/pz/section_fan.py
app/pz/wastewater_presentation.py
app/pz/wastewater_building_drafting.py
app/pz/templates/fire_station_design_table.html
app/pz/templates/pump_table.html
app/pz/templates/subitems_residential.html
demo/samara_station_review.json
'''.split()
PARTIAL = ['app/intake/studio_intake.py', 'app/pz/spec.py',
           'app/web/static/studio.js', 'app/web/templates/studio.html']


def once(text, old, new):
    assert text.count(old) == 1, f'Unexpected production source: {old[:90]}'
    return text.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists(), 'Use a fresh staging directory'
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True)
    shutil.copyfile(root / 'deploy/samara-ios2.dockerignore', args.output / '.dockerignore')
    manifest = {}
    for name in FULL + PARTIAL:
        source = root / name
        base = args.baseline / ('zarya-samara-base-app' if name.startswith('app/') else 'zarya-samara-base-demo') / name.split('/', 1)[1]
        data = source.read_bytes()
        if name in PARTIAL:
            text = base.read_text()
            if name.endswith('studio_intake.py'):
                text = once(text, 'def answer_field(draft: dict, key: str, raw) -> None:\n',
                    'def answer_field(draft: dict, key: str, raw) -> None:\n'
                    "    if draft.get('study', {}).get('kind') == 'samara':\n"
                    "        raise IntakeError('Самарский контрольный пример имеет фиксированные проверенные исходные. Для другого объекта вернитесь к своему проекту.')\n")
            elif name.endswith('spec.py'):
                text = once(text, '            if fp.required and fp.top3:\n',
                    "            if fp.station_design:\n"
                    "                from app.pz.fire_station_binding import station_spec_rows\n"
                    "                for row in station_spec_rows(fp.station_design):\n"
                    "                    sec.rows.append(SpecRow(next_pos(), row['name'], type_mark=row['mark'],\n"
                    "                        unit=row['unit'], qty=row['qty'], note=row['note']))\n"
                    '            elif fp.required and fp.top3:\n')
            elif name.endswith('studio.js'):
                # The three inserted lines are self-contained UI branches.
                additions = [line for line in source.read_text().splitlines(True)
                             if "if(draft.study?.kind==='samara')" in line or 'if(p?.ios2 && p?.fire_station)' in line]
                assert len(additions) == 3
                text = once(text, '  function setup() {\n', '  function setup() {\n' + additions[0])
                text = once(text, "    if(draft.study) return `<section class=\"delivery\"", additions[1] + "    if(draft.study) return `<section class=\"delivery\"")
                text = once(text, '  function projectResults() {\n    const p = draft.project_calculation;\n',
                    '  function projectResults() {\n    const p = draft.project_calculation;\n' + additions[2])
            else:
                text = once(text, '/static/studio.js?v=32', '/static/studio.js?v=34-samara')
                card = next(line for line in source.read_text().splitlines(True) if 'data-kind="samara"' in line)
                anchor = next(line for line in text.splitlines(True) if 'data-kind="three"' in line)
                text = once(text, anchor, anchor + card)
            data = text.encode()
        target = args.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = {
            'sha256': hashlib.sha256(data).hexdigest(),
            'baseline_sha256': hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
            'scope': 'partial' if name in PARTIAL else 'full',
        }
    for name in ('samara-ios2.Dockerfile', 'samara-ios2.override.yaml', 'activate-samara-ios2.sh'):
        target = args.output / 'deploy' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(root / 'deploy' / name, target)
    for name in ('verify_backup_restore.py', 'verify_pilot_container.py',
                 'verify_section_release.py', 'verify_samara_release.py'):
        target = args.output / 'scripts' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(root / 'scripts' / name, target)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Staged {len(manifest)} runtime files; {len(PARTIAL)} narrow patches; no legacy/auth/project-store changes.')


if __name__ == '__main__':
    main()
