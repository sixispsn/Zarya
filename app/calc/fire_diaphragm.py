"""SP10 Appendix B input preparation, not a guessed aperture formula.

Amendment 1 replaces B.2.1: P is the pressure DIFFERENCE to dissipate.
The source nomogram is a raster, not a certified loss curve for an actual item.
This module deliberately returns no aperture or discharge coefficient.
"""
from dataclasses import dataclass
from math import isfinite, isclose

from app.calc.fire_hydraulics import MPA_TO_M

NORMATIVE_SOURCES = (
    {'file': 'SP10.13130.2020.pdf', 'pdf_page': 35, 'clause': 'Приложение Б, номограмма',
     'sha256': '58126f661c57fe2e53d86c0bc0e202bfba395e8563eaf5c5875db437185ad86a'},
    {'file': 'sp-10.13130-izm.1.pdf', 'pdf_page': 33, 'printed_page': 32,
     'clause': 'Б.2.1: разница фактического и необходимого давлений',
     'sha256': '930d6d249938dba8a9175791ed0576648db367a461e89a246296d596725c2225'},
)


@dataclass(frozen=True)
class DiaphragmNomogramInputs:
    valve_dn: int
    flow_lps: float
    inlet_pressure_mpa: float
    required_outlet_pressure_mpa: float
    pressure_drop_mpa: float
    pressure_axis_value: float
    within_printed_axes: bool
    source: str = 'СП 10.13130.2020, приложение Б; Б.2.1 в редакции изменения 1'
    aperture_mm: float | None = None
    selection_confirmed: bool = False


def prepare_nomogram_inputs(*, valve_dn, flow_lps, inlet_head_m, required_outlet_head_m):
    """All heads share the valve elevation. P axis = 100*(p_in-p_out), MPa.

    Published axes: q=2.5..10 l/s, P=2..70 (0.02..0.70 MPa).
    An out-of-axis point remains an explicit unsupported graphical reading;
    it is never clamped or extrapolated. DN is the valve, not the aperture.
    """
    if valve_dn not in (50, 65):
        raise ValueError('Appendix B has only DN50 and DN65 valve scales')
    if (not all(isfinite(v) for v in (flow_lps, inlet_head_m, required_outlet_head_m))
            or flow_lps <= 0 or required_outlet_head_m < 0
            or inlet_head_m <= required_outlet_head_m):
        raise ValueError('Positive flow and a positive pressure difference required')
    drop = (inlet_head_m-required_outlet_head_m)/MPA_TO_M
    # Include exact printed boundaries despite binary subtraction roundoff;
    # this is not an engineering tolerance or permission to extrapolate.
    inside_drop = ((drop >= .02 or isclose(drop,.02,rel_tol=1e-12))
                   and (drop <= .70 or isclose(drop,.70,rel_tol=1e-12)))
    return DiaphragmNomogramInputs(valve_dn, flow_lps, inlet_head_m/MPA_TO_M,
        required_outlet_head_m/MPA_TO_M, drop, drop*100,
        inside_drop and 2.5 <= flow_lps <= 10)
