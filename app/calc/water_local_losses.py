"""Местные потери холодного водопровода: СП 30.13330.2020, 8.28 (15).

Процент применяется к линейным потерям, не к геометрической высоте,
потерям водомера/нагревателя или готовой сумме с местными сопротивлениями.
"""

import math
from types import MappingProxyType


LOCAL_LOSS_FACTORS = MappingProxyType({
    "domestic": 0.30,
    "combined": 0.20,
    "industrial": 0.20,
    "industrial_fire": 0.15,
    "fire": 0.10,
})


def local_loss_factor(network_kind: str, supplied: float | None = None) -> float:
    """Нормативный k_l; старое ручное значение проверяется, а не скрывает норму."""
    if network_kind not in LOCAL_LOSS_FACTORS:
        raise ValueError(f"Неизвестный тип сети для k_l по СП 30, п. 8.28: {network_kind}")
    factor = LOCAL_LOSS_FACTORS[network_kind]
    if supplied is not None and (
        isinstance(supplied, bool) or not math.isfinite(supplied)
        or not math.isclose(supplied, factor, rel_tol=0, abs_tol=1e-12)
    ):
        raise ValueError(
            f"СП 30, п. 8.28: для сети {network_kind} k_l={factor:g}; "
            f"заданное значение {supplied} не соответствует типу сети"
        )
    return factor


def with_fire_topology(network_kind: str, *, combined: bool) -> str:
    """Уточнить совмещение, сохранив явно заданное назначение сети.

Производственный водопровод нельзя определять только по назначению здания:
в производственном здании также может быть хозяйственно-питьевая сеть.
"""
    local_loss_factor(network_kind)
    if network_kind in {"industrial", "industrial_fire"}:
        return "industrial_fire" if combined else "industrial"
    return "combined" if combined else "domestic"
