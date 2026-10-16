"""Reproducible ruler construction of SP10 Appendix B, not a product passport.

The logarithmic P/q axes are located between printed ticks, then their points
are joined by a straight line (B.2.2-4). Aperture ticks are read graphically.
No orifice coefficient Cd, inverse-fourth-power formula or extrapolation.
"""
from dataclasses import dataclass
from math import isfinite, log

from app.data.fire_diaphragm_nomogram import PRESSURE_TICKS, FLOW_TICKS, DN50_TICKS


def _point(ticks, value, *, logarithmic=False):
    if not isfinite(value):
        raise ValueError('Finite graph input required')
    f=log if logarithmic else lambda v:v
    for a,b in zip(ticks,ticks[1:]):
        if min(a[0],b[0])-1e-12 <= value <= max(a[0],b[0])+1e-12:
            t=(f(value)-f(a[0]))/(f(b[0])-f(a[0]))
            return (a[1]+t*(b[1]-a[1]),a[2]+t*(b[2]-a[2]))
    raise ValueError('Outside transcribed graph axis; extrapolation forbidden')


def _cross(a,b): return a[0]*b[1]-a[1]*b[0]


def _diameter_ticks(offset_px):
    if not isfinite(offset_px) or abs(offset_px)>2:
        raise ValueError('Only an explicit graphical sensitivity of up to 2 native pixels is supported')
    return tuple((d,x,y+offset_px) for d,x,y in DN50_TICKS)


def _read_crossing(start,end,ticks,*,logarithmic=False):
    """Intersect the ruler's full line with the finite tick-scale segments."""
    direction=(end[0]-start[0],end[1]-start[1])
    for a,b in zip(ticks,ticks[1:]):
        span=(b[1]-a[1],b[2]-a[2])
        origin=(a[1]-start[0],a[2]-start[1])
        denominator=_cross(direction,span)
        if abs(denominator)<1e-12: continue
        t=_cross(origin,direction)/denominator
        if -1e-10<=t<=1+1e-10:
            t=max(0,min(1,t))
            value=(a[0]*(b[0]/a[0])**t if logarithmic else a[0]+t*(b[0]-a[0]))
            return value,(a[1]+t*span[0],a[2]+t*span[1])
    raise ValueError('Ruler intersection outside transcribed scale; no extrapolation')


@dataclass(frozen=True)
class ApertureGraphReading:
    valve_dn: int
    flow_lps: float
    pressure_drop_mpa: float
    approximate_aperture_mm: float
    pressure_point_px: tuple[float,float]
    flow_point_px: tuple[float,float]
    aperture_point_px: tuple[float,float]
    selection_confirmed: bool = False
    evidence: str = 'raster_nomogram_reading_not_product_curve'


def read_aperture(*,valve_dn,flow_lps,pressure_drop_mpa,axis_offset_px=0.):
    if valve_dn!=50:
        raise ValueError('Only the DN50 scale is visually audited for automated reading')
    p=_point(PRESSURE_TICKS,pressure_drop_mpa*100,logarithmic=True)
    q=_point(FLOW_TICKS,flow_lps,logarithmic=True)
    diameter,crossing=_read_crossing(p,q,_diameter_ticks(axis_offset_px))
    return ApertureGraphReading(valve_dn,flow_lps,pressure_drop_mpa,diameter,p,q,crossing)


def read_pressure_drop(*,valve_dn,flow_lps,aperture_mm,axis_offset_px=0.):
    """Reverse the same straight-line construction at a given q and aperture.

    This is not an unlimited DeltaP(q) product curve. Graph-axis failures raise.
    """
    if valve_dn!=50:
        raise ValueError('Only DN50 scale audited')
    q=_point(FLOW_TICKS,flow_lps,logarithmic=True)
    d=_point(_diameter_ticks(axis_offset_px),aperture_mm)
    pressure,_=_read_crossing(q,d,PRESSURE_TICKS,logarithmic=True)
    return pressure/100


def read_flow(*,valve_dn,pressure_drop_mpa,aperture_mm,axis_offset_px=0.):
    if valve_dn!=50:
        raise ValueError('Only DN50 scale audited')
    p=_point(PRESSURE_TICKS,pressure_drop_mpa*100,logarithmic=True)
    d=_point(_diameter_ticks(axis_offset_px),aperture_mm)
    flow,_=_read_crossing(p,d,FLOW_TICKS,logarithmic=True)
    return flow


def flow_domain(*,valve_dn,aperture_mm,axis_offset_px=0.):
    """Intersection of both printed axes for an explicit aperture; no extension."""
    try:
        read_pressure_drop(valve_dn=valve_dn,flow_lps=2.5,aperture_mm=aperture_mm,axis_offset_px=axis_offset_px)
        low=2.5
    except ValueError:
        low=read_flow(valve_dn=valve_dn,pressure_drop_mpa=.02,aperture_mm=aperture_mm,axis_offset_px=axis_offset_px)
    try:
        read_pressure_drop(valve_dn=valve_dn,flow_lps=10,aperture_mm=aperture_mm,axis_offset_px=axis_offset_px)
        high=10
    except ValueError:
        high=read_flow(valve_dn=valve_dn,pressure_drop_mpa=.70,aperture_mm=aperture_mm,axis_offset_px=axis_offset_px)
    if low>=high: raise ValueError('Empty graph domain')
    return low,high


def neighbouring_apertures(reading,available):
    """Return adjacent real sizes for comparison, never auto-round/select."""
    values=sorted(set(available))
    if not values or any(not isfinite(x) or x<=0 for x in values):
        raise ValueError('Explicit positive catalogue sizes required')
    d=reading.approximate_aperture_mm
    below=[x for x in values if x<=d]
    above=[x for x in values if x>=d]
    if not below or not above:
        raise ValueError('Graph diameter not bracketed by supplied catalogue')
    return tuple(sorted(set((below[-1],above[0]))))
