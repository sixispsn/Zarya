# -*- coding: utf-8 -*-
"""Тесты Wizard (без live-сервера: проверяем парсинг форм → DTO и шаблоны).

Live-путь (uvicorn + POST + скачивание PDF) прогнан вручную и работает;
здесь — быстрые структурные проверки, не зависящие от портов/httpx.
"""
import os
import pytest


def test_wizard_router_importable():
    from app.web.wizard import router
    paths = {r.path for r in router.routes}
    assert "/wizard" in paths
    assert "/wizard/design" in paths
    assert "/wizard/result/{run_id}" in paths
    assert "/wizard/file/{run_id}/{name}" in paths


def test_wizard_included_in_app():
    from app.main import app
    paths = app.openapi()["paths"].keys()
    assert "/wizard" in paths
    assert "/wizard/design" in paths


def test_root_redirects_to_workspace():
    from app.main import root
    response = root()
    assert response.status_code == 307
    assert response.headers["location"] == "/wizard"


def test_document_stage_label_preserves_string_stage():
    from app.pz.project import DocumentInfo
    assert DocumentInfo(stage="Р").stage_label == "Р"


def test_templates_exist_and_valid_jinja():
    from app.web.wizard import _TPL
    tdir = "app/web/templates"
    for name in ("wizard_form.html", "wizard_result.html"):
        assert os.path.exists(os.path.join(tdir, name))
        _TPL.env.get_template(name)   # парсится с фильтрами веб-приложения


def test_form_template_has_all_sections():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("app/web/templates"))
    # рендерим шаблон — имена run/riser-полей генерятся циклом
    html = env.get_template("wizard_form.html").render(errors=[])
    assert html.count("<fieldset") == 7
    for field in ("cipher", "object_name", "building_type", "floors", "height",
                  "room_name", "run1_from", "riser1_name", "source_node"):
        assert f'name="{field}"' in html


def test_result_template_shows_key_numbers():
    html = open("app/web/templates/wizard_result.html", encoding="utf-8").read()
    for token in ("fire.pk_total", "fire.required_head", "pdfs", "status"):
        assert token in html


def test_invalid_form_keeps_entered_values():
    import asyncio
    from app.web.wizard import wizard_design

    class RequestStub:
        async def form(self):
            return {
                "cipher": "ERR-ИОС2",
                "object_name": "Дом с ошибкой",
                "organization": "Тест",
                "building_type": "residential",
                "floors": "0",
                "height": "48",
            }

    response = asyncio.run(wizard_design(RequestStub()))
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Дом с ошибкой" in body
    assert "floors должно быть &gt; 0" in body
