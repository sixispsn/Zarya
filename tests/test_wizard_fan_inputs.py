import asyncio
import json
from dataclasses import replace
from html.parser import HTMLParser

import pytest
from starlette.datastructures import FormData
from starlette.requests import Request

from app.intake.project_store import ProjectStore
from app.intake.yaml_io import load_request
from app.web import wizard
from app.web.fan_inputs import FanFormInput
from tests.test_fan_geometry_input import fan_form
from tests.test_yaml_io import GOOD


class FormParser(HTMLParser):
    def __init__(self, body):
        super().__init__()
        self.nodes = []
        self.feed(body.decode())

    def handle_starttag(self, tag, attrs):
        self.nodes.append(dict(attrs))

    def find(self, key, value=None):
        return next(
            n for n in self.nodes if key in n and (value is None or n[key] == value)
        )


def request(payload=None, revision=None):
    headers = [(b"if-match", revision.encode())] if revision else []
    raw = json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": raw}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/wizard/design",
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("test", 123),
            "server": ("test", 80),
        },
        receive,
    )


def test_save_only_fan_data_preserves_all_other_inputs_and_detects_stale_version(
    tmp_path, monkeypatch
):
    store = ProjectStore(str(tmp_path))
    monkeypatch.setattr(wizard, "_STORE", store)
    original = load_request(GOOD)
    pid = store.save(original)
    revision = store.source_sha256(pid)
    result = asyncio.run(
        wizard.save_fan_inputs(request(fan_form().to_mapping(), revision), pid)
    )
    restored = store.load(pid)
    assert restored == replace(original, **fan_form().request_fields())
    assert result["revision"] == store.source_sha256(pid) != revision
    conflict = asyncio.run(
        wizard.save_fan_inputs(request(fan_form().to_mapping(), revision), pid)
    )
    assert conflict.status_code == 409
    assert store.load(pid) == restored


@pytest.mark.parametrize(
    "payload",
    [{"roof_level": True}, {"fan_geometry": {"confirmed": True}}, {"extra": 1}],
)
def test_bad_inputs_do_not_overwrite_project(tmp_path, monkeypatch, payload):
    store = ProjectStore(str(tmp_path))
    monkeypatch.setattr(wizard, "_STORE", store)
    pid = store.save(load_request(GOOD))
    revision = store.source_sha256(pid)
    response = asyncio.run(wizard.save_fan_inputs(request(payload, revision), pid))
    assert response.status_code == 422
    assert store.source_sha256(pid) == revision


def test_reopening_restores_form_payload_and_version(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    monkeypatch.setattr(wizard, "_STORE", store)
    req = replace(load_request(GOOD), **fan_form().request_fields())
    pid = store.save(req)
    response = wizard.wizard_open(request(), pid)
    soup = FormParser(response.body)
    value = json.loads(soup.find("name", "fan_data")["value"])
    assert FanFormInput.parse(json.dumps(value)) == fan_form()
    assert soup.find("data-fan-editor")["data-revision"] == store.source_sha256(pid)


def test_other_form_errors_preserve_fan_inputs_and_unknown_proofs():
    req = request()
    value = fan_form().to_mapping()
    value["fan_geometry"]["confirmed"] = False
    value["fan_ventilation"]["external_ventilation_verified"] = None
    req._form = FormData({"fan_data": json.dumps(value)})
    response = asyncio.run(wizard.wizard_design(req))
    soup = FormParser(response.body)
    assert json.loads(soup.find("name", "fan_data")["value"]) == value
    assert "Проверьте исходные данные" in response.body.decode()


def test_invalid_form_fan_input_is_not_silently_discarded():
    req = request()
    req._form = FormData({"fan_data": '{"roof_level":"bad"}'})
    response = asyncio.run(wizard.wizard_design(req))
    assert "Отметка кровли должна быть конечным числом" in response.body.decode()
    assert "bad" in response.body.decode()


def test_validation_route_does_not_require_or_create_a_project(tmp_path, monkeypatch):
    store = ProjectStore(str(tmp_path))
    monkeypatch.setattr(wizard, "_STORE", store)
    result = asyncio.run(wizard.validate_fan_inputs(request(fan_form().to_mapping())))
    assert result["data"] == fan_form().to_mapping()
    assert store.list() == []
