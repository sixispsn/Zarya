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
    assert "/wizard/proof/{run_id}" in paths
    assert "/wizard/impact/{run_id}" in paths
    assert "/wizard/defense/{run_id}" in paths
    assert "/wizard/defense/{run_id}/answer" in paths
    assert "/wizard/view/{run_id}/{name}" in paths
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
    for name in ("wizard_form.html", "wizard_result.html",
                 "wizard_defense.html"):
        assert os.path.exists(os.path.join(tdir, name))
        _TPL.env.get_template(name)   # парсится с фильтрами веб-приложения


def test_form_template_has_all_sections():
    from app.web.wizard import _TPL, _form_context
    # рендерим шаблон — имена run/riser-полей генерятся циклом
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    assert html.count("<fieldset") == 5


def test_example_form_keeps_moscow_and_roof_area_for_storm_calculation():
    from pathlib import Path

    from app.intake.yaml_io import load_request_file
    from app.web.wizard import _TPL, _form_context

    demo = Path(__file__).parents[1] / "demo" / "demo_project.yaml"
    prefill = load_request_file(str(demo))
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[], prefill=prefill, example_mode=True),
    )
    assert "Учебный К2: Москва" in html
    assert 'value="moscow" selected' in html
    assert 'name="storm_roof_area" value="900.0"' in html
    assert 'name="sewer_safety1_fixture" value="К1-Ун1"' in html
    assert 'name="sewer_safety1_connection_abs" value="147.42"' in html
    assert 'name="sewer_manhole1_id" value="КК-1"' in html
    assert 'name="sewer_manhole1_level1" value="146.6"' in html
    assert 'name="sewer_internal_node1_id" value="К1-Ст1"' in html
    assert 'name="sewer_internal_node2_upstream" value="К1-М1"' in html
    assert 'name="wastewater_basement_floor_elevation_m" value="-3.2"' in html


def test_form_template_has_collapsed_wastewater_element_registry():
    from app.web.wizard import _TPL, _form_context

    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]),
    )
    assert "Реестр элементов схемы и спецификации К1/К2/К3" in html
    assert 'name="sewer_element1_id"' in html
    assert 'name="sewer_element24_include_spec"' in html
    assert 'name="sewer_safety8_fixture"' in html
    assert 'name="sewer_manhole3_id"' in html
    assert 'name="sewer_internal_node4_id"' in html
    assert 'name="wastewater_basement_floor_elevation_m"' in html
    assert 'data-wastewater-outlet-registry-lamp' in html
    assert 'data-outlet-completeness-lamp="slope"' in html
    assert 'data-outlet-completeness-lamp="invert"' in html
    assert 'data-outlet-completeness-lamp="dn"' in html
    assert 'name="sewer_pipe1_nominal"' in html
    assert html.count('<details class="input-section"') == 5
    assert html.count('<details class="input-section" open') == 1
    assert 'data-design-form novalidate' in html
    assert 'name="fire_height" value=""' in html
    assert html.count('name="fire_height"') == 1
    assert html.count('data-state="не задано">не задано</span>') == 5
    for field in ("cipher", "object_name", "building_type", "floors", "height",
                  "fire_mode", "fire_height", "fire_category",
                  "consumer1_name", "consumer1_code", "consumer1_count",
                  "room_name", "run1_from", "riser1_name", "source_node"):
        assert f'name="{field}"' in html
    assert "Магистраль В2" not in html
    assert "Расстановка пожарных кранов" not in html
    assert "Стояки В2" not in html
    assert 'value="residential_full_bath"' in html
    assert "Пожарно-техническая высота" in html
    assert '<div class="row building-row">' in html
    assert (
        '<span class="field-caption">Пожарно-техническая высота '
        'h<sub>пт</sub>, м '
    ) in html
    assert "ГОСТ Р 21.619-2023" in html
    assert 'name="consumer1_count" aria-label="Количество потребителей 1" value=""' in html
    assert 'name="run1_from" value=""' in html
    assert 'name="available_head" value=""' in html
    assert "Загрузить учебный пример" in html


def test_form_exposes_all_sp30_consumer_norms():
    from app.data.sp30_tables import list_consumer_norms
    from app.web.wizard import _TPL, _form_context
    html = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    for norm in list_consumer_norms():
        assert f'value="{norm.code}"' in html


def test_result_template_shows_key_numbers():
    html = open("app/web/templates/wizard_result.html", encoding="utf-8").read()
    for token in ("fire.pk_total", "fire.required_head", "fire.note",
                  "pdfs", "document_groups", "status"):
        assert token in html
    assert '<details class="protocol">' in html
    assert 'id="project-proof"' in html
    assert 'data-proof-open="v1-q-day"' in html
    assert 'data-proof-open="v1-head"' in html
    assert 'data-proof-dialog' in html
    assert "Скачать доказательства JSON" in html
    assert "Что изменится?" in html
    assert 'data-impact-dialog' in html
    assert 'data-endpoint="/wizard/impact/{{ run_id }}"' in html
    assert "sewage.scheme_ready" in html
    assert "Схема не сформирована — выпущен только каркас" in html
    assert "p.state == 'incomplete'" in html


def test_incomplete_wastewater_topology_marks_scheme_documents(monkeypatch):
    from types import SimpleNamespace

    from app.web import wizard

    monkeypatch.setattr(
        wizard,
        "build_wastewater_topology",
        lambda project: SimpleNamespace(ready=False),
    )
    bundle = SimpleNamespace(
        project=object(),
        wastewater_package_pdf="/tmp/Комплект_ИОС3.pdf",
        wastewater_scheme_pdf="/tmp/Схема_К1_К2.pdf",
    )

    documents, groups = wizard._bundle_documents(bundle)

    assert len(documents) == 2
    assert all(document["state"] == "incomplete" for document in documents)
    assert all(document["state_note"] for document in documents)
    assert groups[0]["key"] == "ios3"


def test_interface_presents_ios2_and_ios3_as_one_project():
    from app.web.wizard import _TPL, _form_context

    form = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))
    result = open(
        "app/web/templates/wizard_result.html", encoding="utf-8").read()
    projects = open(
        "app/web/templates/wizard_projects.html", encoding="utf-8").read()

    assert "ZARYA / IOS2 + IOS3" in form
    assert "Инженерные системы ИОС2 / ИОС3" in form
    assert "Собрать ИОС2 + ИОС3" in form
    assert "ИОС2 · В1 В2 Т3 Т4" in form
    assert "ИОС3 · К1 К2" in form
    assert "Базовый шифр проекта" in form
    assert "автоматически заменяется на ИОС3" in form
    assert "ИОС2 + ИОС3 · комплект успешно собран" in result
    assert 'data-discipline="{{ group.key }}"' in result
    assert "ИОС2 + ИОС3 · локальное хранилище" in projects


def test_form_marks_only_blocking_inputs_with_status_lamps():
    from app.web.wizard import _TPL, _form_context

    form = _TPL.env.get_template("wizard_form.html").render(
        **_form_context(errors=[]))

    for field in ("building_type", "floors", "height", "fire_height",
                  "fire_category", "fire_hall_seats", "fire_area_m2",
                  "streams"):
        assert f'data-required-for="{field}"' in form
    assert form.count('data-required-rule="positive"') == 2
    assert 'data-required-rule="fire-auto"' in form
    assert 'data-required-rule="fire-manual"' in form
    assert 'data-required-rule="fire-category-auto"' in form
    assert 'data-required-rule="fire-theatre"' in form
    assert 'data-required-rule="fire-area"' in form
    assert 'data-required-rule="nonempty"' in form
    assert 'name="total_area"' in form
    total_area = form.split('name="total_area"', 1)[1].split("</label>", 1)[0]
    assert "required" not in total_area
    assert '<details class="validation-panel"' in form
    assert form.count('<details class="field-help">') >= 6
    object_block = form.split('<fieldset id="object"', 1)[1].split(
        "</fieldset>", 1
    )[0]
    assert "required-lamp" not in object_block


def test_blueprint_ui_marks_edited_sections():
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    css = open("app/web/static/wizard.css", encoding="utf-8").read()
    assert 'state.textContent = "изменено"' in js
    assert ".accepted.changed" in css
    assert ".accepted::before" not in css


def test_dark_theme_is_default_and_responsive():
    css = open("app/web/static/wizard.css", encoding="utf-8").read()
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    assert "--canvas: #0b0b0e" in css
    assert 'html[data-theme="light"]' in css
    assert "background-image" not in css
    assert "@media (max-width: 1080px)" in css
    assert "@media (max-width: 680px)" in css
    assert ".building-row { grid-template-columns: repeat(3,minmax(0,1fr)); }" in css
    assert 'localStorage.setItem("zarya-theme"' in js


def test_proof_ui_is_interactive_and_responsive():
    css = open("app/web/static/wizard.css", encoding="utf-8").read()
    js = open("app/web/static/wizard.js", encoding="utf-8").read()
    assert ".proof-dialog::backdrop" in css
    assert ".proof-status[data-status=\"missing\"]" in css
    assert ".proof-impact-grid" in css
    assert 'document.querySelectorAll("[data-proof-open]")' in js
    assert 'proofDialog.showModal()' in js
    assert 'fetch(impactForm.dataset.endpoint' in js
    assert ".impact-delta.changed" in css
    assert ".impact-output-grid" in css


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
    assert "fireHeight >= 30" in js
    assert "пп. 1.1, 7.5–7.6" in js
    assert "больше не подменяет общественное здание офисной строкой" in js


def test_demo_is_available_only_by_explicit_query():
    from app.web.wizard import _DEMO_PROJECT
    from app.intake.yaml_io import load_request_file

    demo = load_request_file(str(_DEMO_PROJECT))
    assert demo.consumers[0].count == 480
    assert demo.fire_category == "residential_f13"
    assert demo.fire_geometry_confirmed is True


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
