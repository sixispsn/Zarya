"""Manufacturer geometry, deliberately separate from the SP/legacy meter table.

No prices, inferred fitting lengths, inferred hydraulic resistance or model substitution.
Published PN is a nameplate rating, not permission to ignore temperature derating.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class MeterPressureLossLimit:
    """One published inequality at Qmax, NOT a measured point or loss curve."""
    max_mpa: float
    at_flow_m3h: float
    source_id: str
    reference: str
    checked_on: str
    review_revision: str


@dataclass(frozen=True)
class FlangeConnection:
    """Known catalogue interface; omitted drilling/face data stay unknown."""
    standard: str
    face: str = "unknown"
    bolt_circle_mm: float | None = None
    bolt_count: int | None = None
    bolt_hole_mm: float | None = None


@dataclass(frozen=True)
class MeterStraightSections:
    before_dn: float
    after_dn: float
    source_id: str
    reference: str


@dataclass(frozen=True)
class MeteringProduct:
    id: str
    manufacturer: str
    model: str
    article: str
    kind: str
    dn: int
    source_ids: tuple[str, ...]
    dimension_status: str
    dimensions_mm: Mapping[str, float]
    connection_standard: str
    connection_sex: str
    thread: str
    kit_pipe_thread: str | None
    pn_bar: float
    temperature_c: tuple[float, float]
    pressure_temperature: tuple[tuple[float, float], ...]
    drive: str
    mounting: str
    remote_readout: bool | None
    remote_interface: str
    flows_m3h: Mapping[str, float]
    notes: tuple[str, ...]
    pressure_loss_limit: MeterPressureLossLimit | None = None
    technology: str = "mechanical"
    country_of_manufacture: str = "unknown"
    origin_source_ids: tuple[str, ...] = ()
    full_bore: bool | None = None
    dimension_basis: str = "nominal"
    flange: FlangeConnection | None = None
    straight_sections: MeterStraightSections | None = None
    valve_type: str = "unknown"
    filter_type: str = "mesh"
    installation: Mapping = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.manufacturer} {self.model} DN{self.dn}"

    @property
    def body_length_mm(self) -> float | None:
        if self.dimension_status != "verified":
            return None
        return self.dimensions_mm.get("L")

    @property
    def connection_label(self) -> str:
        if self.flange:
            return f"Фланцевое DN{self.dn} PN{self.pn_bar:g}; {self.flange.standard}"
        return f"{self.connection_standard}{self.thread}"


@dataclass(frozen=True)
class MeterConnectionKit:
    id: str
    name: str
    meter_ids: tuple[str, ...]
    meter_thread: str
    pipe_thread: str
    length_with_meter_reference_mm: float
    status: str
    source_ids: tuple[str, ...]
    meter_seal: str = "unknown"
    pipe_connection_sex: str = "unknown"
    protects_straight_sections: bool = False
    # Composition of the proposed factory kit, not additional purchase rows.
    contents: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class PipeClamp:
    id: str
    name: str
    article: str
    pipe_material: str
    outer_diameter_mm: tuple[float, float]
    thread: str
    dimensions_mm: Mapping[str, float]
    fa_z_n: float
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class MeteringConnector:
    """A pipe socket and a threaded equipment port, not an inferred DN."""
    id: str
    article: str
    manufacturer: str
    pipe_material: str
    pipe_system: str
    pipe_outer_diameter_mm: float
    joining: str
    connection_standard: str
    thread: str
    connection_sex: str
    pn_bar: float | None
    max_temperature_c: float | None
    dimension_status: str
    dimensions_mm: Mapping[str, float]
    source_ids: tuple[str, ...]

    @property
    def body_length_mm(self):
        return self.dimensions_mm.get("L") if self.dimension_status == "verified" else None


@dataclass(frozen=True)
class ThreadConnector:
    """Explicitly oriented two-thread fitting between equipment and socket part."""
    id: str
    article: str
    manufacturer: str
    connection_standard: str
    equipment_thread: str
    equipment_sex: str
    pipe_connector_thread: str
    pipe_connector_sex: str
    pn_bar: float
    temperature_c: tuple[float, float]
    dimension_status: str
    dimensions_mm: Mapping[str, float]
    source_ids: tuple[str, ...]
    pressure_temperature: tuple[tuple[float, float], ...] = ()

    @property
    def body_length_mm(self):
        return self.dimensions_mm.get("L") if self.dimension_status == "verified" else None


@dataclass(frozen=True)
class ThreadReducer:
    """Two unequal ports; direction is assigned by the schematic location.

    DN is nominal port identification, never an internal pipe diameter.
    Only dimensions actually entered in dimensions_mm have been verified.
    """
    id: str
    article: str
    manufacturer: str
    large_dn: int
    small_dn: int
    connection_standard: str
    large_thread: str
    large_sex: str
    small_thread: str
    small_sex: str
    pn_bar: float
    temperature_c: tuple[float, float]
    pressure_temperature: tuple[tuple[float, float], ...]
    dimension_status: str
    dimensions_mm: Mapping[str, float]
    source_ids: tuple[str, ...]

    @property
    def body_length_mm(self):
        return self.dimensions_mm.get("L") if self.dimension_status == "verified" else None


@dataclass(frozen=True)
class MeteringCatalogue:
    revision: str
    sources: Mapping[str, Mapping]
    products: Mapping[str, MeteringProduct]
    connection_kits: Mapping[str, MeterConnectionKit]
    pipe_clamps: Mapping[str, PipeClamp]
    connectors: Mapping[str, MeteringConnector]
    thread_connectors: Mapping[str, ThreadConnector]
    reducers: Mapping[str, ThreadReducer]
    service_products: Mapping = field(default_factory=dict)
    # Additive dimension releases do not invalidate unchanged existing IDs.
    # This is NOT the compatibility revision accepted in saved projects.
    dimension_revisions: tuple[str, ...] = ()
    fittings: Mapping = field(default_factory=dict)

    def fitting_candidates(self, kind, dn, *, branch_dn=None, connection=None, material=None,
                           russian_only=False):
        return tuple(p for p in self.fittings.values() if p.kind == kind and p.ports[0].dn == dn
            and (branch_dn is None or (p.ports[2].dn if len(p.ports) > 2 else p.ports[1].dn) == branch_dn)
            and (connection is None or p.ports[0].connection == connection)
            and (material is None or p.material == material)
            and (not russian_only or p.country_of_manufacture == "RU" and p.origin_source_ids))

    def candidates(self, kind: str, dn: int | None, *, drive: str | None = None,
                   russian_only: bool = False, technology: str | None = None):
        """Geometry candidates only, NOT approved hydraulic/product selections."""
        return tuple(p for p in self.products.values()
                     if p.kind == kind and p.dn == dn
                     and p.dimension_status == "verified"
                     and (not russian_only or (p.country_of_manufacture == "RU" and p.origin_source_ids))
                     and (technology is None or p.technology == technology)
                     and (drive is None or p.drive == drive))

    def coverage(self, dn: int, *, russian_only: bool = False):
        """Exact geometry candidates, not a claim of installation readiness."""
        return {role: tuple(p.id for p in self.candidates(kind, dn, drive=drive,
                    russian_only=russian_only, technology="mechanical" if kind == "meter" else None))
                for role, kind, drive in (("meter", "meter", None),
                    ("manual_valve", "shutoff", "manual"), ("filter", "strainer", None),
                    ("check_valve", "check", None), ("electric_valve", "shutoff", "electric"))}


@lru_cache(maxsize=1)
def get_metering_catalogue() -> MeteringCatalogue:
    raw = json.loads(Path(__file__).with_name("metering_products.json").read_text(encoding="utf-8"))
    supplement = json.loads(Path(__file__).with_name("metering_products_20261012.json").read_text(encoding="utf-8"))
    raw["sources"].update(supplement["sources"])
    raw["families"].extend(supplement["families"])
    raw["thread_connectors"].extend(supplement.get("thread_connectors", []))
    flanged = json.loads(Path(__file__).with_name("metering_products_flanged.json").read_text(encoding="utf-8"))
    if set(raw["sources"]) & set(flanged["sources"]):
        raise ValueError("Дубликат источника фланцевого каталога")
    raw["sources"].update(flanged["sources"])
    raw["families"].extend(flanged["families"])
    fitting_data = json.loads(Path(__file__).with_name("metering_fittings.json").read_text(encoding="utf-8"))
    if set(raw["sources"]) & set(fitting_data["sources"]):
        raise ValueError("Дубликат источника фасонины")
    raw["sources"].update(fitting_data["sources"])
    raw["families"].extend(fitting_data["equipment_families"])
    from app.data.metering_fittings import load_fittings, extend_thread_rows
    fittings = load_fittings(fitting_data)
    extend_thread_rows(raw, fitting_data)
    from app.data.metering_service_products import load_service_products
    service_sources, service_products = load_service_products()
    raw["sources"].update(service_sources)
    for family in raw["families"]:
        family.update(supplement.get("family_updates", {}).get(family["id"], {}))
    products, kits, clamps, connectors, thread_connectors, reducers = {}, {}, {}, {}, {}, {}
    non_dimensions = {"dn", "article", "article_suffix", "thread", "body_thread", "kit_pipe_thread",
                      "pn_bar", "qmin_B", "qmin_C", "qn", "qmax",
                      "bolt_circle_mm", "bolt_count", "bolt_hole_mm"}
    for family in raw["families"]:
        for values in family["rows"]:
            if len(values) != len(family["columns"]):
                raise ValueError(f"Некорректная строка каталога {family['id']}")
            row = dict(zip(family["columns"], values))
            dn = row["dn"]
            ident = f"{family['id']}-dn{dn}"
            if ident in products or type(dn) is not int or dn <= 0:
                raise ValueError(f"Некорректный DN/дубликат {ident}")
            dimensions = {k: v for k, v in row.items() if k not in non_dimensions}
            if any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                   for v in dimensions.values()):
                raise ValueError(f"Некорректные размеры {ident}")
            if any(s not in raw["sources"] for s in (*family["source_ids"], *family.get("origin_source_ids", []))):
                raise ValueError(f"Нет источника {ident}")
            flange = None
            if family.get("flange"):
                flange = FlangeConnection(**family["flange"], **{
                    k: row[k] for k in ("bolt_circle_mm", "bolt_count", "bolt_hole_mm") if k in row})
                if (family["connection_sex"] != "flanged" or row.get("thread") or row.get("body_thread")
                    or not flange.standard or flange.face not in ("unknown", "B")
                    or any(v is not None and (type(v) not in (int, float) or not isfinite(v) or v <= 0)
                           for v in (flange.bolt_circle_mm, flange.bolt_hole_mm))
                    or (flange.bolt_count is not None and (type(flange.bolt_count) is not int or flange.bolt_count <= 0))):
                    raise ValueError(f"Некорректное фланцевое присоединение {ident}")
            straight = None
            valve_type = family.get("valve_type", "unknown")
            if valve_type not in ("unknown", "ball", "gate") or (valve_type != "unknown" and family["kind"] != "shutoff"):
                raise ValueError(f"Некорректный тип запорной арматуры {ident}")
            if family.get("straight_sections"):
                straight = MeterStraightSections(**family["straight_sections"])
                if (family["kind"] != "meter" or straight.source_id not in family["source_ids"]
                    or not straight.reference or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                        for v in (straight.before_dn, straight.after_dn))):
                    raise ValueError(f"Некорректное требование прямых участков {ident}")
            table = family.get("pressure_temperature_table", {})
            temperatures = table.get("temperatures_c", [])
            pressures = table.get("by_dn", {}).get(str(dn), [])
            if len(temperatures) != len(pressures):
                raise ValueError(f"Некорректная таблица P/T {ident}")
            limit = family.get("pressure_loss_limit")
            pressure_loss_limit = None
            if limit:
                if (family["kind"] != "meter" or limit.get("kind") != "upper_bound_at_qmax"
                    or limit.get("source_id") not in family["source_ids"]
                    or not raw.get("hydraulic_review_revision")
                    or not limit.get("reference") or not limit.get("checked_on")
                    or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                           for v in (limit.get("mpa"), row.get("qmax")))):
                    raise ValueError(f"Некорректный паспортный предел потерь {ident}")
                pressure_loss_limit = MeterPressureLossLimit(
                    limit["mpa"], row["qmax"], limit["source_id"], limit["reference"],
                    limit["checked_on"], raw["hydraulic_review_revision"],
                )
            products[ident] = MeteringProduct(
                id=ident, manufacturer=family["manufacturer"], model=family["model"],
                article=row.get("article", f"{family['model']}.{row['article_suffix']}"
                                if "article_suffix" in row else ""),
                kind=family["kind"], dn=dn, source_ids=tuple(family["source_ids"]),
                dimension_status=family["dimension_status"],
                dimensions_mm=MappingProxyType(dimensions),
                connection_standard=family["connection_standard"],
                connection_sex=family["connection_sex"],
                thread=row.get("thread", row.get("body_thread", "")),
                kit_pipe_thread=row.get("kit_pipe_thread"),
                pn_bar=row.get("pn_bar", family.get("pn_bar")),
                temperature_c=tuple(family["temperature_c"]),
                pressure_temperature=tuple(zip(temperatures, pressures)),
                drive=family["drive"], mounting=family["mounting"],
                remote_readout=family.get("remote_readout"),
                remote_interface=family.get("remote_interface", ""),
                flows_m3h=MappingProxyType({k: row[k] for k in ("qmin_B", "qmin_C", "qn", "qmax") if k in row}),
                notes=tuple(family["notes"]),
                pressure_loss_limit=pressure_loss_limit,
                technology=family.get("technology", "mechanical"),
                country_of_manufacture=family.get("country_of_manufacture", "unknown"),
                origin_source_ids=tuple(family.get("origin_source_ids", ())),
                full_bore=family.get("full_bore"),
                dimension_basis=family.get("dimension_basis", "nominal"),
                flange=flange, straight_sections=straight, valve_type=valve_type,
                filter_type=family.get("filter_type", "mesh"),
            )
            kit = family.get("connection_kit")
            if kit:
                kit_id = f"{kit['id']}-dn{dn}"
                if kit_id in kits:
                    raise ValueError(f"Дубликат комплекта {kit_id}")
                installation = kit.get("installation", {})
                contents = installation.get("contents", [])
                if (installation.get("meter_seal", "unknown") not in ("unknown", "flat_gasket")
                    or installation.get("pipe_connection_sex", "unknown") not in ("unknown", "male", "female")
                    or type(installation.get("protects_straight_sections", False)) is not bool
                    or any(not isinstance(item, list) or len(item) != 2 or not isinstance(item[0], str)
                           or not item[0].strip() or type(item[1]) is not int or item[1] <= 0 for item in contents)):
                    raise ValueError(f"Некорректный состав/монтаж комплекта {kit_id}")
                kits[kit_id] = MeterConnectionKit(
                    kit_id, f"{kit['name']} DN{dn}", (ident,), row["body_thread"],
                    row["kit_pipe_thread"], row["L1_reference"], kit["status"],
                    tuple(family["source_ids"]),
                    installation.get("meter_seal", "unknown"),
                    installation.get("pipe_connection_sex", "unknown"),
                    installation.get("protects_straight_sections", False),
                    tuple(tuple(item) for item in contents),
                )
    family = raw["pipe_clamps"]
    for values in family["rows"]:
        if len(values) != len(family["columns"]):
            raise ValueError("Некорректная строка каталога хомутов")
        row = dict(zip(family["columns"], values))
        ident = f"walraven-{row['article']}"
        numbers = {k: v for k, v in row.items() if k != "article"}
        if (ident in clamps or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                                   for v in numbers.values())
                or row["d_min"] > row["d_max"]
                or any(s not in raw["sources"] for s in family["source_ids"])):
            raise ValueError(f"Некорректный хомут {ident}")
        clamps[ident] = PipeClamp(
            ident, f"{family['manufacturer']} {family['model']}", row["article"],
            family["pipe_material"], (row["d_min"], row["d_max"]), family["thread"],
            MappingProxyType({k: row[k] for k in ("B", "H", "h", "b", "s")}),
            row["fa_z_n"], tuple(family["source_ids"]),
        )
    for row in raw.get("connectors", []):
        ident = row["id"]
        dimensions = row["dimensions_mm"]
        if (ident in connectors or any(s not in raw["sources"] for s in row["source_ids"])
                or row["dimension_status"] not in ("verified", "conflict")
                or row["connection_sex"] not in ("male", "female")
                or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                       for v in [row["pipe_outer_diameter_mm"], *dimensions.values()])
                or (row["pn_bar"] is not None and (type(row["pn_bar"]) not in (int, float)
                    or not isfinite(row["pn_bar"]) or row["pn_bar"] <= 0))
                or (row["max_temperature_c"] is not None and
                    (type(row["max_temperature_c"]) not in (int, float) or not isfinite(row["max_temperature_c"])))
                or (row["dimension_status"] == "verified" and "L" not in dimensions)):
            raise ValueError(f"Некорректный переходник {ident}")
        connectors[ident] = MeteringConnector(**{**row,
            "dimensions_mm": MappingProxyType(dimensions), "source_ids": tuple(row["source_ids"])})
    for row in raw.get("thread_connectors", []):
        ident, dimensions = row["id"], row["dimensions_mm"]
        temperature = row["temperature_c"]
        table = row.get("pressure_temperature", [])
        if (ident in thread_connectors or any(s not in raw["sources"] for s in row["source_ids"])
                or row["dimension_status"] not in ("verified", "conflict")
                or any(row[key] not in ("male", "female") for key in ("equipment_sex", "pipe_connector_sex"))
                or any(not isinstance(row[key], str) or not row[key].strip()
                       for key in ("connection_standard", "equipment_thread", "pipe_connector_thread"))
                or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                       for v in [row["pn_bar"], *dimensions.values()])
                or len(temperature) != 2
                or any(type(v) not in (int, float) or not isfinite(v) for v in temperature)
                or temperature[0] > temperature[1]
                or (row["dimension_status"] == "verified" and "L" not in dimensions)
                or any(len(pair) != 2 or any(type(v) not in (int,float) or not isfinite(v) for v in pair)
                       or pair[1] <= 0 for pair in table)
                or len({pair[0] for pair in table}) != len(table)):
            raise ValueError(f"Некорректный резьбовой соединитель {ident}")
        thread_connectors[ident] = ThreadConnector(**{**row,
            "dimensions_mm": MappingProxyType(dimensions), "source_ids": tuple(row["source_ids"]),
            "temperature_c": tuple(temperature), "pressure_temperature": tuple(map(tuple,table))})
    for row in raw.get("reducers", []):
        ident, dimensions, temperature = row["id"], row["dimensions_mm"], row["temperature_c"]
        table = row["pressure_temperature"]
        if (ident in reducers or not row["source_ids"]
                or any(s not in raw["sources"] for s in row["source_ids"])
                or any(type(row[k]) is not int or row[k] <= 0 for k in ("large_dn", "small_dn"))
                or row["large_dn"] <= row["small_dn"]
                or row["dimension_status"] not in ("verified", "conflict")
                or any(row[k] not in ("male", "female") for k in ("large_sex", "small_sex"))
                or any(not isinstance(row[k], str) or not row[k].strip()
                       for k in ("connection_standard", "large_thread", "small_thread"))
                or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                       for v in [row["pn_bar"], *dimensions.values()])
                or len(temperature) != 2
                or any(type(v) not in (int, float) or not isfinite(v) for v in temperature)
                or temperature[0] > temperature[1]
                or any(len(pair) != 2 or any(type(v) not in (int, float) or not isfinite(v) for v in pair)
                       or pair[1] <= 0 for pair in table)
                or len({pair[0] for pair in table}) != len(table)
                or (row["dimension_status"] == "verified" and "L" not in dimensions)):
            raise ValueError(f"Некорректный переход {ident}")
        reducers[ident] = ThreadReducer(**{**row,
            "dimensions_mm": MappingProxyType(dimensions), "source_ids": tuple(row["source_ids"]),
            "temperature_c": tuple(temperature), "pressure_temperature": tuple(map(tuple, table))})
    from app.data.metering_installation import apply_installation_profiles
    apply_installation_profiles(products, raw["sources"])
    return MeteringCatalogue(raw["revision"], MappingProxyType({
        k: MappingProxyType(v) for k, v in raw["sources"].items()
    }), MappingProxyType(products), MappingProxyType(kits), MappingProxyType(clamps),
       MappingProxyType(connectors), MappingProxyType(thread_connectors), MappingProxyType(reducers),
       MappingProxyType(service_products), (supplement["revision"], flanged["revision"], fitting_data["revision"]), fittings)
