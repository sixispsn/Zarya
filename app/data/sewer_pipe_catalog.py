"""Проверенный сортамент К1; выбор материала не создаёт трассу или расход.

Ostendorf, «Техническая информация 2026.01», PDF-страница 2, таблица HT.
Ключ размера — наружный диаметр, не условный проход и не внутренний D.
Каталог В1/В2/Т3/Т4 и рабочие алгоритмы legacy здесь не изменяются.
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class SewerPipeSeries:
    series_id: str
    name: str
    material: str
    standard: str
    source_url: str
    source_pdf_page: int
    sizes: tuple[tuple[float, float], ...]  # Dн, стенка, мм
    application: str = "internal_gravity_k1"


@dataclass(frozen=True)
class SewerPipeGeometry:
    series: SewerPipeSeries
    outer_diameter_mm: float
    wall_thickness_mm: float

    @property
    def inner_diameter_mm(self) -> float:
        return round(self.outer_diameter_mm - 2 * self.wall_thickness_mm, 1)


OSTENDORF_HT = SewerPipeSeries(
    series_id="ostendorf_ht_pp",
    name="Ostendorf HT / HTEM",
    material="pp",
    standard="DIN EN 1451-1; DIN 19560-10",
    source_url=(
        "https://ostendorf.ru/upload/iblock/dc9/"
        "nfeeb46tp12d1bs999oxbirr3q6tyvxw/cataloge_2026_1.pdf"
    ),
    source_pdf_page=2,
    sizes=((32, 1.8), (40, 1.8), (50, 1.8), (75, 1.9),
           (90, 2.2), (110, 2.7), (125, 3.1), (160, 3.9)),
)
SEWER_PIPE_SERIES = MappingProxyType({OSTENDORF_HT.series_id: OSTENDORF_HT})

# Separate opt-in study series. Do not silently allow this through the HT-only
# production input adapter: pressure-rated couplings/anchors need their own check.
DUEKER_SML = SewerPipeSeries(
    series_id="dueker_sml_dn100_study", name="Düker SML DN100",
    material="cast_iron", standard="DIN EN 877; DIN 19522",
    source_url="https://www.dueker.de/fileadmin/download/de/02_Abflusstechnik/GAT_Planungsunterlage_SML.pdf",
    source_pdf_page=37, sizes=((110, 3.5),), application="rainwater_study_with_restrained_couplings",
)


def sewer_pipe_geometry(series_id: str, outer_diameter_mm: float) -> SewerPipeGeometry:
    """Точное совпадение, без округления, интерполяции и подмены DN100 на Ø110."""
    try:
        series = SEWER_PIPE_SERIES[series_id]
    except KeyError as exc:
        raise ValueError(f"Неизвестная серия канализационной трубы: {series_id}") from exc
    for outer, wall in series.sizes:
        if outer_diameter_mm == outer:
            return SewerPipeGeometry(series, outer, wall)
    raise ValueError(f"В серии {series.name} нет наружного Ø{outer_diameter_mm:g}")


def catalog_pipe_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Разрешить явно выбранную серию в существующие поля трубы YAML.

    Старые строки без серии сохраняют ручной ввод. При наличии серии запрещены
    конфликтующие размеры/материал. Никакие длины, уклоны или расходы не добавляются.
    """
    fields: dict[str, Any] = {
        "material": str(row.get("material", "")),
        "standard": str(row.get("standard", "")),
        "outer_diameter_mm": float(row.get("outer_diameter_mm", 0)),
        "wall_thickness_mm": float(row.get("wall_thickness_mm", 0)),
    }
    series_id = str(row.get("catalog_series_id", ""))
    if not series_id:
        return fields
    geometry = sewer_pipe_geometry(series_id, fields["outer_diameter_mm"])
    resolved = {
        "material": geometry.series.material,
        "standard": geometry.series.standard,
        "outer_diameter_mm": geometry.outer_diameter_mm,
        "wall_thickness_mm": geometry.wall_thickness_mm,
    }
    for key, value in resolved.items():
        if key in row and fields[key] != value:
            raise ValueError(f"{series_id}: {key} противоречит каталогу ({value})")
    if (row.get("system", "K1") != "K1" or row.get("pressure_rated")
            or row.get("pressure_class_bar") is not None):
        raise ValueError("Серия HT в этом каталоге принята только для внутренней самотечной К1")
    return resolved
