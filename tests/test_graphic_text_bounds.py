"""The external frame cells must not become a blanket margin exemption."""

import cairosvg
import pymupdf
import pytest

from app.pz.graphic_document_frame import drawing_frame_svg
from tests.graphic_text_bounds import assert_graphic_text_bounds
from tests.test_station_graphic_frames import qa_document


@pytest.mark.parametrize("change", ["none", "left", "bottom", "missing", "shifted"])
def test_external_labels_are_checked_in_their_own_cells(change):
    frame = drawing_frame_svg(
        qa_document(), width_mm=420, height_mm=297,
        title="Контроль", system_label="В1",
    )
    extra = ""
    if change in ("left", "bottom"):
        x, y = (9, 220) if change == "left" else (390, 296)
        extra = f'<text x="{x}" y="{y}" font-size="3">STRAY</text>'
    elif change == "missing":
        frame = frame.replace("Взам. инв. №", "")
    elif change == "shifted":
        frame = frame.replace("translate(11.500", "translate(3.500")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" '
        f'viewBox="0 0 420 297">{frame}{extra}</svg>'
    )
    with pymupdf.open(stream=cairosvg.svg2pdf(bytestring=svg.encode()), filetype="pdf") as pdf:
        if change == "none":
            assert_graphic_text_bounds(pdf[0], 420, 297, "А3")
        else:
            with pytest.raises(AssertionError):
                assert_graphic_text_bounds(pdf[0], 420, 297, "А3")
