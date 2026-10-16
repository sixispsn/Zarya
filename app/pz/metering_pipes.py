"""Local pipe geometry of a VU, independent of hydraulic/legacy selection.

DN is not inferred from outside diameter. A declared pipe/source is not an
approved connector or mounting BOM; different materials may coexist in a VU.
"""
from dataclasses import dataclass
from math import isfinite


PIPE_ROLES = {
    "inlet": ("У1", "Труба ввода"),
    "before_meter": ("У2", "Обвязка до счётчика"),
    "after_meter": ("У3", "Обвязка после счётчика"),
    "outlet": ("У4", "Выход после обратного клапана"),
    "bypass": ("У5", "Обводная линия"),
    "fire_branch": ("У6", "Ответвление В2 до учёта"),
}
MATERIALS = {
    "unknown": "Материал не задан", "steel": "Сталь",
    "galvanized_steel": "Оцинкованная сталь", "stainless_steel": "Нержавеющая сталь",
    "copper": "Медь", "pe": "ПЭ", "ppr": "PP-R", "pex": "PE-X",
    "multilayer": "Многослойная труба", "other": "Иной материал",
}
JOINING = {
    "unknown": "Способ соединения не задан", "threaded": "Резьбовое",
    "welded": "Сварное (металл)", "flanged": "Фланцевое", "press": "Прессовое",
    "socket_fusion": "Муфтовая полифузионная сварка",
    "butt_fusion": "Стыковая сварка полимера", "electrofusion": "Электромуфтовое",
    "compression": "Компрессионное", "other": "Иное соединение",
}


@dataclass(frozen=True)
class MeteringPipeSection:
    material: str = "unknown"
    series: str = ""
    nominal_dn: int | None = None
    outer_diameter_mm: float | None = None
    wall_thickness_mm: float | None = None
    joining: str = "unknown"
    geometry_source: str = ""
    # Explicit system identity for socket/press compatibility; no brand
    # inference from the display label or the building-wide material string.
    system_id: str = ""
    # Optional versioned selection; old manual projects remain valid.
    catalogue_id: str = ""
    catalogue_fingerprint: str = ""

    @classmethod
    def from_catalogue(cls, ident: str, *, joining: str):
        """Explicit selection, never pick a pipe by the nearest DN/diameter."""
        from app.data.engineering_catalogue import get_engineering_catalogue
        c = get_engineering_catalogue()
        p = c.require(ident, kind="pipe")
        if joining not in p.joinings:
            raise ValueError("Способ соединения не предусмотрен карточкой трубы")
        return cls(material=p.material, series=p.series, nominal_dn=p.dn,
            outer_diameter_mm=p.dimensions_mm["outer_diameter_mm"],
            wall_thickness_mm=p.dimensions_mm["wall_thickness_mm"], joining=joining,
            geometry_source=f"{p.standard}; {p.locator}", system_id=p.system_id,
            catalogue_id=p.id, catalogue_fingerprint=c.fingerprint(p.id))

    def validate(self) -> list[str]:
        errors = []
        for name, choices in (("material", MATERIALS), ("joining", JOINING)):
            value = getattr(self, name)
            if not isinstance(value, str) or value not in choices:
                errors.append(f"{name}: неизвестное значение")
        for name in ("series", "geometry_source", "system_id", "catalogue_id", "catalogue_fingerprint"):
            if not isinstance(getattr(self, name), str):
                errors.append(f"{name}: требуется строка")
        if self.nominal_dn is not None and (type(self.nominal_dn) is not int or self.nominal_dn <= 0):
            errors.append("nominal_dn: требуется положительный целый DN")
        for name in ("outer_diameter_mm", "wall_thickness_mm"):
            value = getattr(self, name)
            if value is not None and (type(value) not in (int, float) or not isfinite(value) or value <= 0):
                errors.append(f"{name}: требуется положительное конечное число")
        if not errors and self.outer_diameter_mm is not None and self.wall_thickness_mm is not None:
            if 2 * self.wall_thickness_mm >= self.outer_diameter_mm:
                errors.append("толщина стенки не оставляет проходного сечения")
        if not errors and (self.catalogue_id or self.catalogue_fingerprint):
            from app.data.engineering_catalogue import get_engineering_catalogue
            c = get_engineering_catalogue()
            try:
                p = c.require(self.catalogue_id, kind="pipe")
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if self.catalogue_fingerprint != c.fingerprint(p.id):
                    errors.append("Редакция выбранной трубы изменилась или не подтверждена; повторите выбор")
                if self.joining not in p.joinings:
                    errors.append("Способ соединения не соответствует карточке трубы")
                expected = {"material":p.material, "series":p.series, "nominal_dn":p.dn,
                    "system_id":p.system_id, "outer_diameter_mm":p.dimensions_mm["outer_diameter_mm"],
                    "wall_thickness_mm":p.dimensions_mm["wall_thickness_mm"],
                    "geometry_source":f"{p.standard}; {p.locator}"}
                for key, value in expected.items():
                    if getattr(self, key) != value:
                        errors.append(f"{key}: сохранённая труба расходится с каталогом; автоматической замены нет")
        return errors

    @property
    def inner_diameter_mm(self) -> float | None:
        if self.validate() or self.outer_diameter_mm is None or self.wall_thickness_mm is None:
            return None
        # Geometry only. Never replace legacy hydraulic diameter/roughness.
        return self.outer_diameter_mm - 2 * self.wall_thickness_mm


def pipe_checks(detail, *, bypass, fire_branch, meter_dn=None):
    """Contradictions vs. unresolved installation decisions; no auto-substitution."""
    errors, pending = [], []
    expected = {"inlet": detail.inlet_dn, "before_meter": meter_dn,
                "after_meter": meter_dn, "bypass": detail.bypass_dn,
                "fire_branch": detail.fire_branch_dn}
    for role, (_, title) in PIPE_ROLES.items():
        section = detail.pipe_sections.get(role)
        active = (bypass if role == "bypass" else fire_branch if role == "fire_branch" else True)
        if section is not None and not active:
            errors.append(f"{title}: труба задана, но этой ветви в принятой схеме нет")
        elif active and section is None:
            pending.append(f"{title}: материал и размер не заданы")
        elif section is not None:
            errors.extend(f"{title}: {e}" for e in section.validate())
            if (section.nominal_dn is not None and expected.get(role) is not None
                    and section.nominal_dn != expected[role]):
                errors.append(f"{title}: DN трубы расходится с DN принятой схемы; "
                              "нужна отдельная привязка перехода, автоматической замены нет")
            if section.material == "unknown" or section.inner_diameter_mm is None:
                pending.append(f"{title}: нужны материал, наружный диаметр и толщина стенки")
            if not section.geometry_source.strip():
                pending.append(f"{title}: источник размеров не задан")
            if section.joining == "unknown":
                pending.append(f"{title}: способ соединения не задан")
    if detail.pipe_sections:
        pending.extend((
            "Соединители подбираются по обоим присоединениям: системе труб, размерам, резьбе/фланцам и исполнению. "
            "Совпадение DN не подтверждает совместимость; смена материала требует проверки переходной детали.",
            "Заданные трубы не подтверждают пригодность по давлению, температуре, качеству воды и условиям В2. "
            "Требуются паспорта конкретных исполнений, крепления и компенсация перемещений.",
        ))
    return tuple(errors), tuple(pending)


def support_pipe(detail):
    """Bind a clamp to current local pipe, never to a stale manual DN/diameter."""
    if not detail.support_pipe_section:
        return detail.support_pipe_outer_diameter_mm, detail.support_pipe_material, ()
    section = detail.pipe_sections.get(detail.support_pipe_section)
    if section is None:
        return None, "unknown", ("Участок трубы для крепления не задан",)
    errors = []
    diameter = section.outer_diameter_mm
    if (detail.support_pipe_outer_diameter_mm is not None
            and detail.support_pipe_outer_diameter_mm != diameter):
        errors.append("Ручной диаметр крепления расходится с привязанным участком трубы")
    # Legacy generic 'plastic' remains an explicit local input, not a pipe type.
    material = section.material
    old_material = detail.support_pipe_material
    equivalent = (old_material == "plastic" and material in ("pe", "ppr", "pex", "multilayer"))
    if old_material != "unknown" and old_material != material and not equivalent:
        errors.append("Ручной материал крепления расходится с привязанным участком трубы")
    return diameter, material, tuple(errors)
