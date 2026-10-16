"""Preliminary screening only; geometry is not seismic/installation approval."""
from dataclasses import dataclass
from math import isfinite


FLEX_ROLES = ('inlet','before_meter')
MOVEMENTS = ('compression_mm','extension_mm','angular_deg','lateral_mm')


@dataclass
class FlexibleConnectionChoice:
    catalogue_id: str = ''
    catalogue_fingerprint: str = ''
    compression_mm: float | None = None
    extension_mm: float | None = None
    angular_deg: float | None = None
    lateral_mm: float | None = None
    movement_basis: str = ''
    # Interface approval is separate; missing values never imply type 11/B.
    mating_flange_type: str = ''
    mating_flange_face: str = ''
    mating_flange_series: int | None = None
    mounting_precompression_mm: float | None = None

    def validate(self):
        errors = []
        for k in MOVEMENTS:
            v = getattr(self,k)
            if v is not None and (type(v) not in (int,float) or not isfinite(v) or v < 0):
                errors.append(f'{k}: нужно конечное неотрицательное перемещение')
        for k in ('catalogue_id','catalogue_fingerprint','movement_basis','mating_flange_type','mating_flange_face'):
            if not isinstance(getattr(self,k),str):
                errors.append(f'{k}: нужна строка')
        if self.mating_flange_series is not None and (type(self.mating_flange_series) is not int or self.mating_flange_series not in (1,2)):
            errors.append('mating_flange_series: допустим ряд 1 или 2')
        v = self.mounting_precompression_mm
        if v is not None and (type(v) not in (int,float) or not isfinite(v) or not 3 <= v <= 5):
            errors.append('mounting_precompression_mm: по паспорту требуется предварительное сжатие 3–5 мм')
        return errors


def check_flexible_connection(choice, *, dn, material, orientation, pressure_bar, temperature_c,
                              russian_only=False):
    from app.data.engineering_catalogue import get_engineering_catalogue
    c = get_engineering_catalogue()
    errors, pending = list(choice.validate()), []
    item = None
    if not errors:
        try:
            item = c.require(choice.catalogue_id,kind='flexible_connection')
        except ValueError as exc:
            errors.append(str(exc))
    if item:
        if choice.catalogue_fingerprint != c.fingerprint(item.id):
            errors.append('Паспортная карточка изменилась либо не подтверждена; повторите выбор')
        req = item.native['requirements']
        if type(dn) is not int or item.dn != dn:
            errors.append('DN гибкого соединения не совпадает с участком')
        if material in req['forbidden_pipe_materials']:
            errors.append('Паспорт запрещает эту вставку на ПНД/полипропиленовых трубопроводах')
        elif material not in ('steel','galvanized_steel','stainless_steel'):
            pending.append('Материал и ответные соединения требуют паспортной проверки')
        if orientation not in req['orientations']:
            errors.append('Не задано допустимое монтажное положение')
        elif orientation.startswith('vertical'):
            pending.append(req['vertical_tie_rods'])
        if russian_only and not (item.country_of_manufacture == 'RU' and item.origin_source_ids):
            errors.append('Российское производство конкретного изделия не подтверждено')
        for name, value in (('Давление',pressure_bar),('Температура',temperature_c)):
            if value is None:
                pending.append(f'{name}: нет расчётного значения')
            elif type(value) not in (int,float) or not isfinite(value):
                errors.append(f'{name}: некорректное значение')
            elif name == 'Давление' and not 0 < value <= item.pn_bar:
                errors.append('Давление вне паспортного диапазона; вакуум не допускается')
            elif name == 'Температура' and not item.temperature_c[0] <= value <= item.temperature_c[1]:
                errors.append('Температура вне внесённого рабочего диапазона −10…+95 °C; экстремальный режим не принят')
        for key in MOVEMENTS:
            value = getattr(choice,key)
            if value is None:
                pending.append(f'{key}: требуется перемещение по КР, для отсутствующего задаётся явный ноль')
            elif type(value) in (int,float) and isfinite(value) and value > item.native['movement_limits'][key]:
                errors.append(f'{key}: превышено паспортное рабочее перемещение')
        if not choice.movement_basis.strip():
            pending.append('Не задано основание расчётных перемещений по КР')
        ext, lat = choice.extension_mm, choice.lateral_mm
        if type(ext) in (int,float) and type(lat) in (int,float) and ext > 0 and lat > 0:
            errors.append('Паспорт запрещает одновременное растяжение и боковой сдвиг')
        elif sum(type(getattr(choice,k)) in (int,float) and getattr(choice,k) > 0 for k in MOVEMENTS) > 1:
            pending.append(req['combined_movement'])
        for key, expected in (('mating_flange_type',('11',)),('mating_flange_face',('A','B')),
                              ('mating_flange_series',(2 if dn == 80 else 1,))):
            value = getattr(choice,key)
            if value in ('',None):
                pending.append(f'{key}: требуется ответный фланец по паспорту')
            elif value not in expected:
                errors.append(f'{key}: ответный фланец не разрешён паспортом')
        pending.append('Проверить ответную сверловку, среду, смежную арматуру и опоры; дополнительные эластичные прокладки запрещены')
        if choice.mounting_precompression_mm is None:
            pending.append('Не задано предварительное сжатие 3–5 мм; L0 — свободная длина, не монтажный размер')
    return {'catalogue_id':item.id if item else '', 'dimension_length_mm':item.dimensions_mm['L'] if item else None,
            'installed_length_mm': (item.dimensions_mm['L'] - choice.mounting_precompression_mm
                                    if item and not errors and choice.mounting_precompression_mm is not None else None),
            'status':'incompatible' if errors else 'needs_data' if pending else 'screened',
            'errors':errors, 'pending':pending, 'installation_approved':False, 'seismic_approved':False}


def check_flexible_choices(detail, meter_dn):
    result = []
    for role, choice in detail.flexible_connections.items():
        pipe = detail.pipe_sections.get(role)
        check = check_flexible_connection(choice, dn=detail.inlet_dn if role == 'inlet' else meter_dn,
            material=getattr(pipe,'material','unknown'), orientation=detail.assembly_orientation,
            pressure_bar=detail.design_pressure_bar, temperature_c=detail.water_temperature_c,
            russian_only=detail.russian_equipment_only)
        result.append({'role':role, **check})
    return tuple(result)
