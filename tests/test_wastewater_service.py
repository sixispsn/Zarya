"""Settings/requirements only: no invented wastewater meters or sump sizing."""
from dataclasses import asdict, replace
import json
import os
import shutil
import subprocess

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request, dump_request, YamlFormatError
from app.pz.generator import generate_pz_html, generate_wastewater_pz_html
from app.pz.project import Project
from app.pz.wastewater_gost import audit_wastewater_gost
from app.pz.wastewater_service import WastewaterServiceInput, assess, from_dict, from_studio
from tests.test_pump_bridge import _request
from tests import test_studio as studio

client = studio.client


def configured(**kwargs):
    return replace(WastewaterServiceInput(
        k1_metering_enabled=True, k1_metering_location="Выпуск К1-1, помещение 001",
        k1_metering_regime="gravity", k1_metering_basis="ТУ, п. 4",
        sump_enabled=True, sump_room="pump_room", sump_location="Насосная 002",
        sump_reserve_location="installed", sump_basis="Задание ВК",
        sump_discharge_note="Приёмная сеть требует согласования",
    ), **kwargs)


@pytest.mark.parametrize("data", [[], {"k3_metering_enabled": True},
    {"sump_enabled": "false"}, {"k1_metering_enabled": 1},
    {"sump_location": None}, {"sump_basis": "x" * 201},
    {"sump_room": "parking"}, {"sump_reserve_location": "none"},
    {"k1_metering_regime": "guess"}])
def test_invalid_inputs_rejected(data):
    with pytest.raises(ValueError):
        from_dict(data)


@pytest.mark.parametrize("room,reserve", [
    ("pump_room", 1), ("meter_room", 1), ("itp", 1),
    ("technical_subfloor", 1), ("used_basement", 1), ("supply_ventilation", 0),
    ("other", None), ("", None),
])
def test_reserve_requirements_are_current_and_not_equipment_selection(room, reserve):
    result = assess(configured(sump_room=room, sump_reserve_location=""))["sump"]
    assert result["reserve_pumps_required"] == reserve
    assert result["duty_pumps_required"] == (None if reserve is None else 1)
    assert result["status"] == "needs_design"
    assert "pump_model" not in result and "volume_m3" not in result
    assert "Q/H" in " ".join(result["requirements"])


@pytest.mark.parametrize("room,ok", [("pump_room", False), ("meter_room", False),
    ("itp", False), ("technical_subfloor", True), ("used_basement", True),
    ("supply_ventilation", False), ("other", False), ("", False)])
def test_warehouse_exception_not_applied_to_every_room(room, ok):
    result = assess(configured(sump_room=room, sump_reserve_location="warehouse"))["sump"]
    assert bool(result["errors"]) is not ok
    assert (result["status"] == "needs_design") is ok


def test_disabled_keeps_saved_inputs_without_activating_requirements():
    data = configured(k1_metering_enabled=False, sump_enabled=False, sump_reserve_location="warehouse")
    r = assess(data)
    assert r["input"] == asdict(data)
    for key in ("meter", "sump"):
        assert r[key]["status"] == "disabled" and not r[key]["requirements"]
    assert r["sump"]["reserve_pumps_required"] is None


def test_yaml_project_roundtrip_and_old_projects():
    req = _request()
    req.wastewater_service = configured()
    restored = load_request(dump_request(req))
    assert restored.wastewater_service == req.wastewater_service
    project = build_project(restored)
    assert project.wastewater_service == req.wastewater_service
    project.wastewater_service.sump_location = "Изменено"
    assert restored.wastewater_service.sump_location == "Насосная 002"
    assert build_project(_request()).wastewater_service == WastewaterServiceInput()
    broken = dump_request(req).replace("sump_enabled: true", "sump_enabled: 'false'")
    with pytest.raises(YamlFormatError):
        load_request(broken)


def test_pz_and_audit_show_unfinished_requirements_not_fake_design():
    p = Project()
    original_water = generate_pz_html(p)
    before = asdict(p)
    p.wastewater_service = configured(sump_reserve_location="warehouse")
    html = generate_wastewater_pz_html(p)
    assert "Узел учёта К1" in html and "Насосная 002" in html
    assert "Расчёт объёма, Q/H и подбор насоса не выполнены" in html
    assert "Насосы для бытовых и производственных стоков" in html
    assert "Система сбора дренажных вод в исходных данных не задана" not in html
    assert "Хранение резервного насоса на складе" in html
    assert "насосы ещё не подобраны" in html
    assert html.index("Узел учёта К1") < html.index("5. Канализационное насосное")
    checks = [c for c in audit_wastewater_gost(p).checks if "SERVICE" in c.code]
    assert len(checks) == 2 and all(c.status == "missing" for c in checks)
    assert generate_pz_html(p) == original_water  # No K1 service requirements in IOS2.
    assert p.sewage.pipes == before["sewage"]["pipes"] == []
    assert p.sewage.elements == before["sewage"]["elements"] == []
    assert not p.sewage.pump_required
    p.wastewater_service = replace(p.wastewater_service, sump_enabled=False, k1_metering_enabled=False)
    html = generate_wastewater_pz_html(p)
    assert "Узел учёта К1" not in html and "Насосная 002" not in html
    assert not [c for c in audit_wastewater_gost(p).checks if "SERVICE" in c.code]


def test_request_to_public_studio_and_calculations_unchanged(client):
    state = studio.residential_project(client)
    original = client.post('/studio/api/calculate', json={"revision": state["revision"]}).json()
    state = original
    vals = {"sewer_service_" + k: ("yes" if v else "no") if type(v) is bool else v
            for k, v in asdict(configured()).items()}
    response = client.patch('/studio/api/answers', json={"revision": state["revision"], "answers": vals})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["wastewater_service"]["sump"]["reserve_pumps_required"] == 1
    assert state["wastewater_service"]["meter"]["status"] == "needs_design"
    state = client.post('/studio/api/calculate', json={"revision": state["revision"]}).json()
    assert state["calculation"] == original["calculation"]
    assert state["project_calculation"]["flows"] == original["project_calculation"]["flows"]
    blockers = state["project_calculation"]["gost_blockers"]
    assert {r["rule_id"] for r in blockers} >= {"K-GOST-SERVICE-METER", "K-GOST-SERVICE-SUMP"}
    restored = client.get('/studio/api/draft').json()
    assert restored["wastewater_service"] == state["wastewater_service"]
    assert from_studio(vals) == configured()
    state = studio.answer(client, state, "sewer_service_sump_enabled", "no")
    assert state["wastewater_service"]["sump"]["status"] == "disabled"
    assert state["wastewater_service"]["input"]["sump_location"] == "Насосная 002"


def test_conditional_fields_and_saved_conflicts_remain_accessible():
    node = os.environ.get("NODE_BINARY") or shutil.which("node")
    assert node
    result = subprocess.run([node, '-e', """
global.window={}; require('./app/web/static/studio_configurator.js');
const visible=window.ZaryaConfigurator.fanFieldVisible;
console.log(JSON.stringify([
 visible('sewer_service_sump_enabled', {}),
 visible('sewer_service_sump_location', {}),
 visible('sewer_service_k1_metering_location', {sewer_service_k1_metering_enabled:'yes'}),
 visible('sewer_service_sump_reserve_location', {sewer_service_sump_enabled:'yes',sewer_service_sump_room:'supply_ventilation'}),
 visible('sewer_service_sump_reserve_location', {sewer_service_sump_enabled:'yes',sewer_service_sump_room:'supply_ventilation',sewer_service_sump_reserve_location:'warehouse'})
]));"""], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [True, False, True, False, True]
