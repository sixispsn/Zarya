# -*- coding: utf-8 -*-
"""Тесты листов ТЗ и ТУ (исходные документы проекта)."""
import os
from pypdf import PdfReader

from app.intake.request_dto import (
    IOS2Request, DocumentRequest, RoomRequest, NetworkRequest,
    MainRunRequest, RiserRequest, SourceDataRequest,
)
from app.intake.project_builder import build_project
from app.pz.generator import generate_tz_pdf, generate_tu_pdf


def _project_with_sd():
    req = IOS2Request(
        document=DocumentRequest(cipher="047-ИОС2", object_name="Жилой дом",
                                 organization="Орг", gip="Соколов В.П."),
        building_type="residential", floors=17, building_height_m=51.3, streams=2,
        zones=2, rooms=[RoomRequest("Коридор", 38, 2.2, 2.85)],
        network=NetworkRequest(
            runs=[MainRunRequest("A", "B", 28), MainRunRequest("B", "C", 15),
                  MainRunRequest("C", "D", 28), MainRunRequest("D", "A", 15)],
            risers=[RiserRequest("Ст-1", "A", 52, 48),
                    RiserRequest("Ст-2", "C", 52, 48)],
            source_node="A", available_head_m=26.0),
        source_data=SourceDataRequest(
            customer="ООО СЗ", tu_org="АО Водоканал",
            tu_number="ТУ-1184/26", tu_date="18.02.2026",
            connection_point="колодец ВК-3", guaranteed_head_m=26.0,
            tu_limit_q_day=185.0, tu_fire_outdoor_l_s=25.0, water_main_dn=300))
    return build_project(req), req.source_data


def test_tz_is_a4(tmp_path):
    p, sd = _project_with_sd()
    out = str(tmp_path / "tz.pdf")
    generate_tz_pdf(p, out, sd)
    box = PdfReader(out).pages[0].mediabox
    assert abs(float(box.width) / 72 * 25.4 - 210) < 2
    assert abs(float(box.height) / 72 * 25.4 - 297) < 2


def test_tz_content():
    p, sd = _project_with_sd()
    import tempfile
    out = os.path.join(tempfile.mkdtemp(), "tz.pdf")
    generate_tz_pdf(p, out, sd)
    t = PdfReader(out).pages[0].extract_text().replace("\n", " ")
    assert "ЗАДАНИЕ НА ПРОЕКТИРОВАНИЕ" in t
    assert "СП 10.13130.2020" in t
    assert "2 струи" in t                 # склонение
    assert "26,0 м" in t                  # напор из исходных данных
    assert "047-ИОС2.ТЗ" in t             # шифр с суффиксом


def test_tu_content():
    p, sd = _project_with_sd()
    import tempfile
    out = os.path.join(tempfile.mkdtemp(), "tu.pdf")
    generate_tu_pdf(p, out, sd)
    t = PdfReader(out).pages[0].extract_text().replace("\n", " ")
    assert "ИСХОДНЫЕ ДАННЫЕ" in t
    assert "ТУ-1184/26" in t
    assert "Ду300" in t
    assert "185,0 м³/сут" in t
    assert "25,0 л/с" in t                # наружное пожаротушение
    assert "047-ИОС2.ИД" in t


def test_tz_without_source_data_uses_placeholders():
    # без исходных данных — плейсхолдеры, не падение
    p, _ = _project_with_sd()
    import tempfile
    out = os.path.join(tempfile.mkdtemp(), "tz.pdf")
    generate_tz_pdf(p, out, None)         # source_data=None
    assert os.path.getsize(out) > 1000


def test_builder_carries_source_data():
    p, _ = _project_with_sd()
    # исходные данные долетели в WaterSource проекта
    assert p.source.guaranteed_head_m == 26.0
    assert p.source.tu_number == "ТУ-1184/26"
