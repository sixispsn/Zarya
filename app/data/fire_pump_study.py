"""Verified source rows for L06 comparison, NOT the production pump catalog.

Q-H is the bare pump characteristic; internal PFFS losses, tolerances and
NPSH are not silently invented. One duty pump; a reserve never doubles Q.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FirePumpStudyCandidate:
    id: str
    pump_model: str
    station_model: str
    power_per_pump_kw: float
    station_connection_dn: int
    curve: tuple[tuple[float, float], ...]
    curve_pdf_page: int
    station_pdf_page: int
    station_printed_page: int
    curve_source: str = "Каталог CDM, CDMF.pdf"
    curve_sha256: str = "abc39dac7beba67fe392c27a427f3f52c629474244901d8cc20deb7b6fccfac0"
    station_source: str = "Каталог PFFS.pdf"
    station_sha256: str = "fab7ea4dc4c37bf0d7c865f8398165139e6d0a77cc0689b039cc7dafc683dc39"
    evidence: str = "user_supplied_manufacturer_catalog_2025"
    selection_confirmed: bool = False
    unresolved: tuple[str, ...] = (
        "PFFS_internal_losses_and_guaranteed_station_curve",
        "curve_tolerances_and_maximum_shutoff_head",
        "NPSH_and_manufacturer_operating_range",
        "complete_fire_configuration_and_automation",
        "actual_cabinet_and_regulator_characteristics",
    )


STUDY_CANDIDATES = (
    FirePumpStudyCandidate(
        "cnp-cdm20-4", "CNP CDM20-4", "PFFS 2 CDM20-4 D", 5.5, 80,
        tuple(zip((0, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 29),
                  (55.5, 52.5, 51, 50, 49, 48, 46, 44, 41, 37, 33, 31.5))),
        31, 38, 39),
    FirePumpStudyCandidate(
        "cnp-cdm32-3", "CNP CDM32-3", "PFFS 2 CDM32-3 D", 5.5, 100,
        tuple(zip((0, 16, 20, 24, 28, 32, 36, 40),
                  (57, 54, 51, 48, 44, 40, 35, 27))),
        33, 40, 40),
)
