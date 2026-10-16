"""Render the explicitly synthetic regression fixture, never the accepted demo."""
from pathlib import Path

from app.pz.wastewater_scheme_service import generate_wastewater_fan_binding_preview
from tests.fan_binding_fixture import fan_binding_fixture


if __name__ == "__main__":
    project, details = fan_binding_fixture()
    output = Path(__file__).resolve().parents[1] / "output/pdf/К1_К2_привязка_фановых_узлов.pdf"
    print(generate_wastewater_fan_binding_preview(project, details, str(output)))
