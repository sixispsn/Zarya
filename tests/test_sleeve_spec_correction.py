"""Approved 11.10.2026: bounded sleeve selection and dependent annular volume.

Counts, hydraulic geometry and outside-wall inlet assumptions stay unchanged.
The normative source is the uploaded SP-30-4.pdf, p. 11.5 (printed page 37).
"""
from copy import deepcopy
from dataclasses import asdict
import math

import pytest

from app.pz.spec import build_water_specification
from tests.test_spec_materials import _demo_project
from tests.test_water_pipe_binding import source_project


def rows_for(project, system):
    return next(s.rows for s in build_water_specification(project).sections
                if s.title.startswith(system + " —"))


def test_samara_riser_geometry_uses_smaller_sleeve_and_same_count_without_mutation():
    p = source_project()
    p.building.risers_v1 = 9
    p.source.inputs_count = 2
    before = deepcopy(asdict(p))
    rows = rows_for(p, "В1")
    sleeves = [r for r in rows if "Гильза" in r.name]
    assert [(r.type_mark, r.qty) for r in sleeves] == [
        ("DN50; Ø60×3,5; dвн=53 мм", 144),
        ("DN125; Ø140×4,5; dвн=131 мм", 2),
    ]
    assert "разность диаметров 5 мм" in sleeves[0].note
    assert "принято 8" not in sleeves[0].note
    # Independent annular volumes (m³ -> litres), same 0.20/0.30 m depths.
    expected = math.pi / 4 * ((.053**2 - .048**2) * .20 * 144
                             + (.131**2 - .110**2) * .30 * 2) * 1000
    assert expected == pytest.approx(13.80777095)
    sealing = next(r for r in rows if "заделки зазоров" in r.name)
    assert "13,8 дм³" in sealing.note and "предварительный" in sealing.note
    assert sealing.qty is None and sealing.unit == "кг"
    assert asdict(p) == before


def test_unmatched_internal_sleeve_preserves_count_but_not_a_partial_total_volume():
    p = source_project()
    p.building.risers_v1 = 9
    # VGP DN32 OD42.3: nearest ID53 has 10.7 mm clearance, outside p.11.5.
    p.v1_sections[2].material = "Стальная 42,3x3,2"
    p.v1_sections[2].inner_diameter_mm = 35.9
    rows = rows_for(p, "В1")
    sleeve = next(r for r in rows if "внутренней проходки" in r.name)
    assert sleeve.qty == 144
    assert sleeve.type_mark == "dвн=47,3–52,3 мм"
    assert "в каталоге ВГП нет" in sleeve.note
    sealing = next(r for r in rows if "заделки зазоров" in r.name)
    assert sealing.qty is None and "Объём не определён" in sealing.note
    assert "дм³" not in sealing.note  # No inlet-only volume pretending to be the total.
    # Removing the crossings leaves only the explicitly partial inlet volume.
    p.building.risers_v1 = 0
    sealing = next(r for r in rows_for(p, "В1") if "заделки зазоров" in r.name)
    assert "Частичный объём" in sealing.note and "только вводы" in sealing.note


def test_unmatched_inlet_does_not_prevent_specification_but_withholds_total_volume():
    p = source_project()
    p.building.risers_v1 = 9
    p.v1_sections[0].material = "ПЭ 200x11,9"
    p.v1_sections[0].inner_diameter_mm = 176.2
    rows = rows_for(p, "В1")
    sleeve = next(r for r in rows if "наружного ввода" in r.name)
    assert sleeve.qty == p.source.inputs_count
    assert "требуется подбор" in sleeve.name and sleeve.type_mark == "По узлу ввода"
    sealing = next(r for r in rows if "заделки зазоров" in r.name)
    assert "Объём не определён" in sealing.note and "дм³" not in sealing.note


def test_one_unmatched_fire_riser_prevents_partial_firestop_volume():
    p = _demo_project()
    # Other risers retain their valid DN65 size; do not silently sum only those.
    p.fire_network.risers[0].dn = 80
    rows = rows_for(p, "В2")
    pending = next(r for r in rows if "внутренней проходки" in r.name)
    assert pending.qty == p.building.floors_above
    assert any(r.name == "Гильза стальная ВГП обыкновенная, DN80" for r in rows)
    sealing = next(r for r in rows if "огнезащитный" in r.name.lower())
    assert sealing.qty is None and "Объём не определён" in sealing.note
    assert "дм³" not in sealing.note
