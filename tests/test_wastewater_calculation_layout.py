"""Regression for text escaping fixed-width columns in the actual PDF layout."""
from weasyprint import CSS, HTML
from weasyprint.formatting_structure.boxes import TableBox, TableCellBox, TextBox

from app.intake.project_builder import build_project
from app.intake.yaml_io import load_request_file
from app.pz.generator import (
    TEMPLATES_DIR, _CSS_FILES, generate_wastewater_calculation_html,
)
from app.pz.ios2_orchestrator import design_ios2


def test_calculation_table_text_stays_inside_its_cell(tmp_path):
    project = design_ios2(
        build_project(load_request_file("demo/demo_project.yaml")),
        output_dir=str(tmp_path), render_documents=False,
    ).project
    rendered = HTML(
        string=generate_wastewater_calculation_html(project),
        base_url=str(TEMPLATES_DIR),
    ).render(stylesheets=[
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in (*_CSS_FILES, "wastewater.css")
    ])
    checked = set()
    for page in rendered.pages:
        for table in page._page_box.descendants():
            if not isinstance(table, TableBox) or table.element is None:
                continue
            classes = set(table.element.get("class", "").split())
            targets = classes & {"riser-calc", "hydraulic-calc"}
            if not targets:
                continue
            checked.update(targets)
            for cell in table.descendants():
                if not isinstance(cell, TableCellBox):
                    continue
                left = cell.content_box_x()
                right = left + cell.width
                for text in cell.descendants():
                    if isinstance(text, TextBox):
                        assert text.position_x >= left - 0.5, text.text
                        assert text.position_x + text.width <= right + 0.5, text.text
    assert checked == {"riser-calc", "hydraulic-calc"}
