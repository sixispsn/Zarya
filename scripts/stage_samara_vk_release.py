"""Narrow IOS2/IOS3 overlay on the inspected 20261004 production snapshot."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

FULL = '''
app/calc/fire_repair_flow.py
app/data/fire_diaphragm_layout.py
app/intake/samara_study.py
app/pz/aux_schemes.py
app/pz/fire_diaphragm_correction_report.py
app/pz/fire_station_binding.py
app/pz/fire_station_design_report.py
app/pz/fire_station_design_scheme.py
app/pz/generator.py
app/pz/residential_concept_section.py
app/pz/residential_plan_section.py
app/pz/section_fan_drawing.py
app/pz/section_main_hydraulics.py
app/pz/section_storm.py
app/pz/spec.py
app/pz/templates/fire_station_design_table.html
app/pz/templates/pump_document.css
app/pz/templates/wastewater_calculation_body.html
app/pz/templates/wastewater_pz_body.html
app/pz/wastewater_floor_drafting.py
app/pz/wastewater_gost.py
app/pz/wastewater_graphic_exports.py
app/pz/wastewater_ugo.py
demo/samara_station_review.json
'''.split()
PARTIAL = ['app/web/static/studio.js', 'app/web/templates/studio.html']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('baseline',type=Path)
    parser.add_argument('output',type=Path);args=parser.parse_args()
    assert not args.output.exists(), 'Use a fresh staging directory'
    root=Path(__file__).resolve().parents[1];args.output.mkdir(parents=True)
    shutil.copyfile(root/'deploy/samara-ios2.dockerignore',args.output/'.dockerignore')
    manifest={}
    for name in FULL+PARTIAL:
        source=root/name
        base=args.baseline/('zarya-vk-base-app' if name.startswith('app/') else 'zarya-vk-base-demo')/name.split('/',1)[1]
        data=source.read_bytes()
        if name in PARTIAL:
            text=base.read_text();local=source.read_text()
            if name.endswith('studio.js'):
                for marker in ("if(draft.study?.kind==='samara')",'if(p?.ios2 && p?.fire_station)'):
                    old=[l for l in text.splitlines(True) if marker in l]
                    new=[l for l in local.splitlines(True) if marker in l]
                    assert len(old)==len(new)==(2 if 'draft.study' in marker else 1)
                    for a,b in zip(old,new):
                        assert text.count(a)==1;text=text.replace(a,b,1)
            else:
                old=next(l for l in text.splitlines(True) if 'data-kind="samara"' in l)
                new=next(l for l in local.splitlines(True) if 'data-kind="samara"' in l)
                text=text.replace(old,new,1)
                assert text.count('studio.js?v=34-samara')==1
                text=text.replace('studio.js?v=34-samara','studio.js?v=35-samara-vk')
            data=text.encode()
        dest=args.output/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
        manifest[name]=dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
            scope='partial' if name in PARTIAL else 'full')
    for name in ('samara-vk.Dockerfile','samara-vk.override.yaml','activate-samara-vk.sh'):
        dest=args.output/'deploy'/name;dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(root/'deploy'/name,dest)
    for name in ('verify_backup_restore.py','verify_pilot_container.py','verify_section_release.py',
                 'verify_samara_vk_release.py','verify_samara_vk_live.py','verify_samara_vk_overlay.py'):
        dest=args.output/'scripts'/name;dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(root/'scripts'/name,dest)
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Staged {len(manifest)} files; only Samara UI branches; no auth/storage/legacy changes.')


if __name__=='__main__':main()
