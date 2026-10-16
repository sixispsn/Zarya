"""Read-only review of one saved project. Never a production release gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.intake.project_builder import RequestValidationError, build_project
from app.intake.request_dto import IOS2Request
from app.pz.project import Project
from app.pz.wastewater_fan_binding import (
    build_bound_fan_preview_svgs,
    fan_details_from_project,
)
from app.pz.wastewater_ventilation import audit_project_fan_ventilation
from app.web.fan_inputs import FanFormInput


@dataclass(frozen=True)
class FanReview:
    checks: tuple[dict, ...]
    project: Project | None = None

    @property
    def preview_ready(self) -> bool:
        return bool(self.checks) and all(c["status"] == "verified" for c in self.checks)

    def to_mapping(self, revision: str) -> dict:
        return {
            "revision": revision,
            "preview_ready": self.preview_ready,
            "production_ready": False,
            "scope": "Контроль фановых узлов сохранённой версии. Не допуск комплекта ПД к выпуску.",
            "checks": list(self.checks),
        }


def assess_fan_preview(req: IOS2Request, *, check_drawing: bool = True) -> FanReview:
    """No mutations, formulas or fallback geometry. Missing proof stays pending."""
    checks: list[dict] = []

    def add(code, area, status, message, *, detail=""):
        checks.append(
            dict(
                code=code,
                area=area,
                target="К1",
                status=status,
                message=message,
                reference="",
                detail=detail,
            )
        )

    try:
        project = build_project(req)
    except RequestValidationError as exc:
        for i, message in enumerate(exc.problems):
            add(f"INPUT-{i}", "project", "fail", message)
        return FanReview(tuple(checks))
    add(
        "PROJECT-INPUT",
        "project",
        "verified",
        "Сохранённые исходные данные проекта прочитаны",
    )
    audit = audit_project_fan_ventilation(project)
    checks.extend(dict(asdict(c), area="normative", detail="") for c in audit.checks)
    geometry = project.sewage.fan_geometry
    add(
        "FAN-GEOMETRY",
        "geometry",
        "verified" if geometry and geometry.confirmed else "pending",
        "Геометрия узлов подтверждена"
        if geometry and geometry.confirmed
        else "Задайте геометрию всех узлов, основание и подтвердите отметки",
    )
    if project.sewage.roof_relative_elevation_m is None:
        add(
            "FAN-ROOF-LEVEL",
            "geometry",
            "pending",
            "Укажите общую относительную отметку кровли",
        )
    try:
        FanFormInput.from_request(req).validate_links()
    except ValueError as exc:
        add("FAN-GROUP-LINKS", "geometry", "fail", str(exc))
    if any(c["status"] != "verified" for c in checks):
        return FanReview(tuple(checks), project)
    try:
        data = fan_details_from_project(project)
    except ValueError as exc:
        add(
            "FAN-BUILDING-BINDING",
            "geometry",
            "fail",
            _binding_message(str(exc)),
            detail=str(exc),
        )
        return FanReview(tuple(checks), project)
    add(
        "FAN-BUILDING-BINDING",
        "geometry",
        "verified",
        "Узлы связаны с реальными стояками, отметками и выпусками проекта",
    )
    if check_drawing:
        try:
            build_bound_fan_preview_svgs(project, data)
        except ValueError as exc:
            add(
                "FAN-DRAWING",
                "drawing",
                "fail",
                "Контроль графики не пройден: PDF не сформирован. Проверьте техническую причину.",
                detail=str(exc),
            )
            return FanReview(tuple(checks), project)
        add(
            "FAN-DRAWING",
            "drawing",
            "verified",
            "Связность элементов, ссылки между листами и графические проверки пройдены",
        )
    return FanReview(tuple(checks), project)


def _binding_message(detail: str) -> str:
    messages = {
        "fan port elevation differs": "Отметка стыка фанового узла не совпадает с верхним концом трубы стояка. Согласуйте обе привязки.",
        "fan port must be inside": "Стык фанового узла должен находиться внутри верхнего этажа выше ревизии. Проверьте ограничения текущей деталировки.",
        "valve floor/ceiling differs": "Пол или потолок узла клапана не совпадают с отметками верхнего этажа.",
        "detail roof level differs": "Отметка кровли узла отличается от отметки здания.",
        "explicit storey height": "Укажите высоту этажа и общую отметку кровли.",
        "nonuniform": "Эта привязка пока поддерживает только одинаковую высоту этажей. Неравномерный профиль здания требует отдельной деталировки.",
        "bound preview currently supports": "Контрольная привязка пока поддерживает только плоскую кровлю.",
        "unsupported valve contour": "Чертёж выбранного клапана пока не поддержан графическим адаптером. Автоматическая замена запрещена.",
        "this valve outline requires": "Поддержанный контур клапана требует присоединения с наружным диаметром 110 мм. Переход не задан.",
        "valve connection OD differs": "Наружный диаметр трубы не совпадает с присоединением клапана. Необходимо явно задать переход.",
        "valve must be above": "Клапан не помещается между бортом прибора и потолком с учётом его высоты.",
        "building inputs incomplete": "Не хватает исходных данных для общей схемы здания. См. перечень в технической причине.",
    }
    return next(
        (message for key, message in messages.items() if detail.startswith(key)),
        "Привязка фановых узлов не прошла проверку. См. техническую причину; данные не подменены.",
    )
