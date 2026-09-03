from pathlib import Path

from pypdf import PdfReader

from app.pz.wastewater_graphic_exports import (
    assess_wastewater_graphic_exports,
    generate_wastewater_graphic_export,
    wastewater_graphic_export,
)
from app.pz.generator import generate_wastewater_pressure_scheme_pdf
from tests.test_wastewater_k3_scheme import _k3_project
from tests.test_wastewater_pressure_scheme import _pressure_project


def test_export_catalog_separates_gravity_k3_and_pressure_sewer():
    k3_rows = {
        row.key: row for row in assess_wastewater_graphic_exports(_k3_project())
    }
    pressure_rows = {
        row.key: row
        for row in assess_wastewater_graphic_exports(_pressure_project())
    }

    assert tuple(k3_rows) == ("k1-k2", "k3", "pressure")
    assert k3_rows["k1-k2"].requires_architecture_binding
    assert k3_rows["k3"].applicable and k3_rows["k3"].ready
    assert not k3_rows["pressure"].applicable
    assert pressure_rows["pressure"].applicable
    assert pressure_rows["pressure"].ready
    assert not pressure_rows["k3"].applicable


def test_export_dispatcher_has_no_legacy_or_unknown_fallback(tmp_path):
    project = _pressure_project()
    output = tmp_path / "pressure.pdf"

    result = generate_wastewater_graphic_export(
        project,
        "pressure",
        str(output),
    )

    assert result.output_path == str(output)
    assert result.backend == "pressure-sewer-confirmed-curve-v1"
    assert len(PdfReader(output).pages) == 2
    assert Path(result.output_path).is_file()

    for key in ("legacy", "scheme", "k3"):
        try:
            wastewater_graphic_export(project, key)
        except ValueError as exc:
            message = str(exc)
            assert "не заявлена" in message or "Неизвестный" in message
        else:  # pragma: no cover
            raise AssertionError(f"unexpected export fallback for {key}")


def test_architecture_export_uses_the_same_optional_dispatcher(
    tmp_path,
    monkeypatch,
):
    from app.web import architecture_import as web

    class ImportSession:
        @staticmethod
        def survey(import_id):
            assert import_id == "confirmed-import"
            return object()

    monkeypatch.setattr(web, "_STORE", ImportSession())
    monkeypatch.setattr(web, "_EXPORT_ROOT", str(tmp_path))
    monkeypatch.setattr(
        web,
        "_linked_project",
        lambda _import_id, *, require_current: _pressure_project(),
    )

    response = web.architecture_wastewater_graphic_pdf(
        "confirmed-import",
        "pressure",
    )

    assert response.status_code == 200
    assert Path(response.path).name == "Схема_напорной_канализации.pdf"
    assert len(PdfReader(response.path).pages) == 2

    wizard_output = tmp_path / "wizard-pressure.pdf"
    generate_wastewater_pressure_scheme_pdf(
        _pressure_project(),
        str(wizard_output),
    )
    assert Path(response.path).read_bytes() == wizard_output.read_bytes()
    assert (
        web.architecture_wastewater_graphic_pdf(
            "confirmed-import",
            "legacy",
        ).status_code
        == 422
    )
