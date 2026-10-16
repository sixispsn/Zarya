"""PDF composition preserves navigation, page geometry and the original on failure."""
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link

from app.pz.generator import append_pdf, merge_pdfs


def source(path, title, pages=2):
    with PdfWriter() as writer:
        for index in range(pages):
            writer.add_blank_page(width=300 + index, height=500 + index)
        writer.pages[-1].rotate(90)
        parent = writer.add_outline_item(title, 0)
        writer.add_outline_item(f"{title} / расчёт ⌀100", pages - 1, parent=parent)
        writer.add_annotation(0, Link(rect=(20, 20, 80, 40), target_page_index=pages - 1))
        # Local PDF destinations use page references, not a remote page number.
        writer.pages[0]["/Annots"][0].get_object()["/Dest"][0] = writer.pages[-1].indirect_reference
        writer.add_metadata({"/Title": title})
        writer.write(path)
    return str(path)


def outline(reader, rows=None, depth=0):
    result = []
    for row in reader.outline if rows is None else rows:
        if isinstance(row, list):
            result.extend(outline(reader, row, depth + 1))
        else:
            result.append((depth, row.title, reader.get_destination_page_number(row)))
    return result


def test_merge_nested_bookmarks_links_geometry_and_metadata(tmp_path):
    a = source(tmp_path / "ИОС2.pdf", "Водоснабжение")
    b = source(tmp_path / "Расчёт.pdf", "Расчёт В1", pages=3)
    result = PdfReader(merge_pdfs([a, b], str(tmp_path / "combined.pdf")))
    assert outline(result) == [
        (0, "Водоснабжение", 0), (1, "Водоснабжение / расчёт ⌀100", 1),
        (0, "Расчёт В1", 2), (1, "Расчёт В1 / расчёт ⌀100", 4),
    ]
    assert result.metadata.title == "Водоснабжение"
    assert [p.mediabox.width for p in result.pages] == [300, 301, 300, 301, 302]
    assert [p.rotation for p in result.pages] == [0, 90, 0, 0, 90]
    for first, last in [(0, 1), (2, 4)]:
        dest = result.pages[first]["/Annots"][0].get_object()["/Dest"][0]
        assert result.get_page_number(dest.get_object()) == last


def test_repeated_in_place_append_then_package_preserves_all_bookmarks(tmp_path):
    a = source(tmp_path / "ПЗ.pdf", "ИОС3")
    b = source(tmp_path / "К1.pdf", "К1")
    c = source(tmp_path / "К2.pdf", "К2")
    assert append_pdf(a, b) == a
    assert append_pdf(a, c) == a
    expected = outline(PdfReader(a))
    assert [row[2] for row in expected] == [0, 1, 2, 3, 4, 5]
    final = merge_pdfs([a, b], str(tmp_path / "Комплект.pdf"))
    assert outline(PdfReader(final))[:6] == expected
    assert outline(PdfReader(final))[-1] == (1, "К1 / расчёт ⌀100", 7)


def test_plain_pdf_without_bookmarks_is_kept(tmp_path):
    a = source(tmp_path / "ПЗ.pdf", "ИОС2")
    plain = tmp_path / "drawing.pdf"
    with PdfWriter() as writer:
        writer.add_blank_page(width=840, height=594)
        writer.write(plain)
    append_pdf(a, str(plain))
    assert len(PdfReader(a).pages) == 3
    assert len(outline(PdfReader(a))) == 2


@pytest.mark.parametrize("failure", ["missing", "write"])
def test_failed_append_preserves_base_and_leaves_no_temporary_file(tmp_path, monkeypatch, failure):
    a = source(tmp_path / "ПЗ.pdf", "ИОС2")
    b = source(tmp_path / "Расчёт.pdf", "В1")
    before = Path(a).read_bytes()
    paths = set(tmp_path.iterdir())
    if failure == "write":
        def fail(*args, **kwargs):
            raise OSError("write failed")
        monkeypatch.setattr(PdfWriter, "write", fail)
    else:
        b = str(tmp_path / "missing.pdf")
    with pytest.raises(OSError):
        append_pdf(a, b)
    assert Path(a).read_bytes() == before
    assert set(tmp_path.iterdir()) == paths


def test_empty_merge_rejected_before_overwrite(tmp_path):
    a = source(tmp_path / "ПЗ.pdf", "ИОС2")
    before = Path(a).read_bytes()
    with pytest.raises(ValueError):
        merge_pdfs([], a)
    assert Path(a).read_bytes() == before


def test_section_titles_must_match_sources_before_overwrite(tmp_path):
    a = source(tmp_path / "ПЗ.pdf", "ИОС2")
    before = Path(a).read_bytes()
    with pytest.raises(ValueError):
        merge_pdfs([a], a, section_titles=[])
    assert Path(a).read_bytes() == before
