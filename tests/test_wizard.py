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


def test_empty_submit_returns_visible_validation_errors():
    import asyncio
    from starlette.datastructures import FormData
    from starlette.requests import Request
    from app.web.wizard import wizard_design

    request = Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/wizard/design", "root_path": "",
        "query_string": b"", "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    })
    request._form = FormData()
    response = asyncio.run(wizard_design(request))

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Проверьте исходные данные" in body
    assert 'data-design-form novalidate' in body
    assert '<details class="input-section" open' in body


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
    from app.web.wizard import _TPL, _form_context
    # рендерим шаблон — имена run/riser-полей генерятся циклом
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    assert html.count("<fieldset") == 5
    assert html.count('<details class="input-section"') == 5
    assert html.count('<details class="input-section" open') == 2
    assert 'data-design-form novalidate' in html
    assert html.count('<span class="accepted">принято</span>') == 5
    for field in ("cipher", "object_name", "building_type", "floors", "height",
                  "fire_mode", "fire_height",
                  "consumer1_name", "consumer1_code", "consumer1_count",
                  "room_name", "run1_from", "riser1_name", "source_node"):
        assert f'name="{field}"' in html
    assert "Магистраль В2" not in html
    assert "Расстановка пожарных кранов" not in html
    assert "Стояки В2" not in html
    assert 'value="residential_full_bath"' in html
    assert "Пожарно-техническая высота" in html
    assert "ГОСТ Р 21.619-2023" in html


def test_form_exposes_all_sp30_consumer_norms():
    from app.data.sp30_tables import list_consumer_norms
    from app.web.wizard import _TPL, _form_context
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    for norm in list_consumer_norms():
        assert f'value="{norm.code}"' in html


def test_result_template_shows_key_numbers():
    html = open("app/web/templates/wizard_result.html", encoding="utf-8").read()
    for token in ("fire.pk_total", "fire.required_head", "pdfs", "status"):
        assert token in html
    assert '<details class="protocol">' in html


def test_blueprint_ui_marks_edited_sections():
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    css = open("app/web/static/wizard.css", encoding="utf-8").read()
    assert 'state.textContent = "изменено"' in js
    assert ".accepted.changed" in css


def test_dark_theme_is_default_and_responsive():
    css = open("app/web/static/wizard.css", encoding="utf-8").read()
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    assert "--canvas: #0b0b0e" in css
    assert 'html[data-theme="light"]' in css
    assert "background-image" not in css
    assert "@media (max-width: 1080px)" in css
    assert "@media (max-width: 680px)" in css
    assert 'localStorage.setItem("zarya-theme"' in js


def test_live_normative_advisories_are_wired():
    from app.web.wizard import _TPL, _form_context
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    assert "data-validation-panel" in html
    assert 'data-purpose="residential"' in html
    assert 'data-purpose="public"' in html
    assert "height > 75" in js
    assert "height > 50" in js
    assert "fireHeight > 30" in js
    assert "пп. 1.1, 7.5–7.6" in js


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
                "consumer1_name": "Жилая часть",
                "consumer1_code": "residential_central_hw",
                "consumer1_count": "480",
                "consumer2_name": "Спортивный комплекс",
                "consumer2_code": "sport_pool",
                "consumer2_count": "120",
            }

    response = asyncio.run(wizard_design(RequestStub()))
    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Дом с ошибкой" in body
    assert "floors должно быть &gt; 0" in body
    assert "Жилая часть" in body
    assert "Спортивный комплекс" in body
    assert 'value="sport_pool" data-unit=' in body
    assert 'data-unit="чел" data-purpose="public" selected' in body
