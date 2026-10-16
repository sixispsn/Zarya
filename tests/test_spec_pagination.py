"""Physical PDF rows, not a fixed number of entries, determine page breaks."""
from dataclasses import asdict
from copy import deepcopy

import pytest
from weasyprint import CSS, HTML
from weasyprint.formatting_structure.boxes import TableBox, TableRowBox

from app.pz.generator import _build_env
from app.pz.project import DocumentInfo
from app.pz.spec import Specification, SpecSection, SpecRow
from app.pz.spec_pagination import specification_pages, TEMPLATES, MM


def rendered(spec):
    env = _build_env()
    pages = specification_pages(spec, env)
    body = env.get_template('spec_table.html').render(pages=pages)
    html = env.get_template('spec_document.html').render(doc=DocumentInfo(), body_html=body)
    doc = HTML(string=html, base_url=str(TEMPLATES)).render(stylesheets=[
        CSS(filename=str(TEMPLATES/n)) for n in ('spec_frame.css','spec.css')])
    return pages, doc


@pytest.mark.parametrize('long', [False, True])
def test_rows_are_unique_fill_to_stamp_and_never_overflow(long):
    spec = Specification(sections=[SpecSection('В1', 'Водоснабжение', [
        SpecRow(i, f'Изделие {i}', qty=i, note=('Полное примечание. '*18 if long and i % 3 == 0 else ''))
        for i in range(1, 46)])], note='Общие условия сохраняются без сокращения.')
    before = deepcopy(asdict(spec))
    planned, doc = rendered(spec)
    assert len(doc.pages) == len(planned)
    assert asdict(spec) == before
    assert all(h >= 5 for page in planned for h in page['blanks'])
    found = []
    for index, page in enumerate(doc.pages):
        boxes = list(page._page_box.descendants())
        tables = [b for b in boxes if isinstance(b, TableBox) and b.element.get('class') == 'spec']
        assert len(tables) == 1
        table = tables[0]
        bottom = (table.position_y+table.border_height())/MM
        assert bottom == pytest.approx(237 if index == 0 else 277, abs=.2)
        rows = [b for b in boxes if isinstance(b, TableRowBox) and b.element.get('data-layout-key')]
        assert sum(b.element.get('data-layout-key') == 'header' for b in rows) == 1
        keys = [b.element.get('data-layout-key') for b in rows]
        found += [k for k in keys if k.startswith('r')]
        for b in rows:
            assert b.position_y/MM >= 5-.2
            assert (b.position_y+b.height)/MM <= (237 if index == 0 else 277)+.2
    assert found == [f'r0-{i}' for i in range(45)]
    if not long:
        assert any(sum(e['kind']=='item' for e in page['rows']) > 8 for page in planned)


def test_new_section_stays_with_first_item_and_continuation_repeats_title():
    spec = Specification(sections=[SpecSection(f'Раздел {s}', 'Водоснабжение', [
        SpecRow(s*30+i, f'Товар {s}-{i}') for i in range(30)]) for s in range(3)])
    pages = specification_pages(spec, _build_env())
    for page in pages:
        entries = page['rows']
        assert entries[0]['kind'] == 'division'
        assert entries[1]['kind'] == 'section'
        assert entries[2]['kind'] == 'item'
        assert entries[-1]['kind'] == 'item'
    assert any('продолжение' in e.get('title','') for p in pages for e in p['rows'])


def test_impossible_single_row_fails_instead_of_clipping():
    spec = Specification(sections=[SpecSection('В1', rows=[SpecRow(1,'Арматура',note='Сведения '*4000)])])
    with pytest.raises(ValueError, match='выше доступного поля'):
        specification_pages(spec, _build_env())
