"""Prepare the immutable reviewed case, then use the actual Studio render path.

--prepare recomputes the full L06 matrix and legacy parity; no old PDF reused.
Without it, renders the fingerprint-checked result already prepared locally.
"""
from dataclasses import asdict
import argparse
import json
import os
from pathlib import Path

from app.intake import samara_study
from app.intake.studio_intake import accepted_values
from app.intake.yaml_io import dump_request, load_request
from app.intake.project_builder import build_project
from app.pz.ios2_orchestrator import design_ios2
from app.pz.fire_station_binding import compact_design, digest, validate_design
from scripts.build_samara_section_study import load_basis, make_draft, make_request, make_fire_station, run_checks, OUTPUT
from scripts.build_samara_station_design import calculate_station_design
from scripts.build_samara_diaphragm_correction import calculate_correction, compact_review


def prepare():
    basis=load_basis();draft=make_draft(basis);req=make_request(draft);station=make_fire_station(basis)
    checks=run_checks(draft,os.environ['NODE_BINARY'])
    yaml = dump_request(req)
    # Runtime uses the persisted request, not a privileged script-only object.
    bundle=design_ios2(build_project(load_request(yaml)),output_dir=str(OUTPUT/'coherent-check'),
                       fire_station=station,render_documents=False)
    repair=calculate_correction()
    result=calculate_station_design(basis,bundle,layout_override=repair['apertures_mm'])
    result['repair_review']=compact_review(repair)
    payload=dict(answers=draft['answers'],accepted_values=accepted_values(draft),request_yaml=yaml,
        station=asdict(station),basis=basis,parity=checks,
        result=compact_design(result,bundle.project,station))
    data=dict(payload=payload,payload_sha256=digest(payload),engine_sha256=samara_study.engine_fingerprint())
    validate_design(payload['result'],bundle.project,station)
    audit_dir=OUTPUT/'repair';audit_dir.mkdir(parents=True,exist_ok=True)
    (audit_dir/'diaphragm-correction.json').write_text(json.dumps(repair,ensure_ascii=False,indent=2,allow_nan=False))
    samara_study.CASE.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
    return data


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    if args.prepare or args.prepare_only:
        data=prepare();print(json.dumps(dict(prepared=str(samara_study.CASE),fingerprint=data['payload_sha256'])))
    if not args.prepare_only:
        draft=dict(revision=0,answers={},documents=[])
        samara_study.initialize(draft,None)
        docs,fingerprint=samara_study.render(draft,OUTPUT/'coherent')
        print(json.dumps(dict(output=str(OUTPUT/'coherent'),documents=docs,hash=fingerprint),ensure_ascii=False))


if __name__=='__main__':main()
