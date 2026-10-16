"""Versioned dimensional catalogue; not a replacement hydraulic calculator.

JSON is the reviewed source of truth; SQLite is a disposable, indexed export.
Product identity, size designation, material and manufacturing are independent.
Missing values stay null. Geometry verification is NOT installation approval.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, fields, is_dataclass
from functools import lru_cache
import hashlib
import json
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


SCHEMA_VERSION = 1
_DATA = Path(__file__).with_suffix('.json')


def plain(value):
    """JSON-safe conversion without deepcopy of immutable mapping proxies."""
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class CataloguePort:
    name: str
    connection: str = 'unknown'
    dn: int | None = None
    outer_diameter_mm: float | None = None
    wall_thickness_mm: float | None = None
    system_id: str = ''
    sex: str = 'unknown'
    thread: str = ''
    standard: str = ''
    flange_face: str = 'unknown'
    bolt_circle_mm: float | None = None
    bolt_count: int | None = None
    bolt_hole_mm: float | None = None


@dataclass(frozen=True)
class CatalogueItem:
    id: str
    family_id: str
    kind: str
    name: str
    source_ids: tuple[str, ...]
    locator: str
    status: str
    dimensions_mm: Mapping
    ports: tuple[CataloguePort, ...]
    dimension_meanings: Mapping = field(default_factory=dict)
    manufacturer: str = ''
    article: str = ''
    material: str = 'unknown'
    grade: str = ''
    manufacturing: str = 'unknown'
    coating: str = 'unknown'
    standard: str = ''
    series: str = ''
    system_id: str = ''
    joinings: tuple[str, ...] = ()
    pn_bar: float | None = None
    temperature_c: tuple | None = None
    pressure_temperature: tuple = ()
    country_of_manufacture: str = 'unknown'
    origin_source_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    # Native payload retained losslessly: modern options, sensor interfaces,
    # mounting rules, flange types, passport limits, etc. are not discarded.
    native: Mapping = field(default_factory=dict)

    @property
    def dn(self):
        return self.ports[0].dn if self.ports else None

    @property
    def inner_diameter_mm(self):
        if self.kind != 'pipe' or self.status != 'verified':
            return None
        return self.dimensions_mm['outer_diameter_mm'] - 2 * self.dimensions_mm['wall_thickness_mm']


@dataclass(frozen=True)
class EngineeringCatalogue:
    revision: str
    sources: Mapping
    items: Mapping[str, CatalogueItem]
    schema_version: int = SCHEMA_VERSION

    def require(self, ident, *, kind=None, verified=True):
        item = self.items.get(ident)
        if item is None:
            raise ValueError(f'Неизвестная позиция каталога: {ident}; подмена ближайшим размером запрещена')
        if kind is not None and item.kind != kind:
            raise ValueError(f'{ident}: требуется тип {kind}')
        if verified and item.status != 'verified':
            raise ValueError(f'{ident}: размеры не подтверждены ({item.status})')
        return item

    def fingerprint(self, ident):
        item = self.require(ident, verified=False)
        # Unrelated additions do not invalidate existing saved selections.
        evidence = {s: self.sources[s] for s in item.source_ids}
        return digest({'schema_version': self.schema_version, 'item': item, 'evidence': evidence})

    def card(self, ident):
        item = self.require(ident, verified=False)
        return {**plain(item), 'fingerprint': self.fingerprint(ident),
                'inner_diameter_mm': item.inner_diameter_mm,
                'installation_approved': False,
                'sources': {s: plain(self.sources[s]) for s in item.source_ids}}

    def search(self, *, kind=None, material=None, dn=None, outer_diameter_mm=None,
               system_id=None, manufacturing=None, connection=None,
               status='verified', russian_only=False):
        """Exact filters only. Outer diameter filter addresses mating pipe size."""
        return tuple(p for p in self.items.values()
                     if (kind is None or p.kind == kind)
                     and (material is None or p.material == material)
                     and (status is None or p.status == status)
                     and (dn is None or any(q.dn == dn for q in p.ports))
                     and (outer_diameter_mm is None or any(q.outer_diameter_mm == outer_diameter_mm for q in p.ports))
                     and (system_id is None or p.system_id == system_id or any(q.system_id == system_id for q in p.ports))
                     and (manufacturing is None or p.manufacturing == manufacturing)
                     and (connection is None or connection in p.joinings or any(q.connection == connection for q in p.ports))
                     and (not russian_only or p.country_of_manufacture == 'RU' and p.origin_source_ids))

    def summary(self):
        return {'schema_version': self.schema_version, 'revision': self.revision,
                'total': len(self.items), 'by_kind': dict(Counter(p.kind for p in self.items.values())),
                'by_status': dict(Counter(p.status for p in self.items.values())),
                'pipe_materials': dict(Counter(p.material for p in self.items.values() if p.kind == 'pipe')),
                'installation_approved': False}

    def pipe_connection_candidates(self, ident, *, joining):
        """Exact pipe-side dimensional shortlist, not installed/pressure approval.

        No DN equivalence is inferred. Threaded and flanged pipe ends need an
        explicit connector; plain OD alone cannot identify them.
        """
        pipe = self.require(ident, kind='pipe')
        if joining not in pipe.joinings:
            raise ValueError('Способ соединения не предусмотрен карточкой трубы')
        result = []
        for p in self.items.values():
            if p.kind == 'pipe' or p.status != 'verified' or p.material != pipe.material:
                continue
            matching = []
            for q in p.ports:
                if q.connection != joining or q.outer_diameter_mm != pipe.dimensions_mm['outer_diameter_mm']:
                    continue
                if joining == 'socket_fusion':
                    if not pipe.system_id or q.system_id != pipe.system_id or q.sex != 'socket':
                        continue
                elif joining == 'welded':
                    if q.wall_thickness_mm != pipe.dimensions_mm['wall_thickness_mm']:
                        continue
                else:
                    continue  # Requires additional published compatibility data.
                matching.append(q.name)
            if matching:
                result.append({'id':p.id, 'matching_ports':matching,
                               'scope':'pipe_side_dimensions_only', 'installation_approved':False})
        return tuple(result)


def _number(value):
    return type(value) in (int, float) and isfinite(value) and value > 0


def validate_item(item, sources):
    if not item.id or not item.kind or not item.family_id or not item.locator:
        raise ValueError('Нет идентификатора, типа или ссылки на таблицу каталога')
    if item.status not in ('verified', 'conflict', 'missing', 'reference_only'):
        raise ValueError(f'{item.id}: неизвестный статус размеров')
    if not item.source_ids or any(s not in sources for s in (*item.source_ids, *item.origin_source_ids)):
        raise ValueError(f'{item.id}: отсутствует источник')
    if any(v is not None and not _number(v) for v in item.dimensions_mm.values()):
        raise ValueError(f'{item.id}: размеры должны быть положительными числами или null')
    if item.status == 'verified' and not item.dimensions_mm:
        raise ValueError(f'{item.id}: нет проверенных размеров')
    if item.status == 'verified' and any(v is None for v in item.dimensions_mm.values()):
        raise ValueError(f'{item.id}: неизвестный размер нельзя пометить проверенным')
    if item.pn_bar is not None and not _number(item.pn_bar):
        raise ValueError(f'{item.id}: неверное PN')
    for port in item.ports:
        if port.dn is not None and (type(port.dn) is not int or port.dn <= 0):
            raise ValueError(f'{item.id}: неверный DN')
        for attr in ('outer_diameter_mm', 'wall_thickness_mm', 'bolt_circle_mm', 'bolt_hole_mm'):
            val = getattr(port, attr)
            if val is not None and not _number(val):
                raise ValueError(f'{item.id}: неверный размер порта {attr}')
        if port.bolt_count is not None and (type(port.bolt_count) is not int or port.bolt_count <= 0):
            raise ValueError(f'{item.id}: неверное число отверстий')
    if item.kind == 'pipe':
        d, s = (item.dimensions_mm.get(k) for k in ('outer_diameter_mm', 'wall_thickness_mm'))
        if not _number(d) or not _number(s) or 2*s >= d:
            raise ValueError(f'{item.id}: некорректное сечение трубы')
        if item.dn is not None and item.material in ('ppr', 'pe'):
            raise ValueError(f'{item.id}: DN полимерной трубы не выводится из Dн')
        # Gross source inconsistency only, NOT pipe sizing/SDR rounding logic.
        sdr = item.native.get('sdr')
        if sdr is not None and (not _number(sdr) or
                item.status == 'verified' and abs(d/s - sdr) > 1):
            raise ValueError(f'{item.id}: D/s противоречит заявленной серии SDR; нужен карантин')


def load_families(raw, inherited_sources=None):
    """Strict seed loader. A schema bump requires an explicit migration."""
    if raw.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Неподдержанная версия схемы инженерного каталога')
    if raw.get('units') != {'dimensions':'mm', 'pressure':'bar', 'temperature':'degC'}:
        raise ValueError('Неподдержанные единицы каталога')
    sources = dict(inherited_sources or {})
    if set(sources) & set(raw['sources']):
        raise ValueError('Дубликат источника инженерного каталога')
    sources.update(raw['sources'])
    items, family_ids = {}, set()
    for f in raw['families']:
        if f['id'] in family_ids:
            raise ValueError('Дубликат семейства')
        family_ids.add(f['id'])
        if len(set(f['columns'])) != len(f['columns']):
            raise ValueError('Дубликат столбца')
        known_columns = {'article','dn','outer_diameter_mm','wall_thickness_mm','status','note'} | set(f.get('dimension_meanings',{}))
        if not set(f['columns']) <= known_columns:
            raise ValueError('Неизвестный столбец: требуется явная схема/единицы размера')
        for values in f['rows']:
            if len(values) != len(f['columns']):
                raise ValueError(f"{f['id']}: число ячеек не соответствует столбцам")
            row = dict(zip(f['columns'], values))
            d, s = row.get('outer_diameter_mm'), row.get('wall_thickness_mm')
            if not _number(d) or s is not None and not _number(s):
                raise ValueError(f"{f['id']}: некорректный Dн/стенка")
            article = row.get('article', '')
            key = article.lower() if article else ('od' + f'{d:g}' + (f'-s{s:g}' if s is not None else ''))
            ident = f['id'] + '-' + key.replace('.', 'p')
            if ident in items:
                raise ValueError('Дубликат позиции: ' + ident)
            ispipe = f['kind'] == 'pipe'
            dimensions = ({'outer_diameter_mm':d, 'wall_thickness_mm':s} if ispipe
                          else {k:row[k] for k in f['dimension_meanings']})
            port = dict(connection='plain_pipe' if ispipe else f['connection'],
                        dn=row.get('dn'), outer_diameter_mm=d, wall_thickness_mm=s,
                        system_id=f.get('system_id', ''), sex='plain' if ispipe else f['port_sex'])
            ports = tuple(CataloguePort(name, **port) for name in ('in','out','branch','branch2')[:f.get('port_count', 2)])
            notes = tuple(f.get('notes', ())) + ((row['note'],) if row.get('note') else ())
            item = CatalogueItem(ident, f['id'], f['kind'],
                ' '.join(filter(None,(f['manufacturer'], f['series'], article, f'Ø{d:g}' + (f'×{s:g}' if s is not None else '')))),
                tuple(f['source_ids']), f['locator'], row.get('status','verified'), freeze(dimensions), ports,
                freeze(f.get('dimension_meanings', {})), manufacturer=f['manufacturer'], article=article,
                material=f['material'], grade=f.get('grade',''), manufacturing=f['manufacturing'],
                coating=f.get('coating','unknown'), standard=f['standard'], series=f['series'],
                system_id=f.get('system_id',''), joinings=tuple(f.get('joinings',())), pn_bar=f.get('pn_bar'),
                notes=notes, native=freeze({'sdr':f.get('sdr'), 'angle_deg':f.get('angle_deg')}))
            validate_item(item, sources)
            items[ident] = item
    return sources, items


@lru_cache(maxsize=1)
def get_engineering_catalogue():
    from app.data.engineering_catalogue_adapters import existing_items
    sources, existing = existing_items()
    from app.data.flexible_connections import flexible_catalogue_items
    flex_sources, flexible = flexible_catalogue_items()
    if set(sources) & set(flex_sources):
        raise ValueError('Дубликат источника гибких соединений')
    sources.update(flex_sources)
    raw = json.loads(_DATA.read_text(encoding='utf-8'))
    sources, added = load_families(raw, sources)
    items = {}
    for item in (*existing, *added.values(), *flexible):
        if item.id in items:
            raise ValueError('Дубликат позиции: ' + item.id)
        validate_item(item, sources)
        items[item.id] = item
    return EngineeringCatalogue(raw['revision'], freeze(sources), MappingProxyType(items))
