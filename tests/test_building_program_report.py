from pathlib import Path

import pytest
from pypdf import PdfReader

from app.architecture.program_report import (
    PAGE_HEIGHT_MM,
    PAGE_WIDTH_MM,
    generate_building_program_report_pdf,
)
from app.architecture.program_store import BuildingProgramStore
from app.architecture.residential_program import ResidentialProgramInput


def _input(*, floors_above: int = 9) -> ResidentialProgramInput:
    return ResidentialProgramInput(
        floors_above=floors_above,
        apartments_total=floors_above * 4,
        source_ref="ТЗ: контрольный жилой дом",
        floors_below=1,
        sections_count=1,
        sanitary_shafts_per_section=2,
        lift_shafts_per_section=1,
        has_refuse_chamber=False,
        has_underground_parking=False,
        fixture_condition_answers=(
            ("apartment_has_washing_machine", False),
            ("apartment_has_dishwasher", False),
            ("refuse_chamber_has_drain", False),
        ),
    )


def _confirmed_draft(tmp_path: Path, *, floors_above: int = 9):
    store = BuildingProgramStore(tmp_path / "models")
    draft = store.save(
        _input(floors_above=floors_above),
        title="Учебный жилой дом, Москва",
    )
    return store.confirm_basis(
        draft.model_id,
        expected_topology_sha256=draft.topology_sha256,
        confirmed_by="Проектировщик Zarya",
        confirmation_note="Контрольный выпуск",
    )


def test_building_program_report_is_vector_paginated_and_traceable(tmp_path):
    draft = _confirmed_draft(tmp_path)
    output = tmp_path / "building-program.pdf"

    assert generate_building_program_report_pdf(draft, output) == str(output)

    reader = PdfReader(output)
    assert len(reader.pages) == 2
    page = reader.pages[0]
    width_mm = float(page.mediabox.width) * 25.4 / 72
    height_mm = float(page.mediabox.height) * 25.4 / 72
    assert width_mm == pytest.approx(PAGE_WIDTH_MM, abs=0.2)
    assert height_mm == pytest.approx(PAGE_HEIGHT_MM, abs=0.2)
    text = "\n".join(row.extract_text() or "" for row in reader.pages)
    compact = "".join(text.split())
    assert "КОНТРОЛЬНЫЙЛИСТТИПОЛОГИЧЕСКОЙМОДЕЛИ" in compact
    assert "Учебныйжилойдом,Москва" in compact
    assert draft.model_id in compact
    assert "ПОМЕЩЕНИЕ-&gt;ПРИБОР" in compact or "ПОМЕЩЕНИЕ->ПРИБОР" in compact
    assert "схема:ждётгеометриюАР" in compact
    assert "Этаж9" in compact


def test_register_is_paginated_without_hiding_levels(tmp_path):
    draft = _confirmed_draft(tmp_path, floors_above=40)
    output = tmp_path / "building-program-40.pdf"

    generate_building_program_report_pdf(draft, output)

    reader = PdfReader(output)
    assert len(reader.pages) == 4
    text = "\n".join(row.extract_text() or "" for row in reader.pages)
    compact = "".join(text.split())
    assert "Этаж1" in compact
    assert "Этаж40" in compact
