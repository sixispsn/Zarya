"""Review attachment, deliberately not a GOST purchasing specification."""
from collections import defaultdict
from math import fsum
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from app.pz.drafting_font import DRAFTING_FONT_PATH
from app.pz.network_takeoff import NetworkTakeoff
from app.pz.study_document_frame import build_study_text_pdf


def generate_network_takeoff_pdf(output: str, network: NetworkTakeoff) -> str:
    network.validate()
    pdfmetrics.registerFont(TTFont("TakeoffGOST", str(DRAFTING_FONT_PATH)))
    body = ParagraphStyle("body", fontName="TakeoffGOST", fontSize=12.1, leading=15, spaceAfter=5)
    heading = ParagraphStyle("heading", parent=body, fontSize=19, leading=23, spaceAfter=9)
    story = []

    def para(text, style=body):
        safe = str(text).replace("ü", "u").replace("—", "-").replace("–", "-")
        return Paragraph(escape(safe), style)

    def text(value, style=body):
        story.append(para(value, style))

    def fmt(value):
        return f"{value:.3f}".replace(".", ",")

    def table(rows, widths):
        result = Table([[para(cell) for cell in row] for row in rows],
                       colWidths=[w*mm for w in widths], repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#666666")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend((result, Spacer(1, 4*mm)))

    text("Полная сеть дома. От рисунка к проверяемым количествам", heading)
    for note in network.limitations[:4]:
        text(note)
    text("1. Протяжённость трасс по выбранному сортаменту", heading)
    rows = network.rows()
    table([("Система", "Серия трубы", "Dн x стенка; Dвн, мм", "Известно, м", "Не задано", "Основание")]+[
        (r.system, r.name, r.size, fmt(r.quantity),
         f"{len(r.unknown_ids)} участков" if r.unknown_ids else "Нет",
         "Предложенные трассы" if r.status == "proposed" else "Подтверждённые трассы")
        for r in rows if r.unit == "м"
    ], [22, 75, 75, 35, 40, 138])
    text("Это не чистая длина трубы: размеры фасонных частей и глубины раструбов ещё не вычтены. "
         "Гидравлические диаметры взяты из выбранного сортамента, а не приравнены к DN.")
    text("2. Откуда взялись метры", heading)
    basis_counts = defaultdict(int)
    for route in network.routes:
        basis_counts[route.basis.source] += 1
    table([("Исходное условие / источник", "Участков")]+[
        (source, str(count)) for source, count in basis_counts.items()
    ], [352, 33])
    text("Полный список ID, начало/конец каждого участка, его длина, материал и источник сохранены в JSON рядом с PDF.")

    story.append(PageBreak())
    text("3. Приборы и элементы монтажных узлов", heading)
    text("Считаются все физические экземпляры, включая не показанные на характерном разрезе. "
         "Количество в штуках - целое. Артикулы и комплектация изделий не подтверждены.")
    table([("Система", "Наименование", "Размер / назначение", "Ед.", "Кол.", "Источник экземпляров")]+[
        (r.system, r.name, r.size, r.unit, str(r.quantity),
         "Начальный свободный конец" if r.kind == "wye_45_cleanout" else
         "Открытый проходной узел" if r.kind == "wye_45_through" else
         f"{len(r.member_ids)} ID в полной модели")
        for r in rows if r.unit == "шт"
    ], [22, 104, 102, 15, 20, 122])

    story.append(PageBreak())
    text("4. Контроль полноты и оставшиеся границы", heading)
    points = {p.point_id: p for p in network.points}
    table([("Проверка", "Результат")]+[
        ("Приборы / водосточные воронки", f"{sum(p.role == 'source' and p.system == 'K1' for p in network.points)} / "
                                           f"{sum(p.role == 'source' and p.system == 'K2' for p in network.points)}"),
        ("Участки / экземпляры компонентов", f"{len(network.routes)} / {len(network.components)}"),
        ("Каждый источник доходит до своего выпуска", "Проверено по всем ветвям; циклов и смешения К1/К2 нет"),
        ("Заглушки на проходных узлах", "Не допускаются проверкой; заглушки только у сервисных концов"),
        ("Сокращение рисунка меняет объёмы?", "Нет. Ведомость строится из сети, без чтения SVG и списка видимых квартир"),
        ("Можно заказывать материалы?", "Нет. Это контроль осевых протяжённостей и состава узлов"),
    ], [125, 260])
    text("Контрольные суммы по частям сети", heading)
    grouped = defaultdict(list)
    for route in network.routes:
        system = points[route.start].system
        group = route.route_id.split(":")[0] if route.role in {"apartment_collector", "fixture_connection"} else {
            "riser": "Стояки", "ventilation": "Вытяжные части", "basement_collector": "Коллектор подвала",
            "outlet_drop": "Опуск к выпуску", "building_outlet": "До наружной грани стены",
        }.get(route.role, route.role)
        grouped[(system, group)].append(route)
    table([("Система", "Часть сети", "Участков", "Известная протяжённость, м")]+[
        (system, group, str(len(routes)), fmt(fsum(r.length_m for r in routes if r.length_m is not None))+
         (" + незаданные участки" if any(r.length_m is None for r in routes) else ""))
        for (system, group), routes in grouped.items()
    ], [25, 170, 40, 150])
    for note in network.limitations[4:]:
        text(note)
    text("Контроль состава: ГОСТ Р 21.620-2023, пп. 5.2.2.1-5.2.2.4. "
         "Эта ведомость сопровождает общую принципиальную схему К1/К2; полный комплект ИОС3 и нормативную СО не заменяет.")
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_study_text_pdf(story, title="Проверка количеств по полной сети К1/К2",
        sheet_title="Проверка объёмов К1, К2", cipher="УЧЕБНЫЙ-К1К2.ВО", layout="a3_text",
        detail=f"Версия сети: {network.fingerprint[:20]} | К1 и К2 раздельно | Без автоматического запаса"))
    return str(path)
