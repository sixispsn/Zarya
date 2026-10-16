"""Review sheet: raster evidence with proposed plan-space network bindings.

No geometric calibration or production IOS3 sheet is claimed. Source images
are clipped on the PDF canvas, never altered or interpreted as vector AR.
"""
from __future__ import annotations

from math import hypot
from pathlib import Path

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]

from app.architecture.residential_plan_study import Box, PlanStudy
from app.pz.drafting_font import DRAFTING_FONT_PATH
from app.pz.leader_layout import LeaderBounds, LeaderLayoutEngine, LeaderRequest

INK = colors.HexColor("#192330")
PIPE = colors.HexColor("#c04420")
WET = colors.HexColor("#116b9b")
GRAY = colors.HexColor("#677484")
FONT = "PlanStudyGOST"


class StudySheet:
    """Top-left paper-mm helpers; diagram coordinates are normalized fractions."""
    def __init__(self, path: Path):
        pdfmetrics.registerFont(TTFont(FONT, str(DRAFTING_FONT_PATH)))
        self.canvas = Canvas(str(path), pagesize=(594*mm, 420*mm), pageCompression=1)
        self.canvas.setTitle("ЗАРЯ. Второй жилой пример: мокрые зоны и условный подвал")
        self.canvas.setAuthor("ЗАРЯ")

    def line(self, a, b, color=INK, width=.25, dash=None):
        c = self.canvas
        c.saveState()
        c.setStrokeColor(color)
        c.setLineWidth(width*mm)
        if dash:
            c.setDash(*[v*mm for v in dash])
        c.line(a[0]*mm, (420-a[1])*mm, b[0]*mm, (420-b[1])*mm)
        c.restoreState()

    def text(self, x, y, value, height=3.5, color=INK, align="left"):
        c = self.canvas
        c.setFillColor(color)
        c.setFont(FONT, height*mm/.823)
        draw = {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align]
        draw(x*mm, (420-y)*mm, value)

    def paragraph(self, x, y, value, width, height=3.5):
        line = ""
        for word in value.split():
            candidate = (line+" "+word).strip()
            if line and pdfmetrics.stringWidth(candidate, FONT, height/.823) > width:
                self.text(x, y, line, height)
                y += height*1.6
                line = word
            else:
                line = candidate
        self.text(x, y, line, height)
        return y+height*2.2

    def rect(self, box, color=INK, fill=None, alpha=1, width=.25):
        x1, y1, x2, y2 = box
        c = self.canvas
        c.saveState()
        c.setLineWidth(width*mm)
        c.setStrokeColor(color)
        if fill:
            c.setFillColor(fill)
            c.setFillAlpha(alpha)
        c.rect(x1*mm, (420-y2)*mm, (x2-x1)*mm, (y2-y1)*mm, stroke=1, fill=bool(fill))
        c.restoreState()

    def circle(self, p, radius=2.4):
        c = self.canvas
        c.setLineWidth(.6*mm)
        c.setStrokeColor(PIPE)
        c.setFillColor(colors.white)
        c.circle(p[0]*mm, (420-p[1])*mm, radius*mm, stroke=1, fill=1)

    def arrow(self, tip, vector, length=2.):
        norm = hypot(*vector)
        ux, uy = vector[0]/norm, vector[1]/norm
        bx, by = tip[0]-length*ux, tip[1]-length*uy
        half = length/3
        c = self.canvas
        p = c.beginPath()
        p.moveTo(tip[0]*mm, (420-tip[1])*mm)
        for x, y in ((bx-uy*half, by+ux*half), (bx+uy*half, by-ux*half)):
            p.lineTo(x*mm, (420-y)*mm)
        p.close()
        c.setFillColor(PIPE)
        c.drawPath(p, stroke=0, fill=1)

    def source_crop(self, image: ImageReader, crop: Box, panel: Box):
        c = self.canvas
        left, top, right, bottom = crop
        x, y, x2, y2 = panel
        iw, ih = image.getSize()
        if right > iw or bottom > ih:
            raise ValueError("source image resolution changed; redraw/confirm reference anchors")
        sx, sy = (x2-x)/(right-left), (y2-y)/(bottom-top)
        c.saveState()
        clip = c.beginPath()
        clip.rect(x*mm, (420-y2)*mm, (x2-x)*mm, (y2-y)*mm)
        c.clipPath(clip, stroke=0)
        c.setFillAlpha(.42)
        c.drawImage(image, (x-left*sx)*mm, (420-y-(ih-top)*sy)*mm,
                    width=iw*sx*mm, height=ih*sy*mm)
        c.restoreState()

    def leader(self, target, title, bounds, *, detail="предложение", side=1, offsets=(24., 30., 36., 40.)):
        """Reuse the measured callout engine instead of another layout policy."""
        request = LeaderRequest(title, title, target, title, detail, preferred_side=side, preferred_vertical=1)
        placement = LeaderLayoutEngine(bounds=LeaderBounds(*bounds), units_per_mm=1,
                                       vertical_offsets_mm=offsets).place(request)
        self.rect(placement.text_box, color=colors.white, fill=colors.white)
        self.line(target, placement.knee, color=PIPE)
        self.line(placement.knee, placement.shelf_outer, color=PIPE)
        self.arrow(target, (target[0]-placement.knee[0], target[1]-placement.knee[1]), length=2.8)
        self.text(placement.title_xy[0], placement.title_xy[1], title, color=PIPE)
        self.text(placement.detail_xy[0], placement.detail_xy[1], detail, color=PIPE)


def generate_plan_study_pdf(output: Path, study: PlanStudy, source: Path) -> str:
    study.validate()
    if source.name != study.source_image:
        raise ValueError("wrong plan reference")
    image = ImageReader(str(source))
    if image.getSize() != (1500, 1123):
        raise ValueError("reference anchors belong to the supplied 1500x1123 image")
    output.parent.mkdir(parents=True, exist_ok=True)
    s = StudySheet(output)
    s.rect((20, 5, 589, 415), width=.6)
    s.text(25, 19, "Второй жилой пример. Привязка мокрых зон и подвальной К1", height=5)
    s.text(25, 30, "Шаг 1: разметка исходного листа и предложение трасс. Не расчётная аксонометрия и не готовый ИОС3.")
    s.line((449, 38), (449, 387), color=GRAY)
    floor_panel = (40., 57., 430., 194.)
    basement_panel = (40., 239., 430., 368.)

    def xy(point, panel):
        return panel[0]+point[0]*(panel[2]-panel[0]), panel[1]+point[1]*(panel[3]-panel[1])

    def rectangle(box, panel):
        return (*xy(box[:2], panel), *xy(box[2:], panel))

    s.text(25, 46, "01. Первый / типовой этаж: предполагаемые мокрые группы и стояки")
    s.source_crop(image, study.floor_crop_px, floor_panel)
    for group in study.groups:
        for box in (group.kitchen_box, group.sanitary_box):
            s.rect(rectangle(box, floor_panel), color=WET, fill=WET, alpha=.11, width=.4)
        for box, label in ((group.kitchen_box, "К"), (group.sanitary_box, "СУ")):
            xx, yy = xy((box[0]+.008, box[1]+.04), floor_panel)
            s.text(xx, yy, label, color=WET)
        p = xy(group.position, floor_panel)
        s.circle(p)
        s.leader(p, group.stack.replace("K", "К"), (p[0]-40, 194, p[0]+40, 215), detail="стояк К1", offsets=(40., 43.))
    for i, box in enumerate(study.stairs_boxes, 1):
        s.rect(rectangle(box, floor_panel), color=GRAY, fill=GRAY, alpha=.10)
        p = xy(((box[0]+box[2])/2, box[1]-.025), floor_panel)
        s.text(p[0], p[1], f"ЛК-{i}", color=GRAY, align="center")
    s.text(25, 218, "Положение стояков перенесено на подвал по общему условному контуру; это не размерная привязка.", height=3)
    for group in study.groups:
        xx = xy(group.position, floor_panel)[0]
        s.line((xx, 224), (xx, 234), color=GRAY, dash=(1, 1))
    s.text(25, 232, "02. Условный подвал по фрагменту «План полов»: два независимых направления сбора")
    s.source_crop(image, study.basement_crop_px, basement_panel)
    for route in study.routes:
        cap = xy(study.cap(route), basement_panel)
        outlet = xy((route.outlet_x, route.main_y), basement_panel)
        # One continuous pass-through axis: caps ONLY at the first free end.
        s.line(cap, outlet, color=PIPE, width=.8)
        for dx in (0, -route.direction*1.1):
            s.line((cap[0]+dx, cap[1]-2.3), (cap[0]+dx, cap[1]+2.3), color=PIPE, width=.6)
        s.text(cap[0], cap[1]-6, "Пр.", align="center", color=PIPE)
        for stack in route.ordered_stacks:
            group = study.group(stack)
            p = xy(group.position, basement_panel)
            junction = xy(study.join(route, stack), basement_panel)
            # Matching horizontal/vertical paper offsets make the merge 45°.
            elbow = (p[0], junction[1]+abs(p[0]-junction[0]))
            s.line(p, elbow, color=PIPE, width=.8)
            s.line(elbow, junction, color=PIPE, width=.8)
            s.arrow(junction, (junction[0]-elbow[0], junction[1]-elbow[1]), length=1.6)
            s.circle(p)
            s.text(p[0], p[1]+7, stack.replace("K", "К"), color=PIPE, align="center")
        first = xy(study.join(route, route.ordered_stacks[0]), basement_panel)
        last = xy(study.join(route, route.ordered_stacks[-1]), basement_panel)
        centre = ((first[0]+last[0])/2, first[1])
        s.rect((centre[0]-12, centre[1]-3, centre[0]+12, centre[1]+3), color=colors.white, fill=colors.white)
        s.text(centre[0], centre[1]+1, route.route_id.replace("K", "К").replace("M", "М"), color=PIPE, align="center")
        s.arrow((centre[0]+route.direction*22, centre[1]), (route.direction, 0))
        s.leader(outlet, "Выпуск "+route.outlet[-1],
                 (25, outlet[1]+15, 100, outlet[1]+45) if route.direction < 0
                 else (366, outlet[1]+15, 445, outlet[1]+45), side=-route.direction)
    s.text(25, 382, "Стрелки - направление связей. Диаметры, уклоны, отметки и длины не назначены: исходных данных недостаточно.", height=3.5)

    x, y = 458., 46.
    s.text(x, y, "Что предложено", height=4)
    y = s.paragraph(x, y+9, f"Секций: {len({g.section for g in study.groups})}; мокрых групп на этаже: {len(study.groups)}. "
                    f"Повторение на {len(study.floors)} этажах даёт предварительно {len(study.groups)*len(study.floors)} квартир.", 120)
    y = s.paragraph(x, y, "В каждой группе кухня и санузел подключаются к одному стояку К1. Место стояка - предложение, не считанная шахта АР.", 120)
    y = s.paragraph(x, y, "Секция 1: К1-2 и К1-1 - в выпуск 1. Секция 2: К1-3 и К1-4 - в выпуск 2. Объединение секций не задано.", 120)
    y += 9
    s.text(x, y, "Как читать разметку", height=4)
    y = s.paragraph(x, y+9, "Серое - исходный рисунок. Голубое - предполагаемые кухни (К) и санузлы (СУ). ЛК - лестничная клетка.", 120)
    y = s.paragraph(x, y, "Оранжевое - предложенные стояки и связи К1. Кружок - ось стояка на плане, не отдельное УГО оборудования.", 120)
    y = s.paragraph(x, y, "Пр. - соосный заглушённый свободный конец. На следующих присоединениях магистраль остаётся проходной. Фасонина раскрывается на разрезе.", 120)
    y += 9
    s.text(x, y, "Границы этого шага", height=4)
    y = s.paragraph(x, y+9, "Подвал условно принят по «Плану полов» с разрешения пользователя. Цифры типов полов на подложке игнорируются.", 120)
    y = s.paragraph(x, y, "Балок, высот, проходок и доступа пока нет. Прокладка через перегородки, интервалы обслуживания и самотёк требуют проверки.", 120)
    y = s.paragraph(x, y, "К2 не перенесена из первого дома: кровля выглядит скатной, способ водоотвода нужно выбрать отдельно.", 120)
    y = s.paragraph(x, y, f"Граф связности: {len(study.paths())} групповых источников доходят до своих выпусков. Это не гидравлический расчёт.", 120)
    if y > 391:
        raise ValueError("review notes do not fit; do not shrink labels")
    s.line((20, 395), (589, 395))
    s.line((544, 395), (544, 415))
    s.text(25, 403, "ЗАРЯ | Второй жилой пример | Разметка для согласования")
    s.text(25, 410, "Источник: 1677505735_list-1.jpg. Интерпретация вручную; не автоматическое распознавание АР.", height=3)
    s.text(552, 407, "Лист 1")
    s.canvas.showPage()
    s.canvas.save()
    return str(output)
