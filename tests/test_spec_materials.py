"""Состав труб и изоляции спецификации стадии П."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request
from app.pz.spec import build_specification, format_spec_qty


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
    sleeves = [row for row in rows if "Гильза" in row.name]
    assert [row.type_mark for row in sleeves] == [
        "DN32; Ø42,3×3,2; dвн=35,9 мм",
        "DN65; Ø75,5×4; dвн=67,5 мм",
    ]
    sealant = next(row for row in rows if "заделки зазоров" in row.name)
    assert "27,2 дм³" in sealant.note


def test_demo_spec_contains_exact_v2_ring_and_riser_lengths():
    rows = _section(_demo_spec(), "В2").rows
    ring = next(row for row in rows if "кольцевая магистраль" in row.note)
    risers = next(
        row for row in rows
        if "стояки" in row.note and row.name.startswith("Труба ")
    )
    assert ring.type_mark == "DN100; Ø114×4,5; dвн=105 мм"
    assert ring.qty == pytest.approx(102.0)
    assert risers.type_mark == "DN65; Ø75,5×4; dвн=67,5 мм"
    assert risers.qty == pytest.approx(186.0)
    ring_fix = next(row for row in rows if "Хомут трубный стальной" in row.name)
    riser_fix = next(row for row in rows if "Хомут трубный стояка" in row.name)
    assert ring_fix.qty == 17
    assert riser_fix.qty == 64
    sleeve = next(row for row in rows if "Гильза" in row.name)
    assert sleeve.type_mark == "DN90; Ø101,3×4; dвн=93,3 мм"
    assert sleeve.qty == 64
    firestop = next(row for row in rows if "огнезащитный" in row.name.lower())
    assert firestop.unit == "кг"
    assert "30,2 дм³" in firestop.note


def test_stage_p_sleeves_use_actual_pipe_od_and_sleeve_id():
    spec = _demo_spec()
    v1 = _section(spec, "В1").rows
    sleeves = [row for row in v1 if "Гильза" in row.name]
    assert [row.type_mark for row in sleeves] == [
        "DN40; Ø48×3,5; dвн=41 мм",
        "DN80; Ø88,5×4; dвн=80,5 мм",
    ]
    assert all("на 5–10 мм (принято 8 мм)" in row.note for row in sleeves)
    sealant = next(row for row in v1 if "заделки зазоров" in row.name)
    assert "13,9 дм³" in sealant.note


def test_spec_sections_follow_gost_21_601_order():
    spec = _demo_spec()
    assert [(section.division, section.title.split(" — ")[0]) for section in spec.sections] == [
        ("Водоснабжение холодное", "В1"),
        ("Водоснабжение холодное", "В2"),
        ("Водоснабжение горячее", "Т3-Т4"),
    ]
    positions = [row.pos for section in spec.sections for row in section.rows if row.pos is not None]
    assert positions == list(range(1, len(positions) + 1))


def test_spec_without_vpv_has_no_v2_section_or_v2_note():
    project = _demo_project()
    project.fire.required = False
    spec = build_specification(project)
    assert not any(section.title.startswith("В2") for section in spec.sections)
    assert "Трубы В2 приняты" not in spec.note


def test_discrete_spec_quantities_have_no_decimal_comma():
    assert format_spec_qty(1, "шт.") == "1"
    assert format_spec_qty(8.0, "шт.") == "8"
    assert format_spec_qty(1, "компл.") == "1"
    assert format_spec_qty(12.25, "м") == "12,2"
    with pytest.raises(ValueError, match="Дробное количество"):
        format_spec_qty(1.5, "шт.")
