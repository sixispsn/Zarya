"""L04: published piecewise-linear Q/H curves; no extrapolated working points.

The system curve is the explicitly approved L02 estimate, not a new hydraulic
method. Split each catalog segment at the clamp and residual extremum, then
bisect sign-changing intervals. This also detects tangent/multiple intersections.
"""
from dataclasses import dataclass
import math
from typing import Literal, Sequence

from app.calc.pump_system_curve import required_boost_head

Point = tuple[float, float]
HEAD_TOL = 1e-9  # numerical metres, never an engineering allowance


def valid_curve(curve: Sequence[Point]) -> bool:
    return (len(curve) >= 2
            and all(math.isfinite(q) and math.isfinite(h) and q >= 0 and h >= 0
                    for q, h in curve)
            and all(a[0] < b[0] for a, b in zip(curve, curve[1:])))


def interpolate_head(curve: Sequence[Point], q: float) -> float | None:
    """Closed published range, including both endpoints. None means no data."""
    if not valid_curve(curve) or not math.isfinite(q) or not curve[0][0] <= q <= curve[-1][0]:
        return None
    for (qa, ha), (qb, hb) in zip(curve, curve[1:]):
        if qa <= q <= qb:
            if q == qa:
                return ha
            if q == qb:
                return hb
            return ha + (hb - ha) * (q - qa) / (qb - qa)
    return None


@dataclass(frozen=True)
class WorkingPoint:
    q: float
    h: float
    h_sys: float


@dataclass(frozen=True)
class IntersectionResult:
    status: Literal["unique", "none", "ambiguous", "invalid"]
    points: tuple[WorkingPoint, ...]
    reason: str

    @property
    def working_point(self) -> WorkingPoint | None:
        return self.points[0] if self.status == "unique" else None


def find_intersections(curve: Sequence[Point], h_base: float, k: float) -> IntersectionResult:
    if (not valid_curve(curve) or not math.isfinite(h_base)
            or not math.isfinite(k) or k < 0):
        return IntersectionResult("invalid", (), "Некорректная характеристика насоса или системы")
    roots: list[WorkingPoint] = []
    coincident = False

    def add(q):
        if not any(math.isclose(q, p.q, rel_tol=1e-12, abs_tol=1e-10) for p in roots):
            h = interpolate_head(curve, q)
            assert h is not None  # validated curve; q is inside the current segment
            roots.append(WorkingPoint(q, h, required_boost_head(h_base, k, q)))

    for (qa, ha), (qb, hb) in zip(curve, curve[1:]):
        slope = (hb - ha) / (qb - qa)

        def residual(q):
            return ha + slope * (q - qa) - required_boost_head(h_base, k, q)

        cuts = [qa, qb]
        if k > 0:
            # On the active parabola f'=slope-2*k*q. On the clamp f'=slope.
            cuts.extend(q for q in [slope / (2 * k)] if qa < q < qb)
            if h_base < 0:
                clamp = math.sqrt(-h_base / k)
                if qa < clamp < qb:
                    cuts.append(clamp)
        cuts = sorted(set(cuts))
        for lo, hi in zip(cuts, cuts[1:]):
            flo, fhi = residual(lo), residual(hi)
            if ha == hb and ((k == 0 and ha == max(0, h_base))
                             or (ha == 0 and h_base + k * hi * hi <= 0)):
                coincident = True
            if abs(flo) <= HEAD_TOL:
                add(lo)
            if abs(fhi) <= HEAD_TOL:
                add(hi)
            if flo * fhi >= 0 or abs(flo) <= HEAD_TOL or abs(fhi) <= HEAD_TOL:
                continue
            for _ in range(80):
                mid = (lo + hi) / 2
                fm = residual(mid)
                if abs(fm) <= HEAD_TOL or mid == lo or mid == hi:
                    break
                if flo * fm < 0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            add(mid)
    roots.sort(key=lambda p: p.q)
    if coincident or len(roots) > 1:
        return IntersectionResult("ambiguous", tuple(roots),
                                  "Пересечение неоднозначно: несколько точек или совпадающий участок кривых")
    if not roots:
        return IntersectionResult("none", (), "Пересечения нет в опубликованном диапазоне Q-H")
    return IntersectionResult("unique", tuple(roots), "Единственное пересечение в опубликованном диапазоне Q-H")
