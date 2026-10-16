"""Independent teaching views: frame changes must not change network geometry."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest
from reportlab.lib.units import mm

from app.architecture.residential_plan_study import load_plan_study
from app.pz.drafting_font import ensure_drafting_font_registered
from app.pz.residential_plan_section import build_plan_section_svg
from app.pz.small_residential_preview import build_small_residential_svg
from app.pz.small_residential_rainwater import build_small_residential_k2_svg
from app.pz.small_residential_combined import build_small_residential_combined_svg
from app.pz.study_graphic_frame import validate_study_section_frame
from tests.test_annex_spec_frame import region
from tests.test_small_residential_scheme import model

ROOT = Path(__file__).resolve().parents[1]


def views():
    study = load_plan_study(ROOT / "demo/residential_second_layout.study.json")
    return {
        "second": (study, build_plan_section_svg),
        "preview": (model(), build_small_residential_svg),
        "preview_roof": (model(include_roof=True), build_small_residential_svg),
        "rainwater": (model(include_roof=True), build_small_residential_k2_svg),
        "combined": (model(include_roof=True), build_small_residential_combined_svg),
    }


def engineering_svg(svg):
    root = ET.fromstring(svg)
    kept = []
    for element in root:
        if element.text in ("Условные обозначения", "Принятые для компоновки решения",
                            "Условия и следующие проверки", "Привязка фрагмента А") or element.get("data-study-schedule"):
            break
        if element.tag.endswith("rect") and element.get("x") == "20" and element.get("y") == "5":
            continue
        kept.append(ET.canonicalize(ET.tostring(element, encoding="unicode"), rewrite_prefixes=True).encode())
    return b"".join(kept)


BASELINE = {
    "second": "cb15928480e4d198e4bbf92c71ca265393ca0ca5cb3fb630bbfd75eeb5f108e9",
    "preview": "fa78dfe8101f1088f988829150e637d31ff4cae67980d1fee6877bb5e36f2b60",
    "preview_roof": "3820e16dd490061f84274bc31a3eb6f22e0343eafbf56aa233673e5bde3fb72e",
    "rainwater": "e343171ba2ace98e0a555f6aa22441ba05359f255338daf51cc16415d6e12375",
    "combined": "d52c18da2b5d1ca51d7f6fa0731796117c99c9c8781392f66b061e0625d7e66a",
}


def frame_options(kind):
    if kind in ("second", "preview"):
        return dict(system_label="К1", cipher="УЧЕБНЫЙ-К1.СХ")
    if kind == "preview_roof":
        return dict(system_label="К1", sheet_total=2)
    if kind == "rainwater":
        return dict(system_label="К2", sheet_total=2, sheet_no=2)
    return {}


def check_page(page, *, sheet_no=1, sheet_total=1):
    assert tuple(v / mm for v in page.rect) == pytest.approx((0, 0, 594, 420), abs=.003)
    assert any(tuple(v / mm for v in d["rect"]) == pytest.approx((404, 360, 589, 415), abs=.003)
               for d in page.get_drawings())
    assert region(page, 539, 390, 554, 400) == ""
    assert region(page, 554, 390, 569, 400) == (str(sheet_no) if sheet_total > 1 else "")
    assert region(page, 569, 390, 589, 400) == (str(sheet_total) if sheet_no == 1 else "")
    assert "Не для выпуска" in page.get_text()


@pytest.mark.parametrize("kind", list(BASELINE))
def test_frame_preserves_network_and_does_not_cover_body(kind):
    m, build = views()[kind]
    original = deepcopy(m)
    svg = build(m)
    assert m == original
    assert sha256(engineering_svg(svg)).hexdigest() == BASELINE[kind]
    options = frame_options(kind)
    validate_study_section_frame(svg, **options)
    ensure_drafting_font_registered()
    with fitz.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf") as pdf:
        check_page(pdf[0], sheet_no=options.get("sheet_no", 1), sheet_total=options.get("sheet_total", 1))
    root = ET.fromstring(svg)
    root.remove(next(e for e in root if e.get("data-drawing-frame")))
    with fitz.open(stream=cairosvg.svg2pdf(bytestring=ET.tostring(root)), filetype="pdf") as pdf:
        stamp = fitz.Rect(399 * mm, 355 * mm, 589 * mm, 415 * mm)
        assert not pdf[0].get_text(clip=stamp).strip()
        assert min(pdf[0].get_pixmap(clip=stamp, colorspace=fitz.csGRAY, alpha=False).samples) == 255


@pytest.mark.parametrize("kind", list(BASELINE))
@pytest.mark.parametrize("damage", ["missing", "number", "release"])
def test_export_rejects_damaged_frames_before_touching_existing_file(kind, damage, tmp_path, monkeypatch):
    from app.pz import residential_plan_section as second
    from app.pz import small_residential_preview as preview
    from app.pz import small_residential_rainwater as rainwater
    from app.pz import small_residential_combined as combined

    m, build = views()[kind]
    root = ET.fromstring(build(m))
    frame = next(e for e in root if e.get("data-drawing-frame"))
    if damage == "missing":
        root.remove(frame)
    elif damage == "release":
        root.set("data-release-ready", "true")
    else:
        next(e for e in frame.iter() if e.text == "Листов").text = "999"
    module = {"second": second, "preview": preview, "preview_roof": preview,
              "rainwater": rainwater, "combined": combined}[kind]
    monkeypatch.setattr(module, build.__name__, lambda *a, **kw: ET.tostring(root, encoding="unicode"))
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"unchanged existing artifact")
    with pytest.raises(ValueError):
        if kind == "second":
            second.generate_plan_section_pdf(target, m)
        elif kind == "combined":
            combined.generate_small_residential_combined_pdf(str(target), m)
        else:
            preview.generate_small_residential_pdf(str(target), m)
    assert target.read_bytes() == b"unchanged existing artifact"


def test_two_sheet_document_uses_one_cipher_and_real_numbering(tmp_path):
    from app.pz.small_residential_preview import generate_small_residential_pdf

    path = generate_small_residential_pdf(str(tmp_path / "two.pdf"), model(include_roof=True))
    with fitz.open(path) as pdf:
        assert len(pdf) == 2
        for index, page in enumerate(pdf, 1):
            check_page(page, sheet_no=index, sheet_total=2)
            assert region(page, 469, 360, 589, 370) == "УЧЕБНЫЙ-К1К2.СХ"


def test_apartment_schedule_is_a_closed_table():
    root = ET.fromstring(build_small_residential_combined_svg(model(include_roof=True)))
    table = next(e for e in root if e.get("data-study-schedule"))
    rect = next(e for e in table if e.tag.endswith("rect"))
    assert tuple(float(rect.get(key)) for key in ("x", "y", "width", "height")) == (465, 61, 117, 41)
    lines = {tuple(float(e.get(key)) for key in ("x1", "y1", "x2", "y2"))
             for e in table if e.tag.endswith("line")}
    assert lines == ({(x, 61, x, 102) for x in (501, 533)} |
                     {(465, y, 582, y) for y in (70, 78, 86, 94)})
    labels = list(table.itertext())
    assert all(label in labels for label in ("Квартиры*", "Стояк", "Подключения", "1, 5", "2, 6", "3, 7", "4, 8"))
