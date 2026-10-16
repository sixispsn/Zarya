"""Preliminary profile presentation, without changing the proposal or geometry."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest


from app.intake.yaml_io import load_request_file
from app.pz import wastewater_basement_profile as profile


@pytest.fixture(autouse=True)
def stable_svg_namespace_for_hashes(monkeypatch):
    # Other renderers register a process-wide default SVG namespace.  Pin only
    # serialization for these byte hashes, keeping their pre-edit values intact.
    monkeypatch.delitem(ET._namespace_map, "http://www.w3.org/2000/svg", raising=False)


def context():
    req = load_request_file("demo/residential_2floors_8apartments.yaml")
    return profile.basement_profile_from_request(
        req, proposed_invert_m=-2.2, preview_dn_mm=100,
        proposed_invert_basis="Предварительный вариант, не готовая трасса.")


@pytest.mark.parametrize("dn,expected", [
    (100, "c97b0c71435a02e78c8cc8b073f2bf143fad29031a81ab7bc81e900afbc4e1d9"),
    (150, "4ff5d989d825ecd85e3167c6f4a6f33e71d8b24e4a55b649447b99cbe2084fa1"),
])
def test_geometry_unchanged_and_vector_a3_pdf(tmp_path, dn, expected):
    data = replace(context(), preview_dn_mm=dn)
    before = deepcopy(data)
    svg = profile.build_basement_profile_svg(data)
    assert data == before and not data.release_ready
    root = ET.fromstring(svg)
    assert root.get("data-release-ready") == "false"
    assert root.get("data-horizontal-scale") == "schematic"
    assert root.get("data-vertical-scale-denominator") == "25"
    assert not any(e.tag.endswith("rect") and e.get("fill") == "none" for e in root)
    assert not any(e.get("y1") in {"223.000", "281.000"} for e in root)
    children = list(root)
    start = next(i for i, e in enumerate(children) if e.get("data-profile-slab") == "first-floor")
    end = next(i for i, e in enumerate(children) if e.get("data-profile-notes") == "true")
    fragment = "".join(ET.tostring(e, encoding="unicode") for e in children[start:end])
    assert sha256(fragment.encode()).hexdigest() == expected
    target = tmp_path / "profile.pdf"
    profile.generate_basement_profile_pdf(str(target), data)
    with fitz.open(target) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(420, abs=.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(297, abs=.01)
        text = page.get_text()
        assert profile._PROFILE_NOTICE in text
        assert "Лист 1 из 1" in text
        assert "Стадия" not in text and not page.get_images()
        for note in profile._profile_notes(data):
            assert "".join(note.split()) in "".join(text.split())
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 > 55 and x1 < page.rect.width - 25
            assert y0 > 20 and y1 < page.rect.height - 15


def test_long_basis_wraps_completely_in_export(tmp_path):
    data = replace(context(), proposed_invert_basis="Предварительное основание: " + "проверка " * 60)
    root = ET.fromstring(profile.build_basement_profile_svg(data))
    notes = next(e for e in root if e.get("data-profile-notes") == "true")
    assert len(notes) > 8  # heading plus seven original logical notes
    target = tmp_path / "long.pdf"
    profile.generate_basement_profile_pdf(str(target), data)
    with fitz.open(target) as pdf:
        text = "".join(pdf[0].get_text().split())
        assert "".join(data.proposed_invert_basis.split()) in text
        assert "Наружнаясетьнепроектируется." in text


def test_unbroken_text_is_not_cut_or_shrunk():
    value = "ОБОСНОВАНИЕ" * 50
    root = ET.fromstring(profile._profile_notes_svg([value], width=150, y=50, bottom=250))
    assert "".join("".join(e.itertext()) for e in list(root)[1:]) == value
    assert all(e.get("data-paper-text-height-mm") == "2.5" for e in list(root)[1:])
    with pytest.raises(ValueError, match="не помещаются"):
        profile._profile_notes_svg([value] * 20)


@pytest.mark.parametrize("failure", ["basis", "label", "convert", "replace"])
def test_failed_export_preserves_previous_pdf(tmp_path, monkeypatch, failure):
    target = tmp_path / "profile.pdf"
    target.write_bytes(b"previous pdf")
    data = context()

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    if failure == "basis":
        data = replace(data, proposed_invert_basis="Длинное основание " * 10000)
    elif failure == "label":
        data = replace(data, manhole_cover_m=1e100)
    elif failure == "convert":
        monkeypatch.setattr(cairosvg, "svg2pdf", fail)
    else:
        monkeypatch.setattr(profile.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        profile.generate_basement_profile_pdf(str(target), data)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]
