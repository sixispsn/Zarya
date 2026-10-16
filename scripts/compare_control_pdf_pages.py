"""Render two control builds with Poppler; report every added/removed/changed page.

Read-only inputs. Pixel equality is evidence of unchanged output, not normative
approval. Changed pages must still be inspected by a person or visual reviewer.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import argparse
import json
from pathlib import Path
import subprocess

import pymupdf as fitz
from PIL import Image


def render_build(source, output):
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDFs: {source}")

    def render(item):
        index, pdf = item
        folder = output / f"doc-{index:02d}"
        folder.mkdir(parents=True)
        subprocess.run(["pdftoppm", "-r", "100", "-png", str(pdf), str(folder / "page")],
                       check=True, capture_output=True)
        pngs = sorted(folder.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        rows = []
        with fitz.open(pdf) as doc:
            if not len(doc) or len(pngs) != len(doc):
                raise ValueError(f"Incomplete render: {pdf}")
            for number, (page, png) in enumerate(zip(doc, pngs, strict=True), 1):
                with Image.open(png) as image:
                    rgb = image.convert("RGB")
                    digest = sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
                rows.append(dict(document=pdf.name, page=number, png=str(png.resolve()),
                                 pixel_hash=digest, text_chars=len(page.get_text()),
                                 outside_page=[w[:5] for w in page.get_text("words")
                                               if w[0] < -.5 or w[1] < -.5
                                               or w[2] > page.rect.width + .5
                                               or w[3] > page.rect.height + .5]))
        return rows

    with ThreadPoolExecutor(max_workers=4) as pool:
        return [page for rows in pool.map(render, enumerate(pdfs, 1)) for page in rows]


def main(baseline, current, output):
    # Never overwrite previous evidence or source documents.
    output.mkdir(parents=True, exist_ok=False)
    old = render_build(baseline, output / "baseline")
    new = render_build(current, output / "current")
    def key(page):
        return page["document"], page["page"]
    previous = {key(p): p for p in old}
    present = {key(p): p for p in new}
    for page in new:
        prior = previous.get(key(page))
        page["status"] = ("added" if prior is None else
                          "unchanged" if page["pixel_hash"] == prior["pixel_hash"] else "changed")
        page["baseline_png"] = prior["png"] if prior else None
    removed = [page for page in old if key(page) not in present]
    summary = dict(documents=len({p["document"] for p in new}), pages=len(new),
                   unchanged_pages=sum(p["status"] == "unchanged" for p in new),
                   changed_pages=sum(p["status"] == "changed" for p in new),
                   added_pages=sum(p["status"] == "added" for p in new),
                   removed_pages=len(removed),
                   pages_without_text=sum(not p["text_chars"] for p in new),
                   outside_page_words=sum(len(p["outside_page"]) for p in new))
    result = dict(baseline=str(baseline.resolve()), current=str(current.resolve()),
                  dpi=100, summary=summary, pages=new, removed=removed)
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary))
    for page in new:
        if page["status"] != "unchanged":
            print(page["status"], page["document"], page["page"], page["png"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    main(args.baseline, args.current, args.output)
