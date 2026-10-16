"""Explicit public manufacturer documents for the 2026-10-12 review."""
import hashlib
import json
from pathlib import Path
import urllib.request
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp/metering-source-review-20261012"
LD = "https://xn--d1an.xn--p1ai"
DOCUMENTS = {
    "ld-brass-catalogue": LD + "/api/v1/getDocument/2c496c5c-9e79-11f0-b7ad-005056a4b6de",
    "ld47-passport": LD + "/api/v1/getDocument/5cd2589d-136e-11ef-804a-005056a4b6de",
    "ld-fittings-passport": LD + "/api/v1/getDocument/a2890b15-c3da-11ed-b250-005056a4b6de",
    "pulsar-m2-re3": "https://pulsarm.ru/upload/iblock/565/kg90hm6f3utscu6lwe6l2set8hbyj8iv/RE-Schetchik-vody-UZ-model-2-isp-1-2-Du15_Du40-Red-3.pdf",
}

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    metadata = {}
    for ident, source in DOCUMENTS.items():
        data = urllib.request.urlopen(source, timeout=30).read()
        if data.startswith(b"{"):
            location = json.loads(data)["url"]
            data = urllib.request.urlopen(LD + location, timeout=30).read()
        if not data.startswith(b"%PDF"):
            raise ValueError(ident)
        (OUT / f"{ident}.pdf").write_bytes(data)
        doc = pymupdf.open(stream=data, filetype="pdf")
        (OUT / f"{ident}.txt").write_text("\n".join(
            f"\nPDF PAGE {i+1}\n" + page.get_text() for i, page in enumerate(doc)))
        metadata[ident] = dict(url=source, sha256=hashlib.sha256(data).hexdigest(), pages=len(doc))
        print(ident, metadata[ident])
    (OUT / "new-documents.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
