"""One evidenced PE-X connection candidate, not an installed-unit approval.

VT.4410.NE.20 is for PE-X 20x2, NOT metal-polymer or PE-X 20x2.8.
Its eurocone union needs a mating seat; a plain G3/4 nipple is not enough.
No change to pipe geometry, hydraulic losses or approved calculation methods.
"""
from dataclasses import dataclass
from math import isfinite
import re

REVISION = '2026-10-09.1'
FITTING_SOURCE = {
    'url': 'https://valtec.ru/document/technical/fitingi-collectornye-1125.pdf',
    'sha256': '1bb98d42edf11b1e845ab7fde1738f79229c8698d633ebb79bdbdac19b02ceca',
    'title': 'VALTEC, ПС 47657-2, стр. 1–2, 5, VT.4410.NE.20',
}
ADAPTER_SOURCE_ID = 'vtr-1025'
ADAPTER_SOURCE_SHA256 = '44e8069b8d2e0660acd4e1ca60a2e4f9b42c047db86bf31bafc22ca1a76be6f6'
ADAPTER_SOURCE_URL = 'https://valtec.ru/document/technical/VTr-1025.pdf'
ADAPTER_DRAWING_URL = 'https://valtec.ru/document/technical/drawing/VTr.580.NE/VTr.580.NE.pdf'
ADAPTER_DRAWING_SHA256 = 'cca90a034487f125b74dacd04f46bbb9e12cf791adf04de5c8a9d84e2e9b12f1'


@dataclass(frozen=True)
class ConnectionPort:
    standard: str
    thread: str
    sex: str

    def mates(self, other):
        return (self.standard == other.standard and self.thread == other.thread
                and {self.sex, other.sex} == {'female', 'male'})


@dataclass(frozen=True)
class PipeEndFitting:
    article: str
    outer_mm: float
    wall_mm: float
    port: ConnectionPort
    family: str = 'pex'
    pn_bar: float = 10
    temperature_c: tuple[float, float] = (-20, 110)
    retightening_months: int = 6  # Passport 6.4: keep the union accessible.


@dataclass(frozen=True)
class EuroconeAdapter:
    article: str
    fitting_port: ConnectionPort
    equipment_port: ConnectionPort
    # Passport A=26 mm; separate manufacturer drawing 25.5 mm. Do not sum.
    dimensions_status: str = 'conflict'


FITTINGS = (PipeEndFitting('VT.4410.NE.20', 20, 2,
    ConnectionPort('eurocone', '3/4', 'female')),)
ADAPTERS = (EuroconeAdapter('VTr.580.NE.040E',
    ConnectionPort('eurocone', '3/4', 'male'), ConnectionPort('G', '1/2', 'male')),)


@dataclass(frozen=True)
class PipeEndProposal:
    fitting: PipeEndFitting
    adapter: EuroconeAdapter
    status: str = 'candidate'
    installation_complete: bool = False


def propose_pipe_end(pipe, equipment_port, temperature):
    """Exact geometry + two typed mating pairs; ambiguity leaves a requirement.

    Current temperature only screens the candidate. Pipe brand/service class,
    design pressure, access and installation dimensions still need confirmation.
    """
    from app.data.metering_products import get_metering_catalogue
    if (pipe is None or equipment_port is None or pipe.family != 'pex'
            or re.search(r'\bal\b|алюмин|металло|армирован|stabi', pipe.material.casefold())
            or type(temperature) not in (int, float) or not isfinite(temperature)):
        return None
    source = get_metering_catalogue().sources.get(ADAPTER_SOURCE_ID, {})
    if source.get('sha256') != ADAPTER_SOURCE_SHA256:
        return None
    candidates = [PipeEndProposal(f, a) for f in FITTINGS for a in ADAPTERS
        if (pipe.family, pipe.outer_mm, pipe.wall_mm) == (f.family, f.outer_mm, f.wall_mm)
        and f.temperature_c[0] <= temperature <= f.temperature_c[1]
        and f.port.mates(a.fitting_port) and a.equipment_port.mates(equipment_port)]
    return candidates[0] if len(candidates) == 1 else None
