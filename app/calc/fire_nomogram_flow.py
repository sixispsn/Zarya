"""L06 bounded joint solve against the graphical diaphragm relation.

Study-only: no extrapolated loss, guessed Cd or single-point R*q² conversion.
Unknowns are cabinet flows; the pump boundary is evaluated at their actual sum.
Trials outside printed graph/pump ranges are rejected by line search, not used
as a manufactured characteristic. Numerical failure never becomes approval.
"""
from copy import deepcopy
from math import isfinite, sqrt

from app.calc.fire_diaphragm_graph import read_pressure_drop, flow_domain
from app.calc.fire_hydraulics import MPA_TO_M
from app.calc.fire_pressure_flow import (
    CabinetFlow, PressureFlowResult, PumpFlowCheck, solve_pressure_flows, _linear_solve)
from app.calc.pump_curve import interpolate_head, valid_curve
from app.calc.ring_hydraulics import solve_two_source_scenario


def check_nomogram_operating_point(network, characteristics, curve, *,
        suction_static_head_m, supply_resistance, apertures_mm, max_iterations=60,
        axis_offset_px=0., station_suction_resistance=0., station_discharge_resistance=0.):
    chars=tuple(characteristics)
    for c in chars: c.validate()
    ids=[c.cabinet_id for c in chars]
    if not valid_curve(curve) or any(b[1]>a[1] for a,b in zip(curve,curve[1:])):
        raise ValueError('A non-increasing published pump curve is required')
    if (not isfinite(suction_static_head_m) or
            any(not isfinite(r) or r<0 for r in (supply_resistance,
                station_suction_resistance, station_discharge_resistance)) or max_iterations<1):
        raise ValueError('Invalid explicit source or numerical parameters')
    if set(apertures_mm)-set(ids):
        raise ValueError('Unknown cabinet in diaphragm layout')
    if not apertures_mm:
        from app.calc.fire_pressure_flow import check_pump_operating_point
        return check_pump_operating_point(network,chars,curve,
            suction_static_head_m=suction_static_head_m,supply_resistance=supply_resistance,
            station_suction_resistance=station_suction_resistance,
            station_discharge_resistance=station_discharge_resistance)
    cabs={c.cabinet_id:c for c in network.cabinets}
    if set(ids)!=set(cabs) or len(ids)!=len(set(ids)):
        raise ValueError('Exactly one characteristic per cabinet required')
    domains={i:flow_domain(valve_dn=cabs[i].dn,aperture_mm=d,axis_offset_px=axis_offset_px)
             for i,d in apertures_mm.items()}
    q=[max(c.minimum_flow_lps,sqrt(c.minimum_head_m/c.resistance_head)) for c in chars]
    for j,i in enumerate(ids):
        if i in domains:
            low,high=domains[i]
            q[j]=min(max(q[j],low+1e-5),high-1e-5)
    hp=interpolate_head(curve,sum(q)*3.6)
    if hp is None:
        return PumpFlowCheck('outside_published_curve',None,None,None,None,None,
            'Initial duty outside published pump curve; no extrapolation')
    # Reuse all L06 topology/data checks on an independent copy. This is only
    # validation; the resulting unconstrained outlet flows are NOT used below.
    solve_pressure_flows(network,chars,suction_static_head_m+hp)
    net=deepcopy(network)
    heads={c.cabinet_id:c.minimum_head_m for c in chars}

    def evaluate(flows):
        if any(not isfinite(q) or q<0 for q in flows): raise ValueError('Invalid trial')
        losses=[]
        for i,q in zip(ids,flows):
            if i in domains:
                lo,hi=domains[i]
                if not lo<=q<=hi: raise ValueError('Outside printed graph flow range')
                losses.append(MPA_TO_M*read_pressure_drop(valve_dn=cabs[i].dn,
                    flow_lps=q,aperture_mm=apertures_mm[i],axis_offset_px=axis_offset_px))
            else: losses.append(0.)
        pump=interpolate_head(curve,sum(flows)*3.6)
        if pump is None: raise ValueError('Outside published pump range')
        suction=suction_static_head_m-(supply_resistance+station_suction_resistance)*sum(flows)**2
        header=suction+pump-station_discharge_resistance*sum(flows)**2
        net.source.available_head_m=net.second_source.available_head_m=header
        inner=solve_two_source_scenario(net,net.cabinets,dict(zip(ids,flows)),heads)
        if inner is None or not inner.solve.converged: raise ValueError('Ring solver failed')
        actual={c.cabinet_id:c.actual_head_at_pk_m for c in inner.per_pk}
        residual=[actual[c.cabinet_id]-c.resistance_head*q*q-loss
                  for c,q,loss in zip(chars,flows,losses)]
        return residual,losses,actual,inner,pump,suction,header

    norm=lambda v:max(abs(x) for x in v)
    converged=False
    for iteration in range(1,max_iterations+1):
        try:
            values=evaluate(q)
        except ValueError:
            break
        residual=values[0]
        if norm(residual)<=1e-5:
            converged=True
            break
        jac=[[0.]*len(q) for _ in q]
        valid_jac=True
        for j,value in enumerate(q):
            shift=max(1e-4,value*1e-4)
            for step in (shift,-shift):
                trial=q.copy();trial[j]+=step
                try:
                    r=evaluate(trial)[0]
                    for i in range(len(q)): jac[i][j]=(r[i]-residual[i])/step
                    break
                except ValueError: pass
            else:
                valid_jac=False
                break
        if not valid_jac: break
        try: delta=_linear_solve(jac,[-x for x in residual])
        except ValueError: break
        damping=1.
        for _ in range(28):
            trial=[x+damping*d for x,d in zip(q,delta)]
            try:
                if norm(evaluate(trial)[0])<norm(residual):
                    q=trial
                    break
            except ValueError: pass
            damping/=2
        else: break
    if not converged:
        return PumpFlowCheck('unresolved_within_nomogram_domain',None,None,None,None,None,
            'No converged solution within printed axes; not extrapolated and not an impossibility proof')
    residual,losses,actual,inner,pump,suction,header=values
    energy=max(norm(residual),inner.solve.residual_loop_m,inner.solve.residual_pseudo_m)
    balance=abs(inner.supply1_lps+inner.supply2_lps-sum(q))
    if energy>1e-3 or balance>1e-5:
        raise ValueError('Joint nomogram conservation failure')
    rows=[]
    for c,flow,loss in zip(chars,q,losses):
        h=actual[c.cabinet_id];out=h-loss
        rows.append(CabinetFlow(c.cabinet_id,flow,h,out,loss,c.minimum_flow_lps,c.minimum_head_m,
            flow+1e-6>=c.minimum_flow_lps and out+1e-5>=c.minimum_head_m,
            out<=c.maximum_head_m if c.maximum_head_m is not None else None,
            True if c.cabinet_id in domains else None))
    op=PressureFlowResult(header,sum(q),tuple(rows),iteration,0.,energy,balance,
        ideal_controls=False,product_verified=False,fixed_controls=True)
    status=('suction_unverified' if suction<=0 else
            'outside_characteristic_range' if any(c.within_characteristic_range is False for c in rows) else
            'meets_minimum' if all(c.meets_minimum for c in rows) else 'insufficient_at_cabinet')
    return PumpFlowCheck(status,op,sum(q)*3.6,pump,suction,0.,
        'Graphical SP10 study; explicit station Rs/Rd applied; raster accuracy, real products, '
        'factory station curve and release checks remain unverified')
