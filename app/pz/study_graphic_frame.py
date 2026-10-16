"""Paper-only A2 framing for the bounded educational section views."""
from xml.etree import ElementTree as ET

from app.pz.graphic_document_frame import drawing_frame_svg
from app.pz.leader_layout import _text_width
from app.pz.study_document_frame import _StudyDocumentInfo
from app.pz.wastewater_basement_profile import STYLE, _text


def study_section_frame(*, sheet_total: int = 1, sheet_no: int = 1,
                        system_label: str = "К1, К2", cipher: str = "УЧЕБНЫЙ-К1К2.СХ") -> str:
    return drawing_frame_svg(_StudyDocumentInfo(
        cipher=cipher, object_name="Учебная модель. Не для выпуска",
        object_part="Исходные решения требуют подтверждения", organization="ЗАРЯ"),
        width_mm=594, height_mm=420, title="Принципиальная схема",
        system_label=system_label, sheet_no=sheet_no, sheet_total=sheet_total)


def study_notes_svg(notes, *, x: float, y: float, width: float, bottom: float,
                    height: float = 2.5, pitch: float = 7) -> str:
    """Measure and wrap complete notes; do not clip or reduce the chosen height."""
    size = STYLE.font_size(height, 1)
    result = ['<g data-study-notes="true">']
    for note in notes:
        line = ""
        for word in note.split():
            if _text_width(word, size) > width:
                raise ValueError("Слово не помещается в поле примечаний учебного листа")
            candidate = (line + " " + word).strip()
            if line and _text_width(candidate, size) > width:
                result.append(_text(x, y, line, height=height))
                y += height * 1.5
                line = word
            else:
                line = candidate
        result.append(_text(x, y, line, height=height))
        # Account for descenders below the baseline as well as capital height.
        if y + size * .3 > bottom:
            raise ValueError("Примечания не помещаются в свободное поле учебного листа")
        y += pitch
    return "".join((*result, "</g>"))


def validate_study_section_frame(svg: str, *, sheet_total: int = 1, sheet_no: int = 1,
                                 system_label: str = "К1, К2", cipher: str = "УЧЕБНЫЙ-К1К2.СХ") -> None:
    root = ET.fromstring(svg)
    expected = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg">'
                             + study_section_frame(sheet_total=sheet_total, sheet_no=sheet_no,
                                                   system_label=system_label, cipher=cipher) + '</svg>')[0]
    frames = [element for element in root if element.get("data-drawing-frame")]
    if ((root.get("width"), root.get("height"), root.get("viewBox")) !=
            ("594mm", "420mm", "0 0 594 420") or len(frames) != 1
            or ET.tostring(frames[0]) != ET.tostring(expected)):
        raise ValueError("Учебный разрез требует полной рамки А2 и фактической нумерации")
    if root.get("data-release-ready") != "false":
        raise ValueError("Учебный разрез не подтверждает выпуск")
