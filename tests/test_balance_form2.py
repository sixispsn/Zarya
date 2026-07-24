# -*- coding: utf-8 -*-
"""Форма 2 приложения А ГОСТ Р 21.619-2023."""

import pytest

from app.pz.demand_bridge import compute_flows
from app.pz.flows_bridge import balance_from_calc
from app.pz.generator import generate_balance_html
from app.pz.project import DocumentInfo, Project


def test_full_bath_500_residents_is_90_m3_day():
    flows = compute_flows([("residential_full_bath", 500)])
    balance = balance_from_calc(
        [("Жилая часть", "residential_full_bath", 500)],
        flows,
    )
    assert len(balance.rows) == 1
    row = balance.rows[0]
    assert row.norm_m3_per_unit_day == pytest.approx(0.180)
    assert row.total_m3_day == pytest.approx(90.0)
    assert row.source_city_m3_day == pytest.approx(90.0)
    assert row.sewage_domestic_m3_day == pytest.approx(90.0)


def test_mixed_saved_project_balance_is_97_5_m3_day():
    groups = [
        ("Жилая часть", "residential_full_bath", 500),
        ("Прачечная", "laundry_mech", 20),
        ("Общепит", "cafe_dining_in", 500),
    ]
    flows = compute_flows([(code, count) for _, code, count in groups])
    balance = balance_from_calc(groups, flows)
    assert flows.q_day_tot == pytest.approx(97.5)
    assert sum(row.total_m3_day for row in balance.rows) == pytest.approx(97.5)
    assert sum(row.sewage_domestic_m3_day for row in balance.rows) == pytest.approx(97.5)


def test_form2_html_contains_normative_19_columns():
    p = Project()
    p.document = DocumentInfo(
        cipher="ТЕСТ-ИОС2",
        object_name="Жилой дом",
        object_address="Москва",
    )
    p.flows = compute_flows([("residential_full_bath", 500)])
    p.balance = balance_from_calc(
        [("Жилая часть", "residential_full_bath", 500)],
        p.flows,
    )
    html = generate_balance_html(p)
    for label in (
        "Технологический процесс",
        "Источники водоснабжения",
        "Безвозвратные потери",
        "Городская канализация",
        "Хозяйственно-бытовые стоки",
    ):
        assert label in html
    assert all(f"<th>{n}</th>" in html for n in range(1, 20))
    assert "90,000" in html
    assert "ТЕСТ-ИОС2.БВ" in html
    assert 'class="stamp3"' in html
    assert "Баланс водопотребления и водоотведения" in html


def test_form2_page_uses_a3_frame_and_main_stamp():
    css = open(
        "app/pz/templates/balance_document.css",
        encoding="utf-8",
    ).read()
    assert "size: A3 landscape" in css
    assert 'url("frame-bg-a3.svg")' in css
    assert "content: element(stamp3)" in css


def test_demo_document_has_no_demonstration_signers():
    from pathlib import Path

    from app.intake.project_builder import build_project
    from app.intake.yaml_io import load_request

    req = load_request(Path("demo/demo_project.yaml").read_text(encoding="utf-8"))
    html = generate_balance_html(build_project(req))
    assert "Демонстрационный комплект" not in html
