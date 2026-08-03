"""Состав подраздела ИОС3 по ГОСТ Р 21.620-2023."""
from app.intake.project_builder import build_project
from app.intake.request_dto import SewageRiserRequest, SewerPipeRequest
from app.pz.generator import (
    generate_wastewater_balance_html,
    generate_wastewater_pz_html,
    generate_wastewater_scheme_html,
)
from app.pz.ios2_orchestrator import design_ios2
from app.pz.wastewater_gost import audit_wastewater_gost
from tests.test_pump_bridge import _request


def _gost_request():
    req = _request()
    req.sewage_risers = [SewageRiserRequest(
        "К1-Ст1", 2.5, "pp", "ventilated", 110, 110, 87.5, True,
    )]
    req.sewer_pipes = [SewerPipeRequest(
        "K1", "К1-М1", "горизонтальная сеть", "ПП",
        "ТУ изготовителя", 110, 3.4, 24.0,
        slope_per_mille=20.0,
        fill_ratio=0.55,
        from_node="К1-Ст1",
        to_node="К1-Вып1",
        room="техническое подполье",
        elevation_start_m=-0.40,
        elevation_end_m=-0.88,
    )]
    req.sewage_outlets_count = 1
    req.wastewater_design_assignment_ref = "Задание на проектирование, раздел 6"
    req.wastewater_survey_ref = "ИГИ-2026, том 2"
    req.wastewater_service_life_years = 50
    req.wastewater_overhaul_period_years = 25
    req.wastewater_disposal_mode = "centralized"
    req.wastewater_tu_org = "Водоканал"
    req.wastewater_tu_number = "123-К"
    req.wastewater_tu_date = "01.08.2026"
    req.wastewater_existing_network_type = "раздельная"
    req.wastewater_existing_network_material = "ПЭ"
    req.wastewater_existing_network_standard = "ГОСТ 18599-2001"
    req.wastewater_existing_network_outer_diameter_mm = 200
    req.wastewater_existing_network_wall_thickness_mm = 11.9
    req.wastewater_discharge_point_k1 = "КК-1"
    req.wastewater_k1_min_hourly_m3h = 0.12
    req.wastewater_quality_indicators_note = (
        "хозяйственно-бытовые стоки; показатели в пределах условий подключения"
    )
    req.wastewater_laying_method = "открыто под потолком и в шахтах"
    req.wastewater_fire_barrier_note = "противопожарные муфты по узлам КР"
    req.wastewater_deformation_joint_note = "пересечения не предусмотрены"
    return req


def test_complete_gost_input_passes_structural_audit(tmp_path):
    bundle = design_ios2(
        build_project(_gost_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    )
    audit = audit_wastewater_gost(bundle.project)
    assert audit.complete
    assert all(row.status != "missing" for row in audit.checks)


def test_incomplete_project_is_not_falsely_marked_gost_complete(tmp_path):
    bundle = design_ios2(
        build_project(_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    )
    audit = audit_wastewater_gost(bundle.project)
    assert not audit.complete
    assert any(row.code == "K-GOST-13" for row in audit.missing)
    assert any("wastewater_gost" in warning for warning in bundle.warnings)


def test_water_body_discharge_requires_specific_gost_data(tmp_path):
    req = _gost_request()
    req.wastewater_disposal_mode = "water_body"
    audit = audit_wastewater_gost(design_ios2(
        build_project(req), output_dir=str(tmp_path), render_documents=False,
    ).project)
    assert any(row.code == "K-GOST-04A" for row in audit.missing)


def test_wastewater_pz_has_gost_21620_structure(tmp_path):
    project = design_ios2(
        build_project(_gost_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    ).project
    html = generate_wastewater_pz_html(project)
    for text in (
        "ГОСТ Р 21.620-2023",
        "Исходные данные для проектирования",
        "Существующие и проектируемые системы водоотведения",
        "Обоснование систем сбора, отвода и предварительной очистки",
        "Трубопроводы, прокладка и пересечения конструкций",
        "Графическая часть",
        "Ведомость нормативного контроля",
    ):
        assert text in html
    assert "20,0" in html and "0,55" in html


def test_wastewater_balance_is_appendix_a_with_19_columns(tmp_path):
    project = design_ios2(
        build_project(_gost_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    ).project
    html = generate_wastewater_balance_html(project)
    assert "Приложение А" in html
    assert "ГОСТ Р 21.620-2023" in html
    assert all(f"<th>{n}</th>" in html for n in range(1, 20))
    assert "форме 2 приложения А ГОСТ Р 21.619-2023" not in html
    assert "рекомендуемой форме" not in html


def test_internal_scheme_exposes_required_topology_fields(tmp_path):
    project = design_ios2(
        build_project(_gost_request()),
        output_dir=str(tmp_path),
        render_documents=False,
    ).project
    html = generate_wastewater_scheme_html(project)
    assert "К1-Ст1" in html
    assert "К1-Вып1" in html
    assert "техническое подполье" in html
    assert "20,0" in html
    assert "-0,40" in html and "-0,88" in html
