from pathlib import Path

from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.pz.generator import (
    generate_pz_html, generate_scheme_svg, generate_v1_calculation_html,
    generate_wastewater_pz_html,
)
from app.pz.ios2_orchestrator import design_ios2
from tests.test_pump_bridge import _request


def _text(path: str) -> str:
    return " ".join(page.extract_text() or "" for page in PdfReader(path).pages)


def test_v1_calculation_html_uses_existing_results(tmp_path):
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    html = generate_v1_calculation_html(bundle.project)

    assert "Расчётные обоснования систем В1 и Т3" in html
    assert "Исходные нормы и суточные расходы" in html
    assert "Свободный напор перед диктующим прибором" in html
    assert f"{bundle.project.flows.q_day_tot:.3f}".replace(".", ",") in html
    assert "демонстрац" not in html.lower()


def test_ios2_text_does_not_contain_k1_or_k2_calculation_paragraphs(tmp_path):
    bundle = design_ios2(
        build_project(_request()), output_dir=str(tmp_path), render_documents=False,
    )
    html = generate_pz_html(bundle.project)

    assert "Расчётный расход хозяйственно-бытовых стоков определён" not in html
    assert "Пропускная способность стояков, горизонтальные участки" not in html
    assert "Показатель расчёта К2" not in html


def test_twelve_fire_cabinets_promote_two_inlets_everywhere(tmp_path):
    project = build_project(_request())
    project.fire.pk_total = 12
    project.source.inputs_count = 1
    project.fire_rooms = []
    project.fire_network = None
    bundle = design_ios2(
        project, output_dir=str(tmp_path), render_documents=False,
    )

    assert bundle.project.source.inputs_count == 2
    assert bundle.project.meters.inputs_count == 2
    assert "Ввод водопровода 2x" in generate_scheme_svg(bundle.project)


def test_itp_in_scope_uses_legacy_common_input_and_hot_branch_path(tmp_path):
    request = _request()
    request.hws_type = "central"
    request.source_data.hws_heater_in_scope = True
    request.source_data.h_tepl_m = 3.0
    request.source_data.h_apartment_c_meter_m = 0.4
    request.source_data.h_apartment_h_meter_m = 0.5
    bundle = design_ios2(
        build_project(request), output_dir=str(tmp_path), render_documents=False,
    )

    labels = [row.label.lower() for row in bundle.project.meters.rows]
    assert any("вводе" in label for label in labels)
    assert any("водонагревател" in label for label in labels)
    assert bundle.project.head_paths.hot.head.h_required_m > bundle.project.head_paths.cold.head.h_required_m


def test_no_hws_does_not_create_hot_meter_or_hot_head_path(tmp_path):
    request = _request()
    request.hws_type = "none"
    bundle = design_ios2(
        build_project(request), output_dir=str(tmp_path), render_documents=False,
    )

    labels = [row.label.lower() for row in bundle.project.meters.rows]
    assert all("гвс" not in label and "горяч" not in label for label in labels)
    assert bundle.project.head_paths.hot is None


def test_v1_calculation_is_separate_pdf_and_appended(tmp_path):
    bundle = design_ios2(build_project(_request()), output_dir=str(tmp_path))
    appendix = Path(bundle.v1_calculation_pdf)
    commission = Path(bundle.commission_control_pdf)

    assert appendix.name == "Расчеты_В1.pdf"
    assert appendix.exists()
    appendix_text = _text(str(appendix))
    pz_text = _text(bundle.pz_pdf)

    assert "Расчётные обоснования систем В1 и Т3" in appendix_text
    assert "Расчётный расход стоков К1" not in appendix_text
    assert "Расчёт требуемого напора В1" in appendix_text
    assert "Расчётные обоснования систем В1 и Т3" in pz_text
    wastewater = Path(bundle.wastewater_calculation_pdf)
    assert wastewater.name == "Расчеты_К1_К2.pdf"
    assert wastewater.exists()
    wastewater_text = _text(str(wastewater))
    assert "Расчётные обоснования систем К1 и К2" in wastewater_text
    assert "Расчётный расход хозяйственно-бытовых стоков К1" in wastewater_text
    assert "Расчётные обоснования систем К1 и К2" in pz_text
    wastewater_scheme = Path(bundle.wastewater_scheme_pdf)
    assert wastewater_scheme.name == "Схема_К1_К2.pdf"
    assert wastewater_scheme.exists()
    wastewater_pz = Path(bundle.wastewater_pz_pdf)
    assert wastewater_pz.name == "ПЗ_К1_К2.pdf"
    assert wastewater_pz.exists()
    wastewater_pz_text = _text(str(wastewater_pz))
    assert "Подраздел 5.3 «Система водоотведения»" in wastewater_pz_text
    assert "пункту 18" in wastewater_pz_text
    assert "Расчётные обоснования систем К1 и К2" in wastewater_pz_text
    wastewater_spec = Path(bundle.wastewater_spec_pdf)
    assert wastewater_spec.name == "Спецификация_К1_К2.pdf"
    assert wastewater_spec.exists()
    wastewater_package = Path(bundle.wastewater_package_pdf)
    assert wastewater_package.name == "Комплект_К1_К2.pdf"
    assert wastewater_package.exists()
    package_text = _text(str(wastewater_package))
    assert "Подраздел 5.3 «Система водоотведения»" in package_text
    assert "Расчётные обоснования систем К1 и К2" in package_text
    assert "Принципиальная схема систем К1 и К2" in package_text
    assert "Спецификация оборудования" in package_text
    assert "материалов К1/К2" in package_text
    assert commission.name == "Паспорт_и_нормативный_контроль.pdf"
    assert commission.exists()
    commission_text = _text(str(commission))
    assert "Паспорт проекта и нормативный контроль" in commission_text
    assert "Матрица нормативной трассировки" in commission_text
    assert "Протокол автоматических проверок" in commission_text
    assert bundle.commission_report.project_fingerprint in commission_text
    assert "Матрица нормативной трассировки" in pz_text


def test_wastewater_pz_has_ios3_cipher_and_no_fake_requisites():
    project = build_project(_request())
    project.document.cipher = "2026-14-ИОС2"
    html = generate_wastewater_pz_html(project)

    assert "2026-14-ИОС3" in html
    assert "2026-14-ИОС2.ИОС3" not in html
    assert "демонстрац" not in html.lower()
