from dataclasses import replace

import pytest

from app.analysis.architecture_confirmation import (
    ConfirmedArchitectureSectionInput,
    PdfFloorSectionConfirmation,
    PdfScaleConfirmation,
    PdfSectionBarrierConfirmation,
    PdfSectionCellConfirmation,
    PdfSectionCutConfirmation,
    audit_confirmed_architecture_section,
    build_section_interval_drafts,
    build_confirmed_architecture_section,
    confirmed_architecture_section_from_mapping,
    confirmed_architecture_section_to_mapping,
    find_cut_intersection_candidates,
)
from app.analysis.architecture_pdf import (
    ArchitecturePdfPageSurvey,
    PdfPlanLineCandidate,
    PdfPlanPoint,
)


def _line(x1, y1, x2, y2):
    return PdfPlanLineCandidate(
        PdfPlanPoint(x1, y1),
        PdfPlanPoint(x2, y2),
        1.0,
        "S",
    )


def _page():
    return ArchitecturePdfPageSurvey(
        page_number=1,
        width_pt=300,
        height_pt=150,
        rotation_deg=0,
        vector_lines=(
            _line(0, 0, 0, 100),
            _line(100, 0, 100, 100),
            _line(100.6, 0, 100.6, 100),
            _line(200, 0, 200, 100),
            _line(300, 0, 300, 100),
        ),
        texts=(),
        image_count=0,
        kind="vector",
        selectable_for_vector_confirmation=True,
    )


def _scale():
    return PdfScaleConfirmation(
        PdfPlanPoint(0, 0),
        PdfPlanPoint(100, 0),
        4.0,
    )


def _cut():
    return PdfSectionCutConfirmation(
        PdfPlanPoint(0, 50),
        PdfPlanPoint(300, 50),
    )


def _floor():
    return PdfFloorSectionConfirmation(
        page_number=1,
        floor=1,
        elevation_m=0.0,
        clear_height_m=3.0,
        scale=_scale(),
        cut=_cut(),
        cells=(
            PdfSectionCellConfirmation("F1-101", 0, 100.3, "101", "Кухня"),
            PdfSectionCellConfirmation("F1-102", 100.3, 200, "102", "Коридор", "corridor"),
            PdfSectionCellConfirmation("F1-103", 200, 300, "103", "Санузел"),
        ),
        barriers=(
            PdfSectionBarrierConfirmation("F1-FW-1", 200, "противопожарная стена"),
        ),
    )


def _input():
    return ConfirmedArchitectureSectionInput(
        plan_id="АР-ПДФ-01",
        cut_id="1-1",
        source_name="Планы АР.pdf",
        source_sha256="a" * 64,
        floors=(_floor(),),
    )


def test_cut_intersections_are_candidates_and_close_lines_are_clustered():
    candidates = find_cut_intersection_candidates(_page(), _scale(), _cut())

    assert [row.station_pt for row in candidates] == [100.3, 200.0]
    assert [row.station_m for row in candidates] == [4.012, 8.0]
    assert candidates[0].contributing_lines == 2
    assert candidates[1].point == PdfPlanPoint(200.0, 50.0)


def test_confirmed_cells_build_exact_section_without_room_inference():
    model = build_confirmed_architecture_section(_input())

    assert model.cut_length_m == pytest.approx(12.0)
    floor = model.floor(1)
    assert [(row.number, row.name) for row in floor.cells] == [
        ("101", "Кухня"),
        ("102", "Коридор"),
        ("103", "Санузел"),
    ]
    assert floor.cells[0].end_m == pytest.approx(4.012)
    assert floor.barriers[0].distance_m == pytest.approx(8.0)
    assert "SHA-256" in floor.source_ref


def test_intervals_use_only_selected_candidate_stations():
    intervals = build_section_interval_drafts(_scale(), _cut(), [200, 100.3])

    assert [(row.start_station_pt, row.end_station_pt) for row in intervals] == [
        (0.0, 100.3),
        (100.3, 200.0),
        (200.0, 300.0),
    ]
    assert intervals[1].start_m == pytest.approx(4.012)
    assert intervals[1].end_m == pytest.approx(8.0)


def test_confirmed_section_mapping_roundtrip_is_lossless():
    restored = confirmed_architecture_section_from_mapping(
        confirmed_architecture_section_to_mapping(_input())
    )

    assert restored == _input()
    assert build_confirmed_architecture_section(restored).cut_length_m == 12.0


def test_confirmation_rejects_gaps_overlap_missing_labels_and_bad_scale():
    value = _input()
    broken_cells = (
        replace(value.floors[0].cells[0], name=""),
        replace(value.floors[0].cells[1], start_station_pt=110),
        replace(value.floors[0].cells[2], start_station_pt=190),
    )
    floor = replace(
        value.floors[0],
        scale=replace(value.floors[0].scale, real_distance_m=0),
        cells=broken_cells,
    )
    issues = audit_confirmed_architecture_section(
        replace(value, floors=(floor,))
    )
    codes = {row.code for row in issues}
    assert "scale.invalid" in codes

    floor = replace(value.floors[0], cells=broken_cells)
    issues = audit_confirmed_architecture_section(
        replace(value, floors=(floor,))
    )
    codes = {row.code for row in issues}
    assert "cell.label" in codes
    assert "cell.coverage" in codes
    assert "cell.overlap" in codes


def test_cut_length_must_match_between_confirmed_floors():
    value = _input()
    second = replace(
        value.floors[0],
        floor=2,
        page_number=2,
        scale=replace(value.floors[0].scale, real_distance_m=5.0),
        cells=tuple(
            replace(row, cell_id=f"F2-{row.number}")
            for row in value.floors[0].cells
        ),
        barriers=(),
    )
    issues = audit_confirmed_architecture_section(
        replace(value, floors=(value.floors[0], second))
    )
    assert "cut.length_mismatch" in {row.code for row in issues}
