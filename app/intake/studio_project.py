"""Studio adapter to the existing project pipeline; no engineering formulas."""

from dataclasses import asdict
from tempfile import TemporaryDirectory

from app.intake.preflight import preflight_request
from app.intake.project_builder import build_project
from app.intake.studio_intake import (
    accepted_values,
    build_handoff_request,
    context_issues,
    handoff_missing,
    public_draft,
)
from app.pz.ios2_orchestrator import design_ios2
from app.pz.wastewater_graphic_exports import wastewater_graphic_export
from app.quality_gates import build_release_quality_report
from app.intake.studio_section import section_readiness
from app.pz.metering_options import OPTIONS_NOTICE
from app.pz.equipment_origin import review_equipment_origin
from app.pz.metering_extras import metering_option_rows, resolve_metering_extras
from app.pz.spec_quantity_review import water_spec_quantity_review

STUDIO_HANDOFF_VERSION = "2026-10-16-studio-risers-v1"


def refresh_document_readiness(draft: dict, calculation: dict, commission_report) -> dict:
    """Use the report for this build without recalculating or granting a release.

    The caller supplies the freshly rendered bundle, under the draft lock.
    A preview cannot remove independent calculation/engineering guards.
    """
    if commission_report is None:
        raise ValueError("После сборки отсутствует отчёт проверки документов")
    preflight = preflight_request(build_handoff_request(draft))
    quality = build_release_quality_report(preflight, commission_report)
    from app.intake.studio_readiness import section_readiness as review_sections
    blockers = [row for audit in commission_report.normative_audits
                for row in audit["rows"] if row["blocks_release"]]
    quality_dict = quality.to_dict()
    return {
        **calculation,
        "quality": quality_dict,
        "review_sections": review_sections(quality_dict),
        "gost_blockers": blockers,
        "can_release": bool(calculation.get("can_release") and quality.can_release and not blockers),
    }


def calculate_project(draft: dict, *, artifacts: dict[str, bool] | None = None) -> dict:
    if draft.get("study"):
        from app.intake.studio_study import calculate_study
        return calculate_study(draft)
    if issues := context_issues(draft):
        return {"state": "blocked", "missing": [], "can_release": False, "can_preview": False,
                "issues": [{"code": "studio_scope", "message": note} for note in issues]}
    pending = handoff_missing(draft)
    if pending:
        return {
            "state": "needs_inputs",
            "missing": pending,
            "issues": [],
            "can_release": False,
        }
    req = build_handoff_request(draft)
    preflight = preflight_request(req)
    if not preflight.can_calculate:
        return {
            "state": "blocked",
            "missing": [],
            "can_release": False,
            "issues": [row.to_dict() for row in preflight.blockers],
        }
    try:
        project = build_project(req)
    except ValueError as exc:
        # A domain refusal must not roll back successfully calculated demand.
        return {
            "state": "blocked", "missing": [], "can_release": False,
            "can_preview": False,
            "issues": [{"code": "calculation_input", "message": str(exc)}],
        }
    with TemporaryDirectory(prefix="zarya-studio-calc-") as folder:
        bundle = design_ios2(project, output_dir=folder, render_documents=False)
    project = bundle.project
    if artifacts is not None:
        from app.pz.commission import build_commission_report
        bundle.commission_report = build_commission_report(project, artifacts=artifacts)
    from app.intake.studio_fire_station import summary as station_summary
    station = station_summary(bundle)
    if req.fire_station_model and station is None:
        station = dict(state="needs_data" if project.fire.required else "not_required",
                       note=("ВПВ для здания не требуется; модель станции не применена."
                             if not project.fire.required else "Расчёт станции не выполнен. " +
                             " ".join(w for w in bundle.warnings if w.startswith("fire_station:"))))
        station["pressure_review"] = bundle.fire_pressure_review
    quality = build_release_quality_report(preflight, bundle.commission_report)
    from app.intake.studio_readiness import section_readiness as review_sections
    gost_blockers = [
        row
        for audit in bundle.commission_report.normative_audits
        for row in audit["rows"]
        if row["blocks_release"]
    ]
    inputs = public_draft(draft)
    paths = project.head_paths
    head_ready = bool(paths and paths.complete and not inputs["head_missing"])
    storm_ready = not inputs["storm_missing"] and project.storm.result is not None
    scheme = wastewater_graphic_export(project, "k1-k2")
    quantity_review = next(row for row in inputs["fields"] if row["key"] == "storm_funnels_count")["status"] in {"review", "conflict"}
    from app.intake.studio_metering import layout_summary
    from app.pz.water_station_review import review_station
    from app.pz.suction_check import review_suction
    # Display partial data honestly; a default cannot resolve unknown project inputs.
    return {
        "state": "calculated",
        "handoff_version": STUDIO_HANDOFF_VERSION,
        "missing": [],
        "can_release": preflight.can_release
        and quality.can_release
        and head_ready
        and scheme.ready
        and not quantity_review
        and (not project.t3_sections or bool(project.t3_hydraulic_result and project.t3_hydraulic_result.all_velocities_ok))
        and not gost_blockers,
        "can_preview": True,
        "preview_notes": ([] if head_ready else [
            "Расчёт напора В1/Т3 не завершён. Недостающие потери не приняты равными нулю; "
            "необходимость повысительного насоса и его рабочая точка не подтверждены."
        ]) + (["Количество воронок из документа не подтверждено: в спецификации оно оставлено пустым. "
               "Характерная ветвь К2 показана независимо от общего количества."] if quantity_review else []),
        "sewer_scheme": {"ready": scheme.ready, "reasons": list(scheme.reasons),
                         "presentation": scheme.presentation, "available": scheme.available,
                         "representative": section_readiness(accepted_values(draft))},
        "gost_blockers": gost_blockers,
        "flows": asdict(project.flows),
        "sewage_riser_review": sewage_riser_summary(project),
        "sewage_diagnostic_review": sewage_diagnostic_summary(project),
        "meters": [asdict(row) for row in project.meters.rows],
        "metering_layout": layout_summary(project),
        "water_station_review": review_station(project),
        "suction_check": review_suction(project),
        "metering_options": metering_option_rows(project),
        "metering_equipment": resolve_metering_extras(project),
        "equipment_origin": review_equipment_origin(project),
        "metering_options_notice": OPTIONS_NOTICE if project.metering_detail.enhancements else "",
        "spec_quantity_review": water_spec_quantity_review(project),
        "meter_error": project.meters.selection_error,
        "hydraulics": asdict(project.v1_hydraulic_result) if project.v1_hydraulic_result else None,
        "hot_hydraulics": asdict(project.t3_hydraulic_result) if project.t3_hydraulic_result else None,
        "hws_circulation": hws_circulation_summary(project),
        "head": {
            "ready": head_ready,
            "preliminary": bool(req.source_data.apartment_meter_basis),
            "basis": req.source_data.apartment_meter_basis,
            "paths": [
                dict(asdict(path), complete=path.complete) for path in paths.paths
            ]
            if paths
            else [],
            "required_m": paths.governing.head.h_required_m if head_ready else None,
            "pump_m": paths.governing.head.h_pump_m if head_ready else None,
            "pump_needed": paths.governing.head.pump_needed if head_ready else None,
        },
        "pumps": asdict(project.pumps) if head_ready else None,
        "fire": asdict(project.fire),
        "fire_station": station,
        "storm": asdict(project.storm.result) if storm_ready else None,
        "storm_note": project.storm.system_note,
        "issues": [row.to_dict() for row in preflight.issues],
        "quality": quality.to_dict(),
        "review_sections": review_sections(quality.to_dict()),
        "warnings": bundle.warnings,
        "status": bundle.status,
    }


def sewage_riser_summary(project):
    """Expose the existing result verbatim, including independent failure notes."""
    return asdict(project.sewage.result) if project.sewage.result is not None else None


def sewage_diagnostic_summary(project):
    """Copy an existing diagnostic result; do not run or reinterpret checks."""
    result = project.sewage.hydraulic_assessment
    return asdict(result) if result is not None else None


def hws_circulation_summary(project):
    from app.pz.hws_stage_p import stage_p_circulation
    return {**asdict(stage_p_circulation(project)), "inputs": asdict(project.hws_stage_p)}
