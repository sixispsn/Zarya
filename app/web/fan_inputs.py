"""Wizard fan input contract; saving a draft does not approve a drawing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import isclose, isfinite

from app.pz.wastewater_fan_geometry import FanGeometryInput, FanRoofDetail, FanValveDetail
from app.pz.wastewater_ventilation import FanVentilationInput


@dataclass(frozen=True)
class FanFormInput:
    evidence: FanVentilationInput | None = None
    geometry: FanGeometryInput | None = None
    roof_level: float | None = None

    @classmethod
    def parse(cls, raw: str) -> FanFormInput:
        row = json.loads(raw)
        if not isinstance(row, dict) or set(row) - {"fan_ventilation", "fan_geometry", "roof_level"}:
            raise ValueError("Фановая вентиляция: неверный состав полей")
        z = row.get("roof_level")
        if z is not None and (type(z) not in (int, float) or not isfinite(z)):
            raise ValueError("Отметка кровли должна быть конечным числом")
        evidence = row.get("fan_ventilation")
        geometry = row.get("fan_geometry")
        result = cls(
            FanVentilationInput.from_mapping(evidence) if evidence is not None else None,
            FanGeometryInput.from_mapping(geometry) if geometry is not None else None, z,
        )
        result.validate_links()
        return result

    def validate_links(self) -> None:
        terminals = self.evidence.terminals if self.evidence else ()
        members = [rid for t in terminals for rid in t.riser_ids]
        if len(members) != len(set(members)):
            raise ValueError("Один стояк нельзя включить в несколько фановых узлов")
        if any(t.kind == "valve" and len(t.riser_ids) != 1 for t in terminals):
            raise ValueError("Узел клапана должен быть привязан к одному стояку")
        if self.geometry is None:
            return
        details: tuple[FanRoofDetail | FanValveDetail, ...] = (*self.geometry.roofs, *self.geometry.valves)
        known = {t.terminal_id: t for t in terminals}
        for d in details:
            t = known.get(d.terminal_id)
            roof = isinstance(d, FanRoofDetail)
            if t is None or t.kind != ("roof" if roof else "valve"):
                raise ValueError(f"{d.terminal_id}: геометрия не соответствует типу фанового узла")
            if isinstance(d, FanRoofDetail):
                if {r.riser_id for r in d.risers} != set(t.riser_ids):
                    raise ValueError(f"{d.terminal_id}: состав стояков геометрии и группы различается")
                if self.roof_level is not None and not isclose(d.roof_level_m, self.roof_level):
                    raise ValueError(f"{d.terminal_id}: отметка кровли отличается от общей")
        if self.geometry.confirmed and (
            self.roof_level is None or {d.terminal_id for d in details} != set(known)
        ):
            raise ValueError("Для подтверждения нужны отметка кровли и геометрия каждого узла")

    @classmethod
    def from_request(cls, req) -> FanFormInput:
        return cls(req.wastewater_fan_ventilation, req.wastewater_fan_geometry,
                   req.wastewater_roof_relative_elevation_m)

    def to_mapping(self) -> dict:
        return {
            "fan_ventilation": self.evidence.to_mapping() if self.evidence else None,
            "fan_geometry": self.geometry.to_mapping() if self.geometry else None,
            "roof_level": self.roof_level,
        }

    def request_fields(self) -> dict:
        return dict(wastewater_fan_ventilation=self.evidence,
                    wastewater_fan_geometry=self.geometry,
                    wastewater_roof_relative_elevation_m=self.roof_level)
