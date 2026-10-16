"""Explicit preliminary pipework, not a manufactured PFFS characteristic.

Pipe friction reuses SpecificResistanceBackend. Kv and zeta are explicit design
inputs, never inferred from DN, never combined with a second percentage uplift.
The closed standby path contributes neither flow nor series resistance.
"""
from dataclasses import dataclass, asdict
from math import isfinite, pi

from app.calc.fire_hydraulics import MPA_TO_M, PipeSegment, SpecificResistanceBackend
from app.calc.pump_curve import interpolate_head, valid_curve


@dataclass(frozen=True)
class PipeworkElement:
    id: str
    name: str
    side: str
    dn: int
    quantity_on_active_path: int
    method: str
    value: float
    basis: str
    length_m: float = 0.
    inner_mm: float | None = None

    def resistance(self):
        if (not self.id or not self.basis.strip() or self.side not in ('suction', 'discharge')
                or type(self.dn) is not int or self.dn <= 0
                or type(self.quantity_on_active_path) is not int or self.quantity_on_active_path < 1
                or not isfinite(self.value) or self.value <= 0):
            raise ValueError('Explicit positive sourced pipework data required')
        if self.method == 'A_L':
            if not isfinite(self.length_m) or self.length_m <= 0:
                raise ValueError('Pipe length must be positive')
            r = SpecificResistanceBackend().segment_loss(
                PipeSegment(self.id, 'in', 'out', self.length_m, self.value), 1.)
        elif self.method == 'Kv':
            # Water: dp(bar)=(Q(m3/h)/Kv)^2; q here is l/s.
            r = MPA_TO_M / 10 * (3.6/self.value)**2
        elif self.method == 'zeta':
            if self.inner_mm is None or not isfinite(self.inner_mm) or self.inner_mm <= 0:
                raise ValueError('Actual internal diameter required for zeta')
            area = pi*(self.inner_mm/1000)**2/4
            r = self.value*(.001/area)**2/(2*9.81)
        else:
            raise ValueError('Unknown pipework method')
        return r*self.quantity_on_active_path


@dataclass(frozen=True)
class StationPipework:
    elements: tuple[PipeworkElement, ...]
    basis: str
    evidence: str = 'designer_assumption_authorized_2026-10-04'

    def resistances(self):
        if (not self.elements or not self.basis.strip() or
                len({e.id for e in self.elements}) != len(self.elements)):
            raise ValueError('Unique explicit pipework elements required')
        result = dict(suction=0., discharge=0.)
        for e in self.elements:
            result[e.side] += e.resistance()
        if any(r <= 0 for r in result.values()):
            raise ValueError('Both internal station paths must be specified')
        return result

    def losses(self, q_m3h):
        if not isfinite(q_m3h) or q_m3h < 0:
            raise ValueError('Nonnegative finite flow required')
        return {side: r*(q_m3h/3.6)**2 for side,r in self.resistances().items()}

    def audit(self, q_m3h):
        losses=self.losses(q_m3h)
        return dict(basis=self.basis, evidence=self.evidence,
            q_m3h=q_m3h, losses_m=losses, total_loss_m=sum(losses.values()),
            resistances_m_per_lps2=self.resistances(),
            elements=[dict(**asdict(e), resistance_m_per_lps2=e.resistance(),
                loss_m=e.resistance()*(q_m3h/3.6)**2) for e in self.elements],
            manufacturer_confirmed=False, reserve_in_flow_sum=False,
            geometry_is_preliminary=True, zero_flow_loss_m=0.)


def station_curve_samples(curve, pipework, *, samples=81):
    """Net boost at station boundaries; never present it as a factory guarantee.

    Sampling is dense because a piecewise-linear pump minus Rq² is NOT the
    piecewise-linear interpolation of its corrected published knots.
    """
    if not valid_curve(curve) or type(samples) is not int or samples<2:
        raise ValueError('Published curve and at least two samples required')
    total=sum(pipework.resistances().values())
    flows=sorted({q for q,_ in curve} | {curve[0][0]+(curve[-1][0]-curve[0][0])*i/(samples-1)
                 for i in range(samples)})
    return [dict(q_m3h=q, single_pump_head_m=interpolate_head(curve,q),
                 station_net_boost_m=interpolate_head(curve,q)-total*(q/3.6)**2) for q in flows]
