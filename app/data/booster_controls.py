"""Published station equipment, independent of normative VFD requirements.

This is not a controller simulation or an inferred feature of every pump.
PBS catalogue supplied by the user, 12.05.2025, pp. 6–8, 11.
"""
from dataclasses import dataclass

from app.data.pumps import CURRENT_PUMPS


@dataclass(frozen=True)
class BoosterControl:
    drive: str
    source: str
    description: str


PBS_CONTROL = BoosterControl(
    "Aikon PD ES",
    "CNP/Aikon «Каталог PBS», 12.05.2025, с. 6–8; характеристика при 2900 об/мин — с. 11",
    "Частотный привод Aikon PD ES на каждом насосе; поддержание давления по датчикам "
    "напорного коллектора, останов при отсутствии расхода, защита от сухого хода. "
    "ПЧ и штатные датчики входят в комплект станции; отдельный шкаф с ПЧ повторно не учитывается.",
)
_PBS_MODELS = frozenset(f"{p.brand} {p.model}" for p in CURRENT_PUMPS
                      if p.brand == "CNP / Aikon" and p.model.startswith("PBS CDM"))


def booster_control(pump):
    if not pump.required or pump.model not in _PBS_MODELS or not pump.top3:
        return None
    chosen = pump.top3[0]
    if f"{chosen.brand} {chosen.model}" != pump.model:
        return None
    return PBS_CONTROL
