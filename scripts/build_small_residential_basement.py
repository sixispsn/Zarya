"""Generate the explicitly preliminary basement view of the small example."""
from pathlib import Path

from app.calc.sewer_outlet_depth import preliminary_k1_frost_bound
from app.intake.yaml_io import load_request_file
from app.pz.wastewater_basement_profile import (
    basement_profile_from_request, generate_basement_profile_pdf,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    request = load_request_file(str(root / "demo/residential_2floors_8apartments.yaml"))
    ground = request.wastewater_ground_relative_elevation_m
    frost_depth = request.wastewater_frost_depth_m
    if ground is None or frost_depth is None:
        raise ValueError("ground elevation and frost depth are required for this preview")
    # Explicit educational assumption, not a claim about actual soil data:
    # the supplied 1.5 m is treated as zero-temperature penetration depth.
    # Neither this bound nor schematic DN100 is a confirmed pipe endpoint/size.
    bound = preliminary_k1_frost_bound(
        ground_elevation_m=ground, zero_temperature_depth_m=frost_depth, diameter_mm=100,
    )
    def fmt(value: float) -> str:
        return f"{value:.2f}".replace(".", ",")

    profile = basement_profile_from_request(
        request, proposed_invert_m=bound.highest_invert_m, preview_dn_mm=100,
        proposed_invert_basis=(
            f"Если глубина нулевой температуры {fmt(frost_depth)} м: {fmt(ground)} - {fmt(frost_depth)}"
            f" + 0,30 = {fmt(bound.highest_invert_m)} м; СП 32, п. 6.2.4."
        ),
    )
    output = root / "output/pdf/Жилой_дом_8_квартир_подвал_К1.pdf"
    print(generate_basement_profile_pdf(str(output), profile))


if __name__ == "__main__":
    main()
