"""Build isolated ventilation control nodes; NEVER edits the 8-apartment input."""
from pathlib import Path

from app.pz.wastewater_fan_drafting import (
    FanDetailsInput, FanRiserPosition, FanRoofDetail, FanValveDetail,
    HL900N_DRAWING, generate_fan_details_pdf,
)
from app.pz.wastewater_ventilation import FanRiser, FanTerminal, FanVentilationInput


def control_fan_details() -> FanDetailsInput:
    reference = "Синтетический контроль геометрии; не проектные исходные данные"
    ids = tuple(f"К1-Ст{i}" for i in range(1, 5))
    risers = tuple(FanRiser(rid, 100., "ventilated", "Выпуск-К1") for rid in ids)
    risers += (FanRiser("К1-Ст5", 100., "vacuum_valve", "Выпуск-К1"),)
    terminals = (
        FanTerminal("К1-Вент1", ids, kind="roof", source_ref=reference, height_m=3.,
                    diameter_mm=100., collector_diameter_mm=100., opening_distance_m=4.,
                    open_end_confirmed=True, separate_from_other_systems=True,
                    condensate_drains_to_risers=True, cold_attic=False,
                    plastic_exposed=True, uv_protected=True),
        FanTerminal("К1-ВК5", ("К1-Ст5",), kind="valve", source_ref=reference,
                    separate_from_other_systems=True, valve_above_highest_fixture=True,
                    valve_on_top_floor=True, valve_sizing_verified=True,
                    valve_sizing_ref="Синтетический тест; реальный клапан не подобран"),
    )
    return FanDetailsInput(
        "flat_accessible", risers, FanVentilationInput(terminals, True, reference),
        (FanRoofDetail("К1-Вент1", 6.6, tuple(
            FanRiserPosition(rid, i*2.5, 3.3, 4.85+i*.05) for i, rid in enumerate(ids)
        ), ids[-1], ids[0], reference),),
        (FanValveDetail("К1-ВК5", 3.3, 6.6, 4.15, 4.5, reference, HL900N_DRAWING, 110),),
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(generate_fan_details_pdf(control_fan_details(), str(root / "output/pdf/К1_узлы_фановой_вентиляции.pdf")))
