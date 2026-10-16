"""
Генератор пояснительной записки в PDF.

Берёт модель Project, рендерит Jinja2-шаблоны подпунктов,
вставляет в шаблон листа со штампом, превращает в PDF через WeasyPrint.

ВАЖНО: CSS подключается через stylesheets=, а не инлайном в HTML —
autoescape Jinja2 экранирует кавычки внутри <style> и ломает url(...).
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML
from dataclasses import replace

from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.metering_options import option_requests, OPTIONS_NOTICE
from app.pz.metering_presentation import metering_presentation
from app.pz.metering_extras import metering_option_rows
from app.pz.water_document_binding import water_material_context, water_pressure_presentation
from app.pz.hws_presentation import hws_principle
from app.pz.hws_stage_p import stage_p_circulation
from app.data.booster_controls import booster_control
from app.calc.rainwater_reuse import assess as assess_rainwater
from app.calc.rainwater_treatment import project_context as rainwater_context
from app.pz.project import BuildingPurpose, Project
from app.pz.rules import (
    check_tu_limits, decide_fire_network,
    project_governing_head,
)
from app.pz.pump_chart import PumpChart, render_pump_chart_svg
from app.pz.spec import (
    build_water_specification,
    build_wastewater_specification,
    format_spec_qty,
)
from app.pz.commission import build_commission_report
from app.pz.scheme import build_scheme, SchemeParams, SchemeResult, W as SCHEME_W, H as SCHEME_H


TEMPLATES_DIR = Path(__file__).parent / "templates"

# CSS-файлы ПЗ (порядок важен: рамка -> таблицы). Все лежат в templates/.
_CSS_FILES = ["frame.css", "balance.css", "equipment.css"]


def _write_text_pdf(html, output_path, doc, css_files):
    """Title-less A4 annex: forms 3/6 and actual page count after pagination."""
    from app.pz.text_document_frame import apply_frame
    body = HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(stylesheets=[
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in (*css_files, "measured_text_frame.css")])
    Path(output_path).write_bytes(apply_frame(body, doc))
    return output_path


def _fire_station_document_context(project):
    from app.intake.studio_fire_location import from_model
    from app.data.fire_pump_geometry import connection_review
    return dict(fire_station_location=from_model(project.fire_station_model_input),
                fire_pump_geometry=connection_review(project.fire_station_model_input, project.fire_pumps.model))


def _document_cipher(cipher: str, suffix: str) -> str:
    """Добавить суффикс документа только к реально заданному шифру."""
    if not cipher:
        return ""
    return cipher if cipher.endswith(suffix) else cipher + suffix


def _wastewater_document_cipher(cipher: str) -> str:
    """Получить самостоятельный шифр подраздела ИОС3 из шифра комплекта.

    Пустой шифр остаётся пустым. Если пользователь уже ввёл ИОС3, значение не
    меняется; распространённое окончание ИОС2 заменяется без двойного суффикса.
    """
    if not cipher:
        return ""
    for marker in ("-ИОС2", ".ИОС2"):
        if cipher.endswith(marker):
            return cipher[: -len(marker)] + marker[:-1] + "3"
    if cipher.endswith(("-ИОС3", ".ИОС3")):
        return cipher
    return cipher + ".ИОС3"


def _build_env() -> Environment:
    """Создать Jinja2-окружение, читающее шаблоны из папки templates."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Число в русской записи: num(2) -> "5,76"; None -> "—"
    env.filters["num"] = lambda v, p=2: ("—" if v is None else f"{v:.{p}f}".replace(".", ","))
    # Точная геометрия без ложного округления и без незначащего нуля: 67.5; 105.
    env.filters["compact"] = lambda v, p=1: (
        "—" if v is None else f"{v:.{p}f}".rstrip("0").rstrip(".")
    )
    env.filters["spec_qty"] = format_spec_qty
    from app.pz.meter_products import evaluate_meter_product
    env.globals["meter_product_check"] = evaluate_meter_product
    from app.pz.pump_validation import check_saved_pump_intersection
    env.globals["check_saved_pump_intersection"] = check_saved_pump_intersection
    from app.pz.meter_validation import check_meter_average
    env.globals["check_meter_average"] = check_meter_average
    env.globals["booster_control_for"] = booster_control
    from app.pz.water_station_review import review_station
    env.globals["station_review_for"] = review_station
    from app.pz.suction_check import review_suction
    env.globals["suction_review_for"] = review_suction
    from app.pz.water_station_components import external_items
    env.globals["station_external_items"] = external_items
    return env


def _subitems_template_name(purpose: BuildingPurpose) -> str:
    """Выбрать файл шаблона подпунктов по типу объекта."""
    mapping = {
        BuildingPurpose.PUBLIC: "subitems_public.html",
        BuildingPurpose.RESIDENTIAL: "subitems_residential.html",
        # производственный добавим позже
    }
    name = mapping.get(purpose)
    if name is None:
        raise ValueError(
            f"Шаблон для типа объекта '{purpose.value}' пока не реализован. "
            "На данном этапе доступны жилой и общественный типы."
        )
    return name


def cold_meter_loss(meters) -> float | None:
    """Потери ∑Hвод для Hтр — счётчик на холодном (диктующем) направлении:
    при одном вводе (Qtot) — узел на вводе; иначе — счётчик ХВС."""
    rows = getattr(meters, "rows", None) or []
    for r in rows:
        if "ввод" in r.label.lower():
            return r.h_a
    for r in rows:
        lab = r.label.lower()
        if "хвс" in lab or "холодн" in lab:
            return r.h_a
    return None


def _pump_chart_for(p) -> str:
    """SVG характеристики Q-H принятого насоса (пусто, если насос не нужен)."""
    if not (p.required and p.curve):
        return ""
    from app.pz.pump_validation import check_saved_pump_intersection
    valid_intersection, _ = check_saved_pump_intersection(p)
    return render_pump_chart_svg(PumpChart(
        curve=p.curve,
        h_stat=p.h_stat if p.curve_kind == "quadratic_estimate" else None,
        k_sys=p.k_sys if p.curve_kind == "quadratic_estimate" else None,
        wp=((p.wp_q, p.wp_h) if valid_intersection or p.pressure_review else None),
        duty=((p.q_design_m3h, p.h_design_m) if p.q_design_m3h else None),
        q_opt=p.q_opt,
        title=p.model,
    ))


def _pump_chart_svg(project: Project) -> str:
    return _pump_chart_for(project.pumps)


def _rainwater_body(project: Project, env) -> str:
    if not project.rainwater_reuse.enabled:
        return ""
    return env.get_template("rainwater_reuse_body.html").render(r=assess_rainwater(project.rainwater_reuse, **rainwater_context(project)))


def generate_rainwater_reuse_html(project: Project) -> str:
    from app.pz.rainwater_reuse import functional_svg, assembly_rows, pump_chart_svg, treatment_rows
    env = _build_env()
    body = env.get_template("rainwater_reuse_calculation.html").render(
        r=assess_rainwater(project.rainwater_reuse, **rainwater_context(project)), diagram=functional_svg(project),
        assembly=assembly_rows(project), pump_chart=pump_chart_svg(project),
        treatment_rows=treatment_rows(project),
    )
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".ДВ"),
                  sheet_title="Использование дождевой воды", sheet_no="1", sheet_total="—")
    return env.get_template("document.html").render(
        doc=doc, body_html=body, document_title="Использование дождевой воды · расчётное приложение",
    )


def generate_rainwater_reuse_pdf(project: Project, output_path: str) -> str:
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".ДВ"),
                  sheet_title="Использование дождевой воды")
    return _write_text_pdf(generate_rainwater_reuse_html(project), output_path, doc,
                           (*_CSS_FILES, "wastewater.css"))


def generate_pz_html(project: Project) -> str:
    """Собрать HTML пояснительной записки (без CSS — для отладки/предпросмотра)."""
    from app.pz.fire_review_binding import validate_binding
    from app.pz.metering_presentation import metering_presentation
    validate_binding(project)
    env = _build_env()

    subitems_tpl = env.get_template(_subitems_template_name(project.building.purpose))
    fire_net = decide_fire_network(
        project.fire, project.materials, project.normative,
    )
    head = project_governing_head(
        project, fallback_h_vod_m=cold_meter_loss(project.meters),
    )
    tu_check = check_tu_limits(project.flows, project.source)
    body_html = subitems_tpl.render(
        project=project,
        **_fire_station_document_context(project),
        metering_options=metering_option_rows(project),
        metering_options_notice=OPTIONS_NOTICE,
        metering_principle=metering_presentation(project),
        doc=project.document,
        building=project.building,
        source=project.source,
        materials=project.materials,
        water_materials=water_material_context(project),
        water_pressure=water_pressure_presentation(project),
        hws_principle=hws_principle(project),
        hws_circulation=stage_p_circulation(project),
        flows=project.flows,
        fire=project.fire,
        meters=project.meters,
        pumps=project.pumps,
        fire_pumps=project.fire_pumps,
        balance=project.balance,
        pump_chart_svg=_pump_chart_svg(project),
        fire_pump_chart_svg=_pump_chart_for(project.fire_pumps),
        fire_net=fire_net,
        head=head,
        tu_check=tu_check,
        v1_hydraulics=project.v1_hydraulic_result,
        t3_hydraulics=project.t3_hydraulic_result,
        v1_stage_p=project.v1_stage_p_result,
        normative=project.normative,
        sewage=project.sewage,
        storm=project.storm,
        grease_trap=project.grease_trap,
        inlet_decision=project.water_inlet_decision,
        head_paths=project.head_paths,
    )

    doc_tpl = env.get_template("document.html")
    body_html += _rainwater_body(project, env)
    return doc_tpl.render(
        doc=project.document,
        body_html=body_html,
        digital_passport=project.digital_passport,
    )


def generate_pz_pdf(project: Project, output_path: str) -> str:
    """
    Сгенерировать PDF пояснительной записки.

    Args:
        project: модель проекта со всеми данными
        output_path: куда сохранить PDF

    Returns:
        Путь к созданному PDF.
    """
    html_str = generate_pz_html(project)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in (*_CSS_FILES, "measured_text_frame.css")
    ]
    rendered = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).render(stylesheets=stylesheets)
    # Count this text document, not the separately numbered calculation annexes.
    # A saved/demo stamp total is not evidence of the current pagination.
    total = str(len(rendered.pages))
    if project.document.sheet_total != total:
        stamped = replace(project, document=replace(project.document, sheet_total=total))
        rendered = HTML(string=generate_pz_html(stamped), base_url=str(TEMPLATES_DIR)).render(
            stylesheets=stylesheets)
        if str(len(rendered.pages)) != total:
            raise ValueError("Число листов ПЗ изменилось при заполнении штампа; проверьте вёрстку")
    from app.pz.text_document_frame import apply_frame
    Path(output_path).write_bytes(apply_frame(rendered.write_pdf(), project.document))
    return output_path


def generate_balance_html(project: Project) -> str:
    """Отдельный лист формы 2 приложения А ГОСТ Р 21.619-2023."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".БВ"),
        sheet_title="Баланс водопотребления и водоотведения",
        sheet_no="1",
        sheet_total="1",
    )
    return env.get_template("balance_document.html").render(
        doc=doc,
        balance=project.balance,
        form_label="Форма 2",
        standard_reference="ГОСТ Р 21.619-2023, приложение А",
        balance_note=project.balance.note,
    )


def generate_balance_pdf(project: Project, output_path: str) -> str:
    """Сформировать нормативный баланс на листе А3 альбомной ориентации."""
    html_str = generate_balance_html(project)
    return _write_balance_pdf(project, html_str, output_path, project.document.cipher or "")


def _write_balance_pdf(project, html_str, output_path, cipher):
    from app.pz.text_document_frame import apply_frame
    body = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        stylesheets=[CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
                     for name in ("balance_document.css", "measured_balance_frame.css")])
    doc = replace(project.document, cipher=_document_cipher(cipher, ".БВ"),
                  sheet_title="Баланс водопотребления и водоотведения")
    Path(output_path).write_bytes(apply_frame(body, doc, layout='a3_graphic'))
    return output_path


def generate_wastewater_balance_html(project: Project) -> str:
    """Баланс ИОС3 по форме приложения А ГОСТ Р 21.620-2023."""
    env = _build_env()
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".БВ"),
        sheet_title="Баланс водопотребления и водоотведения",
        sheet_no="1",
        sheet_total="1",
    )
    return env.get_template("balance_document.html").render(
        doc=doc,
        balance=project.balance,
        form_label="Приложение А",
        standard_reference="ГОСТ Р 21.620-2023",
        balance_note=(
            "Суточный баланс сформирован по форме приложения А "
            "ГОСТ Р 21.620-2023. Хозяйственно-бытовое водоотведение принято "
            "равным водопотреблению; расход на полив в канализацию не поступает."
        ),
    )


def generate_wastewater_balance_pdf(project: Project, output_path: str) -> str:
    html_str = generate_wastewater_balance_html(project)
    return _write_balance_pdf(project, html_str, output_path,
                              _wastewater_document_cipher(project.document.cipher or ""))


# ── РАСЧЁТНЫЙ ЛИСТ В1 / Т3 (отдельное приложение) ────────────────────────

def generate_v1_calculation_html(project: Project) -> str:
    """Собрать отдельный расчётный лист без дублирования расчётной логики.

    В шаблон передаются только результаты, уже полученные расчётным ядром.
    Единственное представление Hтр строится той же функцией, что используется
    в ПЗ и листе подбора насосов.
    """
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".РВ1"),
        sheet_title="Расчёты систем В1 и Т3",
        sheet_no="1",
        sheet_total="—",
    )
    head = project_governing_head(
        project, fallback_h_vod_m=cold_meter_loss(project.meters),
    )
    body_html = env.get_template("v1_calculation_body.html").render(
        project=project,
        metering_principle=metering_presentation(project),
        metering_options=metering_option_rows(project),
        metering_options_notice=OPTIONS_NOTICE,
        source=project.source,
        balance=project.balance,
        flows=project.flows,
        meters=project.meters,
        pumps=project.pumps,
        head=head,
        v1_stage_p=project.v1_stage_p_result,
        v1_hydraulics=project.v1_hydraulic_result,
        t3_hydraulics=project.t3_hydraulic_result,
        head_paths=project.head_paths,
    )
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Расчётные обоснования систем В1 и Т3",
        body_html=body_html,
    )


def generate_v1_calculation_pdf(project: Project, output_path: str) -> str:
    """Сформировать самостоятельный PDF расчётов В1 / Т3 на листах А4."""
    html_str = generate_v1_calculation_html(project)
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".РВ1"),
                  sheet_title="Расчёты систем В1 и Т3")
    return _write_text_pdf(html_str, output_path, doc, (*_CSS_FILES, "v1_calculation.css"))


# ── РАСЧЁТНЫЕ ОБОСНОВАНИЯ К1 / К2 ─────────────────────────────────────

def generate_wastewater_calculation_html(project: Project) -> str:
    """Собрать отдельное приложение К1/К2 из результатов расчётного ядра."""
    from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
    from app.pz.wastewater_transients import assess_wastewater_transients
    from app.pz.wastewater_graphic_exports import representative_document_model

    # Old cached assessments may contain sums of riser maxima. Re-evaluate.
    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    if project.sewage.transient_assessment is None:
        project.sewage.transient_assessment = assess_wastewater_transients(project)
    env = _build_env()
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".РР"),
        sheet_title="Расчётные обоснования систем К1 и К2",
        sheet_no="1",
        sheet_total="—",
    )
    body_html = env.get_template("wastewater_calculation_body.html").render(
        section=representative_document_model(project),
        sewage=project.sewage,
        diagnostics=project.sewage.hydraulic_assessment,
        storm=project.storm,
        grease_trap=project.grease_trap,
    )
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Расчётные обоснования систем К1 и К2",
        body_html=body_html,
    )


def generate_wastewater_calculation_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Сформировать самостоятельный PDF расчётов К1/К2 на листах А4."""
    html_str = generate_wastewater_calculation_html(project)
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(project.document, cipher=_document_cipher(cipher, ".РР"),
                  sheet_title="Расчётные обоснования систем К1 и К2")
    return _write_text_pdf(html_str, output_path, doc, (*_CSS_FILES, "wastewater.css"))


def generate_wastewater_pz_html(project: Project) -> str:
    """Самостоятельная текстовая часть подраздела «Система водоотведения»."""
    from app.pz.wastewater_diagnostics import assess_wastewater_diagnostics
    from app.pz.wastewater_graphic_exports import representative_document_model, assess_wastewater_graphic_exports
    from app.pz.section_level_mark import level_text
    from app.pz.wastewater_service import assess as assess_service

    project.sewage.hydraulic_assessment = assess_wastewater_diagnostics(project)
    env = _build_env()
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(
        project.document,
        cipher=cipher,
        sheet_title="Текстовая часть. Система водоотведения",
        sheet_no="1",
        sheet_total="—",
    )
    balance_rows = getattr(project.balance, "rows", None) or []
    sewage_day_m3 = (
        sum(
            row.sewage_domestic_m3_day
            + row.sewage_clean_m3_day
            + row.sewage_mechanical_m3_day
            + row.sewage_chemical_m3_day
            for row in balance_rows
        )
        if balance_rows else None
    )
    roof_labels = {
        "not_set": "не задана",
        "flat": "плоская",
        "sloped": "скатная",
    }
    disposal_labels = {
        "not_set": "",
        "centralized": "отвод в централизованную систему водоотведения",
        "local": "локальная система водоотведения",
        "water_body": "сброс в водный объект",
    }
    from app.pz.wastewater_gost import audit_wastewater_gost
    gost_audit = audit_wastewater_gost(project)
    body_html = env.get_template("wastewater_pz_body.html").render(
        doc=doc,
        building=project.building,
        normative=project.normative,
        balance=project.balance,
        flows=project.flows,
        sewage=project.sewage,
        wastewater_service=assess_service(project.wastewater_service),
        section=representative_document_model(project),
        graphic_exports=assess_wastewater_graphic_exports(project),
        level_text=level_text,
        sewage_day_m3=sewage_day_m3,
        storm=project.storm,
        grease_trap=project.grease_trap,
        consumer_details=project.consumer_details,
        disposal_mode_label=disposal_labels.get(
            project.sewage.disposal_mode, project.sewage.disposal_mode,
        ),
        gost_audit=gost_audit,
        roof_type_label=roof_labels.get(
            project.storm.roof_type, project.storm.roof_type
        ),
    )
    body_html += _rainwater_body(project, env)
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Подраздел 5.3 «Система водоотведения»",
        body_html=body_html,
    )


def generate_wastewater_pz_pdf(project: Project, output_path: str) -> str:
    """Сформировать самостоятельную ПЗ К1/К2 на листах А4."""
    html_str = generate_wastewater_pz_html(project)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in (*_CSS_FILES, "wastewater.css", "measured_text_frame.css")
    ]
    from app.pz.text_document_frame import apply_frame
    body = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(stylesheets=stylesheets)
    doc = replace(project.document,
                  cipher=_wastewater_document_cipher(project.document.cipher or ""),
                  sheet_title="Текстовая часть. Система водоотведения")
    Path(output_path).write_bytes(apply_frame(body, doc))
    return output_path


def generate_wastewater_scheme_html(project: Project) -> str:
    """Принципиальная схема К1/К2/К3 стадии П без вымышленной трассировки."""
    env = _build_env()
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".СК"),
        sheet_title="Принципиальная схема внутренних систем К1, К2 и К3",
        sheet_no="1",
        sheet_total="—",
    )
    from app.pz.wastewater_gost import audit_wastewater_gost
    body_html = env.get_template("wastewater_scheme_body.html").render(
        building=project.building,
        sewage=project.sewage,
        storm=project.storm,
        grease_trap=project.grease_trap,
        fixtures=project.fixtures,
        gost_audit=audit_wastewater_gost(project),
    )
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Принципиальная схема внутренних систем К1, К2 и К3",
        body_html=body_html,
    )


def generate_wastewater_scheme_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Сформировать каноническую многостраничную схему К1/К2 стадии П.

    Production-выпуск не использует старый универсальный SVG-рендерер. Если
    реестр или точная геометрия неполны, сервис создаёт отдельный лист статуса
    без вымышленных участков и фасонных частей.
    """
    from app.pz.wastewater_graphic_exports import (
        generate_wastewater_graphic_export,
    )

    return generate_wastewater_graphic_export(
        project,
        "k1-k2",
        output_path,
    ).output_path


def generate_wastewater_k3_scheme_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Сформировать отдельную каноническую схему самотечной К3.

    Напорные участки и насосная рабочая точка в этот лист не подмешиваются:
    при их наличии сервис возвращает лист контроля неполноты.
    """
    from app.pz.wastewater_graphic_exports import (
        generate_wastewater_graphic_export,
    )

    return generate_wastewater_graphic_export(
        project,
        "k3",
        output_path,
    ).output_path


def generate_wastewater_pressure_scheme_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Сформировать отдельные листы напорной К1/К3 и рабочей точки.

    Насос, Q-H кривая, потери, трубопроводы и арматура должны быть явно
    подтверждены исходными данными; каталог насосов В1/В2 не используется.
    """
    from app.pz.wastewater_graphic_exports import (
        generate_wastewater_graphic_export,
    )

    return generate_wastewater_graphic_export(
        project,
        "pressure",
        output_path,
    ).output_path


def generate_architecture_section_node_pdf(
    registry_path: str,
    output_path: str,
) -> str:
    """Собрать контрольный архитектурный разрез из строгого реестра планов.

    Функция намеренно не принимает только этажность: помещения, шахты,
    противопожарные преграды, отметки и линия разреза должны быть подтверждены
    в нормализованном реестре АР.
    """
    from app.pz.architecture_section_engine import (
        generate_architecture_section_control_pdf,
        load_architecture_plan_registry,
    )

    registry = load_architecture_plan_registry(registry_path)
    return generate_architecture_section_control_pdf(output_path, registry)


def generate_bound_architecture_wastewater_pdf(
    project: Project,
    architecture,
    binding,
    output_path: str,
) -> str:
    """Собрать А1-разрез К1/К2 по подтверждённым координатам АР.

    ``architecture`` и ``binding`` являются проверенными объектами из
    ``app.analysis``. Инженерные рёбра, марки участков и УГО берутся из
    ``project.sewage``; функция не создаёт отсутствующие приборы или связи.
    """
    from app.analysis.architecture_wastewater_binding import (
        build_bound_wastewater_layout,
    )
    from app.pz.wastewater_graphic_exports import (
        generate_wastewater_graphic_export,
    )

    layout = build_bound_wastewater_layout(architecture, binding, project)
    return generate_wastewater_graphic_export(
        project,
        "k1-k2",
        output_path,
        confirmed_layout=layout,
    ).output_path


def generate_wastewater_diagnostic_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Сформировать ненормативный цветной лист проверки потока и прочистки."""
    ensure_drafting_font_registered()
    import cairosvg

    svg = _svg_to_a1_mm(generate_wastewater_scheme_svg(
        project,
        diagnostics=True,
    ))
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path


def generate_wastewater_ugo_pdf(
    project: Project,
    output_path: str,
) -> str:
    """Лист 2 — ведомость УГО К1/К2/К3 с нормативной трассировкой."""
    ensure_drafting_font_registered()
    import cairosvg

    from app.pz.wastewater_ugo import build_wastewater_ugo_sheet

    cipher = _wastewater_document_cipher(project.document.cipher or "")
    ugo_doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".СК"),
        sheet_title="Ведомость условных графических обозначений К1, К2 и К3",
        sheet_no="1",
        sheet_total="1",
    )
    svg = build_wastewater_ugo_sheet(replace(project, document=ugo_doc))
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path


def generate_wastewater_scheme_result(
    project: Project,
    *,
    diagnostics: bool = False,
):
    """Вернуть старый сравнительный SVG с диагностическими замечаниями.

    Функция сохраняется для регрессионных и диагностических тестов. Она не
    является production-путём PDF; выпуск выполняет
    :func:`app.pz.wastewater_scheme_service.generate_wastewater_scheme`.
    """
    from app.pz.wastewater_scheme import build_wastewater_scheme

    cipher = _wastewater_document_cipher(project.document.cipher or "")
    scheme_doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".СК"),
        sheet_title="Принципиальная схема внутренних систем К1, К2 и К3",
        sheet_no="1",
        sheet_total="1",
    )
    return build_wastewater_scheme(
        replace(project, document=scheme_doc),
        diagnostics=diagnostics,
    )


def generate_wastewater_lower_turn_node_pdf(
    output_path: str,
    *,
    system: str = "K1",
    dn_mm: int = 100,
) -> str:
    """Generate the first reusable installation node of the sewer drafter.

    This approval sheet is intentionally separate from the full principle
    scheme.  Once accepted, the same semantic assembly will be inserted by the
    floor/basement layout engine instead of redrawing the node ad hoc.
    """
    from app.pz.wastewater_drafting import generate_lower_turn_control_pdf

    return generate_lower_turn_control_pdf(
        output_path,
        system=system,
        dn_mm=dn_mm,
    )


def generate_wastewater_typical_floor_node_pdf(
    output_path: str,
    *,
    fixtures=None,
    floor_no: int = 2,
    floor_elevation_m: float = 3.0,
    riser_id: str = "К1-Ст1",
) -> str:
    """Generate the isolated reusable K1 typical-floor module.

    The control sheet remains separate from the complete building scheme
    until its installation topology and GOST-style layout are accepted.
    """
    from app.pz.wastewater_floor_drafting import generate_typical_floor_control_pdf

    return generate_typical_floor_control_pdf(
        output_path,
        fixtures=fixtures,
        floor_no=floor_no,
        floor_elevation_m=floor_elevation_m,
        riser_id=riser_id,
    )


def generate_wastewater_stack_node_pdf(
    output_path: str,
    *,
    floors_above: int = 9,
    floor_height_m: float = 3.0,
    riser_id: str = "К1-Ст1",
    riser_dn_mm: int = 100,
    roof_kind: str = "flat_non_accessible",
    fixtures_by_floor=None,
    floor_slope_dn50: float = 0.03,
    floor_slope_dn100: float = 0.02,
    max_floors_per_sheet: int = 5,
    collapse_typical_floors: bool = True,
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    basement_collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
    outlet_dn_mm: int | None = None,
) -> str:
    """Generate the multi-page gravity K1 stack control drawing."""
    from app.pz.wastewater_stack_drafting import (
        generate_wastewater_stack_control_pdf,
    )

    return generate_wastewater_stack_control_pdf(
        output_path,
        floors_above=floors_above,
        floor_height_m=floor_height_m,
        riser_id=riser_id,
        riser_dn_mm=riser_dn_mm,
        roof_kind=roof_kind,
        fixtures_by_floor=fixtures_by_floor,
        floor_slope_dn50=floor_slope_dn50,
        floor_slope_dn100=floor_slope_dn100,
        max_floors_per_sheet=max_floors_per_sheet,
        collapse_typical_floors=collapse_typical_floors,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        basement_collector_slope_per_mille=basement_collector_slope_per_mille,
        outlet_id=outlet_id,
        outlet_dn_mm=outlet_dn_mm,
    )


def generate_wastewater_stack_node_pdf_from_project(
    output_path: str,
    project: Project,
    *,
    riser_id: str = "К1-Ст1",
    floor_height_m: float,
    roof_kind: str,
    max_floors_per_sheet: int = 5,
    collapse_typical_floors: bool = True,
) -> str:
    """Generate one control stack entirely from confirmed project registries.

    Floor height and roof case remain explicit arguments because the current
    Project model has no exact per-floor elevations or roof accessibility.
    """
    from app.pz.wastewater_project_inputs import (
        resolve_wastewater_stack_project_inputs,
    )

    inputs = resolve_wastewater_stack_project_inputs(project, riser_id=riser_id)
    if not inputs.complete:
        detail = "; ".join(inputs.diagnostics) or ", ".join(
            inputs.missing_project_inputs
        )
        raise ValueError(
            "project data are insufficient for the K1 basement sheet: " + detail
        )
    return generate_wastewater_stack_node_pdf(
        output_path,
        floors_above=inputs.floors_above,
        floor_height_m=floor_height_m,
        riser_id=inputs.riser_id,
        riser_dn_mm=inputs.riser_dn_mm,
        roof_kind=roof_kind,
        fixtures_by_floor=inputs.fixtures_by_floor,
        floor_slope_dn50=inputs.slope_dn50,
        floor_slope_dn100=inputs.slope_dn100,
        max_floors_per_sheet=max_floors_per_sheet,
        collapse_typical_floors=collapse_typical_floors,
        basement_floor_elevation_m=inputs.basement.basement_floor_elevation_m,
        outlet_invert_elevation_m=inputs.basement.outlet_invert_elevation_m,
        basement_collector_slope_per_mille=(
            inputs.basement.collector_slope_per_mille
        ),
        outlet_id=inputs.basement.outlet_id,
        outlet_dn_mm=inputs.basement.outlet_dn_mm,
    )


def generate_wastewater_building_node_pdf_from_project(
    output_path: str,
    project: Project,
    *,
    floor_height_m: float,
    roof_kind: str,
) -> str:
    """Generate the combined registry-backed K1/K2 building schematic."""
    from app.pz.wastewater_building_drafting import (
        generate_wastewater_building_pdf_from_project,
    )

    return generate_wastewater_building_pdf_from_project(
        output_path,
        project,
        floor_height_m=floor_height_m,
        roof_kind=roof_kind,
    )

def generate_wastewater_basement_node_pdf(
    output_path: str,
    *,
    riser_id: str = "К1-Ст1",
    dn_mm: int = 100,
    first_floor_elevation_m: float = 0.0,
    basement_floor_elevation_m: float | None = None,
    outlet_invert_elevation_m: float | None = None,
    collector_slope_per_mille: float | None = None,
    outlet_id: str = "К1-1",
    outlet_dn_mm: int | None = None,
) -> str:
    """Generate the isolated reusable K1 basement and outlet module."""
    from app.pz.wastewater_basement_drafting import (
        generate_wastewater_basement_control_pdf,
    )

    return generate_wastewater_basement_control_pdf(
        output_path,
        riser_id=riser_id,
        dn_mm=dn_mm,
        first_floor_elevation_m=first_floor_elevation_m,
        basement_floor_elevation_m=basement_floor_elevation_m,
        outlet_invert_elevation_m=outlet_invert_elevation_m,
        collector_slope_per_mille=collector_slope_per_mille,
        outlet_id=outlet_id,
        outlet_dn_mm=outlet_dn_mm,
    )


def generate_wastewater_scheme_svg(
    project: Project,
    *,
    diagnostics: bool = False,
) -> str:
    """SVG листа А1 по подтверждённым элементам и участкам."""
    return generate_wastewater_scheme_result(
        project,
        diagnostics=diagnostics,
    ).svg


# ── РАСЧЁТ И ПОДБОР НАСОСНЫХ УСТАНОВОК (отдельное приложение) ────────────

def generate_pump_selection_html(project: Project) -> str:
    """HTML самостоятельного расчётного листа подбора насосов В1/В2.

    Лист ничего не пересчитывает: использует уже сформированные HeadCalc и
    PumpSystem, то есть те же результаты, что показаны в основной ПЗ.
    """
    from app.pz.fire_review_binding import validate_binding
    validate_binding(project)
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".РН"),
        sheet_title="Расчёт и подбор насосных установок",
    )
    head = project_governing_head(
        project, fallback_h_vod_m=cold_meter_loss(project.meters),
    )
    return env.get_template("pump_document.html").render(
        **_fire_station_document_context(project),
        project=project,
        doc=doc,
        head=head,
        v1=project.pumps,
        v2=project.fire_pumps,
        v1_chart=_pump_chart_for(project.pumps),
        v2_chart=_pump_chart_for(project.fire_pumps),
        head_paths=project.head_paths,
    )


def generate_pump_selection_pdf(project: Project, output_path: str) -> str:
    """PDF расчётного листа насосов (А4) для отдельной выдачи и приложения к ПЗ."""
    html_str = generate_pump_selection_html(project)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / "pump_document.css"),
            base_url=str(TEMPLATES_DIR)),
        CSS(filename=str(TEMPLATES_DIR / "equipment.css"),
            base_url=str(TEMPLATES_DIR)),
    ]
    from app.pz.text_document_frame import apply_frame
    body = HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(stylesheets=stylesheets)
    doc = replace(project.document,
                  cipher=_document_cipher(project.document.cipher or '', '.РН'),
                  sheet_title='Расчёт и подбор насосных установок')
    Path(output_path).write_bytes(apply_frame(body, doc))
    return output_path


# ── КОМИССИОННЫЙ ПАСПОРТ И НОРМАТИВНЫЙ КОНТРОЛЬ ────────────────────────

_COMMISSION_STATUS_LABELS = {
    "verified": "подтверждено",
    "specified": "принято",
    "stage_r": "стадия Р",
    "missing": "не хватает данных",
    "not_applicable": "не требуется",
    "pending_build": "после сборки",
    "manual_review": "ручная проверка",
    "fail": "не соответствует",
}


def generate_commission_control_html(project: Project, report=None) -> str:
    """Паспорт версии, матрица трассировки и протокол проверки стадии П."""
    env = _build_env()
    report = report or build_commission_report(project)
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".НК"),
        sheet_title="Паспорт и нормативный контроль",
        sheet_no="1",
        sheet_total="—",
    )
    body_html = env.get_template("commission_control_body.html").render(
        report=report,
        status_labels=_COMMISSION_STATUS_LABELS,
        digital_passport=project.digital_passport,
    )
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Паспорт проекта и нормативный контроль",
        body_html=body_html,
    )


def generate_commission_control_pdf(project: Project, output_path: str, report=None) -> str:
    """Сформировать самостоятельный комиссионный паспорт на листах А4."""
    html_str = generate_commission_control_html(project, report=report)
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".НК"),
                  sheet_title="Паспорт и нормативный контроль")
    return _write_text_pdf(html_str, output_path, doc, (*_CSS_FILES, "commission_control.css"))


def append_pdf(base_path: str, appendix_path: str) -> str:
    """Добавить приложение, сохранив закладки и атомарно заменив исходный PDF."""
    return merge_pdfs([base_path, appendix_path], str(base_path))


def merge_pdfs(source_paths: list[str], output_path: str, *,
               section_titles: list[str] | None = None) -> str:
    """Склеить документы с иерархией закладок и переназначением ссылок на страницы.

    add_page переносит только страницы, поэтому теряет оглавление. append
    импортирует outline и внутренние назначения с учётом нового смещения.
    Выход можно использовать как первый источник: замена только после записи.
    """
    import os
    import tempfile
    from pypdf import PdfReader, PdfWriter

    if not source_paths:
        raise ValueError("Для объединения PDF нужен хотя бы один документ")
    if section_titles is not None and len(section_titles) != len(source_paths):
        raise ValueError("Каждому PDF должно соответствовать название раздела")
    target = Path(output_path)
    tmp = None
    try:
        with PdfWriter() as writer:
            for index, source in enumerate(source_paths):
                reader = PdfReader(source)
                writer.append(reader, import_outline=True,
                              outline_item=section_titles[index] if section_titles else None)
                if index == 0 and reader.metadata:
                    writer.add_metadata({k: str(v) for k, v in reader.metadata.items() if v is not None})
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=f".{target.stem}-", suffix=".pdf", delete=False,
            ) as fh:
                tmp = Path(fh.name)
                writer.write(fh)
                fh.flush()
                os.fsync(fh.fileno())
        tmp.replace(target)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return output_path


# ── СПЕЦИФИКАЦИЯ (отдельный документ, шифр .С, форма 3) ────────────────────

def generate_spec_html(project: Project) -> str:
    """HTML спецификации оборудования, изделий и материалов (ГОСТ 21.110)."""
    env = _build_env()
    spec = build_water_specification(project)
    from app.pz.spec_pagination import render_specification_body
    body_html = render_specification_body(spec, env)
    cipher = project.document.cipher
    spec_doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".СО"),
        sheet_title="Спецификация оборудования, изделий и материалов",
    )
    return env.get_template("spec_document.html").render(doc=spec_doc, body_html=body_html)


def generate_spec_pdf(project: Project, output_path: str) -> str:
    """PDF спецификации. CSS: рамка + spec.css."""
    from app.pz.spec_pagination import write_specification_pdf
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".СО"),
                  sheet_title="Спецификация оборудования, изделий и материалов")
    return write_specification_pdf(generate_spec_html(project), output_path, doc)


def generate_wastewater_spec_html(project: Project) -> str:
    """HTML самостоятельной спецификации оборудования К1/К2/К3."""
    env = _build_env()
    spec = build_wastewater_specification(project)
    from app.pz.spec_pagination import render_specification_body
    body_html = render_specification_body(spec, env)
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    spec_doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".СО"),
        sheet_title="Спецификация оборудования, изделий и материалов К1/К2/К3",
    )
    return env.get_template("spec_document.html").render(
        doc=spec_doc,
        body_html=body_html,
    )


def generate_wastewater_spec_pdf(project: Project, output_path: str) -> str:
    """PDF самостоятельной спецификации К1/К2/К3 по ГОСТ 21.110."""
    from app.pz.spec_pagination import write_specification_pdf
    cipher = _wastewater_document_cipher(project.document.cipher or "")
    doc = replace(project.document, cipher=_document_cipher(cipher, ".СО"),
                  sheet_title="Спецификация оборудования, изделий и материалов К1/К2/К3")
    return write_specification_pdf(generate_wastewater_spec_html(project), output_path, doc)


# ── ПРИНЦИПИАЛЬНАЯ СХЕМА (разрез В1/Т3/Т4 А2; прежняя ветвь В1/В2 А1) ─────

# Физический размер листа А1 по ГОСТ 2.301 (альбомная): 841×594 мм.
# SVG схемы задан в пикселях (SCHEME_W×SCHEME_H) с сохранением этой пропорции;
# для PDF подменяем width/height на мм, чтобы MediaBox = А1 в натуральную
# величину (иначе cairosvg берёт 96 dpi и лист выходит ~742×524 мм — не по ГОСТ).
_A1_MM = (841, 594)


def generate_scheme_svg(project: Project, params: "SchemeParams | None" = None) -> str:
    """SVG: общий жилой разрез В1/Т3/Т4 А2 либо прежняя схема В1/В2 А1.

    Предупреждения раскладки выносок (если есть) не роняют генерацию —
    они доступны через generate_scheme_result().
    """
    return generate_scheme_result(project, params).svg


def generate_scheme_result(project: Project, params: "SchemeParams | None" = None) -> SchemeResult:
    """Полный результат схемы: .svg + .warnings (для логов/валидации пайплайна)."""
    from app.pz.water_residential_section import can_draw_residential_water_section, build_residential_water_section
    if params is None and can_draw_residential_water_section(project):
        return build_residential_water_section(project, profile="residential_full_bath")
    from app.pz.water_building_section import can_draw_water_section, build_water_section
    if params is None and can_draw_water_section(project):
        return build_water_section(project)
    result = build_scheme(project, params)
    if params is None and project.building.purpose.value == 'residential':
        result.warnings.append(
            'Сохранена прежняя компоновка воды: общий разрез В1/Т3/Т4 пока не охватывает '
            'все заданные условия (зоны/В2/полив/повторное использование/стадия).')
    return result


def _svg_to_a1_mm(svg: str) -> str:
    """Проставить физический размер А1 в мм вместо пиксельных width/height.

    viewBox остаётся в пикселях — внутренняя геометрия масштабируется cairosvg
    автоматически. Заменяется только первое вхождение (атрибуты корневого <svg>).
    """
    w_mm, h_mm = _A1_MM
    return svg.replace(
        f'width="{SCHEME_W}" height="{SCHEME_H}"',
        f'width="{w_mm}mm" height="{h_mm}mm"',
        1,
    )


def generate_scheme_pdf(project: Project, output_path: str,
                        params: "SchemeParams | None" = None, *,
                        scheme_result: SchemeResult | None = None) -> str:
    """Векторный PDF: А2 для общего разреза, А1 для прежней ветви В1/В2.

    Рендер SVG→PDF напрямую через cairosvg (не WeasyPrint): лист чисто
    векторный и уже собран целиком, включая рамку и штамп форма 3, — прямой
    векторный вывод сохраняет физические размеры линий и текста при печати.
    """
    import cairosvg  # опциональная зависимость вывода схемы

    # Use the exact reviewed SVG: do not choose/build a second drawing during export.
    if scheme_result is not None and params is not None:
        raise ValueError("Передайте готовую схему либо параметры, не оба варианта")
    result = scheme_result if scheme_result is not None else generate_scheme_result(project, params)
    svg = _svg_to_a1_mm(result.svg)
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path


def _generate_aux_scheme_pdf(svg: str, output_path: str) -> str:
    import cairosvg
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
    return output_path


def generate_metering_scheme_pdf(project: Project, output_path: str) -> str:
    from io import BytesIO
    from xml.etree import ElementTree
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.drafting_font import ensure_drafting_font_registered
    from app.pz.metering_detail import build_metering_detail_pages

    ensure_drafting_font_registered()
    writer = PdfWriter()
    previous_title = None
    for svg in build_metering_detail_pages(project):
        root = ElementTree.fromstring(svg)
        title_node = root.find("{http://www.w3.org/2000/svg}text")
        title = "".join(title_node.itertext()).strip() if title_node is not None else "Водомерный узел"
        page_index = len(writer.pages)
        rendered = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        writer.add_page(PdfReader(BytesIO(rendered)).pages[0])
        if title != previous_title:
            writer.add_outline_item(title, page_index)
            previous_title = title
    with open(output_path, "wb") as stream:
        writer.write(stream)
    return output_path


def generate_pump_zone_scheme_pdf(project: Project, output_path: str, *, include_building_section=True) -> str:
    from io import BytesIO
    import cairosvg
    from pypdf import PdfReader, PdfWriter
    from app.pz.water_station_drafting import build_pump_zone_scheme_pages

    writer = PdfWriter()
    for page, svg in enumerate(build_pump_zone_scheme_pages(project, include_building_section=include_building_section, include_review=True)):
        rendered = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        writer.add_page(PdfReader(BytesIO(rendered)).pages[0])
        from xml.etree import ElementTree as ET
        texts = [e.text for e in ET.fromstring(svg).iter() if e.tag.endswith('text') and e.text]
        writer.add_outline_item(texts[0] if texts else 'В1. Насосная и проверки', page)
    with open(output_path, "wb") as stream:
        writer.write(stream)
    return output_path


# ── ГИДРАВЛИЧЕСКИЙ РАСЧЁТ В2 (лист расчёта, ГОСТ 21.110) ────────────────────

def _conclusion_to_html(report) -> str:
    """Текст заключения (блок 5 отчёта) → HTML-абзацы."""
    from app.calc.fire_hydraulic_report import FireHydraulicReport  # noqa
    text = report._render_conclusion()
    # первая строка — заголовок ЗАКЛЮЧЕНИЕ, дальше абзацы
    lines = [l for l in text.split("\n")[1:] if l.strip()]
    return "".join(f"<p>{l}</p>" for l in lines)


def generate_hydraulic_report_html(project: Project, report) -> str:
    """HTML листа гидравлического расчёта В2 из готового FireHydraulicReport.

    report: FireHydraulicReport (сборка из результатов гидравлики + аудита).
    Генератор НЕ считает — только рендерит переданный отчёт.
    """
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".ГР"),
        sheet_title="Гидравлический расчёт В2",
    )
    return env.get_template("hydraulic_document.html").render(
        doc=doc, h=report.header, segments=report.segments,
        station_preliminary=project.fire_station_input is not None,
        fire_pumps=project.fire_pumps,
        dictating_paths=report.dictating_paths,
        conclusion_html=_conclusion_to_html(report),
    )


def generate_hydraulic_report_pdf(project: Project, report, output_path: str) -> str:
    """PDF листа гидравлического расчёта В2. CSS: hydraulic.css (А4 книжная)."""
    html_str = generate_hydraulic_report_html(project, report)
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".ГР"),
                  sheet_title="Гидравлический расчёт В2")
    return _write_text_pdf(html_str, output_path, doc, ("hydraulic.css", "equipment.css"))


# ── ЛИСТ ПРОВЕРКИ ЖИВУЧЕСТИ КОЛЬЦА В2 ───────────────────────────────────────

def generate_resilience_html(project: Project, resilience_report) -> str:
    """HTML листа живучести из готового RingResilienceReport (не считает)."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=_document_cipher(cipher, ".ЖВ"),
        sheet_title="Проверка живучести сети В2")
    return env.get_template("resilience_document.html").render(
        doc=doc, rep=resilience_report)


def generate_resilience_pdf(project: Project, resilience_report,
                            output_path: str) -> str:
    """PDF листа живучести (А4, рамка+штамп — колея гидролиста)."""
    html_str = generate_resilience_html(project, resilience_report)
    doc = replace(project.document, cipher=_document_cipher(project.document.cipher or "", ".ЖВ"),
                  sheet_title="Проверка живучести сети В2")
    return _write_text_pdf(html_str, output_path, doc, ("resilience.css",))


# ── ТЗ и ТУ (исходные документы проекта) ─────────────────────────────────────

def _tz_ctx(project, sd):
    """Общий контекст для листов ТЗ/ТУ."""
    from app.intake.request_dto import SourceDataRequest
    return dict(
        doc=project.document, b=project.building, building=project.building,
        fire=project.fire, src=project.source, zones=project.building.zones,
        sd=(sd or SourceDataRequest()))


def generate_tz_pdf(project, output_path, source_data=None):
    """PDF задания на проектирование В2 (А4, рамка+штамп)."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(project.document, cipher=_document_cipher(cipher, ".ТЗ"),
                  sheet_title="Задание на проектирование В2")
    ctx = _tz_ctx(project, source_data); ctx["doc"] = doc
    html_str = env.get_template("tz_document.html").render(**ctx)
    return _write_text_pdf(html_str, output_path, doc, ("tz.css",))


def generate_tu_pdf(project, output_path, source_data=None):
    """PDF листа исходных данных (ТУ на подключение) (А4, рамка+штамп)."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(project.document, cipher=_document_cipher(cipher, ".ИД"),
                  sheet_title="Исходные данные (ТУ на подключение)")
    ctx = _tz_ctx(project, source_data); ctx["doc"] = doc
    html_str = env.get_template("tu_document.html").render(**ctx)
    return _write_text_pdf(html_str, output_path, doc, ("tz.css",))
