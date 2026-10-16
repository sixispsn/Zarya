"""Stage the reviewed IOS2/Studio overlay; retain live sewer intake and auth."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

FULL = [
    "app/quality_gates.py",
    "app/normative/audit_matrix.py",
    "app/web/studio.py",
    "app/web/wizard.py",
    "app/calc/fire_pump_station.py",
    "app/intake/studio_fire_station.py",
    "app/intake/studio_fire_review.py",
    "app/intake/request_dto.py",
    "app/intake/studio_fire_pipework.py",
    "app/intake/studio_fire_location.py",
    "app/intake/project_builder.py",
    "app/intake/studio_fire_fittings.py",
    "app/intake/yaml_io.py",
    "app/intake/preflight.py",
    "app/pz/fire_station_study_sheet.py",
    "app/pz/commission.py",
    "app/pz/ios2_orchestrator.py",
    "app/pz/fire_principle_scheme.py",
    "app/pz/fire_review_scheme.py",
    "app/pz/fire_pressure_review_report.py",
    "app/pz/spec.py",
    "app/pz/fire_station_input_report.py",
    "app/pz/generator.py",
    "app/pz/fire_repair_review_report.py",
    "app/pz/fire_calculation_evidence.py",
    "app/pz/fire_review_binding.py",
    "app/pz/project.py",
    "app/data/fire_pump_geometry.py",
    "app/web/static/studio.css",
    "app/web/static/studio_fire_station.js",
    "app/web/templates/studio.html",
    "app/pz/templates/resilience_document.html",
    "app/pz/templates/fire_review_table.html",
    "app/pz/templates/subitems_residential.html",
    "app/pz/templates/pump_table.html",
    "app/pz/templates/fire_automation.html",
    "app/pz/templates/hydraulic_document.html",
    "app/pz/templates/hydraulic.css",
    "demo/samara_station_review.json"
]
PARTIAL = ['app/intake/studio_intake.py','app/intake/studio_project.py','app/web/static/studio_configurator.js','app/web/static/studio.js']


def segment(text, start, end):
    a=text.index(start)
    return text[a:text.index(end,a)]


def replace_once(text, old, new):
    assert text.count(old)==1, old[:100]
    return text.replace(old,new,1)


def partial(name, old, new):
    if name.endswith('studio_project.py'):
        for line in new.splitlines(True):
            if line.lstrip().startswith(('quantity_review =', 'and not quantity_review')):
                new=replace_once(new,line,'')
        start,end='        "preview_notes":','        "sewer_scheme":'
        return replace_once(new,segment(new,start,end),segment(old,start,end))
    if name.endswith('studio_intake.py'):
        for start,end in [
            ('    Field("fire_topology",','    Field(\n        "fire_corridor_length_m"'),
            ('    if field.kind == "fire_station":','    if field.kind == "t3_sections":'),
            ('def fire_topology_missing(', 'def context_issues('),
        ]:
            old=replace_once(old,end,segment(new,start,end)+end)
        for before,after in [
            ('\nOPTIONS = {\n','\nOPTIONS = {\n'+segment(new,'    "fire_topology":','    "section_k1_flow_basis":')),
            ('    pending.extend(fire_missing(draft))\n','    pending.extend(fire_missing(draft))\n    pending.extend(fire_topology_missing(draft))\n'),
            ('    return IOS2Request(\n',segment(new,'    station_model = values.get("fire_station_model")','        rainwater_reuse=')),
            ('        apartments=values.get("apartments", 0),\n', '        apartments=values.get("apartments", 0),\n'+segment(new,'        floor_elevations_m={','        hws_type=values["hws_type"],')),
            ('        fire_mode="auto",\n',segment(new,'        fire_mode="auto",','        fire_height_m=')),
            ('        source_data=SourceDataRequest(\n',segment(new,'        source_data=SourceDataRequest(\n','            apartment_meter_basis=')),
        ]:
            old=replace_once(old,before,after)
        before=segment(old,'    add("fire", "Уточнение для проверки В2",','    from app.intake.studio_section import section_readiness')
        after=segment(new,'    add("fire", "Уточнение для проверки В2",','    from app.intake.studio_section import section_readiness')
        return replace_once(old,before,after)
    if name.endswith('studio_configurator.js'):
        before="        ['Другие условия ТУ',['connection_note']],\n"
        after=segment(new,"        ['Другие условия ТУ',","        ['Схема К1")
        return replace_once(old,before,after)
    if name.endswith('studio.js'):
        # The separate sewer editor is not part of this release.
        return replace_once(new,segment(new,"    const fanMode=","    const technology="),"")
    raise AssertionError(name)


def main():
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();root=Path(__file__).resolve().parents[1]
    assert not a.output.exists()
    a.output.mkdir(parents=True)
    manifest={}
    for name in FULL+PARTIAL:
        base=a.baseline/name
        data=(root/name).read_bytes()
        if name in PARTIAL: data=partial(name,base.read_text(),data.decode()).encode()
        target=a.output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        manifest[name]=dict(sha256=hashlib.sha256(data).hexdigest(),
            baseline_sha256=hashlib.sha256(base.read_bytes()).hexdigest() if base.exists() else None,
            scope='partial' if name in PARTIAL else 'full')
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for name in ['studio-ios2.Dockerfile','studio-ios2.override.yaml','activate-studio-ios2.sh']:
        target=a.output/'deploy'/name;target.parent.mkdir(exist_ok=True)
        shutil.copyfile(root/'deploy'/name,target)
    for name in ['verify_backup_restore.py','verify_studio_ios2_release.py']:
        target=a.output/'scripts'/name;target.parent.mkdir(exist_ok=True)
        shutil.copyfile(root/'scripts'/name,target)
    shutil.copyfile(root/'output/pdf/studio-ios2-checked/answers.json',a.output/'qa-answers.json')
    print(json.dumps(dict(files=len(manifest),output=str(a.output),legacy_auth_unchanged=True)))

if __name__=='__main__': main()
