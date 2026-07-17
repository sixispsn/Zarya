# -*- coding: utf-8 -*-
"""Тесты рендера гидравлического листа В2 (generator + шаблон)."""
import os
import pytest

from app.pz.project import Project, DocumentInfo
from app.calc.fire_hydraulics import (
    FireNetwork, HydraulicNode, PipeSegment, FireCabinetNode, HydraulicSource,
    SourceKind, NetworkMode, solve_fire_hydraulics_scenario,
)
from app.calc.diameter_audit import audit_sections
from app.calc.fire_hydraulic_report import build_hydraulic_report
from app.pz.generator import (
    generate_hydraulic_report_html, generate_hydraulic_report_pdf,
)


def _report_and_project():
    net = FireNetwork(
        nodes={"src": HydraulicNode("src", 0.0), "fork": HydraulicNode("fork", 0.0),
               "a": HydraulicNode("a", 27.5), "b": HydraulicNode("b", 27.5)},
        segments=[
            PipeSegment("mag", "src", "fork", length_m=30, A=0.00246, equiv_length_m=8, diameter_mm=65),
            PipeSegment("rA", "fork", "a", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50),
            PipeSegment("rB", "fork", "b", length_m=27.5, A=0.011, equiv_length_m=4, diameter_mm=50)],
        cabinets=[FireCabinetNode("PK-A", "a", riser_id="R1"),
                  FireCabinetNode("PK-B", "b", riser_id="R2")],
        source=HydraulicSource("src", kind=SourceKind.CITY_MAIN, available_head_m=30.0))
    r = solve_fire_hydraulics_scenario(net, 2, mode=NetworkMode.PURE_FIRE)
    audit = audit_sections(r.dictating_scenario.sections, NetworkMode.PURE_FIRE,
                           dn_by_segment={"mag": 65, "rA": 50, "rB": 50})
    report = build_hydraulic_report(r, audit)
    p = Project()
    p.document = DocumentInfo(cipher="2026-14-ИОС2", object_name="Жилой дом",
                              object_part="Корпус 1", organization="ООО «Заря»",
                              developer_name="Иванов", gip_name="Сидоров")
    return report, p


def test_html_contains_all_blocks():
    report, p = _report_and_project()
    html = generate_hydraulic_report_html(p, report)
    assert "Гидравлический расчёт" in html
    assert "Таблица гидравлического расчёта по участкам" in html
    assert "Вердикт по диаметрам" in html
    assert "Диктующий путь" in html
    assert "Заключение" in html


def test_html_has_segment_rows():
    report, p = _report_and_project()
    html = generate_hydraulic_report_html(p, report)
    assert "mag" in html and "rA" in html and "rB" in html
    assert "PK-A" in html


def test_html_cipher_suffix_gr():
    report, p = _report_and_project()
    html = generate_hydraulic_report_html(p, report)
    assert "2026-14-ИОС2.ГР" in html   # шифр листа расчёта


def test_html_shows_pump_duty():
    report, p = _report_and_project()
    html = generate_hydraulic_report_html(p, report)
    assert "требуется" in html
    assert "12.6" in html or "12,6" in html


def test_html_never_sizes_pump_from_ring_failure():
    report, p = _report_and_project()
    html = generate_hydraulic_report_html(p, report)
    assert "рабочую точку принять по аварийному режиму" not in html


def test_pdf_is_a4(tmp_path):
    from pypdf import PdfReader
    report, p = _report_and_project()
    out = str(tmp_path / "hydr.pdf")
    generate_hydraulic_report_pdf(p, report, out)
    box = PdfReader(out).pages[0].mediabox
    w_mm = float(box.width) / 72 * 25.4
    h_mm = float(box.height) / 72 * 25.4
    assert abs(w_mm - 210) < 2 and abs(h_mm - 297) < 2


def test_pdf_created(tmp_path):
    report, p = _report_and_project()
    out = str(tmp_path / "hydr.pdf")
    generate_hydraulic_report_pdf(p, report, out)
    assert os.path.exists(out) and os.path.getsize(out) > 1000


def test_hydraulic_page_has_a4_frame(tmp_path):
    """Гидролист несёт ГОСТ-рамку А4 (SVG-обвод подключён в CSS)."""
    import os
    css = open("app/pz/templates/hydraulic.css", encoding="utf-8").read()
    assert "frame-bg-a4.svg" in css          # рамка подключена
    assert os.path.exists("app/pz/templates/frame-bg-a4.svg")   # файл есть


def test_frame_svg_is_a4_portrait():
    svg = open("app/pz/templates/frame-bg-a4.svg", encoding="utf-8").read()
    assert 'viewBox="0 0 210 297"' in svg     # А4 книжная
    assert "Формат А4" in svg
