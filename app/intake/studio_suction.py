"""Studio transport for the shared, project-bound suction check."""
from tempfile import TemporaryDirectory

from pydantic import Field

from app.intake.studio_intake import IntakeError, build_handoff_request, handoff_missing
from app.pz import suction_check
from app.schemas.pump_suction import ProjectSuctionInput


class StudioSuctionInput(ProjectSuctionInput):
    revision: int = Field(ge=0)
    reviewed: bool = False


def project_context(project, *, dependencies=None):
    try:
        return suction_check.project_context(project, dependencies=dependencies)
    except suction_check.SuctionCheckError as exc:
        raise IntakeError(str(exc)) from exc


def evaluate(context, payload):
    try:
        return suction_check.evaluate(context, payload)
    except suction_check.SuctionCheckError as exc:
        raise IntakeError(str(exc)) from exc


def current_context(draft):
    if draft.get('study'):
        raise IntakeError('Отдельную проверку сохраняйте в своём проекте. '
                          'Подписанный учебный пример не редактируется.')
    if handoff_missing(draft):
        raise IntakeError('Сначала задайте исходные и рассчитайте проект.')
    from app.intake.preflight import preflight_request
    from app.intake.project_builder import build_project
    from app.pz.ios2_orchestrator import design_ios2
    request = build_handoff_request(draft)
    if not preflight_request(request).can_calculate:
        raise IntakeError('Текущие исходные требуют уточнения перед проверкой всасывания.')
    with TemporaryDirectory(prefix='zarya-suction-') as folder:
        project = design_ios2(build_project(request), output_dir=folder,
                              render_documents=False).project
    return project_context(project)


def saved_view(draft, context):
    saved = draft.get('suction_check')
    if not saved:
        return dict(status='not_saved', inputs=None, result=None)
    stale = saved['inputs']['fingerprint'] != context['fingerprint']
    result = None if stale else evaluate(context, StudioSuctionInput.model_validate(saved['inputs']))
    return dict(status='stale' if stale else 'current', inputs=saved['inputs'], result=result)


def save_check(draft, context, payload):
    saved = draft.get('suction_check')
    if (saved and saved['inputs']['fingerprint'] != context['fingerprint']
            and not payload.reviewed):
        raise IntakeError('Исходные изменились: перепроверьте значения и основания потерь '
                          'и явно подтвердите повторную проверку.')
    evaluate(context, payload)
    draft['suction_check'] = dict(inputs=payload.model_dump())
