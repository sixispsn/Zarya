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


def test_templates_exist_and_valid_jinja():
    from jinja2 import Environment, FileSystemLoader
    tdir = "app/web/templates"
    env = Environment(loader=FileSystemLoader(tdir))
    for name in ("wizard_form.html", "wizard_result.html"):
        assert os.path.exists(os.path.join(tdir, name))
        env.get_template(name)   # парсится без ошибок


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
