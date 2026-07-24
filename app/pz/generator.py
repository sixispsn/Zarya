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

from app.pz.project import BuildingPurpose, Project
from app.pz.rules import calc_required_head, check_tu_limits, decide_fire_network
from app.pz.pump_chart import PumpChart, render_pump_chart_svg
from app.pz.spec import build_specification, format_spec_qty
from app.pz.scheme import build_scheme, SchemeParams, SchemeResult, W as SCHEME_W, H as SCHEME_H


TEMPLATES_DIR = Path(__file__).parent / "templates"

# CSS-файлы ПЗ (порядок важен: рамка -> таблицы). Все лежат в templates/.
_CSS_FILES = ["frame.css", "balance.css", "equipment.css"]


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
            "На данном этапе доступен только общественный (public)."
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
    return render_pump_chart_svg(PumpChart(
        curve=p.curve,
        h_stat=p.h_stat,
        k_sys=p.k_sys,
        wp=((p.wp_q, p.wp_h) if p.wp_q else None),
        q_opt=p.q_opt,
        title=p.model,
    ))


def _pump_chart_svg(project: Project) -> str:
    return _pump_chart_for(project.pumps)


def generate_pz_html(project: Project) -> str:
    """Собрать HTML пояснительной записки (без CSS — для отладки/предпросмотра)."""
    env = _build_env()

    subitems_tpl = env.get_template(_subitems_template_name(project.building.purpose))
    fire_net = decide_fire_network(project.fire, project.materials)
    head = calc_required_head(project.source, h_vod_m=cold_meter_loss(project.meters))
    tu_check = check_tu_limits(project.flows, project.source)
    body_html = subitems_tpl.render(
        doc=project.document,
        building=project.building,
        source=project.source,
        materials=project.materials,
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
        v1_stage_p=project.v1_stage_p_result,
    )

    doc_tpl = env.get_template("document.html")
    return doc_tpl.render(doc=project.document, body_html=body_html)


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
        for name in _CSS_FILES
    ]
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets
    )
    return output_path


def generate_balance_html(project: Project) -> str:
    """Отдельный лист формы 2 приложения А ГОСТ Р 21.619-2023."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=(cipher if cipher.endswith(".БВ") else cipher + ".БВ"),
        sheet_title="Баланс водопотребления и водоотведения",
        sheet_no="1",
        sheet_total="1",
    )
    return env.get_template("balance_document.html").render(
        doc=doc,
        balance=project.balance,
    )


def generate_balance_pdf(project: Project, output_path: str) -> str:
    """Сформировать нормативный баланс на листе А3 альбомной ориентации."""
    html_str = generate_balance_html(project)
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path,
        stylesheets=[CSS(
            filename=str(TEMPLATES_DIR / "balance_document.css"),
            base_url=str(TEMPLATES_DIR),
        )],
    )
    return output_path


# ── РАСЧЁТНЫЙ ЛИСТ В1 / Т3 / К1 (отдельное приложение) ──────────────────

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
        cipher=(cipher if cipher.endswith(".РВ1") else cipher + ".РВ1"),
        sheet_title="Расчёты систем В1, Т3 и К1",
        sheet_no="1",
        sheet_total="—",
    )
    head = calc_required_head(
        project.source,
        h_vod_m=cold_meter_loss(project.meters),
    )
    body_html = env.get_template("v1_calculation_body.html").render(
        balance=project.balance,
        flows=project.flows,
        meters=project.meters,
        pumps=project.pumps,
        head=head,
        v1_stage_p=project.v1_stage_p_result,
        v1_hydraulics=project.v1_hydraulic_result,
    )
    return env.get_template("document.html").render(
        doc=doc,
        document_title="Расчётные обоснования систем В1, Т3 и К1",
        body_html=body_html,
    )


def generate_v1_calculation_pdf(project: Project, output_path: str) -> str:
    """Сформировать самостоятельный PDF расчётов В1 / Т3 / К1 на листах А4."""
    html_str = generate_v1_calculation_html(project)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in (*_CSS_FILES, "v1_calculation.css")
    ]
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets,
    )
    return output_path


# ── РАСЧЁТ И ПОДБОР НАСОСНЫХ УСТАНОВОК (отдельное приложение) ────────────

def generate_pump_selection_html(project: Project) -> str:
    """HTML самостоятельного расчётного листа подбора насосов В1/В2.

    Лист ничего не пересчитывает: использует уже сформированные HeadCalc и
    PumpSystem, то есть те же результаты, что показаны в основной ПЗ.
    """
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=(cipher if cipher.endswith(".РН") else cipher + ".РН"),
        sheet_title="Расчёт и подбор насосных установок",
    )
    head = calc_required_head(
        project.source,
        h_vod_m=cold_meter_loss(project.meters),
    )
    return env.get_template("pump_document.html").render(
        doc=doc,
        head=head,
        v1=project.pumps,
        v2=project.fire_pumps,
        v1_chart=_pump_chart_for(project.pumps),
        v2_chart=_pump_chart_for(project.fire_pumps),
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
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets,
    )
    return output_path


def append_pdf(base_path: str, appendix_path: str) -> str:
    """Добавить приложение в конец PDF атомарной заменой исходного файла."""
    from pypdf import PdfReader, PdfWriter

    base = Path(base_path)
    tmp = base.with_name(base.stem + ".with-appendix.pdf")
    writer = PdfWriter()
    for source in (base_path, appendix_path):
        for page in PdfReader(source).pages:
            writer.add_page(page)
    with tmp.open("wb") as fh:
        writer.write(fh)
    tmp.replace(base)
    return str(base)


# ── СПЕЦИФИКАЦИЯ (отдельный документ, шифр .С, форма 3) ────────────────────

def generate_spec_html(project: Project) -> str:
    """HTML спецификации оборудования, изделий и материалов (ГОСТ 21.110)."""
    env = _build_env()
    spec = build_specification(project)
    body_html = env.get_template("spec_table.html").render(spec=spec)
    cipher = project.document.cipher
    spec_doc = replace(
        project.document,
        cipher=(cipher if cipher.endswith(".СО") else cipher + ".СО"),
        sheet_title="Спецификация оборудования, изделий и материалов",
    )
    return env.get_template("spec_document.html").render(doc=spec_doc, body_html=body_html)


def generate_spec_pdf(project: Project, output_path: str) -> str:
    """PDF спецификации. CSS: рамка + spec.css."""
    html_str = generate_spec_html(project)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / name), base_url=str(TEMPLATES_DIR))
        for name in ("spec_frame.css", "spec.css")
    ]
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets
    )
    return output_path


# ── ПРИНЦИПИАЛЬНАЯ СХЕМА В1/В2 (отдельный лист А1, штамп форма 3) ───────────

# Физический размер листа А1 по ГОСТ 2.301 (альбомная): 841×594 мм.
# SVG схемы задан в пикселях (SCHEME_W×SCHEME_H) с сохранением этой пропорции;
# для PDF подменяем width/height на мм, чтобы MediaBox = А1 в натуральную
# величину (иначе cairosvg берёт 96 dpi и лист выходит ~742×524 мм — не по ГОСТ).
_A1_MM = (841, 594)


def generate_scheme_svg(project: Project, params: "SchemeParams | None" = None) -> str:
    """SVG принципиальной схемы систем В1, В2 (лист А1 со штампом форма 3).

    Предупреждения раскладки выносок (если есть) не роняют генерацию —
    они доступны через generate_scheme_result().
    """
    return build_scheme(project, params).svg


def generate_scheme_result(project: Project, params: "SchemeParams | None" = None) -> SchemeResult:
    """Полный результат схемы: .svg + .warnings (для логов/валидации пайплайна)."""
    return build_scheme(project, params)


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
                        params: "SchemeParams | None" = None) -> str:
    """PDF принципиальной схемы В1/В2, лист А1 в натуральную величину.

    Рендер SVG→PDF напрямую через cairosvg (не WeasyPrint): лист чисто
    векторный и уже собран целиком, включая рамку и штамп форма 3, — прямой
    векторный вывод сохраняет качество линий и текста при печати А1.
    """
    import cairosvg  # опциональная зависимость вывода схемы

    svg = _svg_to_a1_mm(generate_scheme_svg(project, params))
    cairosvg.svg2pdf(bytestring=svg.encode("utf-8"), write_to=output_path)
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
        cipher=(cipher if cipher.endswith(".ГР") else cipher + ".ГР"),
        sheet_title="Гидравлический расчёт В2",
    )
    return env.get_template("hydraulic_document.html").render(
        doc=doc, h=report.header, segments=report.segments,
        fire_pumps=project.fire_pumps,
        dictating_paths=report.dictating_paths,
        conclusion_html=_conclusion_to_html(report),
    )


def generate_hydraulic_report_pdf(project: Project, report, output_path: str) -> str:
    """PDF листа гидравлического расчёта В2. CSS: hydraulic.css (А4 книжная)."""
    html_str = generate_hydraulic_report_html(project, report)
    stylesheets = [
        CSS(filename=str(TEMPLATES_DIR / "hydraulic.css"),
            base_url=str(TEMPLATES_DIR)),
        CSS(filename=str(TEMPLATES_DIR / "equipment.css"),
            base_url=str(TEMPLATES_DIR)),
    ]
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets)
    return output_path


# ── ЛИСТ ПРОВЕРКИ ЖИВУЧЕСТИ КОЛЬЦА В2 ───────────────────────────────────────

def generate_resilience_html(project: Project, resilience_report) -> str:
    """HTML листа живучести из готового RingResilienceReport (не считает)."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(
        project.document,
        cipher=(cipher if cipher.endswith(".ЖВ") else cipher + ".ЖВ"),
        sheet_title="Проверка живучести сети В2")
    return env.get_template("resilience_document.html").render(
        doc=doc, rep=resilience_report)


def generate_resilience_pdf(project: Project, resilience_report,
                            output_path: str) -> str:
    """PDF листа живучести (А4, рамка+штамп — колея гидролиста)."""
    html_str = generate_resilience_html(project, resilience_report)
    stylesheets = [CSS(filename=str(TEMPLATES_DIR / "resilience.css"),
                       base_url=str(TEMPLATES_DIR))]
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=stylesheets)
    return output_path


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
    doc = replace(project.document,
                  cipher=(cipher if cipher.endswith(".ТЗ") else cipher + ".ТЗ"))
    ctx = _tz_ctx(project, source_data); ctx["doc"] = doc
    html_str = env.get_template("tz_document.html").render(**ctx)
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=[CSS(filename=str(TEMPLATES_DIR / "tz.css"),
                                      base_url=str(TEMPLATES_DIR))])
    return output_path


def generate_tu_pdf(project, output_path, source_data=None):
    """PDF листа исходных данных (ТУ на подключение) (А4, рамка+штамп)."""
    env = _build_env()
    cipher = project.document.cipher or ""
    doc = replace(project.document,
                  cipher=(cipher if cipher.endswith(".ИД") else cipher + ".ИД"))
    ctx = _tz_ctx(project, source_data); ctx["doc"] = doc
    html_str = env.get_template("tu_document.html").render(**ctx)
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=[CSS(filename=str(TEMPLATES_DIR / "tz.css"),
                                      base_url=str(TEMPLATES_DIR))])
    return output_path
