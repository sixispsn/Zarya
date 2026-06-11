"""
Генератор пояснительной записки в PDF.

Берёт модель Project, рендерит Jinja2-шаблоны подпунктов,
вставляет в шаблон листа со штампом, превращает в PDF через WeasyPrint.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.pz.project import BuildingPurpose, Project


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _build_env() -> Environment:
    """Создать Jinja2-окружение, читающее шаблоны из папки templates."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _subitems_template_name(purpose: BuildingPurpose) -> str:
    """Выбрать файл шаблона подпунктов по типу объекта."""
    mapping = {
        BuildingPurpose.PUBLIC: "subitems_public.html",
        # жилой и производственный добавим позже
    }
    name = mapping.get(purpose)
    if name is None:
        raise ValueError(
            f"Шаблон для типа объекта '{purpose.value}' пока не реализован. "
            "На данном этапе доступен только общественный (public)."
        )
    return name


def generate_pz_html(project: Project) -> str:
    """Собрать полный HTML пояснительной записки (для отладки/предпросмотра)."""
    env = _build_env()

    # 1. Рендерим текст подпунктов
    subitems_tpl = env.get_template(_subitems_template_name(project.building.purpose))
    body_html = subitems_tpl.render(
        doc=project.document,
        building=project.building,
        source=project.source,
        materials=project.materials,
        flows=project.flows,
        fire=project.fire,
        meters=project.meters,
        pumps=project.pumps,
    )

    # 2. Читаем CSS рамки
    frame_css = (TEMPLATES_DIR / "frame.css").read_text(encoding="utf-8")

    # 3. Вставляем в шаблон листа со штампом
    doc_tpl = env.get_template("document.html")
    full_html = doc_tpl.render(
        frame_css=frame_css,
        doc=project.document,
        body_html=body_html,
    )
    return full_html


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
    HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf(output_path)
    return output_path