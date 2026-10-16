"""Explicit NPSHa balance, CNP CDM/CDMF catalogue, p. 18.

Separate manufacturer method, not a replacement for the legacy pump selector.
Hmax = 10.2*Pb - NPSHr - Hf - Hv - Hs, H = z_pump - z_source.
Hence NPSHa = 10.2*Pb + z_source - z_pump - Hf - Hv.
All pressures here are absolute unless explicitly identified as gauge pressure.
No temperature correlation, source elevation, losses or operating flow is guessed.
"""
from dataclasses import dataclass, field
import math


METHOD = "cnp_cdm_cdmf_p18"
FORMULA = "NPSHa = 10.2·Pb(abs) + z_source - z_pump - Hf - Hv"
SOURCE = "CNP CDM/CDMF, каталог 24.11.2025, с. 18"


@dataclass(frozen=True)
class NpshaInput:
    pressure_kind: str | None = None  # absolute / gauge, never inferred
    pressure_bar: float | None = None
    atmospheric_pressure_bar: float | None = None  # only for gauge pressure
    source_elevation_m: float | None = None
    pump_elevation_m: float | None = None
    suction_losses_m: float | None = None  # complete path, at max operating flow
    vapor_head_m: float | None = None  # explicit Hv from source for temperature
    max_flow_m3h: float | None = None  # max operating flow of one pump, not Qdesign
    temperature_c: float | None = None
    basis: str = ""  # source pressure/datum, flow mode, losses and Hv reference
    npshr_m: float | None = None  # at the same maximum operating flow
    npshr_basis: str = ""  # model / curve / flow
    safety_margin_m: float = 0.5  # published CNP minimum, visible to user


@dataclass(frozen=True)
class NpshaResult:
    status: str
    available_m: float | None = None
    required_m: float | None = None  # NPSHr + Hs
    margin_m: float | None = None  # signed difference; never rounded for check
    check_ok: bool | None = None
    absolute_pressure_bar: float | None = None
    elevation_difference_m: float | None = None
    missing: list[str] = field(default_factory=list)
    method: str = METHOD
    formula: str = FORMULA
    source: str = SOURCE
    notes: tuple[str, ...] = (
        "Проверка только заданного режима по методике CNP, не разрешение пуска.",
        "Hf и NPSHr должны относиться к максимальной рабочей подаче; резервный насос не суммируется.",
        "Hf включает весь путь до всасывающего патрубка, в том числе ВУ, фильтры и общие участки, без повторного учёта.",
        "Hv задаётся с основанием при расчётной температуре; по температуре автоматически не вычисляется.",
    )


def calculate_npsha(data: NpshaInput) -> NpshaResult:
    """Return incomplete evidence explicitly; invalid supplied data raise ValueError."""
    if data.pressure_kind not in (None, "absolute", "gauge"):
        raise ValueError("Укажите вид давления: absolute или gauge")
    numbers = ("pressure_bar", "atmospheric_pressure_bar", "source_elevation_m",
               "pump_elevation_m", "suction_losses_m", "vapor_head_m", "max_flow_m3h",
               "temperature_c", "npshr_m", "safety_margin_m")
    for name in numbers:
        value = getattr(data, name)
        if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(f"{name}: требуется конечное число")
    for name in ("suction_losses_m", "vapor_head_m", "npshr_m"):
        value = getattr(data, name)
        if value is not None and value < 0:
            raise ValueError(f"{name}: значение не может быть отрицательным")
    for name in ("atmospheric_pressure_bar", "max_flow_m3h"):
        value = getattr(data, name)
        if value is not None and value <= 0:
            raise ValueError(f"{name}: требуется положительное значение")
    if data.safety_margin_m is None or data.safety_margin_m < 0.5:
        raise ValueError("Запас Hs по CNP должен быть не менее 0,5 м")
    if data.pressure_kind == "absolute" and data.atmospheric_pressure_bar is not None:
        raise ValueError("К абсолютному давлению атмосферное повторно не прибавляется")
    pressure = data.pressure_bar
    if data.pressure_kind == "gauge":
        pressure = (pressure + data.atmospheric_pressure_bar
                    if pressure is not None and data.atmospheric_pressure_bar is not None else None)
    if data.pressure_kind is not None and pressure is not None and pressure <= 0:
        raise ValueError("Абсолютное давление должно быть положительным")

    required = ["pressure_kind", "pressure_bar", "source_elevation_m", "pump_elevation_m",
                "suction_losses_m", "vapor_head_m", "max_flow_m3h", "temperature_c"]
    if data.pressure_kind == "gauge":
        required.append("atmospheric_pressure_bar")
    missing = [name for name in required if getattr(data, name) is None]
    if not data.basis.strip():
        missing.append("basis")
    if missing:
        return NpshaResult(status="needs_data", missing=missing)

    delta = data.source_elevation_m - data.pump_elevation_m
    available = 10.2 * pressure + delta - data.suction_losses_m - data.vapor_head_m
    if not math.isfinite(available):
        raise ValueError("Переполнение расчёта NPSHa: проверьте исходные данные")
    required_head = margin = ok = None
    status = "available_only"
    if data.npshr_m is None:
        missing.append("npshr_m")
    if not data.npshr_basis.strip():
        missing.append("npshr_basis")
    if not missing:
        required_head = data.npshr_m + data.safety_margin_m
        margin = available - required_head
        if not math.isfinite(required_head) or not math.isfinite(margin):
            raise ValueError("Переполнение сравнения NPSH: проверьте исходные данные")
        ok = available >= required_head
        status = "margin_satisfied" if ok else "insufficient_margin"
    return NpshaResult(status=status, available_m=available, required_m=required_head,
                       margin_m=margin, check_ok=ok, absolute_pressure_bar=pressure,
                       elevation_difference_m=delta, missing=missing)
