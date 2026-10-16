"""Reviewed apartment filter evidence; no price score or hydraulic substitution.

The user's 14.10.2026 preference is quality before price. Here this means finer
mechanical filtration and serviceability, only among compatible, reviewed
products. It does not mean that VT.386 dominates VT.192 in pressure rating.
"""
from dataclasses import dataclass

REVISION = '2026-10-14.1'
SOURCE_HASHES = {
    'vt192-0825': '603d2085bb2a6685d5fdf44ad29b6cecc7f1ae68baa79ebde9be69a54eee3d62',
    'vt386-0625': '427e9a91b2a8bae33c8a4331d53e8af764774b147adda39d7dac9d0bd3a925b3',
}


@dataclass(frozen=True)
class FilterEvidence:
    source_id: str
    mesh_microns: int
    plug_thread_outside_water: bool
    pn_bar: float
    temperature_c: tuple[float, float]


# VT.192 ПС-47243-2, §3; VT.386 ПС-47335-3, §§1.4, 2, 6.1.
FILTERS = {
    **{f'valtec-vt192-dn{dn}': FilterEvidence(
        'vt192-0825', mesh, False, pn, (5, 150))
       for dn, mesh, pn in ((15,500,20), (20,500,20), (25,500,20),
                            (32,800,16), (40,800,16), (50,1000,16))},
    **{f'valtec-vt386-dn{dn}': FilterEvidence(
        'vt386-0625', 300, True, 16, (1, 110)) for dn in (15,20,25)},
}


def filter_evidence(product, catalogue):
    evidence = FILTERS.get(product.id) if product else None
    if (not evidence or evidence.source_id not in product.source_ids
            or not SOURCE_HASHES.get(evidence.source_id)
            or catalogue.sources.get(evidence.source_id, {}).get('sha256')
               != SOURCE_HASHES.get(evidence.source_id)
            or product.pn_bar != evidence.pn_bar
            or product.temperature_c != evidence.temperature_c):
        return None
    return evidence


def preferred_apartment_filter(candidates, catalogue):
    """Resolve only the reviewed comparison, not arbitrary catalogue ties.

Inputs have already passed DN/thread/temperature/horizontal-mount screening.
Branch working pressure and product loss still require project confirmation.
An unreviewed alternative or changed passport requires a fresh comparison.
"""
    if len(candidates) < 2:
        return None
    reviewed = [(p, filter_evidence(p, catalogue)) for p in candidates]
    if any(e is None for _, e in reviewed):
        return None
    best = [p for p, e in reviewed if e.plug_thread_outside_water
            and all(e.mesh_microns < other.mesh_microns
                    for q, other in reviewed if q.id != p.id)]
    return best[0] if len(best) == 1 else None
