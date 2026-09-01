# -*- coding: utf-8 -*-
"""Фасад полного пути ``ProjectIntent → Project → комплект``.

Расчётные функции остаются в прежних модулях. Фасад лишь обеспечивает единый
вход, предвыпускную проверку и совместимый вызов существующего координатора.
"""
from __future__ import annotations

from typing import Any

from app.intake.preflight import preflight_request
from app.intake.project_builder import RequestValidationError, build_project
from app.intake.project_intent import IntentLike
from app.pz.ios2_orchestrator import IOS2DesignBundle, design_ios2


def design_project(intent: IntentLike, **design_options: Any) -> IOS2DesignBundle:
    """Выполнить существующий конвейер, не подменяя ни одну формулу."""
    report = preflight_request(intent)
    if not report.can_calculate:
        raise RequestValidationError([row.message for row in report.blockers])
    return design_ios2(build_project(intent), **design_options)
