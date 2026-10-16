"""Persistent, explicit fan geometry. Confirmation is not normative approval."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from math import isfinite


@dataclass(frozen=True)
class FanRiserPosition:
    riser_id: str
    x_m: float
    lower_port_m: float
    collector_m: float


@dataclass(frozen=True)
class FanRoofDetail:
    terminal_id: str
    roof_level_m: float
    risers: tuple[FanRiserPosition, ...]
    vent_riser_id: str
    condensate_riser_id: str
    source_ref: str
    scale: float = 50.


@dataclass(frozen=True)
class FanValveDetail:
    terminal_id: str
    floor_level_m: float
    ceiling_level_m: float
    highest_fixture_rim_m: float
    connection_level_m: float
    source_ref: str
    outline_ref: str
    connection_outer_diameter_mm: float
    scale: float = 20.


def _number(value, name: str, *, positive: bool = False) -> None:
    if type(value) not in (int, float) or not isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name}: требуется конечное {'положительное ' if positive else ''}число")


def _text(value, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: требуется непустая строка")


def _mapping(value, cls) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{cls.__name__}: ожидается объект")
    unknown = set(value) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"{cls.__name__}: неизвестные поля: {', '.join(sorted(unknown))}")
    return dict(value)


@dataclass(frozen=True)
class FanGeometryInput:
    roofs: tuple[FanRoofDetail, ...] = ()
    valves: tuple[FanValveDetail, ...] = ()
    confirmed: bool = False
    confirmation_ref: str = ""

    def __post_init__(self):
        if type(self.confirmed) is not bool or not isinstance(self.confirmation_ref, str):
            raise ValueError("Подтверждение геометрии: неверный тип данных")
        if not isinstance(self.roofs, tuple) or not isinstance(self.valves, tuple):
            raise ValueError("Группы геометрии должны быть кортежами")
        ids: set[str] = set()
        members: set[str] = set()
        for detail in (*self.roofs, *self.valves):
            if not isinstance(detail, (FanRoofDetail, FanValveDetail)):
                raise ValueError("Неизвестный тип геометрии фанового узла")
            for key in ("terminal_id", "source_ref"):
                _text(getattr(detail, key), key)
            _number(detail.scale, "scale", positive=True)
            if detail.terminal_id in ids:
                raise ValueError(f"Повтор узла: {detail.terminal_id}")
            ids.add(detail.terminal_id)
        for d in self.roofs:
            if not isinstance(d, FanRoofDetail):
                raise ValueError("roofs: ожидаются узлы кровли")
            _number(d.roof_level_m, "roof_level_m")
            if not isinstance(d.risers, tuple) or not d.risers:
                raise ValueError("В группе кровли нужны явно заданные стояки")
            for r in d.risers:
                if not isinstance(r, FanRiserPosition):
                    raise ValueError("Неверный тип привязки стояка")
                _text(r.riser_id, "riser_id")
                if r.riser_id in members:
                    raise ValueError(f"Повтор стояка: {r.riser_id}")
                members.add(r.riser_id)
                for key in ("x_m", "lower_port_m", "collector_m"):
                    _number(getattr(r, key), key)
                if not r.lower_port_m < r.collector_m < d.roof_level_m:
                    raise ValueError(f"{r.riser_id}: порт < коллектор < кровля — проверьте отметки")
            ordered = sorted(d.risers, key=lambda r: r.x_m)
            if len({r.x_m for r in ordered}) != len(ordered):
                raise ValueError("Оси стояков группы должны различаться")
            if d.vent_riser_id not in {r.riser_id for r in ordered}:
                raise ValueError("Вытяжка должна быть привязана к стояку группы")
            if ordered[-1].riser_id == d.condensate_riser_id:
                ordered.reverse()
            if ordered[0].riser_id != d.condensate_riser_id or any(
                b.collector_m <= a.collector_m for a, b in zip(ordered, ordered[1:])
            ):
                raise ValueError("Коллектор должен стекать к выбранному крайнему стояку без карманов")
        for d in self.valves:
            if not isinstance(d, FanValveDetail):
                raise ValueError("valves: ожидаются узлы клапанов")
            for key in ("floor_level_m", "ceiling_level_m", "highest_fixture_rim_m", "connection_level_m"):
                _number(getattr(d, key), key)
            _number(d.connection_outer_diameter_mm, "connection_outer_diameter_mm", positive=True)
            _text(d.outline_ref, "outline_ref")
            if not d.floor_level_m < d.highest_fixture_rim_m < d.connection_level_m < d.ceiling_level_m:
                raise ValueError("Клапан: пол < борт прибора < присоединение < потолок")
        if self.confirmed:
            if not ids:
                raise ValueError("Нельзя подтвердить пустую геометрию")
            _text(self.confirmation_ref, "Основание подтверждения геометрии")

    @classmethod
    def from_mapping(cls, value) -> FanGeometryInput:
        row = _mapping(value, cls)
        for key, kind in (("roofs", FanRoofDetail), ("valves", FanValveDetail)):
            raw = row.get(key, [])
            if not isinstance(raw, (list, tuple)):
                raise ValueError(f"{key}: ожидается список")
            details = []
            for item in raw:
                detail = _mapping(item, kind)
                if kind is FanRoofDetail:
                    positions = detail.get("risers", [])
                    if not isinstance(positions, (list, tuple)):
                        raise ValueError("risers: ожидается список")
                    detail["risers"] = tuple(FanRiserPosition(**_mapping(p, FanRiserPosition)) for p in positions)
                details.append(kind(**detail))
            row[key] = tuple(details)
        return cls(**row)

    def to_mapping(self) -> dict:
        result = asdict(self)
        result["roofs"] = [dict(d, risers=list(d["risers"])) for d in result["roofs"]]
        result["valves"] = list(result["valves"])
        return result
