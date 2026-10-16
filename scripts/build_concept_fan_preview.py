"""Synthetic control sheet, never edits a user's project or deploys the site.

Run from the repo: PYTHONPATH=. venv/bin/python scripts/build_concept_fan_preview.py
"""
from pathlib import Path

from app.pz.section_fan import SectionFanInput
from app.pz.section_storm import SectionStormInput
from app.pz.wastewater_presentation import SectionMainInput
from app.pz.residential_concept_section import ResidentialConceptSection, generate_concept_section_pdf


def main():
    model = ResidentialConceptSection(3, 3.3, "basement", -3.1, "flat_accessible", "internal",
        "residential_full_bath", title="Проверка К1/К2 и фановой вытяжки · условные исходные",
        funnel_heated=True,
        storm=SectionStormInput(city_code="moscow", roof_type="flat", roof_area_m2=420,
            selected_riser_dn_mm=100, max_riser_flow_lps=3, funnels_count=8),
        k1=SectionMainInput(100, .01, -1.8, "КК-1", "Условные данные контрольного варианта",
            design_flow_lps=2.758, outer_diameter_mm=110, wall_thickness_mm=3.4, material="pp",
            manning_n=.011, roughness_source="Учебное n=0,011; не паспорт изделия"),
        k2=SectionMainInput(200, .008, -1.65, "ДК-2", "Условные данные контрольного варианта"),
        fan=SectionFanInput(mode="common", height_m=3, member_ids=("К1-1", "К1-2", "К1-3", "К1-4"),
            roof_level_m=11.8, space="cold_attic", space_floor_m=9.9,
            collector_low_m=10.6, collector_high_m=10.75,
            working_diameter_mm=100, opening_distance_m=5,
            attic_insulated=True, plastic_exposed=True, uv_protected=True,
            source_ref="Синтетический контроль отрисовки, не исходные реального объекта"))
    print(generate_concept_section_pdf(Path("output/pdf/zarya-fan-section-check.pdf"), model))


if __name__ == "__main__":
    main()
