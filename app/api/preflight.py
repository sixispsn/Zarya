# -*- coding: utf-8 -*-
"""REST-доступ к единому предвыпускному контролю проекта."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.intake.preflight import preflight_request
from app.intake.project_intent import ProjectIntent
from app.intake.questions import questions_for_web
from app.intake.yaml_io import YamlFormatError


router = APIRouter(prefix="/api/project/preflight", tags=["Предпроверка проекта"])


class ProjectPreflightInput(BaseModel):
    project_yaml: str = Field(min_length=1)


@router.get("/questions")
def get_questions():
    """Метаданные уточняющих вопросов и их триггеров для клиентов."""
    return questions_for_web()


@router.post("")
def run_preflight(payload: ProjectPreflightInput):
    """Проверить YAML без запуска расчётов и генерации документов."""
    try:
        intent = ProjectIntent.from_yaml(payload.project_yaml)
    except (YamlFormatError, ValueError) as exc:
        problems = getattr(exc, "problems", [str(exc)])
        raise HTTPException(status_code=422, detail=problems) from exc
    return preflight_request(intent).to_dict()
