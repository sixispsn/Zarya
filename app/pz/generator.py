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

from app.pz.project import BuildingPurpose, Project
from app.pz.rules import calc_required_head, check_tu_limits, decide_fire_network


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_env() -> Environment:
    """Создать Jinja2-окружение, читающее шаблоны из папки templates."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Число в русской записи: num(2) -> "5,76"
    env.filters["num"] = lambda v, p=2: f"{v:.{p}f}".replace(".", ",")
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


def generate_pz_html(project: Project) -> str:
    """Собрать HTML пояснительной записки (без CSS — для отладки/предпросмотра)."""
    env = _build_env()

    subitems_tpl = env.get_template(_subitems_template_name(project.building.purpose))
    fire_net = decide_fire_network(project.fire, project.materials)
    head = calc_required_head(project.source)
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
    frame_css = CSS(
        filename=str(TEMPLATES_DIR / "frame.css"),
        base_url=str(TEMPLATES_DIR),
    )
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(
        output_path, stylesheets=[frame_css]
    )
    return output_path
