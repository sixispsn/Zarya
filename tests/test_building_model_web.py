import asyncio
import json

from starlette.datastructures import FormData
from starlette.requests import Request

from app.web.building_model import (
    _TPL,
    building_model_confirm,
    building_model_json,
    building_model_page,
    building_model_preview,
    building_model_save,
    router,
    saved_building_model_page,
)


def _request(path: str, method: str = "GET") -> Request:
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "root_path": "",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    })


def _form(**changes: str) -> FormData:
    values = {
        "model_title": "Контрольный жилой дом",
        "floors_above": "9",
        "apartments_total": "36",
        "floors_below": "1",
        "sections_count": "1",
        "sanitary_shafts_per_section": "2",
        "lift_shafts_per_section": "1",
        "apartments_by_floor": "",
        "apartment_sanitary_room_id": "apartment_sanitary_unit_shower",
        "has_refuse_chamber": "unknown",
        "has_underground_parking": "unknown",
        "apartment_has_washing_machine": "unknown",
        "apartment_has_dishwasher": "unknown",
        "refuse_chamber_has_drain": "unknown",
        "source_ref": "ТЗ: контрольная модель",
    }
    values.update(changes)
    return FormData(values)


def _post(path: str, form: FormData, endpoint):
    request = _request(path, "POST")
    request._form = form
    return asyncio.run(endpoint(request))


def test_building_model_routes_are_included_in_application():
    from app.main import app

    router_paths = {route.path for route in router.routes}
    app_paths = set(app.openapi()["paths"])

    assert router_paths == {
        "/wizard/building-model",
        "/wizard/building-model.json",
        "/wizard/building-model/save",
        "/wizard/building-model/{model_id}",
        "/wizard/building-model/{model_id}/confirm",
        "/wizard/building-model/{model_id}/model.json",
    }
    assert router_paths <= app_paths


def test_building_model_page_is_available_from_main_navigation():
    response = building_model_page(_request("/wizard/building-model"))
    wizard = _TPL.env.get_template("wizard_form.html").render()

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Модель здания" in body
    assert "АР всегда главнее шаблона" in body
    assert 'href="/wizard/building-model"' in wizard


def test_building_model_preview_expands_default_residential_program():
    response = _post(
        "/wizard/building-model",
        _form(),
        building_model_preview,
    )

    assert response.status_code == 200
    body = response.body.decode("utf-8")
    assert "Модель построена · требуется подтверждение" in body
    assert ">36<" in body
    assert ">144<" in body
    assert "apartment_has_washing_machine" in body
    assert "Подземный 1" in body


def test_building_model_json_is_downloadable_and_structured():
    response = _post(
        "/wizard/building-model.json",
        _form(
            has_refuse_chamber="yes",
            has_underground_parking="yes",
            apartment_has_washing_machine="yes",
            apartment_has_dishwasher="no",
            refuse_chamber_has_drain="yes",
        ),
        building_model_json,
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="zarya-building-program.json"'
    )
    payload = json.loads(response.body)
    assert payload["typology_id"] == "residential_multi_apartment"
    assert len(payload["apartments"]) == 36
    assert sum(
        row["archetype_id"] == "washing_machine"
        for row in payload["fixtures"]
    ) == 36
    assert not any(
        row["archetype_id"] == "dishwasher"
        for row in payload["fixtures"]
    )


def test_building_model_rejects_inconsistent_floor_distribution():
    response = _post(
        "/wizard/building-model",
        _form(apartments_by_floor="1: 4, 2: 4"),
        building_model_preview,
    )

    assert response.status_code == 422
    assert "does not match apartments_total" in response.body.decode("utf-8")


def test_building_model_rejects_unknown_tristate_without_server_error():
    response = _post(
        "/wizard/building-model.json",
        _form(has_refuse_chamber="maybe"),
        building_model_json,
    )

    assert response.status_code == 422
    assert "неизвестный вариант" in response.body.decode("utf-8")


def test_building_model_can_be_saved_loaded_and_confirmed(tmp_path, monkeypatch):
    from app.architecture.program_store import BuildingProgramStore
    from app.web import building_model

    store = BuildingProgramStore(tmp_path / "models")
    monkeypatch.setattr(building_model, "_PROGRAM_STORE", store)
    save_response = _post(
        "/wizard/building-model/save",
        _form(
            floors_below="0",
            has_refuse_chamber="no",
            has_underground_parking="no",
            apartment_has_washing_machine="no",
            apartment_has_dishwasher="no",
            refuse_chamber_has_drain="no",
        ),
        building_model_save,
    )

    assert save_response.status_code == 303
    location = save_response.headers["location"]
    model_id = location.rsplit("/", 1)[-1]
    saved_page = saved_building_model_page(
        _request(location),
        model_id,
    )
    body = saved_page.body.decode("utf-8")
    assert "Черновик сохранён · основа не подтверждена" in body
    assert "Контроль передачи" in body
    draft = store.load(model_id)

    confirmation = _post(
        f"/wizard/building-model/{model_id}/confirm",
        FormData({
            "expected_topology_sha256": draft.topology_sha256,
            "confirmed_by": "Иванов И.И.",
            "confirmation_note": "Сверено с ТЗ",
            "confirm_typological_basis": "yes",
        }),
        lambda request: building_model_confirm(request, model_id),
    )
    assert confirmation.status_code == 303
    confirmed_page = saved_building_model_page(
        _request(location),
        model_id,
    )
    confirmed_body = confirmed_page.body.decode("utf-8")
    assert "Типологическая основа подтверждена" in confirmed_body
    assert "Иванов И.И." in confirmed_body
    assert "состав готов" in confirmed_body
    assert "схема ждёт АР" in confirmed_body
