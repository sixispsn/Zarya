# -*- coding: utf-8 -*-
"""Тесты моста расчётного ядра ВПВ в документы (уровень A + поля B):
enrich_fire_from_layout_and_hydraulics, describe_fire_pump_requirement,
сквозная связь pk_total → спецификация В2."""
import pytest

from app.pz.project import (
    Project, DocumentInfo, BuildingFlags, BuildingPurpose, FireSystem,
)
from app.pz.flows_bridge import enrich_fire_from_layout_and_hydraulics
from app.pz.rules import describe_fire_pump_requirement
from app.pz.spec import build_specification


class _LayoutStub:
    def __init__(self, pk):
        self.pk_total = pk


class _HydraPump:
    required_head_at_source_m = 42.6
    available_head_m = 40.0
    needs_pump = True
    dictating_cabinet_id = None
    dictating_scenario = type("S", (), {"active_cabinet_ids": ["PK-A", "PK-C2"]})()


class _HydraNoPump:
    required_head_at_source_m = 38.0
    available_head_m = 45.0
    needs_pump = False
    dictating_cabinet_id = "PK-1"


# ── агрегация pk_total по зданию ─────────────────────────────────────────────

def test_pk_total_sums_over_rooms():
    fire = FireSystem(required=True)
    e = enrich_fire_from_layout_and_hydraulics(
        fire, layout_results=[_LayoutStub(8), _LayoutStub(8), _LayoutStub(10)])
    assert e.pk_total == 26


def test_enrich_does_not_mutate_original():
    fire = FireSystem(required=True, pk_total=0)
    e = enrich_fire_from_layout_and_hydraulics(fire, layout_results=[_LayoutStub(5)])
    assert fire.pk_total == 0        # оригинал не тронут
    assert e.pk_total == 5           # новый объект


# ── перенос гидравлики ───────────────────────────────────────────────────────

def test_hydraulics_fields_transferred():
    e = enrich_fire_from_layout_and_hydraulics(
        FireSystem(required=True), hydraulic_result=_HydraPump())
    assert e.required_head_m == 42.6
    assert e.available_head_m == 40.0
    assert e.needs_pump is True


def test_dictating_pair_joined():
    e = enrich_fire_from_layout_and_hydraulics(
        FireSystem(required=True), hydraulic_result=_HydraPump())
    assert e.dictating_cabinet_id == "PK-A+PK-C2"


def test_dictating_single_cabinet():
    e = enrich_fire_from_layout_and_hydraulics(
        FireSystem(required=True), hydraulic_result=_HydraNoPump())
    assert e.dictating_cabinet_id == "PK-1"


# ── текст пояснительной записки ──────────────────────────────────────────────

def test_pz_text_pump_needed():
    e = enrich_fire_from_layout_and_hydraulics(
        FireSystem(required=True), hydraulic_result=_HydraPump())
    d = describe_fire_pump_requirement(e)
    assert d.needs_pump is True
    assert "насосная установка В2" in d.text
    assert "42.6" in d.text


def test_pz_text_no_pump():
    e = enrich_fire_from_layout_and_hydraulics(
        FireSystem(required=True), hydraulic_result=_HydraNoPump())
    d = describe_fire_pump_requirement(e)
    assert d.needs_pump is False
    assert "не требуется" in d.text


def test_pz_text_no_hydraulics():
    d = describe_fire_pump_requirement(FireSystem(required=True))
    assert d.required_head_m is None
    assert "уточняется" in d.text


def test_pz_text_no_fire():
    d = describe_fire_pump_requirement(FireSystem(required=False))
    assert "не требуется" in d.text


# ── сквозная связь: мост → спецификация В2 ──────────────────────────────────

def test_pk_total_flows_into_spec():
    p = Project()
    p.document = DocumentInfo(cipher="ТЕСТ")
    p.building = BuildingFlags(purpose=BuildingPurpose.RESIDENTIAL, floors_above=12, zones=2)
    p.fire = FireSystem(required=True, streams=2, q_per_stream=2.6, q_total=5.2,
                        nozzle_dn=50, hose_length_m=20)
    # до моста: pk_total=0 → спека без количества
    before = _pk_qty_in_spec(p)
    assert before is None
    # после моста: pk_total=26 → количество проставлено
    p.fire = enrich_fire_from_layout_and_hydraulics(
        p.fire, layout_results=[_LayoutStub(13), _LayoutStub(13)])
    after = _pk_qty_in_spec(p)
    assert after == 26


def _pk_qty_in_spec(project):
    for sec in build_specification(project).sections:
        if "В2" in sec.title:
            for r in sec.rows:
                if "кран пожарный" in r.name.lower():
                    return r.qty
    return "no-section"
