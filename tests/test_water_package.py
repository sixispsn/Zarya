from types import SimpleNamespace

from pypdf import PdfReader

from app.pz.water_package import PARTS, generate_water_package, missing_water_parts
from tests.test_pdf_merge import outline, source


def test_water_package_preserves_parts_and_bookmarks_without_duplicate_calculations(tmp_path):
    parts = {key: source(tmp_path / f"{key}.pdf", title) for key, title in PARTS}
    bundle = SimpleNamespace(**parts,
        wastewater_package_pdf=source(tmp_path / "sewer.pdf", "НЕ ВКЛЮЧАТЬ К1/К2"),
        v1_calculation_pdf=parts["pz_pdf"], balance_pdf=parts["pz_pdf"],
        pump_selection_pdf=parts["pz_pdf"], commission_control_pdf=parts["pz_pdf"])
    reader = PdfReader(generate_water_package(bundle, str(tmp_path / "ИОС2.pdf")))
    assert not missing_water_parts(bundle)
    assert len(reader.pages) == len(PARTS) * 2
    assert [row for row in outline(reader) if row[0] == 0] == [
        (0, title, index * 2) for index, (_, title) in enumerate(PARTS)]
    assert not any("НЕ ВКЛЮЧАТЬ" in row[1] for row in outline(reader))
    assert [p.mediabox.width for p in reader.pages] == [300, 301] * len(PARTS)
    assert all(0 <= row[2] < len(reader.pages) for row in outline(reader))
    for index in range(len(PARTS)):
        dest = reader.pages[index * 2]["/Annots"][0].get_object()["/Dest"][0]
        assert reader.get_page_number(dest.get_object()) == index * 2 + 1


def test_missing_drawing_does_not_silently_look_complete(tmp_path):
    bundle = SimpleNamespace(pz_pdf=source(tmp_path / "ПЗ.pdf", "ИОС2"))
    assert len(missing_water_parts(bundle)) == 4
    reader = PdfReader(generate_water_package(bundle, str(tmp_path / "partial.pdf")))
    assert len(reader.pages) == 2


def test_catalog_marks_missing_water_drawings_incomplete():
    from app.intake.project_builder import build_project
    from app.intake.yaml_io import load_request_file
    from app.pz.ios2_orchestrator import IOS2DesignBundle
    from app.web.wizard import _bundle_documents
    project = build_project(load_request_file("demo/demo_project.yaml"))
    bundle = IOS2DesignBundle(project, pz_pdf="/tmp/ПЗ.pdf", water_package_pdf="/tmp/ИОС2.pdf")
    docs, _ = _bundle_documents(bundle)
    water = next(row for row in docs if row["kind"] == "water_package_pdf")
    assert water["group"] == "ios2" and water["state"] == "incomplete"
    assert "Принципиальная схема водоснабжения" in water["state_note"]
