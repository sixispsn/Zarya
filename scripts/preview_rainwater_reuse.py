"""Reproducible illustrative water balance; not Moscow climate/design data."""
from pathlib import Path
from dataclasses import replace

from app.calc.rainwater_reuse import RainwaterReuseInput
from app.pz.project import Project
from app.pz.project import BuildingPurpose
from app.pz.generator import generate_rainwater_reuse_pdf


def example_project():
    p = Project()
    p.rainwater_reuse = RainwaterReuseInput(
        enabled=True, purpose="irrigation", location="site", demand_m3_day=1,
        useful_volume_m3=2, collection_area_m2=100, collection_factor=0.8,
        profile="2026-06-01; 50\n2026-06-02; 0\n2026-06-03; 0\n2026-06-04; 20\n2026-06-05; 0",
        source="Синтетический контрольный ряд. Площадь, η и объём — условия примера, не климатические данные и не нормативные значения.",
        pump_setup="submersible_irrigation", pump_flow_lps=0.4,
        pump_geometric_head_m=3, pump_terminal_head_m=20,
        pump_network_loss_m=2, pump_treatment_loss_m=2,
        pump_loss_source="Синтетический пример: потери и характеристики полива заданы для теста, не рассчитаны по реальной трассе.",
        pump_min_submergence_m=0.5, pump_max_submergence_m=2, pump_temperature_c=15,
        pump_clean_water="yes", pump_pipe_inner_mm=26, pump_pipe_length_m=12,
        outlets_count=2, hose_choice="custom", hose_model="Условный шланг из задания теста; не каталожная модель",
        hose_length_m=25, hose_inner_mm=25, hose_pn_bar=10, hose_loss_m=3, hose_sets=2,
    )
    return p


def treatment_example_project():
    """Show real candidates, but leave unavailable supplier/quality data missing."""
    from app.data.rainwater_treatment import PACK_ID
    p = example_project()
    p.building.purpose = BuildingPurpose.RESIDENTIAL
    p.sewage.roof_kind = "flat_accessible"
    p.rainwater_reuse = replace(p.rainwater_reuse, treatment_setup=PACK_ID,
                               treatment_surface="hard_terrace")
    return p


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--treatment", action="store_true")
    args = parser.parse_args()
    target = Path("output/pdf/Дождевая_вода_очистка.pdf" if args.treatment else "output/pdf/Дождевая_вода_проверка.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    generate_rainwater_reuse_pdf(treatment_example_project() if args.treatment else example_project(), str(target))
    print(target.resolve())
