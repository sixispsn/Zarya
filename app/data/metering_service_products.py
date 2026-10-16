"""Small, source-backed catalogue of terminal VU service components.

Pressure rating is not a loss coefficient. A conflicting axial dimension never
becomes a mounting length; a gauge is a terminal, not a through-flow fitting.
"""
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
import json
from math import isfinite


@dataclass(frozen=True)
class MeteringServiceProduct:
    id: str
    manufacturer: str
    article: str
    kind: str
    dn: int
    ports: tuple[tuple[str, str, str, str], ...]
    dimension_status: str
    dimensions_mm: object
    pn_bar: float | None
    temperature_c: tuple[float, float]
    source_ids: tuple[str, ...]
    notes: tuple[str, ...]
    range_bar: float | None = None
    country_of_manufacture: str = "unknown"
    origin_source_ids: tuple[str, ...] = ()
    dimension_source_id: str = ""

    @property
    def name(self):
        return f"{self.manufacturer} {self.article}"

    @property
    def body_length_mm(self):
        return self.dimensions_mm.get("L") if self.dimension_status in ("verified", "passport_nominal") else None

    @property
    def dimension_basis(self):
        return {"verified": "nominal", "passport_nominal": "passport_nominal"}.get(self.dimension_status, "unknown")


def load_service_products():
    raw = json.loads(Path(__file__).with_name("metering_service_products.json").read_text(encoding="utf-8"))
    rows = list(raw["parts"])
    gauge = raw["gauge"]
    for pressure in gauge["ranges_bar"]:
        rows.append({**{k: v for k, v in gauge.items() if k != "ranges_bar"},
            "id": f"rosma-tm510r-g12-{pressure}bar", "range_bar": pressure, "pn_bar": None,
            "article": f"ТМ-510Р.00 (0–{pressure / 10:g} МПа) G1/2, кл.1,5"})
    parts = {}
    for row in rows:
        ident = row["id"]
        ports, dims = row["ports"], row["dimensions_mm"]
        temperature = row["temperature_c"]
        if (ident in parts or not row["source_ids"]
            or any(s not in raw["sources"] for s in row["source_ids"])
            or row["kind"] not in ("plug", "gauge_cock", "gauge")
            or len(ports) != (2 if row["kind"] == "gauge_cock" else 1)
            or any(len(p) != 4 or p[0] != "G" or not p[1] or p[2] not in ("male", "female")
                   or p[3] not in ("thread", "flat_gasket") for p in ports)
            or row["dimension_status"] not in ("verified", "conflict", "passport_nominal")
            or (row["dimension_status"] == "passport_nominal" and
                ("L" not in dims or row.get("dimension_source_id") not in row["source_ids"]))
            or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                   for v in (*dims.values(), *((row['pn_bar'],) if row['pn_bar'] is not None else ())))
            or (row['kind'] != 'gauge' and row['pn_bar'] is None)
            or len(temperature) != 2 or temperature[0] > temperature[1]):
            raise ValueError(f"Некорректное сервисное изделие {ident}")
        parts[ident] = MeteringServiceProduct(**{**row, "ports": tuple(map(tuple, ports)),
            "dimensions_mm": MappingProxyType(dims), "temperature_c": tuple(temperature),
            "source_ids": tuple(row["source_ids"]), "notes": tuple(row["notes"])})
    return raw["sources"], parts
