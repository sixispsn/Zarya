"""Read-only inventory of direct PDF rendering sites under app/.

This is NOT a conformance certificate or a whole-program call graph. It tracks
known CairoSVG/WeasyPrint/ReportLab render calls and two study-text wrappers.
Merging, copying and downloads of existing pages are outside this scan;
dynamic dispatch is not resolved. Evidence means an inspection/test entry point, not
proof that every possible document is visually correct. No production imports.
"""
from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SINKS = {"svg2pdf", "write_pdf", "Canvas", "BaseDocTemplate", "SimpleDocTemplate", "build_study_text_pdf"}


def discover(root: Path) -> dict[str, dict]:
    result = {}
    for path in sorted((root / "app").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {
            item.asname or item.name: item.name
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for item in node.names
        }

        class Visitor(ast.NodeVisitor):
            scope = ()

            def visit_FunctionDef(self, node):
                previous = self.scope
                self.scope += (node.name,)
                self.generic_visit(node)
                self.scope = previous

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef

            def visit_Call(self, node):
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else aliases.get(node.func.id, node.func.id) if isinstance(node.func, ast.Name)
                        else "")
                if name in SINKS:
                    key = f"{relative}:{'.'.join(self.scope) or '<module>'}"
                    entry = result.setdefault(key, {"calls": [], "lines": []})
                    entry["calls"].append(name)
                    entry["lines"].append(node.lineno)
                self.generic_visit(node)

        Visitor().visit(tree)
    return result


# Exact function keys: a new sink even in an already listed module is unreviewed.
# shared = connected to a common frame, NOT a visual acceptance of every branch.
# reviewed = explicit earlier scoped visual/frame checks, NOT hydraulic approval.
# pending = separate presentation review required; component = frame primitive.
GROUPS = (
    ("architecture/program_report", "generate_building_program_report_pdf", "reviewed", "tests/test_building_program_report_layout.py"),
    ("pz/architecture_section_engine", "generate_architecture_section_control_pdf", "reviewed", "tests/test_architecture_control_layout.py"),
    ("pz/defense", "generate_expert_response_pdf", "reviewed", "tests/test_defense_pdf_layout.py"),
    ("pz/fire_diaphragm_correction_report", "correction_review_pdf", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_pressure_review_report", "render_pressure_review", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_repair_review_report", "render_repair_review", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_review_scheme", "generate_review_scheme", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_station_design_report", "render_station_design", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_station_design_scheme", "generate_design_scheme", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_station_input_report", "render_station_input_report", "reviewed", "tests/test_station_graphic_frames.py"),
    ("pz/fire_station_study_sheet", "generate_fire_station_study_sheet", "reviewed", "tests/test_study_graphic_frame.py"),
    ("pz/generator", "_write_text_pdf", "reviewed", "tests/test_annex_spec_frame.py"),
    ("pz/generator", "generate_pz_pdf _write_balance_pdf generate_wastewater_pz_pdf", "reviewed", "tests/test_pz_balance_frame.py"),
    ("pz/generator", "generate_wastewater_diagnostic_pdf generate_wastewater_ugo_pdf", "shared", "tests/test_metering_fallback_frames.py"),
    ("pz/generator", "generate_pump_selection_pdf", "reviewed", "tests/test_pump_document_frame.py"),
    ("pz/generator", "generate_scheme_pdf _generate_aux_scheme_pdf generate_metering_scheme_pdf generate_pump_zone_scheme_pdf", "shared", "tests/test_metering_fallback_frames.py"),
    ("pz/network_takeoff_pdf", "generate_network_takeoff_pdf", "reviewed", "tests/test_study_document_frame.py"),
    ("pz/residential_case_section", "generate_residential_case_pdf", "reviewed", "tests/test_study_graphic_frame.py"),
    ("pz/residential_concept_section", "generate_concept_section_pdf", "reviewed", "tests/test_study_graphic_frame.py"),
    ("pz/residential_plan_section", "generate_plan_section_pdf", "reviewed", "tests/test_independent_study_frames.py"),
    ("pz/residential_plan_study_pdf", "StudySheet.__init__", "reviewed", "tests/test_residential_plan_study.py"),
    ("pz/small_residential_calculation_pdf", "generate_residential_calculation_pdf", "reviewed", "tests/test_study_document_frame.py"),
    ("pz/small_residential_combined", "generate_small_residential_combined_pdf", "reviewed", "tests/test_independent_study_frames.py"),
    ("pz/small_residential_preview", "generate_small_residential_pdf", "reviewed", "tests/test_independent_study_frames.py"),
    ("pz/small_residential_section", "generate_small_residential_section_pdf", "reviewed", "tests/test_study_graphic_frame.py"),
    ("pz/spec_pagination", "write_specification_pdf", "reviewed", "tests/test_annex_spec_frame.py"),
    ("pz/study_document_frame", "build_study_text_pdf", "component", "tests/test_study_document_frame.py"),
    ("pz/text_document_frame", "frame_pdf", "component", "tests/test_pump_document_frame.py"),
    ("pz/wastewater_basement_drafting", "generate_wastewater_basement_control_pdf", "reviewed", "tests/test_basement_control_layout.py"),
    ("pz/wastewater_basement_profile", "generate_basement_profile_pdf", "reviewed", "tests/test_basement_profile_layout.py"),
    ("pz/wastewater_building_drafting", "generate_wastewater_building_pdf_from_project", "reviewed", "tests/test_wastewater_visual_golden.py"),
    ("pz/wastewater_drafting", "generate_lower_turn_control_pdf", "reviewed", "tests/test_lower_turn_control_layout.py"),
    ("pz/wastewater_fan_drafting", "generate_fan_details_pdf", "reviewed", "tests/test_fan_control_layout.py"),
    ("pz/wastewater_floor_drafting", "generate_typical_floor_control_pdf", "reviewed", "tests/test_floor_control_layout.py"),
    ("pz/wastewater_k3_drafting", "generate_wastewater_k3_pdf_from_project", "reviewed", "tests/test_wastewater_visual_golden.py"),
    ("pz/wastewater_pressure_drafting", "generate_wastewater_pressure_pdf_from_project", "reviewed", "tests/test_wastewater_visual_golden.py"),
    ("pz/wastewater_status_document", "generate_status_pdf", "reviewed", "tests/test_wastewater_status_document.py"),
    ("pz/wastewater_scheme_service", "_write_svg_pages", "shared", "tests/test_wastewater_scheme_service.py"),
    ("pz/wastewater_stack_drafting", "generate_wastewater_stack_control_pdf", "reviewed", "tests/test_stack_control_layout.py"),
    ("pz/wastewater_structure_renderer", "generate_wastewater_structure_pdf", "reviewed", "tests/test_wastewater_structure_frame.py"),
)


def inventory(root: Path = ROOT):
    found = discover(root)
    classified = {}
    for module, functions, status, evidence in GROUPS:
        for function in functions.split():
            key = f"app/{module}.py:{function}"
            if key in classified:
                raise ValueError(f"duplicate inventory key: {key}")
            classified[key] = {"status": status, "evidence": evidence}
    unknown, stale = sorted(found.keys() - classified.keys()), sorted(classified.keys() - found.keys())
    missing_evidence = sorted({v["evidence"] for v in classified.values()
                               if not (root / v["evidence"]).is_file()})
    rows = [{"site": key, **found[key], **classified.get(key, {"status": "unknown"})}
            for key in sorted(found)]
    return {"scope": "static direct rendering sites in app; not whole-program or normative approval",
            "counts": dict(sorted(Counter(r["status"] for r in rows).items())),
            "unknown": unknown, "stale": stale, "missing_evidence": missing_evidence,
            "sites": rows}


if __name__ == "__main__":
    report = inventory()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(bool(report["unknown"] or report["stale"] or report["missing_evidence"]))
