"""Bind existing loss results to an explicit suction path; no new hydraulics.

A result may cover several physical components (e.g. a pipe with its local
allowance). Each component has exactly one owner. Results from another flow
or temperature are not rescaled or accepted as the maximum-mode result.
"""
from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class SuctionLoss:
    id: str
    covers: tuple[str, ...]
    loss_m: float | None = None
    flow_m3h: float | None = None
    temperature_c: float | None = None
    basis: str = ""


@dataclass(frozen=True)
class SuctionLossResult:
    status: str
    total_loss_m: float | None
    known_loss_m: float
    missing_components: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    note: str = ("Сумма готовых потерь одного явно заданного пути и режима. "
                 "Без повторной процентной надбавки; не расчёт распределения по параллельным ветвям.")


def bind_suction_losses(required_components, losses, *, max_flow_m3h,
                        temperature_c, path_basis):
    """No guessed zero, sum of alternative paths, or partial final total."""
    required = tuple(required_components)
    if (not required or any(not isinstance(x, str) or not x.strip() for x in required)
            or len(set(required)) != len(required)):
        raise ValueError("Путь всасывания: нужны непустые уникальные ID компонентов")
    for name, value in (("max_flow_m3h", max_flow_m3h), ("temperature_c", temperature_c)):
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(name + ": требуется конечное число")
    if max_flow_m3h is not None and max_flow_m3h <= 0:
        raise ValueError("Максимальная подача должна быть положительной")
    issues = []
    if max_flow_m3h is None:
        issues.append("Не задан максимальный рабочий расход пути")
    if temperature_c is None:
        issues.append("Не задана температура воды")
    if not path_basis.strip():
        issues.append("Не заданы границы и режим пути всасывания")
    owners, ids, covered, rows, values = {}, set(), set(), [], []
    for loss in losses:
        if not loss.id.strip() or loss.id in ids:
            raise ValueError("Потери: пустой или повторный ID результата")
        ids.add(loss.id)
        if not loss.covers or len(set(loss.covers)) != len(loss.covers):
            raise ValueError(loss.id + ": пустой или повторный состав покрытия")
        for component in loss.covers:
            if component not in required:
                raise ValueError(loss.id + ": компонент вне выбранного пути: " + component)
            if component in owners:
                raise ValueError("Повторный учёт " + component + ": " + owners[component] + " / " + loss.id)
            owners[component] = loss.id
        for name in ("loss_m", "flow_m3h", "temperature_c"):
            value = getattr(loss, name)
            if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError(loss.id + ": требуется конечное число " + name)
        if loss.loss_m is not None and loss.loss_m < 0:
            raise ValueError(loss.id + ": отрицательные потери")
        if loss.flow_m3h is not None and loss.flow_m3h <= 0:
            raise ValueError(loss.id + ": расход должен быть положительным")
        missing = [name for name in ("loss_m", "flow_m3h", "temperature_c")
                   if getattr(loss, name) is None]
        if not loss.basis.strip():
            missing.append("basis")
        # Tiny representation noise (l/s -> m³/h) is not a new flow regime.
        # No engineering tolerance or scaling from Qdesign to Qmax is allowed.
        if (max_flow_m3h is not None and loss.flow_m3h is not None
                and not math.isclose(loss.flow_m3h, max_flow_m3h, rel_tol=1e-12, abs_tol=0)):
            missing.append("flow_at_maximum_mode")
        if (temperature_c is not None and loss.temperature_c is not None
                and loss.temperature_c != temperature_c):
            missing.append("temperature_at_mode")
        if max_flow_m3h is None or temperature_c is None:
            missing.append("path_mode")
        valid = not missing
        rows.append(dict(id=loss.id, covers=list(loss.covers), loss_m=loss.loss_m,
                         flow_m3h=loss.flow_m3h, temperature_c=loss.temperature_c,
                         basis=loss.basis, status="bound" if valid else "needs_data", missing=missing))
        if valid:
            values.append(loss.loss_m)
            covered.update(loss.covers)
    missing_components = [c for c in required if c not in covered]
    try:
        known = math.fsum(values)
    except OverflowError as error:
        raise ValueError("Переполнение суммы потерь") from error
    if not math.isfinite(known):
        raise ValueError("Переполнение суммы потерь")
    complete = not missing_components and not issues
    return SuctionLossResult("bound" if complete else "needs_data",
                             known if complete else None, known,
                             missing_components, rows, issues)
