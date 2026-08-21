from pathlib import Path

import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.request_dto import SewerElementRequest
from app.intake.yaml_io import dump_request, load_request, load_request_file
from app.pz.generator import (
    generate_wastewater_scheme_pdf,
    generate_wastewater_scheme_result,
)
from app.pz.spec import build_wastewater_specification
from app.pz.wastewater_registry import audit_wastewater_registry


DEMO = Path(__file__).parents[1] / "demo" / "demo_project.yaml"


def _request():
    return load_request_file(str(DEMO))


def test_demo_element_registry_is_valid_and_roundtrips():
    request = _request()
    assert request.validate() == []
    assert len(request.sewer_elements) == 30

    loaded = load_request(dump_request(request))
    assert loaded.sewer_elements == request.sewer_elements

    audit = audit_wastewater_registry(build_project(request))
    assert audit.ready
    assert audit.errors == []
    assert audit.element_count == 30
    assert audit.spec_position_count == 30


def test_registry_validation_rejects_duplicate_and_unknown_section():
    request = _request()
    row = request.sewer_elements[0]
    request.sewer_elements.append(SewerElementRequest(
        element_id=row.element_id,
        system="K1",
        kind="revision",
        name="Ревизия",
        section_id="К1-НЕИЗВЕСТНЫЙ",
    ))
    problems = request.validate()
    assert any("повторяется" in problem for problem in problems)
    assert any("неизвестный участок" in problem for problem in problems)


def test_registry_drives_spec_without_duplicate_funnel_or_outlet():
    spec = build_wastewater_specification(build_project(_request()))
    rows = [row for section in spec.sections for row in section.rows]
    funnels = [row for row in rows if "Воронка водосточная" in row.name]
    outlets = [row for row in rows if "Узел выпуска" in row.name]
    revisions = [row for row in rows if row.name == "Ревизия канализационная"]

    assert len(funnels) == 1
    assert funnels[0].qty == 4
    assert len(outlets) == 2
    assert all(row.qty == 1 for row in outlets)
    assert any("К1" in row.name for row in outlets)
    assert any("К2" in row.name for row in outlets)
    assert len(revisions) == 1
    assert revisions[0].qty == 12
    assert "К1-Р1-7" in revisions[0].note


def test_vector_scheme_contains_registry_topology_and_is_a1(tmp_path):
    project = build_project(_request())
    result = generate_wastewater_scheme_result(project)
    assert any("К1-М1" in row and "0–52 м" in row for row in result.warnings)
    assert "Принципиальная схема внутренних систем канализации и водоотведения" in result.svg
    assert "К1-Р1-7" in result.svg
    assert "R · эт. 4, 7, 10, 13" in result.svg
    assert 'data-element-id="К1-ПрМ1-10"' not in result.svg
    assert 'data-cleanout-callout=' not in result.svg
    assert 'data-ugo="cleanout"' not in result.svg
    assert "Риск засора: зон 8; доступ подтверждён 3/8" in result.svg
    assert result.svg.count('data-cleanout-pipe-width=') == 0
    assert result.svg.count(">Прочистка</text>") == 0
    assert "СХЕМА ИМЕЕТ БЛОКИРУЮЩИЕ ЗАМЕЧАНИЯ" in result.svg
    assert 'data-element-id="К1-Пер1"' in result.svg
    assert 'data-element-id="К2-Пер1"' in result.svg
    assert 'data-element-id="К1-ОтвСт1"' in result.svg
    assert 'data-element-id="К1-ОтвСт2"' in result.svg
    assert result.svg.count('data-fitting-callout="elbow"') == 2
    assert result.svg.count('data-fitting-boundary-count="3"') == 4
    assert result.svg.count('data-fitting-boundaries="double-45"') == 4
    assert 'data-boundary-owner="К2-Ст1"' in result.svg
    assert 'data-boundary-owner="К2-Ст2"' in result.svg
    for marker in result.svg.split('data-fitting-boundaries="double-45"')[1:]:
        assert 'stroke-width="2.6"' in marker.split('/>', 1)[0]
    assert result.svg.count(">2 отвода 45°</text>") == 2
    assert "СП 30: монтажная топология требует исправления." in result.svg
    assert "К2-Вр1" in result.svg
    assert "К2-Вр2" in result.svg
    assert "К2-Ст2" in result.svg
    assert "К1-М1" in result.svg
    assert "К1-Вып1" in result.svg
    assert "абс. 146,55 / 146,45" in result.svg
    assert "№ К-01, СУ-01 · К1-Ст1" in result.svg
    assert result.svg.count('data-fixture-connection=') == 32
    # Кухонная и санитарная ветви одного стояка показаны одним этажным
    # коллектором, но исходные участки остаются адресными в SVG.
    assert result.svg.count('data-gravity-branch=') == 8
    assert result.svg.count('data-source-sections=') == 8
    # Коллектор сегментирован: DN50 до присоединения унитаза и DN100 после него,
    # поэтому один этаж содержит несколько проходных отрезков.
    assert result.svg.count('data-gravity-trunk="true"') == 32
    assert result.svg.count('data-starts-at="К1-Мой1"') == 4
    assert result.svg.count('data-starts-at="К1-Мой2"') == 4
    assert result.svg.count('data-riser-adjacent="true"') == 8
    assert 'data-flow-to="К1-Ван1"' in result.svg
    assert 'data-flow-to="К1-Ун1"' in result.svg
    assert 'data-flow-to="К1-Ст1"' in result.svg
    assert result.svg.count('data-fixture-trap=') == 24
    assert result.svg.count('data-trap-mode="external"') == 24
    assert result.svg.count('data-trap-mode="integral"') == 8
    assert 'data-fixture-trap="К1-Ун1"' not in result.svg
    assert 'data-fixture-trap="К1-Ун2"' not in result.svg
    assert result.svg.count('data-fixture-fitting-boundaries="double-45"') == 32
    assert 'data-fixture-placement="К1-Ван1"' in result.svg
    assert 'data-elevation-m="0,150"' in result.svg
    assert 'data-elevation-m="0,500"' in result.svg
    assert "16 этаж" in result.svg
    assert "3 этаж" in result.svg
    assert "этажи 4–15 повторяются" in result.svg
    assert "планировочная" in result.svg
    assert "часть по АР" in result.svg
    assert "ДАННЫЕ И УКАЗАНИЯ К СХЕМЕ" in result.svg
    assert "Выпуск К1 Ø160" in result.svg
    assert "Абс. отм. 146,450 (-0,820)" in result.svg
    assert result.svg.count('data-gost-dimension="revision-height"') == 2
    assert result.svg.count('data-value-mm="1000"') == 2
    assert result.svg.count('data-lower-connection="double-45"') == 4
    assert result.svg.count('data-building-outlet-crossing=') == 2
    assert "Техподполье" in result.svg
    assert "ГОСТ Р 21.620-2023" in result.svg

    output = tmp_path / "scheme.pdf"
    generate_wastewater_scheme_pdf(project, str(output))
    page = PdfReader(str(output)).pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(841.0, abs=0.02)
    assert height_mm == pytest.approx(594.0, abs=0.02)
