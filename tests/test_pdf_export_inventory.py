"""Inventory completeness is separate from visual/normative acceptance."""
from scripts.audit_pdf_export_inventory import GROUPS, discover, inventory


def test_every_direct_renderer_has_an_explicit_classification_and_evidence():
    report = inventory()
    assert not report["unknown"]
    assert not report["stale"]
    assert not report["missing_evidence"]
    # The direct-site queue may reach zero; its scope still excludes global
    # normative acceptance and must not claim the entire product is approved.
    assert "not whole-program or normative approval" in report["scope"]
    assert len(report["sites"]) == sum(len(functions.split()) for _, functions, _, _ in GROUPS)


def test_scanner_handles_aliases_methods_async_and_multiple_calls(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "new.py").write_text('''
from reportlab.pdfgen.canvas import Canvas as Paper
from cairosvg import svg2pdf as convert
class Sheet:
    def __init__(self):
        self.c = Paper("test.pdf")
async def new_export():
    convert(bytestring=b"svg")
    html.write_pdf()
''')
    sites = discover(tmp_path)
    assert set(sites) == {"app/new.py:Sheet.__init__", "app/new.py:new_export"}
    assert sites["app/new.py:new_export"]["calls"] == ["svg2pdf", "write_pdf"]
    report = inventory(tmp_path)
    assert report["unknown"] == sorted(sites)
    assert report["stale"] and report["missing_evidence"]


def test_new_sink_inside_already_classified_module_is_not_automatically_approved(tmp_path):
    directory = tmp_path / "app/pz"
    directory.mkdir(parents=True)
    (directory / "generator.py").write_text('def new_pdf():\n    doc.write_pdf()\n')
    assert inventory(tmp_path)["unknown"] == ["app/pz/generator.py:new_pdf"]


def test_failure_sheets_have_separate_evidence_from_successful_visual_goldens():
    report = inventory()
    rows = {r["site"]: r for r in report["sites"]}
    status = rows["app/pz/wastewater_status_document.py:generate_status_pdf"]
    assert status["evidence"] == "tests/test_wastewater_status_document.py"
