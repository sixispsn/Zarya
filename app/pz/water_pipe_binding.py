"""Read-only binding of V1 calculation geometry to drawings and schedules.

This is not a sizing algorithm. Only explicit D×s with a matching hydraulic
inner diameter is accepted. Names identify a representative section, not a
complete building network; different sizes in one group remain unresolved.
"""
from dataclasses import dataclass
import math
import re

from app.data.pipe_catalog import steel_nominal_connection


@dataclass(frozen=True)
class DrawingPipe:
    material: str
    family: str
    outer_mm: float
    wall_mm: float
    dn: int | None = None
    mass_kg_m: float | None = None
    dn_basis: str = ""

    @property
    def inner_mm(self):
        return round(self.outer_mm - 2 * self.wall_mm, 6)

    @property
    def size_label(self):
        return f"Ø{self.outer_mm:g}×{self.wall_mm:g}"

    @property
    def label(self):
        return self.size_label.replace(".", ",")


@dataclass(frozen=True)
class PipeBinding:
    role: str
    pipe: DrawingPipe | None
    source_ids: tuple[str, ...]
    issue: str = ""

    @property
    def label(self):
        return self.pipe.label if self.pipe else "Ø по расчёту"


ROLES = {"inlet": "ввод", "main": "магистраль", "riser": "стояк", "apartment": "подводка квартиры"}


def _role(section):
    if getattr(section, "role", "") == "input":
        return "inlet"
    words = re.split(r"[\s_\-]+", section.section_id.casefold())
    for role, names in (
        ("main", {"магистраль", "main"}),
        ("riser", {"стояк", "riser"}),
        ("apartment", {"квартира", "apartment"}),
        ("inlet", {"подвод", "ввод", "inlet"}),
    ):
        if set(words) & names:
            return role
    return None


def _geometry(section):
    material = section.material or ""
    matches = re.findall(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*[xх×]\s*(\d+(?:[.,]\d+)?)", material)
    if len(matches) != 1:
        return None
    outer, wall = (float(x.replace(",", ".")) for x in matches[0])
    inner = section.inner_diameter_mm
    if (inner is None or not math.isfinite(inner) or wall <= 0 or outer <= 2 * wall
            or not math.isclose(outer - 2 * wall, inner, abs_tol=.05)):
        return None
    name = material.casefold()
    family = ("pex" if "pe-x" in name or "сшит" in name else
              "steel" if "сталь" in name or "стальн" in name else
              "pe" if "пэ" in name or "полиэтилен" in name else "unknown")
    # No rounding to the nearest nominal size. 76×3.5 is NOT VGP 75.5×4.
    connection = steel_nominal_connection(outer, wall, material) if family == "steel" else None
    return DrawingPipe(material, family, outer, wall,
        dn=connection.dn if connection else None,
        dn_basis=connection.basis if connection else "")


def bind_v1_pipes(project) -> dict[str, PipeBinding]:
    network = project.v1_network
    groups = {role: [] for role in ROLES}
    sections = network.sections if network else project.v1_sections
    for section in sections:
        role = _role(section)
        if role:
            groups[role].append((section.section_id, section))
    if network:
        groups["inlet"] = [(s.inlet_id, s) for s in network.inlets]
    result = {}
    for role, rows in groups.items():
        pipes = [_geometry(s) for _, s in rows]
        unique = {(p.family, p.outer_mm, p.wall_mm, p.material.casefold().strip()) for p in pipes if p}
        if rows and all(pipes) and len(unique) == 1 and pipes[0].family != "unknown":
            result[role] = PipeBinding(role, pipes[0], tuple(i for i, _ in rows))
        else:
            issue = ("разные сечения/материалы; требуется выбор характерной ветви" if len(unique) > 1 else
                     "нет согласованных материала, Dн×s и dвн")
            result[role] = PipeBinding(role, None, tuple(i for i, _ in rows), f"В1, {ROLES[role]}: {issue}")
    return result


def bind_t3_pipes(project) -> dict[str, PipeBinding]:
    """Only explicit T3 sections; never borrow V1 sizes for hot water/T4."""
    groups = {role: [] for role in ("feed", "main", "riser", "apartment")}
    for section in project.t3_sections:
        if section.section_id.casefold() == "в1-к-водонагревателю":
            groups["feed"].append(section)
        elif section.section_id.casefold().startswith(("т3-", "t3-")):
            role = _role(section)
            if role in groups:
                groups[role].append(section)
    result = {}
    for role, sections in groups.items():
        pipes = [_geometry(s) for s in sections]
        distinct = {(p.family, p.outer_mm, p.wall_mm, p.material.casefold().strip()) for p in pipes if p}
        valid = bool(pipes) and all(pipes) and len(distinct) == 1 and pipes[0].family != "unknown"
        result[role] = PipeBinding(role, pipes[0] if valid else None,
            tuple(s.section_id for s in sections), "" if valid else "Т3: геометрия характерного участка не подтверждена")
    return result
