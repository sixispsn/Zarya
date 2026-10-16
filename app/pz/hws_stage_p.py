"""Recompute the stage-P estimate from current project data at every output."""
from app.calc.hws_stage_p import calculate_stage_p_circulation


def stage_p_circulation(project):
    return calculate_stage_p_circulation(
        project.hws_stage_p, project.flows.q_hr_h or None,
        stage=project.document.stage_label, hws_type=project.building.hws_type.value,
        purpose=project.building.purpose.value,
    )
