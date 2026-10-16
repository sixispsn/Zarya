"""L02: баланс напора и явно обозначенная квадратичная оценка кривой.

Баланс — СП 30, п. 13.11 (19). Квадратичное масштабирование потерь — оценка,
не формула СП и не замена поучасткового расчёта на разных расходах.
Все напоры должны относиться к одной согласованной расчётной схеме.
"""
from dataclasses import dataclass
import math


def finite_value(name: str, value: float | None, *, nonnegative: bool = False) -> float:
    if value is None:
        raise ValueError(f"{name}: требуется исходное значение")
    if not math.isfinite(value):
        raise ValueError(f"{name}: требуется конечное число")
    if nonnegative and value < 0:
        raise ValueError(f"{name}: значение не может быть отрицательным")
    return float(value)


def required_boost_head(h_base: float, k_sys: float, q: float) -> float:
    """Нужная добавка насоса; избыток напора источника не превращается в насос."""
    return max(0.0, h_base + k_sys * q * q)


@dataclass(frozen=True)
class PumpSystemCurve:
    q_design: float
    h_geom: float
    h_losses: float
    h_free: float
    h_available: float

    def __post_init__(self):
        finite_value("Расчётный расход", self.q_design, nonnegative=True)
        if self.q_design <= 0:
            raise ValueError("Расчётный расход должен быть больше 0")
        finite_value("Hgeom", self.h_geom)
        finite_value("Потери напора", self.h_losses, nonnegative=True)
        finite_value("Свободный напор", self.h_free, nonnegative=True)
        finite_value("Hгар", self.h_available, nonnegative=True)
        if not math.isfinite(self.k_sys):
            raise ValueError("Коэффициент кривой системы выходит за численный диапазон")
        if not math.isfinite(self.h_base) or not math.isfinite(self.signed_design_head):
            raise ValueError("Баланс напора выходит за численный диапазон")

    @property
    def h_base(self) -> float:
        # Signed! Clamping this intercept would destroy the design-point balance.
        return self.h_geom + self.h_free - self.h_available

    @property
    def k_sys(self) -> float:
        return self.h_losses / self.q_design / self.q_design

    @property
    def signed_design_head(self) -> float:
        return self.h_base + self.h_losses

    @property
    def h_required(self) -> float:
        return max(0.0, self.signed_design_head)

    def head_at(self, q: float) -> float:
        finite_value("Расход на кривой", q, nonnegative=True)
        return required_boost_head(self.h_base, self.k_sys, q)
