"""Explicit apartment-feed quantities, independent of schematic symbols.

This is an accepted takeoff input, not a hydraulic method or product selection.
The component composition is shared with the representative water diagram.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApartmentWaterUnits:
    mode: str = "unspecified"
    cold_count: int | None = None
    hot_count: int | None = None
    # Same optional input as Studio's approved apartment-meter calculation.
    # Persist the input, not stale selected DN/model or a parsed prose note.
    design_residents: int | None = None

    def validate(self):
        issues = []
        if self.design_residents is not None and (
                type(self.design_residents) is not int or not 1 <= self.design_residents <= 1_000_000):
            issues.append("apartment_water_units.design_residents: требуется целое число от 1 до 1 000 000")
        if self.mode not in ("unspecified", "one_per_apartment", "explicit_counts"):
            issues.append("apartment_water_units.mode: неизвестная схема количества узлов")
        for key in ("cold_count", "hot_count"):
            value = getattr(self, key)
            if value is not None and (type(value) is not int or not 0 <= value <= 1_000_000):
                issues.append(f"apartment_water_units.{key}: требуется целое число от 0 до 1 000 000")
            if value is not None and self.mode != "explicit_counts":
                issues.append(f"apartment_water_units.{key}: количество допустимо только в ручном режиме")
        return issues

    def quantity(self, system, apartments):
        if self.validate():
            raise ValueError("; ".join(self.validate()))
        if system not in ("В1", "Т3"):
            raise ValueError("Квартирные узлы считаются только для В1/Т3")
        if self.mode == "one_per_apartment":
            return apartments if type(apartments) is int and apartments > 0 else None
        if self.mode == "explicit_counts":
            return self.cold_count if system == "В1" else self.hot_count
        return None

    def quantity_source(self, system, apartments):
        count = self.quantity(system, apartments)
        if count is None:
            return "Количество квартирных узлов не задано; не по символам схемы"
        if self.mode == "one_per_apartment":
            return f"Принято: 1 узел {system} на квартиру × {apartments} квартир; по 1 изделию на узел"
        return f"Задано: {count} квартирных узлов {system}; по 1 изделию на узел"

    def quantity_on_floors(self, system, apartments, floor_count, by_floor, selected):
        """A whole-house total never allocates regulators to selected floors.

        Only the accepted one-feed-per-flat mode plus a complete floor schedule
        gives a quantity. No mean occupancy, rounding or drawing multiplication.
        """
        if self.quantity(system, apartments) is None or self.mode != 'one_per_apartment':
            return None
        if type(floor_count) is not int or floor_count <= 0:
            return None
        if (not isinstance(by_floor, dict)
                or any(type(k) is not int for k in by_floor)
                or set(by_floor) != set(range(1, floor_count + 1))
                or any(type(n) is not int or n < 0 for n in by_floor.values())
                or sum(by_floor.values()) != apartments
                or not selected or len(set(selected)) != len(selected)
                or any(type(f) is not int or f not in by_floor for f in selected)):
            return None
        return sum(by_floor[f] for f in selected)


def apartment_units_from_values(values):
    """The same ordinary Studio adapter is used by reproducible control cases."""
    mode = values.get("apartment_units_mode", "unspecified")
    return ApartmentWaterUnits(mode=mode,
        cold_count=values.get("apartment_units_cold_count") if mode == "explicit_counts" else None,
        hot_count=values.get("apartment_units_hot_count") if mode == "explicit_counts" else None,
        design_residents=values.get("apartment_design_residents"))
