"""Control sheet presentation must not alter the architectural model or adapter."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from xml.etree import ElementTree as ET

import cairosvg
import fitz
import pytest

from app.pz import architecture_section_engine as engine
from scripts.verify_architecture_control import long_registry


@pytest.fixture(autouse=True)
def stable_svg_namespace_for_hashes(monkeypatch):
    monkeypatch.delitem(ET._namespace_map, "http://www.w3.org/2000/svg", raising=False)


def registry():
    return engine.load_architecture_plan_registry("demo/architecture_section_registry.json")


def test_architectural_geometry_and_adapter_are_unchanged():
    source = registry()
    before = deepcopy(source)
    model = engine.build_architecture_section(source)
    model_before = deepcopy(model)
    layout = engine.architecture_section_to_wastewater_layout(model)
    root = ET.fromstring(engine.build_architecture_section_control_svg(model))
    assert source == before and model == model_before
    assert engine.architecture_section_to_wastewater_layout(model) == layout
    children = list(root)
    start = next(i for i, e in enumerate(children) if e.get("data-architecture-roof"))
    end = next(i for i, e in enumerate(children) if e.get("data-foundation-slab"))
    group = ET.Element("g")
    for e in children[start:end+1]:
        group.append(e)
    for e in list(group.iter()):
        for child in list(e):
            if child.tag.endswith("text"):
                e.remove(child)
    assert sha256(ET.tostring(group)).hexdigest() == "85a3d9cb9c9d4b1c90fc74468ae5b29f47f42b13f5f6d5a31c82a24cbb343f6c"


@pytest.mark.parametrize("long", [False, True])
def test_complete_text_nonproject_vector_a1(tmp_path, long):
    source = long_registry(registry()) if long else registry()
    model = engine.build_architecture_section(source)
    svg = engine.build_architecture_section_control_svg(model)
    root = ET.fromstring(svg)
    assert root.get("data-release-ready") == "false"
    assert not any(e.tag.endswith("rect") and e.get("fill") == "none" for e in root)
    if long:
        assert len(engine._wrap_label("№601 " + source.floors[-1].rooms[0].name, width=380)) > 3
        assert len(engine._wrap_label("Источник: " + source.source_ref, width=2624, size=16)) == 2
    target = tmp_path / "architecture.pdf"
    engine.generate_architecture_section_control_pdf(str(target), source)
    with fitz.open(target) as pdf:
        assert len(pdf) == 1
        page = pdf[0]
        assert page.rect.width / 72 * 25.4 == pytest.approx(841, abs=.01)
        assert page.rect.height / 72 * 25.4 == pytest.approx(594, abs=.01)
        text = page.get_text()
        assert engine._SECTION_NOTICE in text and "Лист 1 из 1" in text
        assert not page.get_images() and "Стадия" not in text
        normalized = "".join(text.split())
        assert "".join(source.source_ref.split()) in normalized
        for floor in model.displayed_floor_numbers:
            for room in model.floor(floor).cells:
                assert "".join(f"№{room.number} {room.name}".split()) in normalized
        for x0, y0, x1, y1, *_ in page.get_text("words"):
            assert x0 > 40 and x1 < page.rect.width - 40
            assert y0 > 40 and y1 < page.rect.height - 35


def test_unbroken_labels_wrap_without_loss():
    label = "ДЛИННЫЙИДЕНТИФИКАТОР" * 30
    rows = engine._wrap_label(label, width=150)
    assert "".join(rows) == label and len(rows) > 3
    with pytest.raises(ValueError, match="не помещается"):
        engine._wrap_label(label, width=.01)


@pytest.mark.parametrize("failure", ["room", "source", "header", "floors", "convert", "replace"])
def test_failure_preserves_old_pdf(tmp_path, monkeypatch, failure):
    target = tmp_path / "architecture.pdf"
    target.write_bytes(b"previous pdf")
    data = registry()

    def fail(*args, **kwargs):
        raise OSError("synthetic failure")

    if failure == "room":
        data = replace(data, floors=tuple(
            replace(f, rooms=(replace(f.rooms[0], name="Длинное имя " * 2000),) + f.rooms[1:])
            for f in data.floors))
    elif failure == "source":
        data = replace(data, source_ref="Источник " * 10000)
    elif failure == "header":
        data = replace(data, plan_id="Реестр " * 10000)
    elif failure == "floors":
        floor = data.floors[3]
        data = replace(data, floors=data.floors[:3] + (replace(
            floor, rooms=(replace(floor.rooms[0], name="Кухня-ниша"),) + floor.rooms[1:]),) + data.floors[4:])
        assert len(engine.build_architecture_section(data).displayed_floor_numbers) == 7
    elif failure == "convert":
        monkeypatch.setattr(cairosvg, "svg2pdf", fail)
    else:
        monkeypatch.setattr(engine.os, "replace", fail)
    with pytest.raises((ValueError, OSError)):
        engine.generate_architecture_section_control_pdf(str(target), data)
    assert target.read_bytes() == b"previous pdf"
    assert list(tmp_path.iterdir()) == [target]
