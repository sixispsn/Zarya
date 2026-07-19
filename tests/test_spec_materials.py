"""Состав труб и изоляции спецификации стадии П."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.spec import build_specification


def _demo_project():
    req = load_request(Path("demo/demo_project.yaml").read_text(encoding="utf-8"))
    return build_project(req)


def _demo_spec():
    return build_specification(_demo_project())


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


def test_demo_spec_contains_normative_fasteners_and_meter_stand():
    project = _demo_project()
    project.meters.rows = [SimpleNamespace(
        label="Ввод ХВС", dn=32, type_label="крыльчатый",
        need_bypass=True, need_combo=False,
    )]
    rows = _section(build_specification(project), "В1").rows
    stand = next(row for row in rows if "Подставка" in row.name)
    assert stand.qty == 1
    fasteners = [row for row in rows if "Хомут трубный" in row.name or "Крепление скользящее" in row.name]
    by_dn = {row.type_mark: row for row in fasteners}
    assert by_dn["Ду50"].qty == 193
    assert by_dn["Ду32"].qty == 1873
    assert by_dn["Ду20"].qty == 4815
    assert all("уточнить на Р" in row.note for row in fasteners)


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
    ring_fix = next(row for row in rows if "Хомут трубный стальной" in row.name)
    riser_fix = next(row for row in rows if "Хомут трубный стояка" in row.name)
    assert ring_fix.qty == 17
    assert riser_fix.qty == 64
