"""Manufacturer evidence for apartment PRV proposals, not hydraulic approval.

OR.224.G has its own passport. Do not copy VT.085 capacities, cavitation rules
or gauge threads into it merely because the supplier calls it a replacement.
"""
from dataclasses import dataclass

REVISION = '2026-10-07.1'
SOURCE_URL = 'https://valtec.ru/document/technical/OR.224-1023.pdf'
SOURCE_SHA256 = '0633d578cba7f3588fcef8e3ba3ba84fc3297249668297c058166911004cc1e2'
SOURCE_TITLE = 'Officine Rigamonti OR.224.G, ПС-47343, разделы 1–5'
PRODUCT_URL = 'https://valtec.ru/catalog/recommended/klapany_i_vozduhootvodchiki/reduktor_davleniya_membrannyj_pn25.html'
CHECKED_ON = '2026-10-07'


@dataclass(frozen=True)
class ApartmentRegulator:
    id: str
    article: str
    dn: int
    thread: str
    body_length_mm: float
    height_mm: float
    model: str = 'OR.224.G'
    manufacturer: str = 'Officine Rigamonti'
    country: str = 'Италия'
    connection_standard: str = 'G'
    connection_sex: str = 'female'
    temperature_c: tuple[float, float] = (0, 80)
    pn_bar: float = 25
    setting_range_bar: tuple[float, float] = (1, 7)
    static_regulation: bool = True
    upstream_filter_max_microns: int = 500
    status: str = 'catalogued'
    # No default project setting, invented Kv, Qmin or digitized loss curve.


PRODUCTS = (
    ApartmentRegulator('rigamonti-or224-dn15', 'OR.224.G.04', 15, '1/2', 67.5, 127.5),
    ApartmentRegulator('rigamonti-or224-dn20', 'OR.224.G.05', 20, '3/4', 77, 157),
)

# Filter evidence is shared with the apartment quality preference, not tied to
# one model's ID. See apartment_filters.py; the PRV still requires <=500 µm.
