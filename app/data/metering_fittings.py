"""Exact manufacturer fitting geometry. No inferred DN, pipe material or loss.

Elbows store centre-to-face A, not a fictitious axial L. Multi-port fittings
store both run and branch sizes; a tee is never a four-port service assembly.
"""
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType


@dataclass(frozen=True)
class FittingPort:
    dn: int
    connection: str
    thread: str = ""
    sex: str = "female"
    drilling: tuple[float, int, float] | None = None


@dataclass(frozen=True)
class MeteringFitting:
    id: str
    manufacturer: str
    model: str
    article: str
    kind: str
    material: str
    ports: tuple[FittingPort, ...]  # in, out, branch up, branch down
    dimensions_mm: object
    pn_bar: float
    temperature_c: tuple[float, float]
    source_ids: tuple[str, ...]
    source_page: int
    notes: tuple[str, ...] = ()
    dimension_status: str = "verified"
    dimension_basis: str = "nominal"
    country_of_manufacture: str = "unknown"
    origin_source_ids: tuple[str, ...] = ()
    pressure_temperature: tuple[tuple[float, float], ...] = ()

    @property
    def body_length_mm(self):
        return self.dimensions_mm.get("L")

    @property
    def large_dn(self):
        return max(p.dn for p in self.ports)

    @property
    def small_dn(self):
        return min(p.dn for p in self.ports)

    @property
    def branch_length_mm(self):
        return (self.body_length_mm / 2 if self.kind == "cross"
                else self.dimensions_mm.get("branch_length"))

    @property
    def name(self):
        return self.model + " DN" + "×".join(str(p.dn) for p in self.ports)


def load_fittings(raw):
    result = {}
    for family in raw["families"]:
        for values in family["rows"]:
            if len(values) != len(family["columns"]):
                raise ValueError("Некорректная строка фасонины")
            row = dict(zip(family["columns"], values))
            kind, connection, dn = family["kind"], family["connection"], row["dn"]
            other = row.get("small_dn", row.get("branch_dn", dn))
            if (kind not in ("tee", "cross", "elbow90", "coupling", "reducer")
                    or connection not in ("threaded", "flanged")
                    or any(type(n) is not int or n <= 0 for n in (dn, other))):
                raise ValueError("Некорректные порты фасонины")
            ident = family["id"] + f"-dn{dn}" + (f"x{other}" if "small_dn" in row or "branch_dn" in row else "")
            if ident in result or family["source_id"] not in raw["sources"]:
                raise ValueError("Дубликат/отсутствующий источник фасонины")

            def port(size, thread):
                return FittingPort(size, connection, thread if connection == "threaded" else "",
                    "female" if connection == "threaded" else "flanged",
                    tuple(raw["flanges"][str(size)]) if connection == "flanged" else None)

            main = port(dn, row.get("thread", ""))
            ports = [main, port(other, "") if kind == "reducer" else main]
            if kind in ("tee", "cross"):
                ports.append(port(other, row.get("branch_thread", row.get("thread", ""))))
            if kind == "cross":
                ports.append(ports[-1])
            dimensions = {k: row[k] for k in ("L", "A", "branch_length") if k in row}
            if (not dimensions or any(type(v) not in (float, int) or not isfinite(v) or v <= 0
                                       for v in dimensions.values())
                    or (kind != "elbow90" and "L" not in dimensions)
                    or any(p.connection == "threaded" and not p.thread for p in ports)):
                raise ValueError("Не подтверждены размеры фасонины")
            pn = family.get("pn_bar", 40 if dn <= 25 else 25)
            result[ident] = MeteringFitting(ident, family["manufacturer"], family["model"],
                row.get("article", ""), kind, family["material"], tuple(ports),
                MappingProxyType(dimensions), pn,
                tuple(family["temperature_c"]), (family["source_id"],), family["page"],
                tuple(family.get("notes", ())) + ("Размер корпуса не включает уплотнение, посадки и монтажные зазоры.",),
                pressure_temperature=tuple(map(tuple, vtr_pressure_table(pn)))
                    if family["source_id"] == "vtr-fittings-20261012" else ())
    return MappingProxyType(result)


def extend_thread_rows(raw, supplement):
    """Expand printed rows into the existing, already checked connector types."""
    for family_key, target in (("thread_nipples", "thread_connectors"), ("thread_reducers", "reducers")):
        family = supplement[family_key]
        source = ["vtr-fittings-20261012", family["drawing_source_id"]]
        for values in family["rows"]:
            if len(values) != len(family["columns"]):
                raise ValueError("Некорректная строка резьбовой фасонины")
            r = dict(zip(family["columns"], values))
            dn = r.get("dn", r.get("large_dn"))
            pn = 40 if dn <= 25 else 25  # Passport §3.1, not a geometry interpolation.
            conflict = r["L"] != r["drawing_L"]
            # Neither rounding nor a newer passport silently resolves a
            # disagreement with the manufacturer's still-published drawing.
            dimensions = ({"passport_L":r["L"], "drawing_L":r["drawing_L"]}
                          if conflict else {"L":r["L"]})
            base = dict(manufacturer="VALTEC", connection_standard="G", pn_bar=pn,
                        temperature_c=[-40,250], dimension_status="conflict" if conflict else "verified",
                        dimensions_mm=dimensions, source_ids=source,
                        pressure_temperature=vtr_pressure_table(pn))
            if target == "thread_connectors":
                base.update(id="valtec-vtr582-"+r["suffix"], article="VTr.582.N."+r["suffix"],
                    equipment_thread=r["thread"], pipe_connector_thread=r["thread"],
                    equipment_sex="male", pipe_connector_sex="male")
            else:
                base.update(id="valtec-vtr580-"+r["suffix"], article="VTr.580.N."+r["suffix"],
                    large_dn=r["large_dn"], small_dn=r["small_dn"], large_thread=r["large_thread"],
                    small_thread=r["small_thread"], large_sex="male", small_sex="male")
            raw[target].append(base)


def vtr_pressure_table(pn):
    """Published §3.1 points. Not interpolation or constant PN up to +250°C."""
    return [[120,pn],[200,32 if pn == 40 else 20],[250,27 if pn == 40 else 17]]
