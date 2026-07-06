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
from app.pz.spec import build_specification
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


def _cold_meter_loss(meters) -> float | None:
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


def _pump_chart_svg(project: Project) -> str:
    """SVG характеристики Q-H принятого насоса (пусто, если насос не нужен)."""
    p = project.pumps
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


def generate_pz_html(project: Project) -> str:
    """Собрать HTML пояснительной записки (без CSS — для отладки/предпросмотра)."""
    env = _build_env()

    subitems_tpl = env.get_template(_subitems_template_name(project.building.purpose))
    fire_net = decide_fire_network(project.fire, project.materials)
    head = calc_required_head(project.source, h_vod_m=_cold_meter_loss(project.meters))
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
        balance=project.balance,
        pump_chart_svg=_pump_chart_svg(project),
        fire_net=fire_net,
        head=head,
        tu_check=tu_check,
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
