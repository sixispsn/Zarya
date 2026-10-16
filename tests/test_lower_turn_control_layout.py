"""Control sheet only; shared engineering primitives must remain identical."""
from copy import deepcopy
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest

from app.pz import wastewater_drafting as drafting
from app.pz.generator import generate_wastewater_lower_turn_node_pdf


CASES = (
    ("K1", 100, "ebb473a1dd840a3c58f141b2661bb04b5d21c4ab7b5e497abdc6832b48d6b30a",
     "1ac3fbf311d6748ac8819047f0cc7513b67a3d0b5073ab5faa44a917e3acc3c5"),
    ("K2", 150, "83458bd19fdc5d9a8e061eb03d1234d933f59cd8bb240be9ac858eda59bbc5e6",
     "a10317dc0eba8b92c1573fba675189778e35bf710adac7ecee2176336bece7bf"),
    ("K3", 50, "89b24ccdc8f69c41b10bb7064711e718139a003544a5031c77dd936e4c78174f",
     "60e32a1b0cdff842367e26266c7933f48492f9d21fac056a46ad68d4f1cc515b"),
)


@pytest.mark.parametrize("system,dn,normal_hash,diagnostic_hash", CASES)
def test_control_geometry_unchanged_and_nonproject_pdf(tmp_path, system, dn, normal_hash, diagnostic_hash):
    assembly = drafting.build_lower_turn_cleanout_assembly(system=system, dn_mm=dn)
    before = deepcopy(assembly)
    svg = drafting.build_lower_turn_control_sheet_svg(assembly)
    assert assembly == before
    for diagnostics, x, expected in ((False, 260, normal_hash), (True, 780, diagnostic_hash)):
        fragment = drafting.render_lower_turn_assembly_svg(
            assembly, diagnostics=diagnostics, pipe_labels=False, x=x, y=170, scale=1.6)
        assert sha256(fragment.encode()).hexdigest() == expected
        assert fragment in svg
    root = ET.fromstring(svg)
    assert root.get("data-release-ready") == "false"
    # No decorative frame or separators; actual fitting paths/leader shelves remain.
    assert not any(e.tag.endswith("line") for e in root)
    assert len([e for e in root if e.tag.endswith("rect")]) == 1  # white background only
    output = tmp_path / "control.pdf"
    generate_wastewater_lower_turn_node_pdf(str(output), system=system, dn_mm=dn)
    with fitz.open(output) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(297, abs=.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(210, abs=.01)
        text = page.get_text()
        assert drafting._LOWER_CONTROL_NOTICE in text
        assert "Лист 1 из 1" in text
        assert "Стадия" not in text and not page.get_images()
        for note in drafting._LOWER_CONTROL_NOTES:
            assert "".join(note.split()) in "".join(text.split())
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 >= 25 and x1 <= page.rect.width - 25
            assert y0 >= 25 and y1 <= page.rect.height - 20


def test_notes_wrap_without_loss_or_shrinking():
    note = "Длинное пояснение " * 30
    svg = drafting._lower_control_notes_svg([note], width=300, y=100, bottom=600)
    root = ET.fromstring(svg)
    assert "".join("".join(root.itertext()).split()) == "".join(note.split())
    assert all(e.get("font-size") == "12" for e in root)
    unbroken = "ОБЪЕКТ" * 40
    svg = drafting._lower_control_notes_svg([unbroken], width=300, y=100, bottom=600)
    assert "".join(ET.fromstring(svg).itertext()) == unbroken
    with pytest.raises(ValueError, match="не помещаются"):
        drafting._lower_control_notes_svg([note] * 20)


def test_through_node_cannot_be_presented_as_capped_cleanout():
    node = drafting.build_lower_turn_through_junction_assembly()
    with pytest.raises(ValueError, match="тупикового узла"):
        drafting.build_lower_turn_control_sheet_svg(node)


@pytest.mark.parametrize("failure", ["notes", "label", "convert", "replace"])
def test_failures_preserve_old_pdf(tmp_path, monkeypatch, failure):
    target = tmp_path / "control.pdf"
    target.write_bytes(b"previous pdf")
    def fail(*args, **kwargs):
        raise OSError("synthetic failure")
    kwargs = {}
    if failure == "notes":
        monkeypatch.setattr(drafting, "_LOWER_CONTROL_NOTES", ("Замечание " * 3000,))
    elif failure == "label":
        kwargs["dn_mm"] = 10 ** 100
    elif failure == "convert":
        monkeypatch.setattr(cairosvg, "svg2pdf", fail)
    else:
        monkeypatch.setattr(drafting.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        generate_wastewater_lower_turn_node_pdf(str(target), **kwargs)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]
