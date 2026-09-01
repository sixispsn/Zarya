# -*- coding: utf-8 -*-
"""Версионированное намерение проектировщика до сборки модели ``Project``.

``IOS2Request`` остаётся совместимым DTO существующих входов. Этот небольшой
контейнер добавляет к нему версию контракта и происхождение, не переименовывая
массово рабочий код и не затрагивая расчётное ядро.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.intake.request_dto import IOS2Request
from app.intake.yaml_io import (
    CURRENT_PROJECT_SCHEMA_VERSION,
    dump_request,
    load_request,
)


@dataclass(frozen=True)
class ProjectIntent:
    """Единая оболочка входного намерения для Wizard, YAML, REST и импорта."""

    request: IOS2Request
    schema_version: int = CURRENT_PROJECT_SCHEMA_VERSION
    source_kind: str = "user_input"
    source_ref: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != CURRENT_PROJECT_SCHEMA_VERSION:
            raise ValueError(
                "ProjectIntent имеет неподдерживаемую версию: "
                f"{self.schema_version}; ожидается "
                f"{CURRENT_PROJECT_SCHEMA_VERSION}"
            )

    def validate(self) -> list[str]:
        return self.request.validate()

    def dump_yaml(self) -> str:
        return dump_request(self.request)

    @classmethod
    def from_yaml(
        cls,
        text: str,
        *,
        source_ref: str = "",
    ) -> "ProjectIntent":
        return cls(
            request=load_request(text),
            source_kind="yaml",
            source_ref=source_ref,
        )


IntentLike = IOS2Request | ProjectIntent


def as_project_intent(value: IntentLike) -> ProjectIntent:
    if isinstance(value, ProjectIntent):
        return value
    if isinstance(value, IOS2Request):
        return ProjectIntent(request=value)
    raise TypeError("ожидается IOS2Request или ProjectIntent")


def unwrap_project_intent(value: IntentLike) -> IOS2Request:
    return as_project_intent(value).request
