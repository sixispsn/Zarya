"""K3 delta: two removed decorations and one capacity-label baseline move."""
from copy import deepcopy
from xml.etree import ElementTree as ET

import cairosvg
import pytest

from app.pz.wastewater_k3_drafting import build_wastewater_k3_svgs
from app.pz.wastewater_k3_project_inputs import resolve_wastewater_k3_project_inputs
from app.pz.wastewater_k3_scheme_service import _release_project, generate_wastewater_k3_scheme
from scripts.audit_wastewater_visual_golden import K3_OLD_NOTES, restore_k3_fixture_caption
from tests.test_wastewater_k3_scheme import _k3_project
from tests.test_wastewater_visual_golden import _visual_digest


# Captured BEFORE editing production, removing only K3_OLD_NOTES.
BEFORE_WITHOUT_NOTES = (
    "ab951352fd868c60560d8cb62092bd7d0ad130e662eca88c09b5acb054d51cc0",
    "103aa4ab0ceb909cded535687f81d273b1ceda3b9185abce4e0057ac6c798965",
)


@pytest.mark.parametrize("index", [0, 1])
def test_k3_only_reviewed_presentation_changes(index):
    project = _k3_project()
    inputs = resolve_wastewater_k3_project_inputs(project)
    before = deepcopy((project, inputs))
    pages = build_wastewater_k3_svgs(project, inputs)
    assert (project, inputs) == before
    root, old = ET.fromstring(pages[index]), ET.fromstring(K3_OLD_NOTES[index])
    assert not any(n.tag == old.tag and n.attrib == old.attrib for n in root.iter())
    assert len([n for n in root.iter() if n.get("data-title-block")]) == 1
    if index == 0:
        restore_k3_fixture_caption(root)
    assert _visual_digest(ET.tostring(root, encoding="unicode")) == BEFORE_WITHOUT_NOTES[index]


def test_treatment_caption_clear_of_symbol_and_name():
    project = _k3_project()
    svg = build_wastewater_k3_svgs(project, resolve_wastewater_k3_project_inputs(project))[0]
    root = ET.fromstring(svg)
    group = next(n for n in root.iter() if n.get("data-k3-treatment-element"))
    name, caption = group[-2:]
    assert caption.text == "Q=1,0 л/с"
    assert float(caption.get("y")) - float(name.get("y")) == 13
    # Symbol top is 878.94 - 17*.72; text descent is less than 3 SVG units.
    assert float(caption.get("y")) + 3 < 878.94 - 17 * .72


def test_public_k3_pdf_uses_current_pages_without_mutating_project(monkeypatch, tmp_path):
    project = _k3_project()
    before = deepcopy(project)
    released = _release_project(project)
    expected = build_wastewater_k3_svgs(released, resolve_wastewater_k3_project_inputs(released))
    captured = []
    original = cairosvg.svg2pdf

    def capture(*args, **kwargs):
        captured.append(kwargs["bytestring"].decode())
        return original(*args, **kwargs)

    monkeypatch.setattr(cairosvg, "svg2pdf", capture)
    result = generate_wastewater_k3_scheme(project, str(tmp_path / "k3.pdf"))
    assert result.ready and tuple(captured) == expected
    assert project == before
