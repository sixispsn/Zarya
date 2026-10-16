"""One review PDF: existing characteristic section + full-network quantities."""
from dataclasses import asdict
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.intake.studio_study import initialize_study, build_study, verify_legacy
from app.pz.network_takeoff_pdf import generate_network_takeoff_pdf
from app.pz.small_residential_section import generate_small_residential_section_pdf
from app.pz.small_residential_takeoff import educational_residential_takeoff


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = root / "tmp/pdfs/residential-takeoff"
    output = root / "output/pdf/residential-takeoff"
    scratch.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    draft = {"revision": 0, "answers": {}, "documents": []}
    initialize_study(draft, "two", None)
    req, model, calc, water, storm, model_hash = build_study(draft)
    verify_legacy(water, storm, req.residents)
    network = educational_residential_takeoff(model, calc)
    scheme = generate_small_residential_section_pdf(str(scratch / "scheme.pdf"), model,
                                                   calculation=calc, compact_demo=True)
    quantities = generate_network_takeoff_pdf(str(scratch / "takeoff.pdf"), network)
    writer = PdfWriter()
    for document in (scheme, quantities):
        writer.append(PdfReader(document))
    writer.add_metadata({"/Title": "ЗАРЯ - схема и проверка полной сети К1/К2", "/Author": "ЗАРЯ"})
    final = output / "К1_К2_схема_и_объёмы.pdf"
    with final.open("wb") as stream:
        writer.write(stream)
    (output / "network.json").write_text(json.dumps({
        "network": asdict(network), "rows": [asdict(r) for r in network.rows()],
        "network_hash": network.fingerprint, "model_hash": model_hash, "purchase_ready": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(final)
    print(f"{len(network.routes)} routes; {len(network.components)} component instances; {network.fingerprint}")


if __name__ == "__main__":
    main()
