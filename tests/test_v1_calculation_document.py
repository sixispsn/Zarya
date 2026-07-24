from pathlib import Path

from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.pz.generator import generate_v1_calculation_html
from app.pz.ios2_orchestrator import design_ios2
from tests.test_pump_bridge import _request


def _text(path: str) -> str:
    return " ".join(page.extract_text() or "" for page in PdfReader(path).pages)


def test_v1_calculation_html_uses_existing_results(tmp_path):
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    html = generate_v1_calculation_html(bundle.project)

    assert "Расчётные обоснования систем В1, Т3 и К1" in html
    assert "Исходные нормы и суточные расходы" in html
    assert "Свободный напор перед диктующим прибором" in html
    assert f"{bundle.project.flows.q_day_tot:.3f}".replace(".", ",") in html
    assert "демонстрац" not in html.lower()


def test_v1_calculation_is_separate_pdf_and_appended(tmp_path):
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    appendix = Path(bundle.v1_calculation_pdf)

    assert appendix.name == "Расчеты_В1.pdf"
    assert appendix.exists()
    appendix_text = _text(str(appendix))
    pz_text = _text(bundle.pz_pdf)

    assert "Расчётные обоснования систем В1, Т3 и К1" in appendix_text
    assert "Расчётный расход стоков К1" in appendix_text
    assert "Расчёт требуемого напора В1" in appendix_text
    assert "Расчётные обоснования систем В1, Т3 и К1" in pz_text
