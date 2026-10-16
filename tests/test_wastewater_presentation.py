"""One saved presentation and one PDF path for Studio, YAML and the bundle."""
from dataclasses import asdict
from pathlib import Path

import pymupdf
import pytest
from pypdf import PdfReader

from app.intake.project_builder import build_project
from app.intake.studio_intake import accepted_values, build_handoff_request
from app.intake.studio_section import section_model
from app.intake.yaml_io import dump_request, load_request, YamlFormatError
from app.pz.wastewater_presentation import RepresentativeSectionInput
from app.pz.wastewater_graphic_exports import (
    generate_wastewater_graphic_export, representative_section_model,
    wastewater_graphic_export,
)
from tests.test_studio_concept_section import ready_draft
from tests.test_wastewater_scheme_service import _project as confirmed_project


def project():
    return build_project(build_handoff_request(ready_draft()))


def test_saved_handoff_restores_same_model_without_inventing_pipes():
    d = ready_draft()
    req = build_handoff_request(d)
    restored = load_request(dump_request(req))
    p = build_project(restored)
    assert restored.wastewater_presentation == req.wastewater_presentation
    assert representative_section_model(p) == section_model(accepted_values(d))
    assert not p.sewage.pipes and not p.sewage.elements and not p.sewage.risers
    assert asdict(p.flows) == asdict(build_project(req).flows)
    choice = wastewater_graphic_export(p, "k1-k2")
    assert choice.available and not choice.ready
    assert choice.presentation == "representative" and not choice.requires_architecture_binding


def test_changed_project_values_not_frozen_studio_values():
    p = project()
    p.building.floors_above = 3
    p.sewage.floor_height_m = 3.5
    p.sewage.basement_floor_elevation_m = -3.6
    p.document.object_name = "Другой дом"
    m = representative_section_model(p)
    assert (m.floors, m.floor_height_m, m.basement_floor_m, m.title) == (3, 3.5, -3.6, "Другой дом")


@pytest.mark.parametrize("update", [
    {"floor_height_m": None}, {"basement_floor_elevation_m": None}, {"roof_kind": "complex"},
])
def test_missing_geometry_does_not_generate_a_registry_status_sheet(tmp_path, update):
    p = project()
    for key, value in update.items():
        setattr(p.sewage, key, value)
    row = wastewater_graphic_export(p, "k1-k2")
    assert not row.ready and not row.available and row.reasons
    with pytest.raises(ValueError):
        generate_wastewater_graphic_export(p, "k1-k2", str(tmp_path / "scheme.pdf"))
    assert not list(tmp_path.iterdir())


def test_no_basement_and_external_drainage_survive_yaml():
    req = build_handoff_request(ready_draft())
    req.floors_below = 0
    req.wastewater_presentation = RepresentativeSectionInput("none", "external")
    req.wastewater_basement_floor_elevation_m = None
    req.floor_elevations_m.pop(-1, None)  # Removing the basement also removes its AR floor.
    req.wastewater_roof_kind = "gable"
    model = representative_section_model(build_project(load_request(dump_request(req))))
    assert model.basement_floor_m is None and model.drainage == "external"
    assert not any(key.startswith("К2:") for key in model.flow_paths())


def test_known_network_has_priority_and_errors_never_trigger_generic_fallback():
    p = confirmed_project()
    p.sewage.presentation = RepresentativeSectionInput("basement", "internal")
    row = wastewater_graphic_export(p, "k1-k2")
    assert row.ready and row.presentation == "confirmed"
    p.sewage.floor_height_m = None
    broken = wastewater_graphic_export(p, "k1-k2")
    assert not broken.ready and broken.presentation == "confirmed"
    assert broken.requires_architecture_binding and broken.reasons


def test_old_yaml_keeps_old_confirmed_contract():
    p = confirmed_project()
    assert p.sewage.presentation is None
    assert wastewater_graphic_export(p, "k1-k2").presentation == "confirmed"


def test_presentation_cannot_supply_release_flags_or_fake_geometry():
    with pytest.raises(ValueError):
        RepresentativeSectionInput.from_mapping({"mode": "representative", "ready": True})
    req = build_handoff_request(ready_draft())
    text = dump_request(req).replace("mode: representative", "mode: confirmed")
    with pytest.raises(YamlFormatError, match="sewage.presentation"):
        load_request(text)


def test_renderer_failure_has_no_fallback(tmp_path, monkeypatch):
    from app.pz import residential_concept_section as renderer
    def fail(*args):
        raise ValueError("broken drawing")
    monkeypatch.setattr(renderer, "generate_concept_section_pdf", fail)
    with pytest.raises(ValueError, match="broken drawing"):
        generate_wastewater_graphic_export(project(), "k1-k2", str(tmp_path / "scheme.pdf"))
    assert not list(tmp_path.iterdir())


def test_bundle_and_standalone_contain_identical_rendered_section(tmp_path):
    from app.pz.ios2_orchestrator import design_ios2
    from app.web.wizard import _bundle_documents
    p = project()
    bundle = design_ios2(p, output_dir=str(tmp_path / "bundle"))
    direct = tmp_path / "direct.pdf"
    result = generate_wastewater_graphic_export(p, "k1-k2", str(direct))
    assert not result.ready and result.backend == "representative-section"
    standalone = pymupdf.open(bundle.wastewater_scheme_pdf)
    merged = pymupdf.open(bundle.wastewater_package_pdf)
    offset = len(PdfReader(bundle.wastewater_pz_pdf).pages)
    assert standalone[0].get_pixmap().samples == merged[offset].get_pixmap().samples
    assert standalone[0].get_pixmap().samples == pymupdf.open(direct)[0].get_pixmap().samples
    assert "не документ к выпуску" in standalone[0].get_text()
    assert merged.get_toc()  # Retain the PZ's navigable outline after composition.
    docs, _ = _bundle_documents(bundle)
    for kind in ("wastewater_scheme_pdf", "wastewater_package_pdf"):
        doc = next(row for row in docs if row["kind"] == kind)
        assert doc["state"] == "preliminary" and "уклон" in doc["state_note"]
    assert not Path(tmp_path / "bundle" / "Схема_К1_К2.pdf").exists()


def test_release_refuses_restored_preview_even_with_optional_gates_off(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from starlette.requests import Request
    from app.web import wizard
    from app.intake.project_store import ProjectStore
    req = build_handoff_request(ready_draft())
    monkeypatch.setattr(wizard, "_STORE", ProjectStore(str(tmp_path / "projects")))
    monkeypatch.setattr(wizard, "_OUT_ROOT", str(tmp_path / "out"))
    monkeypatch.setattr(wizard, "_HARD_QUALITY_GATES", False)
    monkeypatch.setattr(wizard, "preflight_request", lambda req: SimpleNamespace(can_release=True))
    monkeypatch.setattr(wizard, "review_request", lambda req: [])
    monkeypatch.setattr(wizard, "_form_context", lambda **kw: kw)
    def design(p, output_dir):
        Path(output_dir).mkdir(parents=True)
        return SimpleNamespace(project=p)
    monkeypatch.setattr(wizard, "design_ios2", design)
    monkeypatch.setattr(wizard, "_TPL", SimpleNamespace(
        TemplateResponse=lambda request, template, context, **kw: SimpleNamespace(context=context, **kw)))
    request = Request({"type": "http", "scheme": "http", "path": "/wizard/design",
                       "root_path": "", "query_string": b"", "headers": [], "server": ("test", 80)})
    response = wizard.design_request_response(request, load_request(dump_request(req)))
    assert response.status_code == 422 and "ИОС3 не готов к выпуску" in response.context["errors"][0]
    assert not list((tmp_path / "out").iterdir())
