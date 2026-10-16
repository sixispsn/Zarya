from hashlib import sha256
import json

from pypdf import PdfReader
import pytest
from weasyprint import HTML

from scripts.build_reference_basis_review import build_review, load_basis


@pytest.fixture
def review_input(tmp_path):
    source = tmp_path / "source.pdf"
    HTML(string="<p>Original source plan</p>").write_pdf(source)
    data = {
        "schema_version": 1,
        "purpose": "reference_review",
        "engineering_ready": False,
        "title": "Private reference",
        "source_name": "source.pdf",
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "facts": [
            {"id": "building.floors", "section": "building", "label": "Floors",
             "value": 16, "status": "user_declared", "source_kind": "working_hypothesis",
             "source_ref": "User agreed to a 16-floor working hypothesis"},
            {"id": "head.free_fixture", "section": "source_data", "label": "Free head",
             "value": 20, "status": "user_declared", "source_kind": "user_input",
             "source_ref": "User input, not extracted from PDF"},
            {"id": "building.apartments", "section": "building", "label": "Apartments",
             "value": None, "status": "not_provided", "source_kind": "missing",
             "source_ref": "No confirmed apartment schedule"},
        ],
        "sheets": [{"title": "Review only", "notes": [], "panels": [{
            "title": "Source crop", "source_page": 1,
            "crop_top_left_pt": [10, 10, 200, 200],
            "target_mm": [25, 70, 200, 200],
            "markers": [{"label": "G1", "anchor_top_left_pt": [50, 50]}],
        }]}],
    }
    basis = tmp_path / "basis.json"
    basis.write_text(json.dumps(data), encoding="utf-8")
    return source, basis, data


def test_reference_basis_keeps_hypotheses_and_missing_values(review_input):
    source, basis, _ = review_input
    data, registry = load_basis(basis, source)
    assert registry.require("building.floors").status.value == "user_declared"
    assert registry.require("building.floors").value == 16
    assert registry.require("head.free_fixture").value == 20
    assert registry.require("head.free_fixture").source_kind == "user_input"
    assert registry.require("building.apartments").value is None
    assert data["engineering_ready"] is False


@pytest.mark.parametrize("change", ["source", "confirmed", "release", "crop", "marker"])
def test_reference_basis_rejects_invalid_provenance_or_bounds(review_input, change):
    source, basis, data = review_input
    if change == "source":
        data["source_sha256"] = "0" * 64
    elif change == "confirmed":
        data["facts"][0]["status"] = "confirmed"
    elif change == "release":
        data["engineering_ready"] = True
    elif change == "crop":
        data["sheets"][0]["panels"][0]["crop_top_left_pt"][2] = 20000
    else:
        data["sheets"][0]["panels"][0]["markers"][0]["anchor_top_left_pt"] = [0, 0]
    basis.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_basis(basis, source)


def test_review_is_a2_vector_and_does_not_modify_inputs(review_input, tmp_path):
    source, basis, _ = review_input
    before = source.read_bytes(), basis.read_bytes()
    output = tmp_path / "review.pdf"
    assert build_review(basis, source, output) == output
    assert (source.read_bytes(), basis.read_bytes()) == before
    reader = PdfReader(output)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) * 25.4 / 72 == pytest.approx(594)
    assert float(page.mediabox.height) * 25.4 / 72 == pytest.approx(420)
    text = page.extract_text()
    assert "Original source plan" in text
    assert "Непринципиальнаясхема" in "".join(text.split())
    assert len(page.images) == 0
    assert b"W" in page.get_contents().get_data().split()  # source crop is clipped


@pytest.mark.parametrize("target", ["source", "basis"])
def test_review_cannot_overwrite_its_inputs(review_input, target):
    source, basis, _ = review_input
    before = source.read_bytes(), basis.read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        build_review(basis, source, source if target == "source" else basis)
    assert (source.read_bytes(), basis.read_bytes()) == before
