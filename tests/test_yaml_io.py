# -*- coding: utf-8 -*-
"""Тесты app/intake/yaml_io.py — YAML как второй потребитель Builder'а."""
import pytest

from app.intake.yaml_io import (
    load_request, dump_request, YamlFormatError,
)
from app.intake.project_builder import build_project, RequestValidationError

GOOD = """
document:
  cipher: Т-ИОС2
  object_name: Объект
  organization: Орг
building: {type: residential, floors: 16, height_m: 48}
fire: {streams: 2}
rooms:
  - {name: Коридор, length_m: 42, width_m: 2.4, height_m: 3.0}
network:
  source: {node: К1, kind: city_main, available_head_m: 32}
  runs:
    - {from: К1, to: К2, length_m: 36}
    - {from: К2, to: К3, length_m: 15}
    - {from: К3, to: К4, length_m: 36}
    - {from: К4, to: К1, length_m: 15}
  risers:
    - {name: СТ-1, at: К1, height_m: 46.5, cabinet_elevation_m: 45.6}
    - {name: СТ-2, at: К2, height_m: 46.5, cabinet_elevation_m: 45.6}
"""


def test_load_basic():
    req = load_request(GOOD)
    assert req.document.cipher == "Т-ИОС2"
    assert req.building_type == "residential"
    assert req.floors == 16
    assert req.streams == 2
    assert len(req.rooms) == 1
    assert len(req.network.runs) == 4
    assert req.network.available_head_m == 32.0


def test_roundtrip_identity():
    req = load_request(GOOD)
    assert load_request(dump_request(req)) == req


def test_roundtrip_preserves_optional_fields():
    y = GOOD + "\n"
    req = load_request(y)
    req.network.node_elevations = {"К2": -1.5}
    req2 = load_request(dump_request(req))
    assert req2.network.node_elevations == {"К2": -1.5}


def test_bad_yaml_syntax():
    with pytest.raises(YamlFormatError, match="синтаксис"):
        load_request("document: [unclosed")


def test_root_not_mapping():
    with pytest.raises(YamlFormatError, match="словарём"):
        load_request("- just\n- a list\n")


def test_missing_document_section():
    with pytest.raises(YamlFormatError, match="document"):
        load_request("building: {type: residential, floors: 5, height_m: 15}")


def test_rooms_not_list():
    with pytest.raises(YamlFormatError, match="списком"):
        load_request(GOOD.replace("rooms:\n  - {name: Коридор, length_m: 42, "
                                  "width_m: 2.4, height_m: 3.0}",
                                  "rooms: {oops: 1}"))


def test_semantic_errors_deferred_to_builder():
    # структурно валидный YAML, но с плохими значениями → ловит Builder, не парсер
    bad_values = GOOD.replace("floors: 16", "floors: 0")
    req = load_request(bad_values)          # парсер пропускает
    with pytest.raises(RequestValidationError):
        build_project(req)                  # Builder ловит


def test_full_chain_yaml_to_project():
    req = load_request(GOOD)
    p = build_project(req)
    assert p.fire.streams == 2
    assert p.fire_network is not None
    assert len(p.fire_network.risers) == 2


def test_streams_absent_means_none():
    y = GOOD.replace("fire: {streams: 2}", "fire: {}")
    req = load_request(y)
    assert req.streams is None
