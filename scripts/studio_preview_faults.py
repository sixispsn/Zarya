"""Opt-in private smoke server only. No route or switch is added to the product."""
from hashlib import sha256
import json
from pathlib import Path


def install(root: Path):
    from pypdf import PdfReader
    from app.pz import ios2_orchestrator as renderer
    original = renderer.generate_v1_calculation_pdf

    def controlled_failure(project, output_path):
        trigger = root / "fail-next-preview"
        if trigger.exists():
            trigger.unlink()
            folder = Path(output_path).parent
            pz = folder / "ПЗ.pdf"
            content = pz.read_bytes()
            assert content.startswith(b"%PDF-")
            pages = len(PdfReader(pz).pages)
            assert pages > 0
            (root / "renderer-failure.json").write_text(json.dumps(dict(
                folder=str(folder), first_pdf=str(pz), pages=pages,
                sha256=sha256(content).hexdigest(), failure_before_commit=True)))
            raise OSError("TEST-ONLY: second renderer failed after genuine PZ generation")
        return original(project, output_path)

    renderer.generate_v1_calculation_pdf = controlled_failure

    # Fault at the actual atomic replacement, after every renderer has finished.
    # This installer is only loaded by the opt-in private smoke server.
    from app.intake import studio_store
    original_replace = studio_store.os.replace

    def controlled_replace(source, destination):
        trigger = root / "fail-next-preview-save"
        destination = Path(destination)
        if (trigger.exists() and destination.name == "draft.json"
                and destination.parent.parent == root / "studio"):
            draft = json.loads(Path(source).read_text())
            preview = draft.get("preview") or {}
            if preview.get("id"):
                trigger.unlink()
                folder = destination.parent / "previews" / preview["id"]
                documents = []
                for doc in preview["documents"]:
                    pdf = folder / doc["name"]
                    content = pdf.read_bytes()
                    assert content.startswith(b"%PDF-")
                    pages = len(PdfReader(pdf).pages)
                    assert pages > 0
                    documents.append(dict(name=doc["name"], pages=pages, sha256=sha256(content).hexdigest()))
                assert len(documents) == 17
                (root / "persistence-failure.json").write_text(json.dumps(dict(
                    folder=str(folder), documents=documents, failure_before_commit=True)))
                raise OSError("TEST-ONLY: draft replacement refused after all PDF renderers")
        return original_replace(source, destination)

    studio_store.os.replace = controlled_replace
