"""Состав труб и изоляции спецификации стадии П."""
from pathlib import Path

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.spec import build_specification


def _demo_spec():
    req = load_request(Path("demo/demo_project.yaml").read_text(encoding="utf-8"))
    return build_specification(build_project(req))


def _section(spec, marker):
    return next(section for section in spec.sections if marker in section.title)


def test_demo_spec_contains_stage_p_v1_pipes_and_calculated_insulation():
    rows = _section(_demo_spec(), "В1").rows
    pipes = [row for row in rows if row.name.startswith("Труба ") or row.name.startswith("то же Ду")]
    insulation = [row for row in rows if "теплоизоляционные" in row.name or row.name.startswith("то же толщ.")]
    assert sum(row.qty for row in pipes) == pytest.approx(3852.0)
    assert sum(row.qty for row in insulation) == pytest.approx(1926.0)
    assert all("legacy/SP 61" in row.note for row in insulation)
    assert all("δ" in row.type_mark for row in insulation)


def test_demo_spec_contains_t3_t4_pipes_and_insulation():
    rows = _section(_demo_spec(), "Т3-Т4").rows
    assert any("Труба " in row.name for row in rows)
    assert any("теплоизоляционные" in row.name for row in rows)
    assert any("балансировочный" in row.name.lower() and row.qty == 8 for row in rows)


def test_demo_spec_contains_exact_v2_ring_and_riser_lengths():
    rows = _section(_demo_spec(), "В2").rows
    ring = next(row for row in rows if "кольцевая магистраль" in row.note)
    risers = next(row for row in rows if "стояки" in row.note)
    assert ring.type_mark == "Ду100"
    assert ring.qty == pytest.approx(102.0)
    assert risers.type_mark == "Ду65"
    assert risers.qty == pytest.approx(186.0)
