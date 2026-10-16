#!/usr/bin/env python3
"""Review a private, source-linked building basis without creating design inputs.

The JSON and source PDF stay outside Git (normally under output/). Observed
plan labels are not engineering nodes. Matching labels across sheets do not
prove pipe continuity, apartment counts, elevations or service reachability.
No Project/IOS2Request is constructed and no design or release gate is changed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pypdf import PdfReader, PdfWriter, Transformation  # noqa: E402
from pypdf.generic import RectangleObject  # noqa: E402

from app.intake.facts import FactRegistry, FactStatus, ProjectFact  # noqa: E402

WIDTH_MM = 594.0
HEIGHT_MM = 420.0
PT_PER_MM = 72 / 25.4


def load_basis(path: Path, source: Path) -> tuple[dict, FactRegistry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported reference basis version")
    if sha256(source.read_bytes()).hexdigest() != data["source_sha256"]:
        raise ValueError("source PDF checksum mismatch")
    if data.get("purpose") != "reference_review" or data.get("engineering_ready") is not False:
        raise ValueError("a reference review cannot certify engineering readiness")
    registry = FactRegistry()
    for row in data["facts"]:
        if not row.get("source_ref"):
            raise ValueError("each fact requires its own source")
        registry.add(ProjectFact(
            fact_id=row["id"], section=row["section"], label=row["label"],
            value=row.get("value"), unit=row.get("unit", ""),
            status=FactStatus(row["status"]), source_kind=row["source_kind"],
            source_ref=row["source_ref"],
        ))
    # A hypothesis remains user-declared even after the user agrees to use it.
    for row in data["facts"]:
        if row["source_kind"] == "working_hypothesis" and row["status"] != "user_declared":
            raise ValueError("a working hypothesis cannot become a confirmed PDF fact")
    pages = PdfReader(source).pages
    for sheet in data["sheets"]:
        for panel in sheet.get("panels", []):
            number = panel["source_page"]
            if not isinstance(number, int) or not 1 <= number <= len(pages):
                raise ValueError("invalid source page")
            page = pages[number - 1]
            x0, y0, x1, y1 = panel["crop_top_left_pt"]
            if not (0 <= x0 < x1 <= float(page.mediabox.width)
                    and 0 <= y0 < y1 <= float(page.mediabox.height)):
                raise ValueError("source crop outside page")
            x, y, w, h = panel["target_mm"]
            if not (x >= 0 and y >= 0 and w > 0 and h > 0
                    and x + w <= WIDTH_MM and y + h <= HEIGHT_MM):
                raise ValueError("target panel outside sheet")
            for marker in panel.get("markers", []):
                mx, my = marker["anchor_top_left_pt"]
                if not (x0 <= mx <= x1 and y0 <= my <= y1):
                    raise ValueError("review marker outside source crop")
    return data, registry


def _text(value: str, x: float, y: float, size: float = 3.5,
          *, color: str = "#182333", weight: int = 400) -> str:
    return (f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" '
            f'font-weight="{weight}" fill="{color}">{escape(value)}</text>')


def _panel_transform(panel: dict) -> tuple[float, float, float]:
    x0, y0, x1, y1 = panel["crop_top_left_pt"]
    x, y, w, h = panel["target_mm"]
    scale = min(w / (x1 - x0), h / (y1 - y0))
    left = x + (w - (x1 - x0) * scale) / 2
    top = y + (h - (y1 - y0) * scale) / 2
    return scale, left, top


def _sheet_svg(data: dict, sheet: dict, index: int, *, overlay: bool = False) -> str:
    body = []
    if not overlay:
        body += [
            '<rect width="594" height="420" fill="white"/>',
            '<rect x="15" y="10" width="569" height="400" fill="none" '
            'stroke="#182333" stroke-width="0.35"/>',
            _text("ЗАРЯ / ВОССТАНОВЛЕНИЕ ИСХОДНОЙ ОСНОВЫ", 23, 23, 3.5),
            _text(sheet["title"], 23, 36, 7, weight=700),
            _text(data["title"] + " / шаг 1", 23, 47, 3.8),
            '<line x1="23" y1="54" x2="576" y2="54" stroke="#b1b8c2" stroke-width="0.25"/>',
        ]
        for panel in sheet.get("panels", []):
            x, y, w, h = panel["target_mm"]
            body += [
                _text(panel["title"], x, y - 3, 4.2, weight=700),
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                'fill="none" stroke="#d2d7df" stroke-width="0.25"/>',
            ]
        for block in sheet.get("notes", []):
            x, y = block["x"], block["y"]
            body.append(_text(block["title"], x, y, 4.5, weight=700))
            for n, line in enumerate(block["lines"]):
                body.append(_text(line, x, y + 8 + n * 6, 3.5))
        body += [
            '<line x1="23" y1="389" x2="576" y2="389" stroke="#b1b8c2" stroke-width="0.25"/>',
            _text("Контрольная основа. Не принципиальная схема для выпуска и не расчёт. Измерять по этому обзору нельзя.", 23, 397, 3.5),
            _text(f'Источник: {data["source_name"]}; SHA-256 {data["source_sha256"][:16]}...', 23, 404, 3),
            _text(f'{index} / {len(data["sheets"])}', 560, 404, 3.5),
        ]
    else:
        for panel in sheet.get("panels", []):
            scale, left, top = _panel_transform(panel)
            x0, y0, _, _ = panel["crop_top_left_pt"]
            for marker in panel.get("markers", []):
                mx, my = marker["anchor_top_left_pt"]
                x, y = left + (mx - x0) * scale, top + (my - y0) * scale
                label = marker["label"]
                width = max(8, len(label) * 2.4 + 4)
                body += [
                    f'<rect x="{x:g}" y="{y - 5:g}" width="{width:g}" height="7" '
                    'rx="1" fill="white" stroke="#b44c14" stroke-width="0.45"/>',
                    _text(label, x + 2, y, 3.7, color="#a84010", weight=700),
                ]
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" '
            'viewBox="0 0 594 420"><g font-family="DejaVu Sans, sans-serif">'
            + "".join(body) + '</g></svg>')


def _svg_pages(svgs: list[str]) -> PdfReader:
    from cairosvg import svg2pdf

    # Native SVG conversion keeps lettering metrics in the SVG coordinate
    # system. HTML embedding stretched individual Cyrillic glyph advances.
    writer = PdfWriter()
    for svg in svgs:
        reader = PdfReader(BytesIO(svg2pdf(bytestring=svg.encode("utf-8"))))
        if len(reader.pages) != 1:
            raise ValueError("unexpected review PDF pagination")
        writer.add_page(reader.pages[0])
    stream = BytesIO()
    writer.write(stream)
    stream.seek(0)
    return PdfReader(stream)


def build_review(basis_path: Path, source: Path, output: Path) -> Path:
    if output.resolve() in {basis_path.resolve(), source.resolve()}:
        raise ValueError("review output must not overwrite either input")
    data, _ = load_basis(basis_path, source)
    reader = PdfReader(source)
    base = _svg_pages([_sheet_svg(data, s, i) for i, s in enumerate(data["sheets"], 1)])
    overlay = _svg_pages([_sheet_svg(data, s, i, overlay=True)
                          for i, s in enumerate(data["sheets"], 1)])
    writer = PdfWriter(clone_from=base)
    for i, sheet in enumerate(data["sheets"]):
        page = writer.pages[i]
        for panel in sheet.get("panels", []):
            original = deepcopy(reader.pages[panel["source_page"] - 1])
            x0, y0, x1, y1 = panel["crop_top_left_pt"]
            height = float(original.mediabox.height)
            box = (x0, height - y1, x1, height - y0)
            original.cropbox = RectangleObject(box)
            original.trimbox = RectangleObject(box)
            scale_mm, left, top = _panel_transform(panel)
            scale = scale_mm * PT_PER_MM
            transform = Transformation().scale(scale).translate(
                left * PT_PER_MM - x0 * scale,
                (HEIGHT_MM - top) * PT_PER_MM - (height - y0) * scale,
            )
            page.merge_transformed_page(original, transform, expand=False)
        page.merge_page(overlay.pages[i])
    writer.add_metadata({"/Title": data["title"] + " - контрольная основа",
                         "/Subject": "Source-linked review; not a design release"})
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--basis", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build_review(args.basis, args.source, args.output))


if __name__ == "__main__":
    main()
