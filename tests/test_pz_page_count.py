"""The first-sheet total follows the rendered text, not stale project metadata."""
from io import BytesIO

from pypdf import PdfReader
import pytest

from app.pz import generator
from app.pz.project import Project


@pytest.mark.parametrize("saved_total", ["1", "—", "99", "3"])
def test_rendered_total_without_mutating_project(tmp_path, monkeypatch, saved_total):
    p = Project()
    p.document.sheet_total = saved_total
    seen = []

    def html(project):
        seen.append(project.document.sheet_total)
        return (f"<p>Total sheets: {project.document.sheet_total}</p>"
                '<p style="break-before:page">Second</p>'
                '<p style="break-before:page">Third</p>')

    monkeypatch.setattr(generator, "generate_pz_html", html)
    path = tmp_path / "pz.pdf"
    generator.generate_pz_pdf(p, str(path))
    pdf = PdfReader(BytesIO(path.read_bytes()))
    assert len(pdf.pages) == 3
    assert "Total sheets: 3" in pdf.pages[0].extract_text()
    assert p.document.sheet_total == saved_total
    assert seen == ([saved_total] if saved_total == "3" else [saved_total, "3"])


def test_long_subheading_stays_on_one_page_with_following_text():
    from weasyprint import CSS, HTML
    # Fill most of a small synthetic page, leaving room for only part of the
    # heading. Use the production CSS and override paper geometry, not breaks.
    css = (generator.TEMPLATES_DIR / 'frame.css').read_text()
    css += '@page { size: 100mm 100mm; margin: 10mm; } @page:first { margin: 10mm; }'
    html = ('<div style="height:58mm"></div><p class="subhead">'
            'HEADING_START<br>Second line<br>Third line<br>HEADING_END</p>'
            '<p class="subitem">FOLLOWING_TEXT</p>')
    pdf = PdfReader(BytesIO(HTML(string=html).write_pdf(stylesheets=[CSS(string=css)])))
    texts = [p.extract_text() for p in pdf.pages]
    assert len(texts) == 2
    assert 'HEADING_START' not in texts[0]
    assert all(marker in texts[1] for marker in ('HEADING_START','HEADING_END','FOLLOWING_TEXT'))
