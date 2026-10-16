"""Full-content and safe-publication regression for typological reports."""
from copy import deepcopy
from dataclasses import replace
import re
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from app.architecture import program_report as report
from app.architecture.engineering_handoff import build_engineering_handoff
from app.architecture.program_store import _topology_sha256
from app.architecture.residential_program import ProgramQuestion
from tests.test_building_program_report import _confirmed_draft


def report_case(directory, long=False):
    draft = _confirmed_draft(directory, floors_above=9)
    draft = replace(draft, title="Синтетическая проверка типологической модели. Не для выпуска")
    if not long:
        return draft
    fixtures = tuple(replace(row, label=f"ПРИБОР{i:03d} " + "Длинная подпись прибора " * 8)
                     if i < 20 else row for i, row in enumerate(draft.topology.fixtures))
    questions = tuple(ProgramQuestion(f"qa-{i}", f"ВОПРОС{i:03d} " +
                                     "Подтвердите состав и исходные данные модели. " * 16, "qa")
                      for i in range(10))
    topology = replace(draft.topology, fixtures=fixtures, questions=questions,
                       source_ref="ИСТОЧНИК" * 100)
    return replace(draft, topology=topology, topology_sha256=_topology_sha256(topology),
                   basis_confirmed=False)


def compact_text(path):
    text = " ".join(p.extract_text() for p in PdfReader(path).pages)
    text = re.sub(r"Лист \d+ из \d+", "", text)
    text = text.replace("Контроль типологической основы. Не является планом АР или схемой инженерных сетей.", "")
    return "".join(text.split())


@pytest.mark.parametrize("long", [False, True])
def test_complete_content_bounds_and_input_preservation(tmp_path, long):
    draft = report_case(tmp_path, long)
    before = deepcopy(draft)
    handoff = build_engineering_handoff(draft.topology, basis_confirmed=draft.basis_confirmed)
    target = tmp_path / "report.pdf"
    report.generate_building_program_report_pdf(draft, target)
    assert draft == before
    assert build_engineering_handoff(draft.topology, basis_confirmed=draft.basis_confirmed) == handoff
    text = compact_text(target)
    assert draft.topology_sha256 in text
    assert "".join(draft.topology.source_ref.split()) in text
    for group in report._source_groups(draft):
        assert "".join(group.fixture_label.split()) in text
        assert "".join(group.room_label.split()) in text
    for question in draft.topology.questions:
        assert "".join(question.prompt.split()) in text
    assert ("ТРЕБУЕТПОДТВЕРЖДЕНИЯ" if long else "ОСНОВАПОДТВЕРЖДЕНА") in text
    assert "схема:ждётгеометриюАР" in text
    assert "Ещётиповсвязей:" not in text
    with fitz.open(target) as pdf:
        for number, page in enumerate(pdf, 1):
            assert page.rect.width == pytest.approx(420 / 25.4 * 72, abs=.1)
            assert page.rect.height == pytest.approx(297 / 25.4 * 72, abs=.1)
            assert f"Лист {number} из {len(pdf)}" in page.get_text()
            assert "Не является планом АР" in page.get_text()
            assert not page.get_images()
            for x0, y0, x1, y1, *_ in page.get_text("words"):
                assert x0 >= 49 and x1 <= 1141
                assert y0 >= 35 and y1 <= 816
            for span in [s for b in page.get_text("dict")["blocks"] if "lines" in b
                         for line in b["lines"] for s in line["spans"]]:
                assert "OpenGOST" in span["font"]
            if "ПРИБОР" in page.get_text():
                assert "ПОМЕЩЕНИЕ -> ПРИБОР" in page.get_text()


def test_table_grid_and_repeated_header(tmp_path):
    report.generate_building_program_report_pdf(report_case(tmp_path), tmp_path / "report.pdf")
    # Every cell uses the same closed grid; no line-only summary blocks.
    table = report._table(["A", "B"], [["1", "2"]], [100, 100])
    assert table.repeatRows == 1 and table.splitInRow == 0
    assert any(command[0] == "GRID" and command[1:3] == ((0, 0), (-1, -1))
               for command in table._linecmds)


def test_register_counts_match_model(tmp_path):
    draft = report_case(tmp_path)
    rows = report._register_rows(draft)
    assert len(rows) == len(draft.topology.levels)
    assert sum(int(row[2]) for row in rows) == len(draft.topology.apartments)
    assert sum(int(row[3]) for row in rows) == len(draft.topology.rooms)
    assert sum(int(row[4]) for row in rows) == len(draft.topology.fixtures)
    assert sum(group.count for group in report._source_groups(draft)) == len(draft.topology.fixtures)
    for column, system in enumerate(("V1", "T3", "K1", "K2", "K3"), 6):
        assert sum(int(row[column]) for row in rows) == sum(
            system in row.service_ports for row in draft.topology.fixtures)


def test_question_longer_than_page_is_complete(tmp_path):
    draft = report_case(tmp_path)
    prompt = " ".join(f"ВОПРОС{i:04d} уточните данные." for i in range(1500))
    topology = replace(draft.topology, questions=(ProgramQuestion("qa", prompt, "qa"),))
    target = tmp_path / "report.pdf"
    report.generate_building_program_report_pdf(replace(draft, topology=topology), target)
    assert "".join(prompt.split()) in compact_text(target)


def test_empty_register_does_not_imply_readiness(tmp_path):
    draft = report_case(tmp_path)
    topology = replace(draft.topology, levels=(), rooms=(), fixtures=(), apartments=(),
                       sanitary_shafts=(), questions=())
    target = tmp_path / "report.pdf"
    report.generate_building_program_report_pdf(
        replace(draft, topology=topology, basis_confirmed=False), target)
    text = compact_text(target)
    assert "Зарегистрированныесвязипомещенийиприборовотсутствуют." in text
    assert "ТРЕБУЕТПОДТВЕРЖДЕНИЯ" in text
    assert "составготов" not in text
    assert "ГеометрияАРпо-прежнемуобязательнадлясхем." in text


def test_long_unbroken_title_stays_within_page(tmp_path):
    draft = replace(report_case(tmp_path), title="ОБЪЕКТ" * 120)
    target = tmp_path / "report.pdf"
    report.generate_building_program_report_pdf(draft, target)
    assert draft.title in compact_text(target)
    with fitz.open(target) as pdf:
        for page in pdf:
            for x0, _, x1, _, *_ in page.get_text("words"):
                assert x0 >= 49 and x1 <= 1141


def test_tall_row_is_not_clipped_and_keeps_old_pdf(tmp_path):
    draft = report_case(tmp_path)
    fixtures = (replace(draft.topology.fixtures[0], label="Длинная строка " * 3000),
                *draft.topology.fixtures[1:])
    draft = replace(draft, topology=replace(draft.topology, fixtures=fixtures))
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous pdf")
    with pytest.raises(report.ProgramReportLayoutError, match="не помещается"):
        report.generate_building_program_report_pdf(draft, target)
    assert target.read_bytes() == b"previous pdf"
    assert not list(tmp_path.glob(".building-report-*"))


@pytest.mark.parametrize("failure", ["build", "replace"])
def test_output_failure_keeps_old_pdf(tmp_path, monkeypatch, failure):
    draft = report_case(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("synthetic failure")
    if failure == "build":
        monkeypatch.setattr(report.BaseDocTemplate, "build", fail)
    else:
        monkeypatch.setattr(report.os, "replace", fail)
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous pdf")
    with pytest.raises(OSError, match="synthetic failure"):
        report.generate_building_program_report_pdf(draft, target)
    assert target.read_bytes() == b"previous pdf"
    assert not list(tmp_path.glob(".building-report-*"))


def test_web_reports_layout_error(tmp_path, monkeypatch):
    from app.web import building_model
    draft = report_case(tmp_path)
    monkeypatch.setattr(building_model, "_PROGRAM_STORE", SimpleNamespace(load=lambda _: draft))
    def fail(*args):
        raise report.ProgramReportLayoutError("строка не помещается")
    monkeypatch.setattr(building_model, "generate_building_program_report_pdf", fail)
    with pytest.raises(HTTPException) as failure:
        building_model.saved_building_model_report_pdf(draft.model_id)
    assert failure.value.status_code == 422
    assert failure.value.detail == "строка не помещается"
