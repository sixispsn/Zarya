"""Reviewed permanent support components, not a structural calculation.

Dimensions and limits below are exact published values. A console is NOT a
complete pipe support; neither a DN nor a load limit proves an anchor/base.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

SOURCES = {
    'osvu1': dict(url='https://kromber.ru/wp-content/uploads/tehnicheskij-pasport-izdeliya.-osvu-1.-du50.-reguliruemaya-stojka-vodomernogo-uzla.pdf',
                 sha256='aa31a12bf88f2004638b95ed73a44c0ddd0a31b76d5b6d114e4722cc03cef2d2',
                 locator='ОСВУ-1, технический паспорт, стр. 1'),
    'osvu1-geometry': dict(url='https://kromber.ru/product/stojka-osvu-1/',
                          locator='Карточка изготовителя, размеры; проверено 14.10.2026'),
    'termoclip': dict(url='https://www.termoclip.ru/static/pdf/Termoclip_Catalog.pdf',
                     sha256='e25762345d819b162693bce9ea109b5cb363cd6cffe0c4f211aa0ad89695f0b9',
                     locator='Монтажные системы: стр. 3, 36, 37, 40; нагрузки по схеме 1 или 2'),
}


@dataclass(frozen=True)
class SupportProduct:
    id: str
    title: str
    manufacturer: str
    kind: str
    country: str
    sources: tuple[str, ...]
    # Checked dimensions only. None means no published limit, NOT zero.
    dn: int | None = None
    length_mm: float | None = None
    height_range_mm: tuple[float, float] | None = None
    base_mm: tuple[float, float, float] | None = None
    section_mm: tuple[float, float, float] | None = None
    center_load_n: float | None = None
    end_load_n: float | None = None
    included: tuple[tuple[str, int], ...] = ()
    notes: tuple[str, ...] = ()


PRODUCTS = {
    'kromber-osvu1': SupportProduct('kromber-osvu1', 'Стойка ОСВУ-1, DN50', 'KROMBER',
        'floor_stand', 'RU', ('osvu1', 'osvu1-geometry'), dn=50,
        height_range_mm=(500, 800), base_mm=(200, 200, 10),
        included=(('стойка', 1), ('скоба М10', 1), ('гайка М10', 2), ('шайба М10', 2), ('анкер', 4)),
        notes=('Допустимая нагрузка и диапазон наружных диаметров в паспорте не приведены.',
               'Анкеры перечислены в комплекте поставки; их тип и пригодность к основанию не подтверждены.',
               'Напольная стойка для горизонтальной трубы; не поворачивать для вертикального ВУ.')),
}
for article, length, center, end in (
    ('09105001', 200, 2120, 1060), ('09105002', 320, 1350, 540),
    ('09105103', 440, 1060, 250),
):
    ident = 'termoclip-' + article
    PRODUCTS[ident] = SupportProduct(ident, f'Консоль TCA 28x30x1,8, L={length} мм, арт. {article}',
        'Termoclip', 'wall_console', 'RU', ('termoclip',), length_mm=length,
        base_mm=(40, 120, 6), section_mm=(28, 30, 1.8), center_load_n=center, end_load_n=end,
        included=(('консоль', 1),),
        notes=('Нагрузка вертикально вниз: схема 1 в L/2 либо схема 2 в L; интерполяция не применяется.',
               'Хомут, соединительные элементы и анкеры не подобраны. Это часть опоры, не готовый комплект.',
               'Таблица не подтверждает осевое удержание вертикальной трубы и сейсмостойкость.'))


def fingerprint(ident):
    from dataclasses import asdict
    p = PRODUCTS[ident]
    payload = dict(product=asdict(p), sources={s: SOURCES[s] for s in p.sources})
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


CHOICES = {'none': 'Не задана', **{k: v.title for k, v in PRODUCTS.items()}}
