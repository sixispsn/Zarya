# -*- coding: utf-8 -*-
"""REST-доступ к единому предвыпускному контролю проекта."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.intake.advisories import review_request
from app.intake.preflight import preflight_request
from app.intake.project_intent import ProjectIntent
from app.intake.questions import evaluate_questions, questions_for_web
from app.intake.request_dto import (
    ConsumerGroupRequest,
    DocumentRequest,
    IOS2Request,
)
from app.intake.yaml_io import YamlFormatError


router = APIRouter(prefix="/api/project/preflight", tags=["Предпроверка проекта"])


class ProjectPreflightInput(BaseModel):
    project_yaml: str = Field(min_length=1)


class LiveConsumerInput(BaseModel):
    code: str = ""
    name: str = ""
    count: int = 0


class LivePreflightInput(BaseModel):
    """Минимальный срез формы для серверной применимости и advisories."""

    building_type: str = "residential"
    floors: int = 0
    building_height_m: float = 0.0
    total_area_m2: float = 0.0
    fire_mode: str = "auto"
    fire_height_m: float | None = None
    fire_category: str = ""
    apartments: int = 0
    roof_type: str = "not_set"
    storm_city: str = ""
    storm_roof_area_m2: float = 0.0
    consumers: list[LiveConsumerInput] = Field(default_factory=list)
    group_showers_answer: str = "unknown"
    group_showers_count: int = 0
    food_service_answer: str = "unknown"
    catering_type: str = "none"
    catering_seats: int = 0
    catering_conditional_dishes: int = 0
    school_grease_by_assignment: bool = False
    grease_wastewater_answer: str = "unknown"
    grease_trap_location: str = "unknown"


@router.get("/questions")
def get_questions():
    """Метаданные уточняющих вопросов и их триггеров для клиентов."""
    return questions_for_web()


@router.post("/live")
def run_live_preflight(payload: LivePreflightInput):
    """Вернуть единое серверное состояние вопросов и подсказок формы.

    Этот быстрый маршрут не запускает расчёты и не подменяет итоговый
    ``preflight_request`` перед выпуском.
    """
    request = IOS2Request(
        document=DocumentRequest("", "", ""),
        building_type=payload.building_type,
        floors=payload.floors,
        building_height_m=payload.building_height_m,
        total_area_m2=payload.total_area_m2,
        fire_mode=payload.fire_mode,
        fire_height_m=payload.fire_height_m,
        fire_category=payload.fire_category,
        apartments=payload.apartments,
        roof_type=payload.roof_type,
        storm_city=payload.storm_city,
        storm_roof_area_m2=payload.storm_roof_area_m2,
        consumers=[
            ConsumerGroupRequest(row.code, row.count, row.name)
            for row in payload.consumers
        ],
        group_showers_answer=payload.group_showers_answer,
        group_showers_count=payload.group_showers_count,
        food_service_answer=payload.food_service_answer,
        catering_type=payload.catering_type,
        catering_seats=payload.catering_seats,
        catering_conditional_dishes=payload.catering_conditional_dishes,
        school_grease_by_assignment=payload.school_grease_by_assignment,
        grease_wastewater_answer=payload.grease_wastewater_answer,
        grease_trap_location=payload.grease_trap_location,
    )
    questions = evaluate_questions(request)
    advisories = review_request(request)
    applicable = [row for row in questions if row.applicable]
    missing_fields = [
        field
        for row in applicable
        for field in row.missing_fields
    ]
    return {
        "questions": [row.to_dict() for row in questions],
        "advisories": [
            {
                "level": row.level,
                "code": row.code,
                "message": row.message,
                "reference": row.reference,
            }
            for row in advisories
            if not row.code.startswith("technology_")
        ],
        "summary": {
            "applicable": len(applicable),
            "total": sum(row.total_count for row in applicable),
            "completed": sum(row.completed_count for row in applicable),
            "missing": len(missing_fields),
            "missing_fields": missing_fields,
        },
    }


@router.post("")
def run_preflight(payload: ProjectPreflightInput):
    """Проверить YAML без запуска расчётов и генерации документов."""
    try:
        intent = ProjectIntent.from_yaml(payload.project_yaml)
    except (YamlFormatError, ValueError) as exc:
        problems = getattr(exc, "problems", [str(exc)])
        raise HTTPException(status_code=422, detail=problems) from exc
    return preflight_request(intent).to_dict()
